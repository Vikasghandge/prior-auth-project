"""File-backed human-in-the-loop review queue.

A suspended case is written here as a pending record; a reviewer (or a test) can later
call `resolve()` to record a decision. Kept intentionally simple (JSON files) since the
queue's job in this project is to make suspension auditable and inspectable, not to be a
production job queue.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

_DEFAULT_QUEUE_DIR = Path(__file__).resolve().parents[3] / "logs" / "hitl_queue"


class HITLQueue:
    def __init__(self, queue_dir: Path | None = None) -> None:
        self.queue_dir = queue_dir or _DEFAULT_QUEUE_DIR
        self.queue_dir.mkdir(parents=True, exist_ok=True)

    def enqueue(self, case_id: str, reason: str, status: str, timestamp: datetime,
                context: dict | None = None) -> Path:
        record = {
            "case_id": case_id,
            "reason": reason,
            "workflow_status": status,
            "queued_at": timestamp.isoformat(),
            "review_status": "PENDING_REVIEW",
            "context": context or {},
        }
        path = self.queue_dir / f"{case_id}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
        return path

    def list_pending(self) -> list[dict]:
        pending = []
        for path in sorted(self.queue_dir.glob("*.json")):
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
            if record.get("review_status") == "PENDING_REVIEW":
                pending.append(record)
        return pending

    def resolve(self, case_id: str, decision: str, reviewer: str = "unspecified") -> dict:
        path = self.queue_dir / f"{case_id}.json"
        with open(path, "r", encoding="utf-8") as f:
            record = json.load(f)
        record["review_status"] = decision
        record["reviewer"] = reviewer
        with open(path, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
        return record
