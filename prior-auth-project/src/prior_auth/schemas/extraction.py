"""Schemas for Agent 1 (Extractor) output.

PHI and clinical facts are modeled as SEPARATE objects on purpose: `PatientIdentifiers`
never leaves the Extractor/PHI-masking boundary, while `ExtractedClinicalFacts` is the
de-identified payload that is typed-handed-off to every downstream agent.
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


class ExtractedClinicalFacts(BaseModel):
    """De-identified clinical facts extracted from a doctor's note. Safe to hand off downstream."""

    case_id: str
    age: int = Field(ge=0, le=130)
    sex: str = Field(pattern="^(M|F|U)$")
    diagnosis: str = Field(min_length=3)
    laterality: Laterality = Laterality.NOT_APPLICABLE
    requested_procedure_laterality: Laterality = Laterality.NOT_APPLICABLE
    symptoms: list[str] = Field(default_factory=list)
    failed_treatments: list[str] = Field(default_factory=list)
    conservative_therapy_duration_weeks: Optional[int] = Field(default=None, ge=0)
    imaging_evidence: Optional[str] = None
    requested_procedure: str = Field(min_length=3)
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    phi_detected: bool = False
    phi_fields_masked: list[str] = Field(default_factory=list)

    @field_validator("diagnosis", "requested_procedure")
    @classmethod
    def no_raw_identifiers(cls, v: str) -> str:
        lowered = v.lower()
        for marker in ("mr.", "mrs.", "ms.", "dr.", "ssn", "mrn#"):
            if marker in lowered:
                raise ValueError(f"possible PHI leakage detected in clinical field: {marker!r}")
        return v
