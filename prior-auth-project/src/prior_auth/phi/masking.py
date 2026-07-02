"""PHI masking applied BEFORE any text leaves the Extractor / is sent to an LLM or downstream agent.

This is deliberately regex/rule-based (not LLM-based): PHI detection must be deterministic
and auditable, not subject to model sampling variance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_NAME_LINE = re.compile(r"\b(?:Patient|Name)\s*:\s*(?P<name>[A-Z][a-zA-Z.'-]+(?:\s+[A-Z][a-zA-Z.'-]+)*)")
_HONORIFIC_NAME = re.compile(r"\b(?:Mr|Mrs|Ms|Dr)\.\s+[A-Z][a-zA-Z'-]+(?:\s+[A-Z][a-zA-Z'-]+)*")
_MRN = re.compile(r"\bMRN\s*#?\s*:?\s*([A-Za-z0-9-]+)", re.IGNORECASE)
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
_DOB = re.compile(r"\bDOB\s*:?\s*(\d{1,2}/\d{1,2}/\d{2,4})", re.IGNORECASE)
_ADDRESS = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9.'-]+(?:\s+[A-Za-z0-9.'-]+){0,4}\s+"
    r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Ln|Lane|Dr|Drive|Ct|Court|"
    r"Terrace|Ter|Way|Circle|Cir|Place|Pl|Parkway|Pkwy|Highway|Hwy|Trail|Trl)\b\.?,?\s*"
    r"[A-Za-z .]*,?\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?"
)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


@dataclass
class MaskingResult:
    masked_text: str
    fields_masked: list[str] = field(default_factory=list)
    detected_name: str | None = None
    detected_mrn: str | None = None
    detected_dob: str | None = None
    detected_address: str | None = None
    detected_phone: str | None = None

    @property
    def phi_detected(self) -> bool:
        return bool(self.fields_masked)


def mask_phi(text: str) -> MaskingResult:
    """Strip direct identifiers from clinical note text, returning masked text + what was found.

    The detected raw values are returned ONLY so a case can retain them at the top-level
    (case-management) boundary — they must never be forwarded into `masked_text` or into
    any downstream agent payload.
    """
    masked = text
    fields_masked: list[str] = []
    detected_name = None
    detected_mrn = None
    detected_dob = None
    detected_address = None
    detected_phone = None

    m = _NAME_LINE.search(masked)
    if m:
        detected_name = m.group("name").strip()
        masked = masked[: m.start("name")] + "[REDACTED_NAME]" + masked[m.end("name"):]
        fields_masked.append("name")

    for hm in list(_HONORIFIC_NAME.finditer(masked)):
        masked = masked.replace(hm.group(0), "[REDACTED_NAME]")
        if "name" not in fields_masked:
            fields_masked.append("name")

    m = _MRN.search(masked)
    if m:
        detected_mrn = m.group(1)
        masked = masked[: m.start(1)] + "[REDACTED_MRN]" + masked[m.end(1):]
        fields_masked.append("mrn")

    m = _DOB.search(masked)
    if m:
        detected_dob = m.group(1)
        masked = masked[: m.start(1)] + "[REDACTED_DOB]" + masked[m.end(1):]
        fields_masked.append("dob")

    m = _ADDRESS.search(masked)
    if m:
        detected_address = m.group(0)
        masked = masked.replace(m.group(0), "[REDACTED_ADDRESS]")
        fields_masked.append("address")

    m = _PHONE.search(masked)
    if m:
        detected_phone = m.group(0)
        masked = masked.replace(m.group(0), "[REDACTED_PHONE]")
        fields_masked.append("phone")

    masked = _SSN.sub("[REDACTED_SSN]", masked)
    if _SSN.search(text):
        fields_masked.append("ssn")

    masked = _EMAIL.sub("[REDACTED_EMAIL]", masked)
    if _EMAIL.search(text) and "email" not in fields_masked:
        fields_masked.append("email")

    return MaskingResult(
        masked_text=masked,
        fields_masked=fields_masked,
        detected_name=detected_name,
        detected_mrn=detected_mrn,
        detected_dob=detected_dob,
        detected_address=detected_address,
        detected_phone=detected_phone,
    )


_PHI_LEAK_CHECK_PATTERNS = [_NAME_LINE, _HONORIFIC_NAME, _MRN, _SSN, _PHONE, _DOB, _ADDRESS, _EMAIL]


def contains_phi(text: str) -> bool:
    """Boundary guard: run immediately before any payload is sent to Policy RAG / Form Filler / an LLM."""
    return any(p.search(text) for p in _PHI_LEAK_CHECK_PATTERNS)
