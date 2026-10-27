"""
AHP Sourcing Engine — Scheduled Ingestion Tasks.

Uses APScheduler to periodically run candidate ingestion across all active
connectors (Naukri, Shine, LinkedIn, Email).
"""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.connectors.email import EmailConnector
from app.connectors.linkedin import LinkedInConnector
from app.connectors.naukri import NaukriConnector
from app.connectors.shine import ShineConnector
from app.db.session import async_session_factory
from app.services.ceipal_client import CeipalClient
from app.services.dedup import DeduplicationEngine
from app.services.normalizer import CandidateNormalizer
from app.services.pipeline import IngestionPipeline

logger = logging.getLogger(__name__)


class SchedulerService:
    """Manages periodic sourcing jobs."""

    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler()
        self.settings = get_settings()

    def start(self) -> None:
        """Register connector polling jobs and start scheduler."""
        interval = self.settings.polling_interval_minutes

        self.scheduler.add_job(
            self._run_connector_job,
            "interval",
            minutes=interval,
            args=["email"],
            id="job_email",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_connector_job,
            "interval",
            minutes=interval,
            args=["naukri"],
            id="job_naukri",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_connector_job,
            "interval",
            minutes=interval,
            args=["shine"],
            id="job_shine",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_connector_job,
            "interval",
            minutes=interval,
            args=["linkedin"],
            id="job_linkedin",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info("Scheduler started with %d-minute polling interval.", interval)

    def shutdown(self) -> None:
        """Stop scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped.")

    async def _run_connector_job(self, source_name: str) -> None:
        """Execution task for a single connector."""
        logger.info("Running scheduled ingestion for %s...", source_name)

        connector_map = {
            "email": lambda: EmailConnector(self.settings.imap),
            "naukri": lambda: NaukriConnector(self.settings.naukri),
            "shine": lambda: ShineConnector(self.settings.shine),
            "linkedin": lambda: LinkedInConnector(self.settings.linkedin),
        }

        factory = connector_map.get(source_name)
        if not factory:
            return

        connector = factory()
        normalizer = CandidateNormalizer()
        ceipal_client = CeipalClient(self.settings.ceipal)

        async with async_session_factory() as session:
            dedup = DeduplicationEngine(session)
            pipeline = IngestionPipeline(
                db=session,
                normalizer=normalizer,
                dedup_engine=dedup,
                ceipal_client=ceipal_client,
            )
            try:
                await pipeline.run(source_name=source_name, connector=connector)
            except Exception as exc:
                logger.error("Error in scheduled job for %s: %s", source_name, exc)
            finally:
                await connector.close()
                await ceipal_client.close()
