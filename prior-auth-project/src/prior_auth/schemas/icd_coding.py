"""Schemas for Agent 2 (ICD Coder) output."""
from __future__ import annotations

from pydantic import BaseModel, Field

from prior_auth.schemas.common import Laterality


class ICDCodingResult(BaseModel):
    case_id: str
    diagnosis_text: str
    icd10_code: str
    code_description: str
    laterality: Laterality = Laterality.NOT_APPLICABLE
    laterality_match: bool = True
    is_rare_disease: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""
