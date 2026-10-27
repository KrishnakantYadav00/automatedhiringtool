"""
AHP Sourcing Engine — CEIPAL ATS Client.

Handles pushing normalized and deduplicated candidate profiles into the
CEIPAL ATS REST API with retry policies and batch handling.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import CeipalConfig
from app.models.candidate import Candidate, CandidateStatus
from app.models.schemas import CeipalPushResult

logger = logging.getLogger(__name__)


class CeipalClient:
    """Client for CEIPAL Applicant Tracking System (ATS)."""

    def __init__(self, config: CeipalConfig) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Create or reuse httpx client."""
        if self._client is None or self._client.is_closed:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            api_key = self.config.api_key.get_secret_value()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            if self.config.tenant_id:
                headers["X-Tenant-Id"] = self.config.tenant_id

            self._client = httpx.AsyncClient(
                base_url=self.config.api_url.rstrip("/"),
                headers=headers,
                timeout=30.0,
            )
        return self._client

    async def push_candidate(self, candidate: Candidate) -> CeipalPushResult:
        """Push an individual candidate to CEIPAL with retry logic."""
        api_key = self.config.api_key.get_secret_value()
        if not api_key:
            logger.info("CEIPAL API key not configured. Mocking successful push for development.")
            mock_id = f"CEIPAL-{candidate.id.hex[:8].upper()}"
            candidate.ceipal_candidate_id = mock_id
            candidate.status = CandidateStatus.PUSHED_TO_CEIPAL
            return CeipalPushResult(
                success=True,
                ceipal_candidate_id=mock_id,
                status_code=201,
                detail="Mock push (unconfigured API key)",
            )

        client = await self._get_client()
        payload = self._build_payload(candidate)

        for attempt in range(1, 4):
            try:
                response = await client.post("/candidates", json=payload)
                if response.status_code in {200, 201}:
                    data = response.json()
                    ceipal_id = str(data.get("candidate_id") or data.get("id") or "")
                    candidate.ceipal_candidate_id = ceipal_id
                    candidate.status = CandidateStatus.PUSHED_TO_CEIPAL
                    return CeipalPushResult(
                        success=True,
                        ceipal_candidate_id=ceipal_id,
                        status_code=response.status_code,
                    )
                elif response.status_code == 409:
                    # Already exists in CEIPAL
                    candidate.status = CandidateStatus.CONFIRMED
                    return CeipalPushResult(
                        success=True,
                        status_code=409,
                        detail="Candidate already exists in CEIPAL",
                    )
                else:
                    logger.warning("CEIPAL returned %s: %s", response.status_code, response.text)

            except Exception as exc:
                logger.error("Attempt %d: Error pushing to CEIPAL: %s", attempt, exc)
                if attempt < 3:
                    await asyncio.sleep(2 ** (attempt - 1))

        candidate.status = CandidateStatus.FAILED
        return CeipalPushResult(
            success=False,
            detail="Failed to push to CEIPAL after 3 attempts",
        )

    async def push_batch(self, candidates: list[Candidate]) -> list[CeipalPushResult]:
        """Push a batch of candidates to CEIPAL sequentially or concurrently."""
        results: list[CeipalPushResult] = []
        for candidate in candidates:
            res = await self.push_candidate(candidate)
            results.append(res)
        return results

    def _build_payload(self, candidate: Candidate) -> dict[str, Any]:
        """Convert internal Candidate model to CEIPAL candidate format."""
        return {
            "firstname": candidate.first_name,
            "lastname": candidate.last_name,
            "email": candidate.email,
            "phone": candidate.phone_e164 or candidate.phone,
            "city": candidate.location,
            "current_employer": candidate.current_company,
            "current_title": candidate.current_title,
            "total_experience": candidate.experience_years,
            "skills": ", ".join(candidate.skills) if candidate.skills else "",
            "source": candidate.source_first_seen,
            "resume_url": candidate.resume_url,
            "notes": "Ingested via AHP M1 Sourcing Engine",
        }

    async def health_check(self) -> dict[str, Any]:
        """Verify CEIPAL API endpoint connectivity."""
        if not self.config.api_key.get_secret_value():
            return {
                "source": "ceipal",
                "status": "unconfigured",
                "detail": "CEIPAL API key not set.",
            }

        try:
            client = await self._get_client()
            resp = await client.get("/health")
            return {
                "source": "ceipal",
                "status": "ok" if resp.status_code < 400 else "degraded",
                "status_code": resp.status_code,
            }
        except Exception as exc:
            return {"source": "ceipal", "status": "error", "detail": str(exc)}

    async def close(self) -> None:
        """Close client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
