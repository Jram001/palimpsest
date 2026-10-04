"""API routes. See the module docstring in `app.py` for the security
model these all share (loopback-only, origin-checked, no auth)."""

from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import os
from pathlib import Path

import fitz
from dotenv import set_key
from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from palimpsest.config import loader as config_loader
from palimpsest.config.model import EntityGroups
from palimpsest.core import ir
from palimpsest.core import paths as core_paths
from palimpsest.core.errors import DependencyError
from palimpsest.office import render as office_render
from palimpsest.pdf import layout as pdf_layout
from palimpsest.pdf import reflow
from palimpsest.qa.compare import render_page
from palimpsest.server.jobs import Job
from palimpsest.server.schemas import (
    CreateJobRequest,
    CreateJobResponse,
    DocumentEstimateResponse,
    EntityGroupsResponse,
    EstimateRequest,
    HealthResponse,
    JobResponse,
    SetKeysRequest,
    UploadResponse,
)
from palimpsest.server.uploads import UploadRejected, validate_and_save
from palimpsest.text.protect import EntityGuard
from palimpsest.translate.backend import TranslationContext
from palimpsest.translate.cache import Cache, compute_namespace
from palimpsest.translate.direction import (
    DEFAULT_TARGET,
    SUPPORTED_TARGETS,
    config_for_target,
    resources_for,
)
from palimpsest.translate.estimate import estimate_document

router = APIRouter(prefix="/api")

# The default DPI /pages/{n}.png renders at, and what _layout_envelope's
# px_width/px_height MUST be computed from -- the edit surface positions
# every overlay box as a percentage of these dimensions against the <img>
# it fetches from /pages/{n}.png with no dpi override, so the two have to
# describe the same raster or every box registers in the wrong place.
DEFAULT_PAGE_DPI = 110


def _state(request: Request):
    return request.app.state.palimpsest


# Every visitor is scoped to a browser-generated id (web/prototype/src/
# visitor.js) sent as the X-Palimpsest-Visitor header on fetch() calls, or
# as a `visitor` query param on the few requests that can't set custom
# headers at all (EventSource for job_events, <img>/<a> for page_png and
# download). A request with neither -- curl, scripts, an older frontend,
# or the classic single-user desktop workflow -- falls back to one fixed
# local sentinel, which is exactly today's implicit behavior (one local
# user, one implicit scope) made explicit rather than assumed. This is
# NOT an auth mechanism: nothing is signed, nothing stops a client from
# sending a different id on purpose. It only stops one visitor's browser
# from accidentally seeing another's uploads/jobs/keys during normal use.
_LOCAL_VISITOR = "local"
_VISITOR_HEADER = "X-Palimpsest-Visitor"


def _visitor_id(request: Request) -> str:
    header = request.headers.get(_VISITOR_HEADER)
    query = request.query_params.get("visitor")
    return header or query or _LOCAL_VISITOR


def _resolve_key(state, visitor_id: str, env_name: str) -> str | None:
    """A per-visitor key always wins. Failing that, ONLY the local
    sentinel (the classic single-user desktop workflow) falls back to
    this process's own environment -- a real remote visitor with no key
    of their own gets `None`, never the operator's own credential. See
    `translate.registry.make_backend`'s `allow_env_fallback` for the
    other half of this: `None` reaching that function for a non-local
    visitor must never be handed to an SDK client, which would perform
    its own, uncontrolled env fallback."""
    stored = state.get_keys(visitor_id).get(env_name)
    if stored:
        return stored
    if visitor_id != _LOCAL_VISITOR:
        return None
    if env_name == "GEMINI_API_KEY":
        return os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    return os.environ.get(env_name)


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    from palimpsest import __version__

    state = _state(request)
    visitor_id = _visitor_id(request)
    return HealthResponse(
        version=__version__,
        backend=state.config.backend.name,
        anthropic_key_present=bool(_resolve_key(state, visitor_id, "ANTHROPIC_API_KEY")),
        gemini_key_present=bool(_resolve_key(state, visitor_id, "GEMINI_API_KEY")),
    )


