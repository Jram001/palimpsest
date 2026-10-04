"""In-process job registry and single-worker execution.

One `ThreadPoolExecutor(max_workers=1)` for the whole process, not one
per job and not a process pool. The pipeline is blocking, CPU-bound
PyMuPDF work -- it must run off the asyncio event loop, but a local,
single-user tool has no reason to translate two documents at once (it
would just make both slower on typical hardware) and a single worker
keeps the machine responsive for whatever else the user is doing. No
Celery/Redis: that's infrastructure for a multi-worker hosted service,
the wrong weight entirely for one person's laptop.

Progress delivery: the worker thread calls the `progress` callback
synchronously from inside `translate_pdf_document`/
`translate_office_document` (see `core.progress`). Each call does a
plain `queue.Queue.put` -- thread-safe, and cheap enough to call from a
tight per-chunk loop. The SSE route drains that queue from the asyncio
side via `loop.run_in_executor`, so a blocking `queue.get()` never
stalls the event loop the rest of the app depends on.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from palimpsest.config.model import Config
from palimpsest.core.progress import ProgressEvent
from palimpsest.office.pipeline import translate_office_document
from palimpsest.pdf.classify import Kind
from palimpsest.pdf.pipeline import translate_pdf_document
from palimpsest.qa.compare import build_dual_pdf
from palimpsest.server.uploads import UploadedFile
from palimpsest.text.glossary import Glossary
from palimpsest.translate.backend import Backend
from palimpsest.translate.direction import DEFAULT_TARGET, config_for_target, resources_for

log = logging.getLogger(__name__)

JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]
FileStatus = Literal["pending", "running", "done", "failed"]


@dataclass
class JobFileEvent:
    """A progress event tagged with which file (and which position in
    the job's file list) it came from -- the piece `ProgressEvent` alone
    can't carry, since the pipeline that emits it knows nothing about
    the job wrapping it."""

    file_id: str
    file_index: int
    file_count: int
    event: ProgressEvent


@dataclass
class JobFile:
    file_id: str
    name: str
    kind: str
    status: FileStatus = "pending"
    target: str = "en"
    """The language this file is translated INTO ("en" or "es") -- chosen
    per file in the web UI's Queue step. The source is always the other
    one; see `translate.direction`."""
    report: dict | None = None
    error: str | None = None
    output_path: Path | None = None
    dual_path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "file_id": self.file_id, "name": self.name, "kind": self.kind,
            "status": self.status, "target": self.target,
            "report": self.report, "error": self.error,
        }

    def _persist_dict(self) -> dict:
        """Unlike `to_dict()`, includes local filesystem paths -- this
        goes to the on-disk job record, never to the browser."""
        d = self.to_dict()
        d["output_path"] = str(self.output_path) if self.output_path else None
        d["dual_path"] = str(self.dual_path) if self.dual_path else None
        return d

    @classmethod
    def _from_persist_dict(cls, d: dict) -> JobFile:
        return cls(
            file_id=d["file_id"], name=d["name"], kind=d["kind"],
            status=d.get("status", "pending"), target=d.get("target", "en"),
            report=d.get("report"), error=d.get("error"),
            output_path=Path(d["output_path"]) if d.get("output_path") else None,
            dual_path=Path(d["dual_path"]) if d.get("dual_path") else None,
        )


@dataclass
class Job:
    id: str
    files: list[JobFile]
    backend_name: str
    dual: bool
    status: JobStatus = "queued"
    created_at: float = field(default_factory=time.time)
    error: str | None = None
    visitor_id: str = "local"
    """Which browser-generated visitor created this job (see
    `server/routes.py::_visitor_id`) -- `"local"` matches that module's
    `_LOCAL_VISITOR` sentinel exactly (see `uploads.UploadedFile.visitor_id`
    for why this is a duplicated literal, not an import). Not exposed via
    `to_dict()` (nothing in the browser needs to see it -- ownership is
    enforced server-side, before a `Job` ever reaches a response), but
    IS included in `_persist_dict()` so it survives a server restart."""
    _queue: queue.Queue = field(default_factory=queue.Queue, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "status": self.status,
                "backend": self.backend_name,
                "created_at": self.created_at,
                "error": self.error,
                "files": [f.to_dict() for f in self.files],
            }

    def _persist_dict(self) -> dict:
        with self._lock:
            return {
                "id": self.id,
                "status": self.status,
                "backend": self.backend_name,
                "dual": self.dual,
                "created_at": self.created_at,
                "error": self.error,
                "visitor_id": self.visitor_id,
                "files": [f._persist_dict() for f in self.files],
            }


class JobRegistry:
    """One registry per running server process. Job records also mirror
    to a JSON file per job under `jobs_dir`, so a finished job's report
    -- and now the job list itself -- survives a server restart, even
    though in-flight progress does not (there is no "resume a job"
    story here -- see the plan's explicit non-goals: a job that was
    still queued/running when the process exited has no worker left to
    finish it, so `_load_existing` marks it failed rather than leaving
    it stuck "running" forever)."""

    def __init__(self, jobs_dir: Path):
        self.jobs_dir = jobs_dir
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, Job] = {}
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="palimpsest-job")
        self._load_existing()

    def _load_existing(self) -> None:
        for path in sorted(self.jobs_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                log.warning("could not read persisted job record %s", path, exc_info=True)
                continue
            job = self._job_from_persist_dict(data)
            if job is not None:
                self._jobs[job.id] = job

    def _job_from_persist_dict(self, data: dict) -> Job | None:
        try:
            files = [JobFile._from_persist_dict(f) for f in data["files"]]
            job = Job(
                id=data["id"], files=files, backend_name=data["backend"],
                dual=data.get("dual", False), status=data["status"],
                created_at=data.get("created_at", time.time()), error=data.get("error"),
                visitor_id=data.get("visitor_id", "local"),
            )
        except (KeyError, TypeError):
            log.warning("skipping malformed persisted job record: %r", data, exc_info=True)
            return None

        if job.status in ("queued", "running"):
            for jf in job.files:
                if jf.status in ("pending", "running"):
                    jf.status = "failed"
                    jf.error = jf.error or "server restarted before this file finished"
            job.status = "failed"
            job.error = job.error or "server restarted while this job was in progress"
            self._persist(job)
        # No worker is running for a restored job, so any SSE stream that
        # subscribes now would otherwise block on an empty queue forever
        # -- the sentinel makes it end immediately with a job-done event.
        job._queue.put(None)
        return job

    def create(
        self,
        uploaded: list[UploadedFile],
        backend_name: str,
        dual: bool,
        visitor_id: str = "local",
        targets: dict[str, str] | None = None,
    ) -> Job:
        job_id = uuid.uuid4().hex
        targets = targets or {}
        files = [
            JobFile(
                file_id=u.file_id, name=u.name, kind=str(u.kind),
                target=targets.get(u.file_id, DEFAULT_TARGET),
            )
            for u in uploaded
        ]
        job = Job(
            id=job_id, files=files, backend_name=backend_name, dual=dual, visitor_id=visitor_id
        )
        self._jobs[job_id] = job
        self._persist(job)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def active_count_for(self, visitor_id: str) -> int:
        """How many of `visitor_id`'s own jobs are still `queued`/
        `running` -- used by `routes.py::create_job` to cap how many a
        single visitor can have in flight at once (see
        `config.model.LimitsConfig.max_concurrent_jobs_per_visitor`).
        Jobs already run one at a time process-wide regardless, so this
        only stops one visitor from queueing many ahead of everyone
        else, not a real concurrency limit."""
        return sum(
            1 for j in self._jobs.values()
            if j.visitor_id == visitor_id and j.status in ("queued", "running")
        )

    def active_jobs_for(self, visitor_id: str) -> list[Job]:
        """The actual `Job` objects `active_count_for` counts -- used by
        `routes.py::create_job`'s 429 to name which job is blocking, so
        the client can offer to cancel it."""
        return [
            j for j in self._jobs.values()
            if j.visitor_id == visitor_id and j.status in ("queued", "running")
        ]

    def cancel(self, job_id: str, visitor_id: str) -> Job | None:
        """Frees this visitor's job-limit slot immediately. There is no
        real interruption available once a file is mid-pipeline (see
        `_run`'s module-level docstring reasoning and this module's own
        `_run` guards below) -- a file already running finishes silently
        in the background with its result discarded, but any file that
        hasn't started yet is skipped. Returns `None` for an unknown or
        not-owned job, exactly like `routes.py::_get_owned_job_or_404`'s
        own 404-not-403 convention (enforced by the caller, not here)."""
        job = self._jobs.get(job_id)
        if job is None or job.visitor_id != visitor_id:
            return None
        with job._lock:
            if job.status not in ("queued", "running"):
                return job
            job.status = "cancelled"
            job.error = "cancelled by user"
        self._persist(job)
        return job

    def submit(
        self,
        job: Job,
        uploaded_by_id: dict[str, UploadedFile],
        config: Config,
        backend: Backend,
        entities: tuple[str, ...],
        glossary: Glossary,
        post_rules: tuple[tuple[str, str], ...],
        out_dir: Path,
    ) -> None:
        self._executor.submit(
            self._run, job, uploaded_by_id, config, backend, entities, glossary, post_rules, out_dir
        )

    def _persist(self, job: Job) -> None:
        try:
            (self.jobs_dir / f"{job.id}.json").write_text(
                json.dumps(job._persist_dict(), indent=2), encoding="utf-8"
            )
        except OSError:
            log.warning("could not persist job %s", job.id, exc_info=True)

    def _run(
        self,
        job: Job,
        uploaded_by_id: dict[str, UploadedFile],
        config: Config,
        backend: Backend,
        entities: tuple[str, ...],
        glossary: Glossary,
        post_rules: tuple[tuple[str, str], ...],
        out_dir: Path,
    ) -> None:
        with job._lock:
            job.status = "running"
        self._persist(job)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_count = len(job.files)

        try:
            for index, jf in enumerate(job.files):
                with job._lock:
                    if job.status == "cancelled":
                        break
                    jf.status = "running"
                self._persist(job)
                uploaded = uploaded_by_id[jf.file_id]

                def progress(event: ProgressEvent, jf=jf, index=index) -> None:
                    job._queue.put(
                        JobFileEvent(
                            file_id=jf.file_id, file_index=index,
                            file_count=file_count, event=event,
                        )
                    )

                rel = jf.name
                # Per-file direction: the same pipelines, handed a config /
                # glossary / post-rule set that is correct for THIS file's
                # source->target pair (see translate.direction).
                file_config = config_for_target(config, jf.target)
                file_glossary, file_post_rules = resources_for(jf.target, glossary, post_rules)
                out_path = out_dir / f"{jf.file_id}.{Path(jf.name).suffix.lstrip('.')}"
                try:
                    if uploaded.kind == "office":
                        report = translate_office_document(
                            uploaded.path, out_path, rel, backend,
                            entities, file_glossary, file_post_rules, file_config,
                        )
                    else:
                        # uploads.validate_and_save only ever assigns a
                        # non-Kind string for the "office" case, already
                        # excluded above -- everything else is a real Kind.
                        report = translate_pdf_document(
                            uploaded.path, out_path, rel, backend,
                            entities, file_glossary, file_post_rules, file_config,
                            kind=cast(Kind, uploaded.kind), progress=progress,
                        )
                    with job._lock:
                        jf.status = "done"
                        jf.report = report
                        jf.output_path = out_path
                    if job.dual and uploaded.kind != "office":
                        dual_path = out_dir / f"{jf.file_id}.dual.pdf"
                        build_dual_pdf(uploaded.path, out_path, dual_path)
                        with job._lock:
                            jf.dual_path = dual_path
                except Exception as e:  # noqa: BLE001 -- reported per-file, job continues
                    log.exception("job %s: file %s failed", job.id, jf.file_id)
                    with job._lock:
                        jf.status = "failed"
                        jf.error = str(e)
                self._persist(job)

            with job._lock:
                # A worker thread that was mid-file when `cancel()` set
                # this to "cancelled" must not clobber that on its way
                # out -- the file it was running still finished (and its
                # own status/report above is left as-is), but the JOB's
                # terminal status is whatever cancel() already decided.
                if job.status != "cancelled":
                    any_failed = any(f.status == "failed" for f in job.files)
                    job.status = "failed" if any_failed else "done"
        except Exception as e:  # noqa: BLE001 -- job-level failure, surfaced to the client
            log.exception("job %s failed", job.id)
            with job._lock:
                if job.status != "cancelled":
                    job.status = "failed"
                    job.error = str(e)
        finally:
            self._persist(job)
            job._queue.put(None)  # sentinel: SSE stream ends
