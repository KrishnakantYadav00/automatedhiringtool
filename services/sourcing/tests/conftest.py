"""
Pytest configuration and test fixtures for Sourcing Engine.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.schemas import RawCandidateData


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_raw_candidate() -> RawCandidateData:
    """Fixture providing a realistic raw candidate payload."""
    return RawCandidateData(
        source_name="naukri",
        source_candidate_id="NK-9921",
        full_name="Mr. Rahul Sharma",
        email="Rahul.Sharma@Example.COM",
        phone="+91 98765 43210",
        location="blr",
        current_company="Infosys Ltd",
        current_title="Senior Software Engineer",
        experience_years="5.5 yrs",
        skills=["Python", "FastAPI", "SQL", "python"],
        resume_url="https://s3.amazonaws.com/resumes/rahul.pdf",
        resume_text="Experienced Python developer with 5+ years building FastAPI microservices.",
        raw_payload={"id": "NK-9921", "applicant_source": "portal"},
    )


@pytest.fixture
def sample_duplicate_candidate() -> RawCandidateData:
    """Fixture providing candidate matching Rahul with minor differences."""
    return RawCandidateData(
        source_name="linkedin",
        source_candidate_id="LI-4412",
        full_name="Rahul Sharma",
        email="rahul.sharma@example.com",
        phone="9876543210",
        location="Bengaluru",
        current_company="Infosys",
        current_title="Lead Engineer",
        experience_years=6.0,
        skills=["Python", "Docker", "PostgreSQL"],
        resume_url="https://linkedin.com/in/rahul",
        raw_payload={"id": "LI-4412"},
    )
