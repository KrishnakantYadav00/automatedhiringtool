"""
AHP Sourcing Engine — Dependency Injection.

Provides FastAPI dependencies for database sessions, configuration,
connectors, and pipeline services.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.connectors.base import BaseConnector
from app.connectors.email import EmailConnector
from app.connectors.linkedin import LinkedInConnector
from app.connectors.naukri import NaukriConnector
from app.connectors.shine import ShineConnector
from app.db.session import get_db
from app.services.ceipal_client import CeipalClient
from app.services.dedup import DeduplicationEngine
from app.services.normalizer import CandidateNormalizer
from app.services.pipeline import IngestionPipeline


def get_normalizer() -> CandidateNormalizer:
    """Return a CandidateNormalizer instance."""
    return CandidateNormalizer()


def get_ceipal_client(
    settings: Annotated[Settings, Depends(get_settings)]
) -> CeipalClient:
    """Return configured CeipalClient instance."""
    return CeipalClient(config=settings.ceipal)


def get_dedup_engine(
    db: Annotated[AsyncSession, Depends(get_db)]
) -> DeduplicationEngine:
    """Return DeduplicationEngine bound to current DB session."""
    return DeduplicationEngine(db=db)


def get_connectors(
    settings: Annotated[Settings, Depends(get_settings)]
) -> dict[str, BaseConnector]:
    """Return dictionary of all available source connectors."""
    return {
        "email": EmailConnector(config=settings.imap),
        "naukri": NaukriConnector(config=settings.naukri),
        "shine": ShineConnector(config=settings.shine),
        "linkedin": LinkedInConnector(config=settings.linkedin),
    }


def get_pipeline(
    db: Annotated[AsyncSession, Depends(get_db)],
    normalizer: Annotated[CandidateNormalizer, Depends(get_normalizer)],
    dedup_engine: Annotated[DeduplicationEngine, Depends(get_dedup_engine)],
    ceipal_client: Annotated[CeipalClient, Depends(get_ceipal_client)],
) -> IngestionPipeline:
    """Return an IngestionPipeline instance with all dependencies wired."""
    return IngestionPipeline(
        db=db,
        normalizer=normalizer,
        dedup_engine=dedup_engine,
        ceipal_client=ceipal_client,
    )