@router.put("/keys", response_model=HealthResponse)
def put_keys(request: Request, body: SetKeysRequest) -> HealthResponse:
    # Only reachable at all from an origin OriginCheckMiddleware already
    # allowed (app.py) -- a scoped, deliberate exception to "keys never
    # travel over HTTP", made specifically so a key can be typed into a
    # page instead of a shell. A field left absent/empty is a no-op, not
    # a clear -- see SetKeysRequest. Never echoes the raw value back;
    # health() reports presence only, exactly like every other read path.
    #
    # Every visitor's key is remembered in AppState._keys (in-memory
    # only). Only the local sentinel's key ALSO goes to this process's
    # own environment and its .env file -- a real remote visitor's key
    # must never land in a place `_resolve_key` would hand back to a
    # DIFFERENT visitor (the local-sentinel fallback) or that survives
    # to leak into a later, unrelated process restart.
    state = _state(request)
    visitor_id = _visitor_id(request)
    for env_name, value in (
        ("ANTHROPIC_API_KEY", body.anthropic_api_key),
        ("GEMINI_API_KEY", body.gemini_api_key),
    ):
        if value:
            state.set_key(visitor_id, env_name, value)
            if visitor_id == _LOCAL_VISITOR:
                os.environ[env_name] = value
                set_key(str(state.dotenv_path), env_name, value)
    return health(request)


# -- entities -----------------------------------------------------------


@router.get("/entities", response_model=EntityGroupsResponse)
def get_entities(request: Request) -> EntityGroupsResponse:
    state = _state(request)
    groups = config_loader.load_entity_groups(state.config)
    return EntityGroupsResponse(
        companies=list(groups.companies), people=list(groups.people),
        places=list(groups.places), other=list(groups.other),
    )


@router.put("/entities", response_model=EntityGroupsResponse)
def put_entities(request: Request, body: EntityGroupsResponse) -> EntityGroupsResponse:
    state = _state(request)
    groups = EntityGroups(
        companies=tuple(body.companies), people=tuple(body.people),
        places=tuple(body.places), other=tuple(body.other),
    )
    path = state.entities_path
    config_loader.save_entity_groups(path, groups)
    # Reflected back so the caller sees exactly what was persisted --
    # this process's in-memory `state.entities` is refreshed too, so a
    # job submitted right after a PUT uses the new roster, not a stale
    # snapshot taken at server startup.
    state.refresh_entities()
    return body


# -- uploads --------------------------------------------------------------


@router.post("/uploads", response_model=UploadResponse)
async def upload(request: Request, file: UploadFile) -> UploadResponse:
    state = _state(request)
    content = await file.read()
    try:
        uploaded = validate_and_save(
            file.filename or "upload", content, state.uploads_dir,
            visitor_id=_visitor_id(request),
            max_bytes=state.config.limits.max_upload_bytes,
        )
    except UploadRejected as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    state.remember_upload(uploaded)
    return UploadResponse(
        file_id=uploaded.file_id, name=uploaded.name, kind=str(uploaded.kind),
        pages=uploaded.pages, size=uploaded.size,
    )


def _cache_for(rel: str, state, backend, target: str = DEFAULT_TARGET) -> Cache:
    key = core_paths.cache_key(core_paths.norm_rel(rel))
    cache_path = state.config.paths.cache_dir / f"{key}.json"
    lang = config_for_target(state.config, target).language
    glossary, _ = resources_for(target, state.glossary, state.post_rules)
    namespace = compute_namespace(
        backend.name, getattr(backend, "model", None),
        lang.source, lang.target,
        glossary_terms=glossary.terms, entities=state.entities,
    )
    return Cache(cache_path, namespace=namespace)


def _backend_for_visitor(state, request: Request, config=None):
    """Resolves this visitor's keys and builds a backend via
    `state.backend_factory` -- the one place `estimate()`/`create_job()`
    share this logic. `allow_env_fallback` is only `True` for the local
    sentinel (see `_resolve_key`'s and `translate.registry.make_backend`'s
    docstrings for why a non-local visitor must never get it): a real
    visitor with no key configured gets a clean 503, never a client
    silently constructed against the operator's own environment."""
    visitor_id = _visitor_id(request)
    anthropic_key = _resolve_key(state, visitor_id, "ANTHROPIC_API_KEY")
    gemini_key = _resolve_key(state, visitor_id, "GEMINI_API_KEY")
    try:
        return state.backend_factory(
            config if config is not None else state.config,
            anthropic_api_key=anthropic_key,
            gemini_api_key=gemini_key,
            allow_env_fallback=(visitor_id == _LOCAL_VISITOR),
        )
    except DependencyError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


def _validate_targets(targets: dict[str, str]) -> None:
    for file_id, target in targets.items():
        if target not in SUPPORTED_TARGETS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"unsupported target language {target!r} for {file_id!r}; "
                    f"expected one of {list(SUPPORTED_TARGETS)}"
                ),
            )


