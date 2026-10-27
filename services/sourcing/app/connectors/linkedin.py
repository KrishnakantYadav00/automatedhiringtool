"""
AHP Sourcing Engine — LinkedIn connector.

Uses the LinkedIn API / Recruiter API to fetch candidates and yield
RawCandidateData for normalization and deduplication.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator

import httpx

from app.config import LinkedInConfig
from app.connectors.base import BaseConnector
from app.models.schemas import RawCandidateData

_LINKEDIN_API_BASE = "https://api.linkedin.com/v2"


class LinkedInConnector(BaseConnector):
    """Connector for the LinkedIn Recruiter / Talent Solutions API."""

    def __init__(self, config: LinkedInConfig) -> None:
        super().__init__(name="linkedin", config=config.model_dump())
        self._linkedin_config = config
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazily initialise the HTTP client."""
        if self._client is None or self._client.is_closed:
            token = self._linkedin_config.access_token.get_secret_value()
            self._client = httpx.AsyncClient(
                base_url=_LINKEDIN_API_BASE,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "X-Restli-Protocol-Version": "2.0.0",
                },
                timeout=30.0,
            )
        return self._client

    async def fetch_candidates(self) -> AsyncIterator[RawCandidateData]:
        """Fetch candidate profiles from LinkedIn API."""
        start_time = self._start_timer()

        if not self._linkedin_config.access_token.get_secret_value():
            self.logger.info("LinkedIn access token not configured. Returning empty stream.")
            self._stop_timer(start_time)
            return

        client = await self._get_client()
        start = 0
        count = 50

        try:
            while True:
                response = await client.get("/talentSearch", params={"start": start, "count": count})
                if response.status_code in {401, 403, 404}:
                    self.logger.warning("LinkedIn API returned %s", response.status_code)
                    break

                response.raise_for_status()
                data = response.json()
                elements = data.get("elements", [])
                if not elements:
                    break

                for item in elements:
                    self.metrics.fetched += 1
                    first_name = item.get("firstName", {}).get("localized", {}).get("en_US", "")
                    last_name = item.get("lastName", {}).get("localized", {}).get("en_US", "")
                    full_name = f"{first_name} {last_name}".strip() or item.get("formattedName")

                    yield RawCandidateData(
                        source_name="linkedin",
                        source_candidate_id=str(item.get("id") or item.get("urn", "")),
                        full_name=full_name,
                        email=item.get("emailAddress"),
                        phone=item.get("phoneNumber"),
                        location=item.get("locationName") or item.get("geoLocationName"),
                        current_company=item.get("headline"),
                        current_title=item.get("headline"),
                        experience_years=None,
                        skills=[],
                        resume_url=item.get("publicProfileUrl"),
                        resume_text=None,
                        raw_payload=item,
                    )

                start += count
                if start > 500:
                    break
        except Exception as exc:
            self.metrics.errors += 1
            self.logger.error("Error during LinkedIn candidate fetch: %s", exc)
        finally:
            self._stop_timer(start_time)

    async def health_check(self) -> dict[str, Any]:
        """Verify LinkedIn API connectivity."""
        if not self._linkedin_config.access_token.get_secret_value():
            return {
                "source": self.name,
                "status": "unconfigured",
                "detail": "LinkedIn access token not configured.",
            }

        try:
            client = await self._get_client()
            resp = await client.get("/me")
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
