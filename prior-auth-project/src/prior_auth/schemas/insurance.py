"""Schemas for Agent 6 (Insurance Company / Payer) output.

Everything upstream is the PROVIDER side of prior authorization. `InsuranceDecision` is the
PAYER side's administrative verdict — the only place in the system allowed to say
APPROVED / DENIED / PENDING_REVIEW as a final authorization decision.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class PayerDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PENDING_REVIEW = "PENDING_REVIEW"


class InsuranceDecision(BaseModel):
    case_id: str
    member_status: str          # ACTIVE / INACTIVE
    policy_status: str          # ACTIVE / EXPIRED / SUSPENDED
    coverage_status: str        # COVERED / NOT_COVERED
    provider_status: str        # IN_NETWORK / OUT_OF_NETWORK
    authorization_required: bool = True
    requirements_met: bool = True
    fraud_check: str = "CLEAR"  # CLEAR / DUPLICATE_SUSPECTED
    package_complete: bool = True
    clinical_decision_consistent: bool = True
    final_decision: PayerDecision
    reason: str
    checks_failed: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
