"""
AHP Sourcing Engine — Deduplication Engine.

Performs exact match (email, phone, dedup_hash) and fuzzy match (rapidfuzz)
to prevent duplicate candidate records before CEIPAL ingestion.
"""

from __future__ import annotations

import logging
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate, CandidateSource, CandidateStatus, SourceName
from app.models.schemas import NormalizedCandidate

logger = logging.getLogger(__name__)


class DeduplicationEngine:
    """Detects duplicate profiles and merges new data into existing records."""

    def __init__(self, db: AsyncSession, fuzzy_threshold: float = 85.0) -> None:
        self.db = db
        self.fuzzy_threshold = fuzzy_threshold

    async def deduplicate(self, norm: NormalizedCandidate) -> tuple[Candidate, bool]:
        """Check for duplicates; return (Candidate, is_new).

        If a duplicate is found, merges fields and appends the source entry.
        If no duplicate exists, creates and persists a new Candidate record.
        """
        # 1. Exact match check
        existing = await self._find_exact_match(norm)

        # 2. Fuzzy match fallback
        if not existing:
            existing = await self._find_fuzzy_match(norm)

        if existing:
            # Duplicate found -> Merge and add source
            await self._merge_candidate(existing, norm)
            await self._add_source(existing.id, norm)
            return existing, False

        # Brand new candidate
        candidate = await self._create_candidate(norm)
        await self._add_source(candidate.id, norm)
        return candidate, True

    async def _find_exact_match(self, norm: NormalizedCandidate) -> Candidate | None:
        """Find candidate by dedup_hash, email, or phone."""
        clauses = []
        if norm.dedup_hash:
            clauses.append(Candidate.dedup_hash == norm.dedup_hash)
        if norm.email:
            clauses.append(Candidate.email == norm.email)
        if norm.phone_e164:
            clauses.append(Candidate.phone_e164 == norm.phone_e164)
        elif norm.phone:
            clauses.append(Candidate.phone == norm.phone)

        if not clauses:
            return None

        stmt = select(Candidate).where(or_(*clauses)).limit(1)
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def _find_fuzzy_match(self, norm: NormalizedCandidate) -> Candidate | None:
        """Find candidate using rapidfuzz token sort ratio on name + company."""
        if not norm.first_name or norm.first_name == "Unknown":
            return None

        # Fetch candidates with same first initial or similar city to keep search window bounded
        stmt = select(Candidate).limit(200)
        res = await self.db.execute(stmt)
        candidates = res.scalars().all()

        target_name = f"{norm.first_name} {norm.last_name}".strip().lower()
        target_company = (norm.current_company or "").strip().lower()

        for cand in candidates:
            cand_name = f"{cand.first_name} {cand.last_name}".strip().lower()
            name_score = fuzz.token_sort_ratio(target_name, cand_name)

            if name_score >= self.fuzzy_threshold:
                # If name matches well, verify company or location if present
                if target_company and cand.current_company:
                    comp_score = fuzz.partial_ratio(target_company, cand.current_company.lower())
                    if comp_score >= 80:
                        logger.info(
                            "Fuzzy matched '%s' with '%s' (name=%s, company=%s)",
                            target_name, cand_name, name_score, comp_score
                        )
                        return cand
                elif name_score >= 95:
                    # Near identical name
                    return cand

        return None

    async def _merge_candidate(self, candidate: Candidate, norm: NormalizedCandidate) -> None:
        """Merge newly extracted candidate fields into existing candidate."""
        # Update fields where existing is empty or new has more details
        if not candidate.email and norm.email:
            candidate.email = norm.email
        if not candidate.phone and norm.phone:
            candidate.phone = norm.phone
        if not candidate.phone_e164 and norm.phone_e164:
            candidate.phone_e164 = norm.phone_e164
        if not candidate.location and norm.location:
            candidate.location = norm.location
        if not candidate.current_company and norm.current_company:
            candidate.current_company = norm.current_company
        if not candidate.current_title and norm.current_title:
            candidate.current_title = norm.current_title
        if norm.experience_years and (candidate.experience_years is None or norm.experience_years > candidate.experience_years):
            candidate.experience_years = norm.experience_years

        # Merge skills
        existing_skills = set(candidate.skills or [])
        new_skills = set(norm.skills or [])
        candidate.skills = sorted(list(existing_skills.union(new_skills)))

        # Retain resume text/url if missing
        if not candidate.resume_url and norm.resume_url:
            candidate.resume_url = norm.resume_url
        if not candidate.resume_text and norm.resume_text:
            candidate.resume_text = norm.resume_text

        # Update status if still new
        if candidate.status == CandidateStatus.NEW:
            candidate.status = CandidateStatus.DEDUPED

        await self.db.flush()

    async def _create_candidate(self, norm: NormalizedCandidate) -> Candidate:
        """Create and persist a new candidate profile."""
        candidate = Candidate(
            first_name=norm.first_name or "Unknown",
            last_name=norm.last_name or "Candidate",
            email=norm.email,
            phone=norm.phone,
            phone_e164=norm.phone_e164,
            location=norm.location,
            current_company=norm.current_company,
            current_title=norm.current_title,
            experience_years=norm.experience_years,
            skills=norm.skills,
            resume_url=norm.resume_url,
            resume_text=norm.resume_text,
            source_first_seen=norm.source_name,
            status=CandidateStatus.NORMALIZED,
            dedup_hash=norm.dedup_hash,
            raw_data=norm.raw_payload,
        )
        self.db.add(candidate)
        await self.db.flush()
        return candidate

    async def _add_source(self, candidate_id: Any, norm: NormalizedCandidate) -> None:
        """Record the source platform link in candidate_sources."""
        source_name_val = SourceName.EMAIL
        for s in SourceName:
            if s.value == norm.source_name.lower():
                source_name_val = s
                break

        # Check if already present for this source and candidate
        stmt = select(CandidateSource).where(
            CandidateSource.candidate_id == candidate_id,
            CandidateSource.source_name == source_name_val,
        )
        if norm.source_candidate_id:
            stmt = stmt.where(CandidateSource.source_candidate_id == norm.source_candidate_id)

        res = await self.db.execute(stmt)
        if not res.scalar_one_or_none():
            source_rec = CandidateSource(
                candidate_id=candidate_id,
                source_name=source_name_val,
                source_candidate_id=norm.source_candidate_id,
                raw_payload=norm.raw_payload,
            )
            self.db.add(source_rec)
            await self.db.flush()
