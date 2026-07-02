"""Builds and persists the typed audit trace for a case.

Summaries are built from the already-de-identified Handoff payloads only — never from
`case.raw_note_text` or `case.identifiers` — so the audit trail itself cannot leak PHI.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from prior_auth.schemas.audit import AuditEvent, AuditTrace
from prior_auth.schemas.handoff import Handoff

_DEFAULT_TRACE_DIR = Path(__file__).resolve().parents[3] / "logs" / "audit_traces"


def _summarize(payload: BaseModel | None) -> dict[str, Any]:
    if payload is None:
        return {}
    return payload.model_dump(mode="json")


def make_event(step: int, handoff: Handoff, duration_ms: float, input_summary: dict) -> AuditEvent:
    return AuditEvent(
        case_id=handoff.case_id,
        step=step,
        agent_name=handoff.agent_name,
        timestamp=handoff.timestamp,
        status=handoff.status.value,
        confidence=handoff.confidence,
        input_summary=input_summary,
        output_summary=_summarize(handoff.payload),
        errors=handoff.errors,
        duration_ms=round(duration_ms, 3),
    )


def save_trace(trace: AuditTrace, trace_dir: Path | None = None) -> Path:
    trace_dir = trace_dir or _DEFAULT_TRACE_DIR
    trace_dir.mkdir(parents=True, exist_ok=True)
    path = trace_dir / f"{trace.case_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        f.write(trace.model_dump_json(indent=2))
    return path


def load_trace(case_id: str, trace_dir: Path | None = None) -> AuditTrace:
    trace_dir = trace_dir or _DEFAULT_TRACE_DIR
    path = trace_dir / f"{case_id}.json"
    with open(path, "r", encoding="utf-8") as f:
        return AuditTrace.model_validate(json.load(f))