@router.post("/estimate", response_model=list[DocumentEstimateResponse])
def estimate(request: Request, body: EstimateRequest) -> list[DocumentEstimateResponse]:
    state = _state(request)
    visitor_id = _visitor_id(request)
    backend = _backend_for_visitor(state, request)
    _validate_targets(body.targets)
    results = []
    for file_id in body.file_ids:
        uploaded = state.get_upload(file_id, visitor_id)
        if uploaded is None:
            raise HTTPException(status_code=404, detail=f"unknown file_id {file_id!r}")

        if uploaded.kind == "office":
            from palimpsest.office import ooxml

            strings = ooxml.collect_strings(str(uploaded.path))
            names = [n for n in ooxml.sheet_names(str(uploaded.path)) if ooxml._translatable(n)]
            texts = strings + names
            kind, pages = None, None
        else:
            guard = EntityGuard(state.entities)
            scanned = uploaded.kind in ("scan", "ocr")
            min_size = (
                state.config.thresholds.min_text_size_scan
                if scanned else state.config.thresholds.min_text_size
            )
            doc = fitz.open(str(uploaded.path))
            texts = [
                p.text
                for pno in range(len(doc))
                for p in pdf_layout.extract_paragraphs(doc[pno], min_size=min_size)
                if not guard.skip(p.text)
            ]
            pages = len(doc)
            doc.close()
            kind = uploaded.kind

        target = body.targets.get(file_id, DEFAULT_TARGET)
        lang = config_for_target(state.config, target).language
        glossary, _ = resources_for(target, state.glossary, state.post_rules)
        ctx = TranslationContext(
            source_lang=lang.source, target_lang=lang.target,
            entities=state.entities, glossary=glossary.terms,
        )
        cache = _cache_for(uploaded.name, state, backend, target)
        est = estimate_document(
            uploaded.name, texts, backend, ctx, cache, kind=kind, pages=pages
        )
        results.append(
            DocumentEstimateResponse(
                file_id=file_id, name=uploaded.name, kind=est.kind, pages=est.pages,
                unit_count=est.unit_count, unique_count=est.unique_count,
                cache_hits=est.cache_hits, input_tokens=est.corpus.input_tokens,
                output_tokens=est.corpus.output_tokens, usd=est.corpus.usd,
            )
        )
    return results


# -- jobs -------------------------------------------------------------------


@router.post("/jobs", response_model=CreateJobResponse)
def create_job(request: Request, body: CreateJobRequest) -> CreateJobResponse:
    state = _state(request)
    visitor_id = _visitor_id(request)
    uploaded = []
    for file_id in body.file_ids:
        u = state.get_upload(file_id, visitor_id)
        if u is None:
            raise HTTPException(status_code=404, detail=f"unknown file_id {file_id!r}")
        uploaded.append(u)
    if not uploaded:
        raise HTTPException(status_code=400, detail="file_ids is empty")
    _validate_targets(body.targets)

    max_concurrent = state.config.limits.max_concurrent_jobs_per_visitor
    active = state.jobs.active_jobs_for(visitor_id)
    if len(active) >= max_concurrent:
        # `detail` is a dict here, not a plain string like everywhere
        # else in this file -- FastAPI serializes any JSON-serializable
        # value, and the frontend (api.js's request()) only special-cases
        # a dict shape, so every other route's plain-string `detail` is
        # unaffected. `job_id` names the blocking job so the client can
        # offer to cancel it instead of just waiting (web UI's Estimate
        # screen).
        raise HTTPException(
            status_code=429,
            detail={
                "message": (
                    f"you already have {max_concurrent} job(s) in progress -- "
                    "wait for one to finish"
                ),
                "job_id": active[0].id,
            },
        )

    config = state.config
    if body.backend and body.backend != config.backend.name:
        config = dataclasses.replace(
            config, backend=dataclasses.replace(config.backend, name=body.backend)
        )
    backend = _backend_for_visitor(state, request, config)

    job = state.jobs.create(
        uploaded, backend_name=backend.name, dual=body.dual, visitor_id=visitor_id,
        targets=body.targets,
    )
    uploaded_by_id = {u.file_id: u for u in uploaded}
    out_dir = state.jobs.jobs_dir / job.id
    state.jobs.submit(
        job, uploaded_by_id, config, backend, state.entities, state.glossary,
        state.post_rules, out_dir,
    )
    return CreateJobResponse(job_id=job.id)


