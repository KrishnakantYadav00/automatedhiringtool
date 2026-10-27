"""
Pydantic v2 schemas for the Sourcing Engine.

These schemas define the data contracts between pipeline stages:
RawCandidateData → NormalizedCandidate → Candidate (ORM) → CeipalPushResult,
as well as the external REST API schemas.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pydantic import BaseModel, Field, ConfigDict


class RawCandidateData(BaseModel):
    """Unprocessed candidate payload as received from a source connector."""

    model_config = ConfigDict(populate_by_name=True)

    source_name: str = Field(..., description="Origin connector identifier (e.g. 'naukri', 'email').")
    source_candidate_id: str | None = Field(None, description="ID of the candidate on the source platform.")
    full_name: str | None = Field(None, max_length=512)
    email: str | None = Field(None, max_length=320)
    phone: str | None = Field(None, max_length=32)
    location: str | None = Field(None, max_length=256)
    current_company: str | None = Field(None, max_length=256)
    current_title: str | None = Field(None, max_length=256)
    experience_years: float | str | None = Field(None, description="May arrive as string ('5 yrs') or float.")
    skills: list[str] = Field(default_factory=list)
    resume_url: str | None = Field(None, max_length=2048)
    resume_text: str | None = Field(None, description="Plain-text content extracted from a resume.")
    raw_payload: dict[str, Any] = Field(default_factory=dict, description="Full original response for auditing.")


class NormalizedCandidate(BaseModel):
    """Candidate data after normalisation, ready for deduplication."""

    model_config = ConfigDict(populate_by_name=True)

    source_name: str
    source_candidate_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    phone: str | None = Field(None, description="Phone in original format.")
    phone_e164: str | None = Field(None, description="Phone in E.164 format (+91XXXXXXXXXX).")
    location: str | None = None
    current_company: str | None = None
    current_title: str | None = None
    experience_years: float | None = None
    skills: list[str] = Field(default_factory=list)
    resume_url: str | None = None
    resume_text: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    dedup_hash: str | None = Field(None, description="SHA-256 of normalised email + phone_e164.")

    @property
    def full_name(self) -> str | None:
        """Convenience accessor for display purposes."""
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) if parts else None


class IngestionResult(BaseModel):
    """Summary statistics returned after a pipeline run."""

    source_name: str
    total_fetched: int = 0
    total_normalised: int = 0
    total_new: int = 0
    total_merged: int = 0
    total_pushed_ceipal: int = 0
    total_push_failures: int = 0
    total_errors: int = 0
    started_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    finished_at: dt.datetime | None = None
    error_details: list[str] = Field(default_factory=list)


class CeipalPushResult(BaseModel):
    """Outcome of pushing a single candidate to CEIPAL."""

    success: bool
    ceipal_candidate_id: str | None = None
    status_code: int | None = None
    detail: str | None = None


# ---------------------------------------------------------------------------
# API Request / Response Schemas
# ---------------------------------------------------------------------------


class CandidateSourceResponse(BaseModel):
    """Nested source record in candidate detail response."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_name: str
    source_candidate_id: str | None = None
    fetched_at: dt.datetime
    created_at: dt.datetime


class CandidateResponse(BaseModel):
    """Public candidate profile schema."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    first_name: str
    last_name: str
    email: str | None = None
    phone: str | None = None
    phone_e164: str | None = None
    location: str | None = None
    current_company: str | None = None
    current_title: str | None = None
    experience_years: float | None = None
    skills: list[str] | None = None
    resume_url: str | None = None
    source_first_seen: str | None = None
    status: str
    ceipal_candidate_id: str | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    sources: list[CandidateSourceResponse] = Field(default_factory=list)


class CandidateListResponse(BaseModel):
    """Paginated list of candidates."""

    items: list[CandidateResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class IngestionLogResponse(BaseModel):
    """Log record representing an ingestion run."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_name: str
    status: str
    candidates_fetched: int
    candidates_new: int
    candidates_duplicate: int
    candidates_pushed: int
    error_message: str | None = None
    started_at: dt.datetime
    completed_at: dt.datetime | None = None
    duration_seconds: float | None = None


class SourceTriggerRequest(BaseModel):
    """Options for manual trigger."""

    push_to_ceipal: bool = True


class SourceTriggerResponse(BaseModel):
    """Response returned upon triggering a source ingestion run."""

    message: str
    source: str
    result: IngestionResult | None = None


class TriggerAllResponse(BaseModel):
    """Response returned when triggering all connectors."""

    message: str
    results: dict[str, IngestionResult]


class ConnectorHealthResponse(BaseModel):
    """Health check response for connectors and dependent services."""

    status: str
    connectors: dict[str, dict[str, Any]]
    database: dict[str, Any]
    redis: dict[str, Any]


class StatsResponse(BaseModel):
    """Aggregated sourcing and pipeline statistics."""

    total_candidates: int
    by_source: dict[str, int]
    by_status: dict[str, int]
    total_duplicates_merged: int
    total_pushed_to_ceipal: int
    recent_ingestion_runs: list[IngestionLogResponse]


class CeipalPushBatchRequest(BaseModel):
    """Payload to push candidates in batch."""

    candidate_ids: list[uuid.UUID] | None = None
    limit: int = Field(default=50, ge=1, le=500)


class CeipalWebhookPayload(BaseModel):
    """Webhook payload from CEIPAL for status updates."""

    candidate_id: str
    ceipal_id: str
    status: str
    notes: str | None = None
