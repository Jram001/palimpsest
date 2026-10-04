"""Pydantic response/request models.

Kept separate from `jobs.py`'s dataclasses on purpose: the dataclasses
are the server's internal state (mutable, holding filesystem `Path`s
that must never leak into a response body), these are what actually
goes over the wire.
"""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    version: str
    backend: str
    anthropic_key_present: bool
    gemini_key_present: bool


class SetKeysRequest(BaseModel):
    # A field left absent/empty is a no-op, not a clear -- submitting only
    # a Gemini key must never blank out an already-working Anthropic key
    # from a prior submission or a real shell export. See PUT /api/keys.
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None


class UploadResponse(BaseModel):
    file_id: str
    name: str
    kind: str
    pages: int | None
    size: int


class EstimateRequest(BaseModel):
    file_ids: list[str]
    # file_id -> "en" | "es": which language each file is translated INTO.
    # A file with no entry is translated into English, the original
    # behaviour. See translate.direction.
    targets: dict[str, str] = {}


class DocumentEstimateResponse(BaseModel):
    file_id: str
    name: str
    kind: str | None
    pages: int | None
    unit_count: int
    unique_count: int
    cache_hits: int
    input_tokens: int
    output_tokens: int
    usd: float | None


class CreateJobRequest(BaseModel):
    file_ids: list[str]
    backend: str | None = None
    dual: bool = True
    targets: dict[str, str] = {}


class CreateJobResponse(BaseModel):
    job_id: str


class JobFileResponse(BaseModel):
    file_id: str
    name: str
    kind: str
    status: str
    target: str
    report: dict | None
    error: str | None


class JobResponse(BaseModel):
    id: str
    status: str
    backend: str
    created_at: float
    error: str | None
    files: list[JobFileResponse]


class EntityGroupsResponse(BaseModel):
    companies: list[str]
    people: list[str]
    places: list[str]
    other: list[str]
