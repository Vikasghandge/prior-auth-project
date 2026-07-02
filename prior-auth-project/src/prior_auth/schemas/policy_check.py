"""Schemas for Agent 3 (Policy RAG) output."""
from __future__ import annotations

from pydantic import BaseModel, Field


class PolicyMatch(BaseModel):
    policy_id: str
    title: str
    retrieval_score: float = Field(ge=0.0, le=1.0)


class PolicyCheckResult(BaseModel):
    case_id: str
    policy_id: str
    policy_title: str
    policy_match: bool
    matched_criteria: list[str] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""
