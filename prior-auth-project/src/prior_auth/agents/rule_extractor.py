"""Deterministic fallback extractor: used when Azure OpenAI isn't configured, and always
available so the workflow is fully runnable/testable offline. Operates ONLY on already
PHI-masked text.
"""
from __future__ import annotations

import re

_AGE_SEX_INLINE = re.compile(r"Patient:\s*(\d{1,4})\s*([A-Za-z])\b")
_AGE_YEARS_OLD = re.compile(r"(\d{1,4})\s*[- ]?years?[- ]?old", re.IGNORECASE)

_TREATMENT_SENTENCE = re.compile(
    r"(?:Failed|Conservative management including)\s+(.*?)(?:\s+(?:over|was attempted|without|for)\b|[.\n])",
    re.IGNORECASE,
)
_WEEKS = re.compile(r"(\d{1,3})\s*weeks?", re.IGNORECASE)
_MONTHS = re.compile(r"(\d{1,3})\s*months?", re.IGNORECASE)

_IMAGING_SENTENCE = re.compile(
    r"([^.\n]*\b(?:X-ray|MRI|CT|HRCT|MRCP|imaging|echocardiogram|EMG|biopsy|angiography|"
    r"colonoscopy|enzyme assay|genetic (?:testing|confirmation)|antibody|autoantibody|"
    r"ceruloplasmin|copper|slit-lamp|serum|sweat chloride|confirmed by)\b[^.\n]*)",
    re.IGNORECASE,
)
_NO_IMAGING = re.compile(
    r"(no imaging|imaging.{0,20}pending|imaging workup is still pending|"
    r"has not been (?:performed|obtained|done)|not yet been (?:performed|obtained|done)|"
    r"has not yet been (?:performed|obtained|done))",
    re.IGNORECASE,
)

_PROCEDURE_SENTENCE = re.compile(
    r"(?:requests?(?: authorization for)?|recommends?|requesting)\s+(.*?)(?:[.\n]|$)",
    re.IGNORECASE,
)

_LATERALITY_WORDS = {
    "left": re.compile(r"\bleft\b", re.IGNORECASE),
    "right": re.compile(r"\bright\b", re.IGNORECASE),
    "bilateral": re.compile(r"\bbilateral\b", re.IGNORECASE),
}

_LEADING_PATIENT_TAG = re.compile(r"^Patient:\s*\d{1,4}\s*[A-Za-z]?\.?\s*", re.IGNORECASE)
_IDENTIFIER_LABELS = re.compile(
    r"\b(?:Name|DOB|MRN#?|residing at|phone|email|SSN)\s*:?\s*,?\s*", re.IGNORECASE
)
_REDACTION_TOKEN = re.compile(r"\[REDACTED_\w+\],?\s*")


def _find_age_sex(text: str) -> tuple[int | None, str | None]:
    m = _AGE_SEX_INLINE.search(text)
    if m:
        return int(m.group(1)), m.group(2).upper()

    m = _AGE_YEARS_OLD.search(text)
    if m:
        age = int(m.group(1))
        if re.search(r"\bfemale\b|\bwoman\b", text, re.IGNORECASE):
            return age, "F"
        if re.search(r"\bmale\b|\bman\b", text, re.IGNORECASE):
            return age, "M"
        return age, "U"
    return None, None


def _find_laterality(text: str) -> str:
    hits = [name for name, pattern in _LATERALITY_WORDS.items() if pattern.search(text)]
    if "bilateral" in hits:
        return "bilateral"
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        # Both "left" and "right" mentioned in the same section — report unknown rather
        # than guessing which one applies.
        return "unknown"
    return "not_applicable"


def _find_conservative_weeks(text: str, treatment_sentence: str | None) -> int | None:
    """Duration is read ONLY from the treatment-failure sentence itself, never the whole note —
    otherwise an unrelated duration elsewhere (e.g. "pain for 18 months", describing how long the
    patient has had symptoms, not how long conservative therapy was tried) gets misread as the
    conservative-therapy duration. That's not a harmless mixup: a fabricated 72-week therapy
    duration can make a policy's minimum-conservative-therapy criterion look satisfied when the
    note never actually said so."""
    if treatment_sentence:
        m = _WEEKS.search(treatment_sentence)
        if m:
            return int(m.group(1))
        m = _MONTHS.search(treatment_sentence)
        if m:
            return int(m.group(1)) * 4
    if re.search(r"no conservative therapy|not been (?:tried|attempted|prescribed)|has not tried", text, re.IGNORECASE):
        return 0
    return None


