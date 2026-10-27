"""
Integration tests for Sourcing Engine FastAPI routes.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_db
from app.main import app
from app.models.schemas import IngestionResult


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_root_and_health_endpoints():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Test /
        resp = await client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["module"] == "M1"
        assert data["status"] == "operational"

        # Test /health
        health_resp = await client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_trigger_invalid_source():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/api/v1/sourcing/trigger/unknown_portal")
        assert resp.status_code == 404
        assert "not supported" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_trigger_valid_source():
    mock_result = IngestionResult(
        source_name="naukri",
        total_fetched=5,
        total_normalised=5,
        total_new=4,
        total_merged=1,
        total_pushed_ceipal=4,
    )

    with patch("app.services.pipeline.IngestionPipeline.run", AsyncMock(return_value=mock_result)):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/v1/sourcing/trigger/naukri")
            assert resp.status_code == 200
            data = resp.json()
            assert data["source"] == "naukri"
            assert data["result"]["total_fetched"] == 5
            assert data["result"]["total_new"] == 4
