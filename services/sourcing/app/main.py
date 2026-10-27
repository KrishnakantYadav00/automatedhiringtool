"""
AHP Sourcing Engine — FastAPI Application Entrypoint.

Module M1: Aggregates candidates from Naukri, Shine, LinkedIn, and Email;
normalizes and deduplicates profiles before ingestion into CEIPAL ATS.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as sourcing_router
from app.config import get_settings
from app.db.base import Base
from app.db.session import engine
from app.scheduler.jobs import SchedulerService
from shared.common.logging import get_logger, setup_logging

settings = get_settings()
setup_logging(level=settings.log_level, json_format=settings.app_env != "development")
logger = get_logger("app.main")

scheduler_service = SchedulerService()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan event handler for startup and shutdown routines."""
    logger.info("Initializing AHP Sourcing Engine [M1]...")

    # Create tables automatically on startup for local/dev
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database schemas verified.")
    except Exception as exc:
        logger.warning("Could not auto-create tables on startup (PostgreSQL may be starting up): %s", exc)

    # Start background scheduler
    scheduler_service.start()
    logger.info("AHP Sourcing Engine startup complete.")

    yield

    logger.info("Shutting down AHP Sourcing Engine...")
    scheduler_service.shutdown()
    await engine.dispose()
    logger.info("AHP Sourcing Engine shutdown cleanly.")


app = FastAPI(
    title="AHP Sourcing Engine",
    description="M1 - Candidate Ingestion, Normalization, Deduplication & CEIPAL Integration Service",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routes
app.include_router(sourcing_router)


@app.get("/", tags=["Root"])
async def root() -> dict[str, str]:
    """Service metadata endpoint."""
    return {
        "service": "AHP Sourcing Engine",
        "module": "M1",
        "version": "0.1.0",
        "status": "operational",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def liveness() -> dict[str, str]:
    """Quick liveness probe for Docker healthchecks."""
    return {"status": "ok"}