def _get_job_or_404(state, job_id: str) -> Job:
    job = state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job {job_id!r}")
    return job


def _get_owned_job_or_404(state, request: Request, job_id: str) -> Job:
    """Every job-scoped route in this file uses this instead of
    `_get_job_or_404` directly. A job id that exists but belongs to a
    DIFFERENT visitor gets the exact same 404 as one that doesn't exist
    at all -- never a 403, which would confirm to a guesser that the id
    is real, just not theirs (see `AppState.get_upload`'s identical
    reasoning)."""
    job = _get_job_or_404(state, job_id)
    if job.visitor_id != _visitor_id(request):
        raise HTTPException(status_code=404, detail=f"unknown job {job_id!r}")
    return job


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(request: Request, job_id: str) -> JobResponse:
    job = _get_owned_job_or_404(_state(request), request, job_id)
    return JobResponse(**job.to_dict())


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(request: Request, job_id: str) -> JobResponse:
    """Frees this visitor's job-limit slot -- see `JobRegistry.cancel`'s
    own docstring for exactly what this does and doesn't interrupt. Uses
    `_get_owned_job_or_404` first (rather than relying on `cancel`'s own
    visitor check alone) purely so an unknown/not-owned id gets the same
    404 every other job route gives it."""
    state = _state(request)
    job = _get_owned_job_or_404(state, request, job_id)
    cancelled = state.jobs.cancel(job.id, _visitor_id(request))
    assert cancelled is not None  # job existed and was owned, just confirmed above
    return JobResponse(**cancelled.to_dict())


def _sse(data: dict) -> bytes:
    return f"data: {json.dumps(data)}\n\n".encode()


@router.get("/jobs/{job_id}/events")
async def job_events(request: Request, job_id: str) -> StreamingResponse:
    state = _state(request)
    job = _get_owned_job_or_404(state, request, job_id)

    async def stream():
        loop = asyncio.get_event_loop()
        while True:
            item = await loop.run_in_executor(None, job._queue.get)
            if item is None:
                yield _sse({"type": "job-done", "status": job.status, "error": job.error})
                return
            yield _sse(
                {
                    "type": "progress",
                    "file_id": item.file_id,
                    "file_index": item.file_index,
                    "file_count": item.file_count,
                    "phase": item.event.phase,
                    "status": item.event.status,
                    "detail": item.event.detail,
                    "count": item.event.count,
                    "total": item.event.total,
                }
            )

    return StreamingResponse(stream(), media_type="text/event-stream")


def _job_file_or_404(job: Job, file_id: str | None):
    if file_id is None:
        if not job.files:
            raise HTTPException(status_code=404, detail="job has no files")
        return job.files[0]
    for jf in job.files:
        if jf.file_id == file_id:
            return jf
    raise HTTPException(status_code=404, detail=f"unknown file_id {file_id!r} for this job")


@router.get("/jobs/{job_id}/download/{artifact}")
def download(
    request: Request, job_id: str, artifact: str, file: str | None = Query(None)
) -> StreamingResponse:
    state = _state(request)
    job = _get_owned_job_or_404(state, request, job_id)
    jf = _job_file_or_404(job, file)

    if artifact == "report":
        payload = json.dumps(jf.report or {}, indent=2).encode()
        report_name = f"{Path(jf.name).stem}.report.json"
        return StreamingResponse(
            io.BytesIO(payload), media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{report_name}"'},
        )
    if artifact == "replica":
        path = jf.output_path
    elif artifact == "dual":
        path = jf.dual_path
    else:
        raise HTTPException(status_code=404, detail=f"unknown artifact {artifact!r}")

    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail=f"{artifact} not available for this file yet")
    # The stored file is named by its random id; a download is named for
    # the source document and the language it was translated into.
    suffix = ".dual.pdf" if artifact == "dual" else f".{jf.target}{path.suffix}"
    download_name = f"{Path(jf.name).stem}{suffix}"
    return StreamingResponse(
        io.BytesIO(path.read_bytes()), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


@router.get("/jobs/{job_id}/pages/{page_no}.png")
def page_png(
    request: Request, job_id: str, page_no: int,
    side: str = Query("output"), file: str | None = Query(None), dpi: int = Query(DEFAULT_PAGE_DPI),
) -> StreamingResponse:
    state = _state(request)
    job = _get_owned_job_or_404(state, request, job_id)
    jf = _job_file_or_404(job, file)

    if side == "source":
        uploaded = state.get_upload(jf.file_id, _visitor_id(request))
        path = uploaded.path if uploaded else None
    elif side == "output":
        path = jf.output_path
    else:
        raise HTTPException(status_code=400, detail='side must be "source" or "output"')
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail=f"{side} page not available yet")

    if jf.kind == "office":
        # `fitz.open()` "succeeds" on Office files but doesn't actually
        # render pages (see office.render's docstring) -- convert to a
        # real PDF via LibreOffice first, cached alongside the source
        # file so repeated page requests don't reconvert. Keyed by
        # `side`, not just the file, since source and output are two
        # different documents that happen to share a directory when
        # `side == "output"` (multiple files in one job share `out_dir`).
        try:
            path = office_render.ensure_preview_pdf(path, path.parent, f"{side}-{jf.file_id}")
        except DependencyError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e

    image = render_page(path, page_no, dpi=dpi)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