def _treatment_sentence_match(text: str) -> re.Match | None:
    return _TREATMENT_SENTENCE.search(text)


def _treatment_sentence_span(text: str, match: re.Match) -> str:
    """The full sentence the treatment-failure clause sits in (not just the captured group),
    so a trailing duration like "...was attempted over 15 weeks without improvement." is still
    in scope even though it comes after the captured treatment-list group ends. Scoped to the
    next period only, not the next newline — notes in this dataset wrap a single sentence across
    multiple lines with no period at the line break, so treating '\\n' as a sentence end would
    cut the duration off if it happens to land on the next line."""
    end = match.end()
    stop = text.find(".", end)
    sentence_end = stop if stop != -1 else len(text)
    return text[match.start():sentence_end]


def _find_treatments(match: re.Match | None) -> list[str]:
    if not match:
        return []
    raw = match.group(1)
    parts = re.split(r",\s*(?:and\s+)?|\s+and\s+", raw)
    return [p.strip().rstrip(".") for p in parts if p.strip()]


def _find_imaging(text: str) -> str | None:
    if _NO_IMAGING.search(text):
        return None
    m = _IMAGING_SENTENCE.search(text)
    if m:
        return m.group(1).strip()
    return None


def _clean_diagnosis_section(diagnosis_section: str) -> str | None:
    """The diagnosis field is the full clinical narrative (not just the first clause) so the
    ICD Coder's keyword/fuzzy matcher sees disease names mentioned in later sentences too —
    e.g. "... with hepatic dysfunction. Wilson's disease confirmed by ..." must not lose the
    "Wilson's disease" sentence just because it comes after the first period.
    """
    cleaned = _REDACTION_TOKEN.sub("", diagnosis_section)
    cleaned = _IDENTIFIER_LABELS.sub("", cleaned)
    cleaned = _LEADING_PATIENT_TAG.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.")
    return cleaned or None


def regex_extract(masked_text: str) -> dict:
    """Best-effort structured extraction from de-identified note text.

    Missing/invalid fields are simply absent (or left as parsed-but-invalid, e.g. an
    out-of-range age) so that Pydantic validation surfaces the failure rather than the
    extractor silently guessing — matching the "fail gracefully" requirement.
    """
    age, sex = _find_age_sex(masked_text)
    fields: dict = {}
    if age is not None:
        fields["age"] = age
    if sex is not None:
        fields["sex"] = sex

    # Split the note into a "diagnosis section" and the trailing procedure-request clause so
    # laterality can be read independently for each — this is what lets us catch a note that
    # documents one side but requests the procedure for the other (see edge cases EDGE-0006..10).
    procedure_match = _PROCEDURE_SENTENCE.search(masked_text)
    if procedure_match:
        diagnosis_section = masked_text[: procedure_match.start()]
        procedure_text = procedure_match.group(1)
    else:
        diagnosis_section = masked_text
        procedure_text = ""

    diagnosis = _clean_diagnosis_section(diagnosis_section)
    if diagnosis:
        fields["diagnosis"] = diagnosis

    fields["laterality"] = _find_laterality(diagnosis_section)
    fields["requested_procedure_laterality"] = (
        _find_laterality(procedure_text) if procedure_text else "not_applicable"
    )

    treatment_match = _treatment_sentence_match(masked_text)
    treatments = _find_treatments(treatment_match)
    fields["failed_treatments"] = treatments

    treatment_sentence = _treatment_sentence_span(masked_text, treatment_match) if treatment_match else None
    weeks = _find_conservative_weeks(masked_text, treatment_sentence)
    if weeks is not None:
        fields["conservative_therapy_duration_weeks"] = weeks

    imaging = _find_imaging(masked_text)
    fields["imaging_evidence"] = imaging

    if procedure_text:
        fields["requested_procedure"] = procedure_text.strip().rstrip(".")

    # Confidence reflects how many *critical* fields were successfully parsed out.
    critical = ["age", "sex", "diagnosis", "requested_procedure"]
    found = sum(1 for c in critical if fields.get(c) not in (None, ""))
    optional_bonus = 0.05 * sum(1 for v in (treatments, weeks, imaging) if v)
    fields["extraction_confidence"] = round(min(0.99, 0.5 + 0.1 * found + optional_bonus), 4)

    return fields
