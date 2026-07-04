"""Schemas for Agent 5 (Critique) output.

The Critique Agent is a read-only QA verifier that runs after the Form Filler. Its report
is attached to the audit trace as the fifth pipeline event; it never modifies the case,
the form, or the workflow decision.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class CritiqueStatus(str, Enum):
    PASS = "PASS"
    PASS_WITH_WARNINGS = "PASS_WITH_WARNINGS"
    FAIL = "FAIL"


class CritiqueChecks(BaseModel):
    """One boolean per validation family. A False here always has at least one matching
    entry in `CritiqueReport.errors` explaining exactly what mismatched."""

    required_fields: bool = True
    extractor_match: bool = True
    icd_match: bool = True
    procedure_match: bool = True
    policy_match: bool = True
    decision_match: bool = True
    documents_complete: bool = True
    schema_valid: bool = True
    phi_safe: bool = True


class CritiqueReport(BaseModel):
    case_id: str
    status: CritiqueStatus
    quality_score: int = Field(ge=0, le=100)
    checks: CritiqueChecks = Field(default_factory=CritiqueChecks)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    summary: str
