"""
Services package for Sourcing Engine.
"""

from app.services.ceipal_client import CeipalClient
from app.services.dedup import DeduplicationEngine
from app.services.normalizer import CandidateNormalizer
from app.services.pipeline import IngestionPipeline

__all__ = [
    "CandidateNormalizer",
    "CeipalClient",
    "DeduplicationEngine",
    "IngestionPipeline",
]
