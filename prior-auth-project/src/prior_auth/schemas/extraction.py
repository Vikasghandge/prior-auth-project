"""Schemas for Agent 1 (Extractor) output.

PHI and clinical facts are modeled as SEPARATE objects on purpose: `PatientIdentifiers`
never leaves the Extractor/PHI-masking boundary, while `ExtractedClinicalFacts` is the
de-identified payload that is typed-handed-off to every downstream agent.

`diagnosis` is the normalized *primary* diagnosis (short, human-facing). The full clinical
narrative the note was extracted from is preserved separately in `diagnosis_narrative` — the
ICD Coder and Policy RAG keyword/fuzzy matchers run against that (via `narrative_text`) so
their signal is unchanged, while `diagnosis` stays clean for display and downstream reuse.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from prior_auth.schemas.common import Laterality


class PatientIdentifiers(BaseModel):
    """Direct/quasi identifiers extracted from a note. PHI — must stay behind the masking boundary."""

    name: Optional[str] = None
    mrn: Optional[str] = None
    dob: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None

    def any_present(self) -> bool:
        return any([self.name, self.mrn, self.dob, self.address, self.phone])


class ClinicalModifiers(BaseModel):
    """Clinically relevant modifiers pulled *out* of the diagnosis so the diagnosis itself stays
    a clean disease name. Absent modifiers are `null` (severity/duration) or `not_applicable`
    (laterality) — never guessed."""

    severity: Optional[str] = None  # mild / moderate / severe / advanced / chronic / acute / ...
    laterality: str = Field(default="not_applicable", pattern="^(left|right|bilateral|not_applicable)$")
    duration_weeks: Optional[int] = Field(default=None, ge=0)


class ImagingEvidence(BaseModel):
    """Structured view of the imaging statement. `modality` is `"Imaging"` when a study is
    referenced but its modality is not stated; both fields are `null` when the note documents
    no imaging (or imaging is pending)."""

    modality: Optional[str] = None  # "X-ray", "MRI", "CT", ... or "Imaging" if present-but-unspecified
    finding: Optional[str] = None


class ExtractedClinicalFacts(BaseModel):
    """De-identified clinical facts extracted from a doctor's note. Safe to hand off downstream."""

    case_id: str
    age: int = Field(ge=0, le=130)
    sex: str = Field(pattern="^(M|F|U)$")
    specialty: str = "Unknown"
    diagnosis: str = Field(min_length=3)
    # Full narrative the diagnosis was drawn from; kept so the downstream keyword/fuzzy matchers
    # see disease names that appear later in the note (e.g. rare-disease cases). Defaults to the
    # diagnosis when a caller only supplies the short form (see `narrative_text`).
    diagnosis_narrative: str = ""
    clinical_modifiers: ClinicalModifiers = Field(default_factory=ClinicalModifiers)
    laterality: Laterality = Laterality.NOT_APPLICABLE
    requested_procedure_laterality: Laterality = Laterality.NOT_APPLICABLE
    symptoms: list[str] = Field(default_factory=list)
    symptom_duration: Optional[str] = None
    failed_treatments: list[str] = Field(default_factory=list)
    conservative_therapy_duration_weeks: Optional[int] = Field(default=None, ge=0)
    imaging: ImagingEvidence = Field(default_factory=ImagingEvidence)
    # Retained free-text imaging string for backward compatibility (Policy RAG criteria checks
    # and the form's `imaging_evidence` field still read this); mirrors `imaging.finding`.
    imaging_evidence: Optional[str] = None
    requested_procedure: str = Field(min_length=3)
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    phi_detected: bool = False
    phi_fields_masked: list[str] = Field(default_factory=list)

    @property
    def narrative_text(self) -> str:
        """Text the ICD/Policy matchers should run against: the full narrative when present,
        otherwise the (possibly short) diagnosis. Guarantees matchers never see less signal
        than they did before `diagnosis` was normalized."""
        return self.diagnosis_narrative or self.diagnosis

    @field_validator("diagnosis", "diagnosis_narrative", "requested_procedure")
    @classmethod
    def no_raw_identifiers(cls, v: str) -> str:
        lowered = v.lower()
        for marker in ("mr.", "mrs.", "ms.", "dr.", "ssn", "mrn#"):
            if marker in lowered:
                raise ValueError(f"possible PHI leakage detected in clinical field: {marker!r}")
        return v
