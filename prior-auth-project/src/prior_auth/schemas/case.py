"""Top-level case object that travels through the orchestrator (not handed to LLMs directly)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from prior_auth.schemas.common import WorkflowStatus
from prior_auth.schemas.extraction import ExtractedClinicalFacts, PatientIdentifiers
from prior_auth.schemas.form_output import PriorAuthForm
from prior_auth.schemas.icd_coding import ICDCodingResult
from prior_auth.schemas.policy_check import PolicyCheckResult


class PriorAuthCase(BaseModel):
    case_id: str
    raw_note_text: str
    specialty: str = "unknown"

    identifiers: Optional[PatientIdentifiers] = None  # PHI, never forwarded past the masking boundary
    clinical_facts: Optional[ExtractedClinicalFacts] = None
    icd_result: Optional[ICDCodingResult] = None
    policy_result: Optional[PolicyCheckResult] = None
    form: Optional[PriorAuthForm] = None

    status: WorkflowStatus = WorkflowStatus.IN_PROGRESS
    suspension_reason: Optional[str] = None
