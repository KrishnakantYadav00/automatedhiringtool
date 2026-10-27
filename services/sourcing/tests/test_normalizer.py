"""
Unit tests for CandidateNormalizer.
"""

from __future__ import annotations

import pytest

from app.models.schemas import RawCandidateData
from app.services.normalizer import CandidateNormalizer


@pytest.fixture
def normalizer() -> CandidateNormalizer:
    return CandidateNormalizer()


def test_normalize_name_salutations(normalizer: CandidateNormalizer):
    first, last = normalizer.normalize_name("Mr. Arvind Kumar")
    assert first == "Arvind"
    assert last == "Kumar"

    first, last = normalizer.normalize_name("Dr. Priya Sharma")
    assert first == "Priya"
    assert last == "Sharma"

    first, last = normalizer.normalize_name("Siddharth")
    assert first == "Siddharth"
    assert last == "Candidate"

    first, last = normalizer.normalize_name(None)
    assert first == "Unknown"
    assert last == "Candidate"


def test_normalize_email(normalizer: CandidateNormalizer):
    assert normalizer.normalize_email("  Test.User@Domain.COM  ") == "test.user@domain.com"
    assert normalizer.normalize_email("invalid-email-address") is None
    assert normalizer.normalize_email(None) is None


def test_normalize_phone(normalizer: CandidateNormalizer):
    cleaned, e164 = normalizer.normalize_phone("+91 98765-43210")
    assert e164 == "+919876543210"

    cleaned, e164 = normalizer.normalize_phone("9876543210")
    assert e164 == "+919876543210"

    cleaned, e164 = normalizer.normalize_phone(None)
    assert cleaned is None
    assert e164 is None


def test_normalize_location_abbreviations(normalizer: CandidateNormalizer):
    assert normalizer.normalize_location("blr") == "Bangalore"
    assert normalizer.normalize_location("BENGALURU") == "Bangalore"
    assert normalizer.normalize_location("hyd") == "Hyderabad"
    assert normalizer.normalize_location("ncr") == "Delhi-NCR"
    assert normalizer.normalize_location("pune") == "Pune"


def test_normalize_experience(normalizer: CandidateNormalizer):
    assert normalizer.normalize_experience("5.5 yrs") == 5.5
    assert normalizer.normalize_experience("4 years") == 4.0
    assert normalizer.normalize_experience(3) == 3.0
    assert normalizer.normalize_experience(None) is None


def test_normalize_skills(normalizer: CandidateNormalizer):
    skills = ["Python", "python", " FastAPI ", "DOCKER", "FastAPI"]
    clean = normalizer.normalize_skills(skills)
    assert clean == ["docker", "fastapi", "python"]


def test_dedup_hash_generation(normalizer: CandidateNormalizer):
    hash1 = normalizer.generate_dedup_hash("john@example.com", "+919876543210")
    hash2 = normalizer.generate_dedup_hash("JOHN@example.com", "+919876543210")
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 length


def test_end_to_end_normalization(normalizer: CandidateNormalizer, sample_raw_candidate: RawCandidateData):
    norm = normalizer.normalize(sample_raw_candidate)
    assert norm.first_name == "Rahul"
    assert norm.last_name == "Sharma"
    assert norm.email == "rahul.sharma@example.com"
    assert norm.phone_e164 == "+919876543210"
    assert norm.location == "Bangalore"
    assert norm.experience_years == 5.5
    assert "fastapi" in norm.skills
    assert norm.dedup_hash is not None
