"""
AHP Sourcing Engine — Candidate, CandidateSource, and IngestionLog ORM models.

These tables form the core data layer of the sourcing pipeline:

* **candidates** — normalised candidate records with deduplication hash.
* **candidate_sources** — tracks *which* external source each candidate came
  from and stores the verbatim payload for auditability.
* **ingestion_logs** — per-run metrics for observability dashboards.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CandidateStatus(str, enum.Enum):
    """Lifecycle status of a candidate record."""

    NEW = "new"
    NORMALIZED = "normalized"
    DEDUPED = "deduped"
    PUSHED_TO_CEIPAL = "pushed_to_ceipal"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class SourceName(str, enum.Enum):
    """Supported candidate-ingestion sources."""

    NAUKRI = "naukri"
    SHINE = "shine"
    LINKEDIN = "linkedin"
    EMAIL = "email"


class IngestionStatus(str, enum.Enum):
    """Outcome of a single ingestion run."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Candidate table
# ---------------------------------------------------------------------------


class Candidate(Base):
    """
    A normalised candidate profile.

    Fields are populated progressively as the pipeline normalises, deduplicates,
    and pushes records to CEIPAL.
    """

    __tablename__ = "candidates"

    # -- Identity ------------------------------------------------------------
    first_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Candidate first / given name."
    )
    last_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Candidate last / family name."
    )
    email: Mapped[str | None] = mapped_column(
        String(320), unique=True, index=True, nullable=True, comment="Primary email (RFC-5321 max)."
    )
    phone: Mapped[str | None] = mapped_column(
        String(30), index=True, nullable=True, comment="Phone number (original format)."
    )
    phone_e164: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="Phone number in E.164 format."
    )

    # -- Professional info ---------------------------------------------------
    location: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="Candidate location / city."
    )
    current_company: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="Current employer name."
    )
    current_title: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="Current job title."
    )
    experience_years: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Total years of professional experience."
    )
    skills: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True, comment="Extracted skill tags."
    )

    # -- Resume --------------------------------------------------------------
    resume_url: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="URL or object-store path to the resume file."
    )
    resume_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Plain-text extract of the resume (for search)."
    )

    # -- Pipeline metadata ---------------------------------------------------
    source_first_seen: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="The source that first discovered this candidate."
    )
    status: Mapped[CandidateStatus] = mapped_column(
        Enum(CandidateStatus, name="candidate_status", create_constraint=True),
        default=CandidateStatus.NEW,
        server_default=CandidateStatus.NEW.value,
        nullable=False,
        index=True,
        comment="Current pipeline status.",
    )
    ceipal_candidate_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="ID assigned by CEIPAL after a successful push."
    )
    raw_data: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="Verbatim merged data before normalisation."
    )
    dedup_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="SHA-256 fingerprint for deduplication (email + phone_e164).",
    )

    # -- Relationships -------------------------------------------------------
    sources: Mapped[list[CandidateSource]] = relationship(
        "CandidateSource",
        back_populates="candidate",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # -- Table-level config --------------------------------------------------
    __table_args__ = (
        Index("ix_candidates_name", "first_name", "last_name"),
        Index("ix_candidates_status_created", "status", "created_at"),
        {"comment": "Normalised candidate profiles."},
    )

    def __repr__(self) -> str:
        return (
            f"<Candidate(id={self.id!r}, name='{self.first_name} {self.last_name}', "
            f"email={self.email!r}, status={self.status!r})>"
        )


# ---------------------------------------------------------------------------
# CandidateSource table
# ---------------------------------------------------------------------------


class CandidateSource(Base):
    """
    Junction table linking a :class:`Candidate` to a specific external source.

    Stores the raw, unmodified payload so the original data is always
    recoverable for audit or re-processing.
    """

    __tablename__ = "candidate_sources"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="FK → candidates.id",
    )
    source_name: Mapped[SourceName] = mapped_column(
        Enum(SourceName, name="source_name", create_constraint=True),
        nullable=False,
        comment="Which connector produced this record.",
    )
    source_candidate_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Candidate identifier on the external platform.",
    )
    raw_payload: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="Verbatim JSON payload from the source API/email."
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment="When the record was fetched from the source.",
    )

    # -- Relationships -------------------------------------------------------
    candidate: Mapped[Candidate] = relationship(
        "Candidate", back_populates="sources"
    )

    # -- Table-level config --------------------------------------------------
    __table_args__ = (
        UniqueConstraint(
            "source_name",
            "source_candidate_id",
            name="uq_source_candidate",
        ),
        Index("ix_candidate_sources_source", "source_name", "fetched_at"),
        {"comment": "Per-source raw records linked to normalised candidates."},
    )

    def __repr__(self) -> str:
        return (
            f"<CandidateSource(id={self.id!r}, source={self.source_name!r}, "
            f"ext_id={self.source_candidate_id!r})>"
        )


# ---------------------------------------------------------------------------
# IngestionLog table
# ---------------------------------------------------------------------------


class IngestionLog(Base):
    """
    Audit / observability log for each ingestion run.

    One row is created every time a connector executes, regardless of whether
    it succeeded or failed.
    """

    __tablename__ = "ingestion_logs"

    source_name: Mapped[SourceName] = mapped_column(
        Enum(SourceName, name="source_name", create_constraint=True),
        nullable=False,
        comment="Which connector ran.",
    )
    status: Mapped[IngestionStatus] = mapped_column(
        Enum(IngestionStatus, name="ingestion_status", create_constraint=True),
        nullable=False,
        comment="Overall outcome of the run.",
    )
    candidates_fetched: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False,
        comment="Total candidate records retrieved from the source.",
    )
    candidates_new: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False,
        comment="Records that were genuinely new (not duplicates).",
    )
    candidates_duplicate: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False,
        comment="Records identified as duplicates and merged.",
    )
    candidates_pushed: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False,
        comment="Records successfully pushed to CEIPAL.",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Error details when status != success."
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When the ingestion run started.",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the ingestion run finished (null if still running).",
    )
    duration_seconds: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="Wall-clock duration in seconds."
    )

    # -- Table-level config --------------------------------------------------
    __table_args__ = (
        Index("ix_ingestion_logs_source_started", "source_name", "started_at"),
        {"comment": "Audit trail for every ingestion run."},
    )

    def __repr__(self) -> str:
        return (
            f"<IngestionLog(id={self.id!r}, source={self.source_name!r}, "
            f"status={self.status!r}, fetched={self.candidates_fetched})>"
        )
