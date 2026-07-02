"""The Level-4 confidence gate: the special rule from the project brief lives here as a
single, testable predicate rather than being inlined in the orchestrator or the agent.
"""
from __future__ import annotations

from prior_auth.config import RARE_DISEASE_CONFIDENCE_THRESHOLD
from prior_auth.schemas.icd_coding import ICDCodingResult


def is_rare_disease_low_confidence(icd_result: ICDCodingResult) -> bool:
    """Special rule: a rare-disease diagnosis coded below the confidence threshold must
    suspend the workflow for human review."""
    return icd_result.is_rare_disease and icd_result.confidence < RARE_DISEASE_CONFIDENCE_THRESHOLD
