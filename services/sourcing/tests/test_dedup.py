"""
Unit tests for DeduplicationEngine.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.candidate import Candidate, CandidateStatus
from app.models.schemas import NormalizedCandidate
from app.services.dedup import DeduplicationEngine


@pytest.fixture
def mock_session() -> AsyncMock:
    session = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.mark.asyncio
async def test_dedup_creates_new_candidate(mock_session: AsyncMock):
    # Mock no existing candidate found
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    engine = DeduplicationEngine(db=mock_session)

    norm = NormalizedCandidate(
        source_name="naukri",
        source_candidate_id="NK-123",
        first_name="Pooja",
        last_name="Verma",
        email="pooja.verma@example.com",
        phone_e164="+919876500000",
        location="Delhi",
        current_company="Acme Corp",
        experience_years=4.0,
        skills=["python"],
        dedup_hash="dummyhash123",
    )

    candidate, is_new = await engine.deduplicate(norm)

    assert is_new is True
    assert candidate.first_name == "Pooja"
    assert candidate.last_name == "Verma"
    assert candidate.email == "pooja.verma@example.com"
    mock_session.add.assert_called()


@pytest.mark.asyncio
async def test_dedup_merges_existing_candidate(mock_session: AsyncMock):
    existing = Candidate(
        id=uuid.uuid4(),
        first_name="Pooja",
        last_name="Verma",
        email="pooja.verma@example.com",
        phone_e164="+919876500000",
        location="Delhi",
        current_company="Acme Corp",
        experience_years=4.0,
        skills=["python"],
        status=CandidateStatus.NORMALIZED,
    )

    # First execute call returns existing candidate, second call for source check returns None
    mock_result1 = MagicMock()
    mock_result1.scalar_one_or_none.return_value = existing

    mock_result2 = MagicMock()
    mock_result2.scalar_one_or_none.return_value = None

    mock_session.execute.side_effect = [mock_result1, mock_result2]

    engine = DeduplicationEngine(db=mock_session)

    norm_incoming = NormalizedCandidate(
        source_name="linkedin",
        source_candidate_id="LI-999",
        first_name="Pooja",
        last_name="Verma",
        email="pooja.verma@example.com",
        phone_e164="+919876500000",
        location="Delhi",
        current_company="Acme Corp",
        experience_years=5.0,  # Higher experience
        skills=["python", "fastapi", "docker"],  # New skills
        dedup_hash="dummyhash123",
    )

    candidate, is_new = await engine.deduplicate(norm_incoming)

    assert is_new is False
    assert candidate.experience_years == 5.0
    assert "docker" in candidate.skills
    assert "fastapi" in candidate.skills
