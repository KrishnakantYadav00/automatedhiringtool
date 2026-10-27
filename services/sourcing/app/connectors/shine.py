"""
AHP Sourcing Engine — Shine job-portal connector.

Fetches candidate profiles from Shine API and converts them into
RawCandidateData for normalization and deduplication.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

import httpx

from app.config import ShineConfig
from app.connectors.base import BaseConnector
from app.models.schemas import RawCandidateData


class ShineConnector(BaseConnector):
    """Connector for the Shine job portal API."""

    def __init__(self, config: ShineConfig) -> None:
        super().__init__(name="shine", config=config.model_dump())
        self._shine_config = config
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily initialise the HTTP client."""
        if self._client is None or self._client.is_closed:
            api_key = self._shine_config.api_key.get_secret_value()
            self._client = httpx.AsyncClient(
                base_url=self._shine_config.api_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def fetch_candidates(self) -> AsyncIterator[RawCandidateData]:
        """Fetch candidate profiles from Shine API."""
        start_time = self._start_timer()

        if not self._shine_config.api_key.get_secret_value():
            self.logger.info("Shine API key not configured. Returning empty stream.")
            self._stop_timer(start_time)
            return

        client = await self._get_client()
        page = 1

        try:
            while True:
                response = await client.get("/candidates", params={"page": page, "page_size": 50})
                if response.status_code == 404 or response.status_code == 401:
                    break

                response.raise_for_status()
                data = response.json()
                items = data.get("results") or data.get("candidates") or []
                if not items:
                    break

                for item in items:
                    self.metrics.fetched += 1
                    yield RawCandidateData(
                        source_name="shine",
                        source_candidate_id=str(item.get("candidate_id") or item.get("id") or ""),
                        full_name=item.get("name") or f"{item.get('first_name', '')} {item.get('last_name', '')}".strip(),
                        email=item.get("email"),
                        phone=item.get("phone") or item.get("contact_no"),
                        location=item.get("current_location") or item.get("city"),
                        current_company=item.get("organization") or item.get("current_company"),
                        current_title=item.get("designation") or item.get("current_title"),
                        experience_years=item.get("total_experience") or item.get("experience"),
                        skills=item.get("skills") if isinstance(item.get("skills"), list) else [],
                        resume_url=item.get("resume_url"),
                        resume_text=item.get("resume_text"),
                        raw_payload=item,
                    )

                page += 1
                if page > 50:
                    break
        except Exception as exc:
            self.metrics.errors += 1
            self.logger.error("Error during Shine candidate fetch: %s", exc)
        finally:
            self._stop_timer(start_time)

    async def health_check(self) -> dict[str, Any]:
        """Verify Shine API connectivity."""
        if not self._shine_config.api_key.get_secret_value():
            return {
                "source": self.name,
                "status": "unconfigured",
                "detail": "Shine API key not configured.",
            }

        try:
            client = await self._get_client()
            resp = await client.get("/health")
            return {
                "source": self.name,
                "status": "ok" if resp.status_code < 400 else "degraded",
                "status_code": resp.status_code,
            }
        except Exception as exc:
            return {"source": self.name, "status": "error", "detail": str(exc)}

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        await super().close()
