"""Typed audit trace entries. One AuditEvent is emitted per agent invocation."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class AuditEvent(BaseModel):
    case_id: str
    step: int
    agent_name: str
    timestamp: datetime
    status: str
    confidence: Optional[float] = None
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0


class AuditTrace(BaseModel):
    case_id: str
    events: list[AuditEvent] = Field(default_factory=list)
    final_status: str = "IN_PROGRESS"

    def add(self, event: AuditEvent) -> None:
        self.events.append(event)
