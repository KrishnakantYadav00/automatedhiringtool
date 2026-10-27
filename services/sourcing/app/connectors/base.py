"""
AHP Sourcing Engine — Abstract base class for all source connectors.

Every concrete connector (Naukri, Shine, LinkedIn, Email) inherits from
:class:`BaseConnector`, gaining:

* Structured logging via ``self.logger``.
* Built-in retry wrapper with exponential back-off (:meth:`_retry`).
* Simple counter-based metrics tracking (:attr:`metrics`).
* Lifecycle hooks (:meth:`close`).

Sub-classes **must** implement :meth:`fetch_candidates` and
:meth:`health_check`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from app.models.schemas import RawCandidateData


# ---------------------------------------------------------------------------
# Metrics helper
# ---------------------------------------------------------------------------


@dataclass
class ConnectorMetrics:
    """Simple counter-based metrics bag attached to every connector."""

    fetched: int = 0
    errors: int = 0
    retries: int = 0
    last_run_duration_seconds: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def reset(self) -> None:
        """Reset all counters for a fresh run."""
        self.fetched = 0
        self.errors = 0
        self.retries = 0
        self.last_run_duration_seconds = 0.0
        self.extra.clear()

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serialisable snapshot of current metrics."""
        return {
            "fetched": self.fetched,
            "errors": self.errors,
            "retries": self.retries,
            "last_run_duration_seconds": round(self.last_run_duration_seconds, 3),
            **self.extra,
        }


# ---------------------------------------------------------------------------
# BaseConnector
# ---------------------------------------------------------------------------


class BaseConnector(ABC):
    """Abstract base for every source connector.

    Parameters
    ----------
    name:
        Human-readable connector name (used in logs and metrics keys).
    config:
        Connector-specific configuration dictionary (API keys, URLs, etc.).
    max_retries:
        Maximum number of retry attempts for transient failures.
    retry_base_delay:
        Base delay in seconds for exponential back-off between retries.
    """

    def __init__(
        self,
        name: str,
        config: dict[str, Any],
        *,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
    ) -> None:
        self.name = name
        self.config = config
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self.logger = logging.getLogger(f"connector.{name}")
        self.metrics = ConnectorMetrics()

    # -- Abstract interface ---------------------------------------------------

    @abstractmethod
    async def fetch_candidates(self) -> AsyncIterator[RawCandidateData]:
        """Yield raw candidate data from the external source.

        Implementations should:
        * Handle pagination internally.
        * Yield one :class:`RawCandidateData` per candidate.
        * Update ``self.metrics`` as they go.
        * *Not* raise on individual-record failures — log and continue.
        """
        ...  # pragma: no cover
        # Ensure the method is recognised as an async generator
        if False:  # noqa: SIM108 — type-hint placeholder
            yield  # type: ignore[misc]

    @abstractmethod
    async def health_check(self) -> dict[str, str]:
        """Test connectivity to the upstream source.

        Returns
        -------
        dict
            ``{"status": "ok", "detail": "..."}`` on success or
            ``{"status": "error", "detail": "..."}`` on failure.
        """
        ...  # pragma: no cover

    # -- Lifecycle ------------------------------------------------------------

    async def close(self) -> None:
        """Clean up resources (HTTP clients, IMAP connections, etc.).

        Sub-classes should override and call ``await super().close()`` last.
        """
        self.logger.info("connector.close", extra={"connector": self.name})

    # -- Retry helper ---------------------------------------------------------

    async def _retry(
        self,
        coro_factory,  # noqa: ANN001 – callable returning awaitable
        *,
        operation: str = "operation",
        max_retries: int | None = None,
    ) -> Any:
        """Execute an async callable with exponential back-off.

        Parameters
        ----------
        coro_factory:
            A *callable* (not an awaitable) that returns an awaitable.
            Example: ``lambda: client.get(url)``
        operation:
            Label used in log messages.
        max_retries:
            Override the instance-level ``self.max_retries``.

        Returns
        -------
        The result of the awaitable on success.

        Raises
        ------
        Exception
            The last exception after all retries are exhausted.
        """
        retries = max_retries if max_retries is not None else self.max_retries
        last_exc: BaseException | None = None

        for attempt in range(1, retries + 2):  # attempt 1 is the first try
            try:
                return await coro_factory()
            except Exception as exc:
                last_exc = exc
                if attempt > retries:
                    self.logger.error(
                        "connector.retry_exhausted",
                        extra={
                            "connector": self.name,
                            "operation": operation,
                            "attempt": attempt,
                            "error": str(exc),
                        },
                    )
                    raise
                delay = self.retry_base_delay * (2 ** (attempt - 1))
                self.metrics.retries += 1
                self.logger.warning(
                    "connector.retry",
                    extra={
                        "connector": self.name,
                        "operation": operation,
                        "attempt": attempt,
                        "delay_s": delay,
                        "error": str(exc),
                    },
                )
                await asyncio.sleep(delay)

        # Unreachable but keeps mypy happy.
        raise last_exc  # type: ignore[misc]

    # -- Timer helper ---------------------------------------------------------

    def _start_timer(self) -> float:
        """Record the start of a timed operation and return the start time."""
        return time.monotonic()

    def _stop_timer(self, start: float) -> float:
        """Record elapsed time since *start* and update metrics."""
        elapsed = time.monotonic() - start
        self.metrics.last_run_duration_seconds = elapsed
        return elapsed

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
