"""
Unit tests for IngestionPipeline.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.connectors.base import BaseConnector
from app.models.candidate import Candidate, CandidateStatus
from app.models.schemas import CeipalPushResult, NormalizedCandidate, RawCandidateData
from app.services.ceipal_client import CeipalClient
from app.services.dedup import DeduplicationEngine
from app.services.normalizer import CandidateNormalizer
from app.services.pipeline import IngestionPipeline


class MockTestConnector(BaseConnector):
    """Test connector yielding controlled test records."""

    def __init__(self, candidates: list[RawCandidateData]) -> None:
        super().__init__(name="mock", config={})
        self._candidates = candidates

    async def fetch_candidates(self) -> AsyncIterator[RawCandidateData]:
        for c in self._candidates:
            self.metrics.fetched += 1
            yield c

    async def health_check(self) -> dict[str, str]:
        return {"status": "ok", "source": "mock"}


@pytest.mark.asyncio
async def test_pipeline_run_success():
    mock_db = AsyncMock()
    mock_db.flush = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()

    normalizer = CandidateNormalizer()

    # Mock dedup
    mock_dedup = AsyncMock(spec=DeduplicationEngine)
    test_cand = Candidate(
        id=uuid.uuid4(),
        first_name="Amit",
        last_name="Patel",
        email="amit@example.com",
        status=CandidateStatus.NORMALIZED,
    )
    mock_dedup.deduplicate.return_value = (test_cand, True)

    # Mock CEIPAL
    mock_ceipal = AsyncMock(spec=CeipalClient)
    mock_ceipal.push_candidate.return_value = CeipalPushResult(
        success=True,
        ceipal_candidate_id="CEIPAL-12345",
        status_code=201,
    )

    pipeline = IngestionPipeline(
        db=mock_db,
        normalizer=normalizer,
        dedup_engine=mock_dedup,
        ceipal_client=mock_ceipal,
    )

    test_raw = RawCandidateData(
        source_name="email",
        source_candidate_id="EM-1",
        full_name="Amit Patel",
        email="amit@example.com",
        phone="+919811122233",
    )
    connector = MockTestConnector([test_raw])

    result = await pipeline.run(source_name="email", connector=connector, push_to_ceipal=True)

    assert result.total_fetched == 1
    assert result.total_normalised == 1
    assert result.total_new == 1
    assert result.total_merged == 0
    assert result.total_pushed_ceipal == 1
    assert result.total_errors == 0
    mock_db.commit.assert_called()