def _layout_envelope(source_path: Path, source_name: str, pno: int) -> dict:
    """Same shape (and same code path) as `web/prototype/sample/generate.py`'s
    `build_layout_envelope` -- the browser's edit surface reads this
    without any reshaping, so the two must never diverge.

    `zoom`/`px_width`/`px_height` describe the SAME raster `/pages/{n}.png`
    (at its default DPI) actually returns -- see `DEFAULT_PAGE_DPI`'s
    docstring for why that agreement matters."""
    doc = fitz.open(str(source_path))
    try:
        page = doc[pno]
        paras = pdf_layout.extract_paragraphs(page, min_size=3.0)
        ir_page = pdf_layout.page_to_ir(page, paras)
        document = ir.Document(source=source_name, pages=(ir_page,))
        doc_dict = ir.to_dict(document)
        zoom = DEFAULT_PAGE_DPI / 72
        return {
            "schema": 1,
            "source": doc_dict["source"],
            "pages": doc_dict["pages"],
            "render": {
                "zoom": zoom,
                "pages": [
                    {
                        "number": pno,
                        "px_width": round(page.rect.width * zoom),
                        "px_height": round(page.rect.height * zoom),
                    }
                ],
            },
        }
    finally:
        doc.close()


@router.get("/jobs/{job_id}/layout")
def get_layout(
    request: Request, job_id: str, file: str | None = Query(None), page: int = Query(0)
) -> dict:
    state = _state(request)
    job = _get_owned_job_or_404(state, request, job_id)
    jf = _job_file_or_404(job, file)
    if jf.kind == "office":
        raise HTTPException(status_code=400, detail="edit mode is not available for Office files")
    if jf.output_path is None or not jf.output_path.is_file():
        raise HTTPException(status_code=404, detail="translated output not available yet")
    return _layout_envelope(jf.output_path, jf.name, page)


@router.patch("/jobs/{job_id}/layout")
def patch_layout(
    request: Request, job_id: str, body: dict, file: str | None = Query(None)
) -> JSONResponse:
    """Persists edit-mode edits as JSON (an audit trail / recovery copy,
    kept regardless of reflow success) and regenerates the affected page
    of the translated PDF from them via `pdf.reflow.apply_page_edits`.

    The page to reflow comes from the payload itself
    (`document.pages[0].number`, matching `useEditBoxes.exportPayload`'s
    shape) rather than a query parameter, so the existing frontend call
    needs no changes to get real reflow."""
    state = _state(request)
    job = _get_owned_job_or_404(state, request, job_id)
    jf = _job_file_or_404(job, file)
    if jf.kind == "office":
        raise HTTPException(status_code=400, detail="edit mode is not available for Office files")
    out_dir = state.jobs.jobs_dir / job.id
    out_dir.mkdir(parents=True, exist_ok=True)
    edits_path = out_dir / f"{jf.file_id}.edits.json"
    edits_path.write_text(json.dumps(body, indent=2), encoding="utf-8")

    try:
        pages = body["document"]["pages"]
        page_body = pages[0]
        page_no = int(page_body.get("number", 0))
        paragraphs = page_body["paragraphs"]
    except (KeyError, IndexError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"malformed layout payload: {e}") from e

    if jf.output_path is None or not jf.output_path.is_file():
        raise HTTPException(status_code=404, detail="translated output not available yet")

    render_ctx = reflow.build_render_context(state.config, jf.name)
    try:
        result = reflow.apply_page_edits(jf.output_path, page_no, paragraphs, render_ctx)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"could not save reflowed page: {e}") from e

    return JSONResponse({**body, "reflow": result})
