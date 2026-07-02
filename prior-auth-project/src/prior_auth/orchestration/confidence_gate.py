"""The Level-4 confidence gate: the special rule from the project brief lives here as a
single, testable predicate rather than being inlined in the orchestrator or the agent.
"""
from __future__ import annotations

from prior_auth.config import GENERAL_ICD_CONFIDENCE_THRESHOLD, RARE_DISEASE_CONFIDENCE_THRESHOLD
from prior_auth.schemas.icd_coding import ICDCodingResult


def is_rare_disease_low_confidence(icd_result: ICDCodingResult) -> bool:
    """Special rule from the brief: a rare-disease diagnosis coded below the (stricter)
    confidence threshold must suspend the workflow for human review."""
    return icd_result.is_rare_disease and icd_result.confidence < RARE_DISEASE_CONFIDENCE_THRESHOLD


def is_generally_low_confidence(icd_result: ICDCodingResult) -> bool:
    """General safety net beyond the brief's rare-disease-only rule: ANY top candidate below
    this bar is too unreliable to act on automatically — most often because the diagnosis isn't
    well represented in the knowledge graph at all, so the matcher is guessing rather than
    matching. Catches exactly the failure mode where a wrong code would otherwise be presented
    with no rare-disease flag to trigger the stricter rule above."""
    return icd_result.confidence < GENERAL_ICD_CONFIDENCE_THRESHOLD


def low_confidence_reason(icd_result: ICDCodingResult) -> str:
    if is_rare_disease_low_confidence(icd_result):
        return (
            f"Rare disease candidate '{icd_result.code_description}' has coding confidence "
            f"{icd_result.confidence:.2f}, below the {RARE_DISEASE_CONFIDENCE_THRESHOLD:.2f} gate "
            f"threshold — suspended for human coding review."
        )
    return (
        f"Coding confidence {icd_result.confidence:.2f} for candidate "
        f"'{icd_result.code_description}' is below the {GENERAL_ICD_CONFIDENCE_THRESHOLD:.2f} "
        f"general threshold — likely an under-represented diagnosis in the knowledge graph — "
        f"suspended for human coding review rather than risking a wrong code."
    )
