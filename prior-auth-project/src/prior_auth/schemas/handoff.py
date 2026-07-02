"""Generic typed envelope wrapping every agent-to-agent handoff.

Every agent returns a `Handoff[T]` rather than a bare payload, so the orchestrator
can validate, gate, and audit-log uniformly regardless of which agent produced it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field

from prior_auth.schemas.common import HandoffStatus

T = TypeVar("T", bound=BaseModel)


class Handoff(BaseModel, Generic[T]):
    agent_name: str
    case_id: str
    status: HandoffStatus
    payload: Optional[T] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    errors: list[str] = Field(default_factory=list)
    timestamp: datetime

    @classmethod
    def ok(cls, agent_name: str, case_id: str, payload: T, confidence: float, timestamp: datetime) -> "Handoff[T]":
        return cls(
            agent_name=agent_name,
            case_id=case_id,
            status=HandoffStatus.OK,
            payload=payload,
            confidence=confidence,
            timestamp=timestamp,
        )

    @classmethod
    def suspended(cls, agent_name: str, case_id: str, payload: Optional[T], confidence: Optional[float],
                  reason: str, timestamp: datetime) -> "Handoff[T]":
        return cls(
            agent_name=agent_name,
            case_id=case_id,
            status=HandoffStatus.SUSPENDED,
            payload=payload,
            confidence=confidence,
            errors=[reason],
            timestamp=timestamp,
        )

    @classmethod
    def failed(cls, agent_name: str, case_id: str, errors: list[str], timestamp: datetime,
               status: HandoffStatus = HandoffStatus.VALIDATION_FAILED) -> "Handoff[T]":
        return cls(agent_name=agent_name, case_id=case_id, status=status, errors=errors, timestamp=timestamp)
