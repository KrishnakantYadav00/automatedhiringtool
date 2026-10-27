"""
AHP Sourcing Engine — Ingestion Pipeline Orchestrator.

Coordinates candidate fetching, normalisation, deduplication, persistence,
and pushing verified candidate profiles to CEIPAL ATS.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.base import BaseConnector
from app.models.candidate import CandidateStatus, IngestionLog, IngestionStatus, SourceName
from app.models.schemas import IngestionResult, RawCandidateData
from app.services.ceipal_client import CeipalClient
from app.services.dedup import DeduplicationEngine
from app.services.normalizer import CandidateNormalizer

logger = logging.getLogger(__name__)


class IngestionPipeline:
    """Orchestrates candidate acquisition through ingestion stages."""

    def __init__(
        self,
        db: AsyncSession,
        normalizer: CandidateNormalizer,
        dedup_engine: DeduplicationEngine,
        ceipal_client: CeipalClient,
    ) -> None:
        self.db = db
        self.normalizer = normalizer
        self.dedup_engine = dedup_engine
        self.ceipal_client = ceipal_client

    async def run(
        self,
        source_name: str,
        connector: BaseConnector,
        push_to_ceipal: bool = True,
    ) -> IngestionResult:
        """Run an end-to-end ingestion cycle for a single connector."""
        start_time = time.monotonic()
        started_at = dt.datetime.now(dt.timezone.utc)
        result = IngestionResult(source_name=source_name, started_at=started_at)

        logger.info("Starting ingestion pipeline run for source: %s", source_name)

        new_candidates = []

        try:
            # 1. Stream & process candidates
            async for raw in connector.fetch_candidates():
                result.total_fetched += 1
                try:
                    # 2. Normalize
                    norm = self.normalizer.normalize(raw)
                    result.total_normalised += 1

                    # 3. Deduplicate & Store
                    candidate, is_new = await self.dedup_engine.deduplicate(norm)
                    if is_new:
                        result.total_new += 1
                        new_candidates.append(candidate)
                    else:
                        result.total_merged += 1

                except Exception as rec_err:
                    result.total_errors += 1
                    err_msg = f"Record error: {rec_err}"
                    logger.warning("Pipeline candidate processing error: %s", rec_err)
                    if len(result.error_details) < 10:
                        result.error_details.append(err_msg)

            await self.db.flush()

            # 4. Push new / deduped candidates to CEIPAL
            if push_to_ceipal and new_candidates:
                for cand in new_candidates:
                    try:
                        push_res = await self.ceipal_client.push_candidate(cand)
                        if push_res.success:
                            result.total_pushed_ceipal += 1
                        else:
                            result.total_push_failures += 1
                    except Exception as push_err:
                        result.total_push_failures += 1
                        logger.error("Error pushing candidate %s to CEIPAL: %s", cand.id, push_err)

            await self.db.commit()

        except Exception as pipe_err:
            await self.db.rollback()
            result.total_errors += 1
            result.error_details.append(f"Pipeline failure: {pipe_err}")
            logger.error("Critical error during ingestion for %s: %s", source_name, pipe_err)

        duration = time.monotonic() - start_time
        result.finished_at = dt.datetime.now(dt.timezone.utc)

        # 5. Record ingestion log
        await self._log_ingestion(source_name, result, started_at, result.finished_at, duration)

        logger.info(
            "Completed ingestion for %s in %.2fs: fetched=%d, new=%d, merged=%d, pushed=%d",
            source_name, duration, result.total_fetched, result.total_new,
            result.total_merged, result.total_pushed_ceipal,
        )

        return result

    async def _log_ingestion(
        self,
        source_name: str,
        res: IngestionResult,
        started_at: dt.datetime,
        completed_at: dt.datetime,
        duration: float,
    ) -> None:
        """Persist audit record of this ingestion cycle."""
        source_enum = SourceName.EMAIL
        for s in SourceName:
            if s.value == source_name.lower():
                source_enum = s
                break

        if res.total_errors == 0:
            status = IngestionStatus.SUCCESS
        elif res.total_new > 0 or res.total_merged > 0:
            status = IngestionStatus.PARTIAL
        else:
            status = IngestionStatus.FAILED

        err_str = "; ".join(res.error_details) if res.error_details else None

        log_entry = IngestionLog(
            source_name=source_enum,
            status=status,
            candidates_fetched=res.total_fetched,
            candidates_new=res.total_new,
            candidates_duplicate=res.total_merged,
            candidates_pushed=res.total_pushed_ceipal,
            error_message=err_str,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=round(duration, 3),
        )

        try:
            self.db.add(log_entry)
            await self.db.commit()
        except Exception as exc:
            logger.error("Failed to persist ingestion log: %s", exc)
            await self.db.rollback()
