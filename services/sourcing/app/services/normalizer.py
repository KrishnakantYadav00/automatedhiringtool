"""
AHP Sourcing Engine — Candidate Normalizer.

Standardizes raw candidate payloads from external sources into a unified,
predictable NormalizedCandidate representation.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

import phonenumbers
from phonenumbers import NumberParseException

from app.models.schemas import NormalizedCandidate, RawCandidateData

logger = logging.getLogger(__name__)

# Common salutations to strip
SALUTATIONS = {
    "mr", "mr.", "mrs", "mrs.", "ms", "ms.", "dr", "dr.", "prof", "prof.", "er", "er."
}

# Common Indian location abbreviations
CITY_MAPPINGS = {
    "blr": "Bangalore",
    "bengaluru": "Bangalore",
    "hyd": "Hyderabad",
    "delhi ncr": "Delhi-NCR",
    "ncr": "Delhi-NCR",
    "ggn": "Gurgaon",
    "gurugram": "Gurgaon",
    "bom": "Mumbai",
    "mumbai city": "Mumbai",
    "maa": "Chennai",
    "madras": "Chennai",
    "pnq": "Pune",
    "calcutta": "Kolkata",
    "kol": "Kolkata",
}


class CandidateNormalizer:
    """Normalizes raw candidate inputs into structured format."""

    def normalize(self, raw: RawCandidateData) -> NormalizedCandidate:
        """Transform a RawCandidateData object into NormalizedCandidate."""
        first_name, last_name = self.normalize_name(raw.full_name)
        norm_email = self.normalize_email(raw.email)
        norm_phone, phone_e164 = self.normalize_phone(raw.phone)
        norm_location = self.normalize_location(raw.location)
        norm_experience = self.normalize_experience(raw.experience_years)
        norm_skills = self.normalize_skills(raw.skills)

        # Generate deduplication fingerprint hash
        dedup_hash = self.generate_dedup_hash(norm_email, phone_e164)

        return NormalizedCandidate(
            source_name=raw.source_name,
            source_candidate_id=raw.source_candidate_id,
            first_name=first_name,
            last_name=last_name,
            email=norm_email,
            phone=norm_phone,
            phone_e164=phone_e164,
            location=norm_location,
            current_company=raw.current_company.strip() if raw.current_company else None,
            current_title=raw.current_title.strip() if raw.current_title else None,
            experience_years=norm_experience,
            skills=norm_skills,
            resume_url=raw.resume_url,
            resume_text=raw.resume_text,
            raw_payload=raw.raw_payload,
            dedup_hash=dedup_hash,
        )

    def normalize_name(self, full_name: str | None) -> tuple[str, str]:
        """Split and clean first name and last name."""
        if not full_name:
            return "Unknown", "Candidate"

        # Remove extra whitespaces
        clean_name = " ".join(full_name.strip().split())
        parts = clean_name.split()

        # Filter out salutations
        filtered_parts = [p for p in parts if p.lower() not in SALUTATIONS]
        if not filtered_parts:
            filtered_parts = parts

        if len(filtered_parts) == 1:
            first_name = filtered_parts[0].title()
            last_name = "Candidate"
        else:
            first_name = filtered_parts[0].title()
            last_name = " ".join(p.title() for p in filtered_parts[1:])

        return first_name, last_name

    def normalize_email(self, email_str: str | None) -> str | None:
        """Validate and lowercase email address."""
        if not email_str:
            return None
        cleaned = email_str.strip().lower()
        if "@" in cleaned and "." in cleaned.split("@")[-1]:
            return cleaned
        return None

    def normalize_phone(self, phone_str: str | None, default_region: str = "IN") -> tuple[str | None, str | None]:
        """Normalize phone number to original cleaned string and E.164 format."""
        if not phone_str:
            return None, None

        cleaned = re.sub(r"[^\d+]", "", phone_str.strip())
        if not cleaned:
            return None, None

        e164 = None
        try:
            parsed = phonenumbers.parse(cleaned, default_region)
            if phonenumbers.is_valid_number(parsed):
                e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except NumberParseException:
            # Fallback manual parsing for Indian 10-digit numbers
            digits = re.sub(r"\D", "", cleaned)
            if len(digits) == 10:
                e164 = f"+91{digits}"
            elif len(digits) == 12 and digits.startswith("91"):
                e164 = f"+{digits}"

        return cleaned, e164

    def normalize_location(self, location: str | None) -> str | None:
        """Map city names or aliases to canonical names."""
        if not location:
            return None
        cleaned = location.strip()
        lower_loc = cleaned.lower()
        for alias, canonical in CITY_MAPPINGS.items():
            if alias == lower_loc or f" {alias} " in f" {lower_loc} ":
                return canonical
        return cleaned.title()

    def normalize_experience(self, exp: float | str | None) -> float | None:
        """Parse experience values like '5.5 yrs' or 5 into float."""
        if exp is None:
            return None
        if isinstance(exp, (int, float)):
            return float(exp)

        exp_str = str(exp).lower().strip()
        match = re.search(r"(\d+(\.\d+)?)", exp_str)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    def normalize_skills(self, skills: list[str] | None) -> list[str]:
        """Lowercase, trim and deduplicate skills."""
        if not skills:
            return []
        seen = set()
        clean_skills = []
        for s in skills:
            if isinstance(s, str):
                cleaned = s.strip().lower()
                if cleaned and cleaned not in seen:
                    seen.add(cleaned)
                    clean_skills.append(cleaned)
        return sorted(clean_skills)

    def generate_dedup_hash(self, email: str | None, phone_e164: str | None) -> str | None:
        """Generate SHA-256 hash fingerprint combining email and phone."""
        seed_parts = []
        if email:
            seed_parts.append(email.lower().strip())
        if phone_e164:
            seed_parts.append(phone_e164.strip())

        if not seed_parts:
            return None

        seed = "|".join(seed_parts)
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()
