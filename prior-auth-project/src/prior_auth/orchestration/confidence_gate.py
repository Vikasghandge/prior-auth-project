"""The ICD confidence gate: a single, testable predicate rather than being inlined in the
orchestrator or the agent.

Global rule: ANY top ICD candidate below the confidence threshold suspends the workflow for
human review — not just rare-disease candidates. A wrong code is equally costly whether or not
the underlying condition happens to be rare, and this closes the coverage-gap failure mode
where a common-looking but under-represented diagnosis could previously slip through at a
lower bar just because it wasn't flagged rare.
"""
from __future__ import annotations

from prior_auth.config import ICD_CONFIDENCE_THRESHOLD
from prior_auth.schemas.icd_coding import ICDCodingResult


def is_low_confidence(icd_result: ICDCodingResult) -> bool:
    return icd_result.confidence < ICD_CONFIDENCE_THRESHOLD


def low_confidence_reason(icd_result: ICDCodingResult) -> str:
    return (
        f"ICD coding confidence is below the minimum threshold ({ICD_CONFIDENCE_THRESHOLD:.2f}). "
        f"Manual review is required."
    )
