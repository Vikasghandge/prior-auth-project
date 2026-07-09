"""Extractor-level safety gate: three checks that catch a bad extraction before it can
reach the ICD coder and cause a wrong downstream decision, rather than relying on the
ICD confidence gate (which only looks at coding, not what the Extractor itself found).

Checked in order, first match wins:
1. Implausible value  — a parsed number is outside any clinically sane range (a garbled
   or misparsed number, e.g. a duration read from the wrong sentence, would otherwise
   silently satisfy a policy's minimum-therapy-duration criterion).
2. Sparse extraction   — almost none of the optional clinical signals (treatments,
   duration, imaging, symptoms) were found at all, suggesting the note's phrasing/format
   fell outside what the regex extractor recognizes rather than that those details are
   genuinely absent from the note.
3. Low confidence      — the Extractor's own confidence score (which blends how many
   critical/optional fields were found) is below the bar for auto-proceeding.
"""
from __future__ import annotations

from prior_auth.schemas.extraction import ExtractedClinicalFacts

EXTRACTION_CONFIDENCE_THRESHOLD = 0.65
MAX_PLAUSIBLE_DURATION_WEEKS = 260  # 5 years — beyond this a duration is almost certainly misparsed


def extraction_review_reason(facts: ExtractedClinicalFacts) -> str | None:
    """Returns a human-readable reason to suspend for review, or None if the extraction
    looks trustworthy enough to proceed."""

    if (
        facts.conservative_therapy_duration_weeks is not None
        and facts.conservative_therapy_duration_weeks > MAX_PLAUSIBLE_DURATION_WEEKS
    ):
        return (
            f"Extracted conservative-therapy duration ({facts.conservative_therapy_duration_weeks} "
            f"weeks) is implausibly long and was likely misread from the wrong part of the note — "
            f"suspended for human review rather than trusting the number."
        )

    optional_signals = [
        facts.failed_treatments,
        facts.conservative_therapy_duration_weeks,
        facts.imaging_evidence,
        facts.symptoms,
    ]
    if sum(1 for v in optional_signals if v) == 0:
        return (
            "Almost no clinical detail (treatment history, therapy duration, imaging, symptoms) "
            "could be extracted from this note — its format may be unusual, so it is suspended "
            "for human review instead of proceeding on a near-empty record."
        )

    if facts.extraction_confidence < EXTRACTION_CONFIDENCE_THRESHOLD:
        return (
            f"Extractor confidence ({facts.extraction_confidence:.2f}) is below the minimum "
            f"threshold ({EXTRACTION_CONFIDENCE_THRESHOLD:.2f}) — some fields may be missing or "
            f"unreliable, so the case is suspended for human review."
        )

    return None
