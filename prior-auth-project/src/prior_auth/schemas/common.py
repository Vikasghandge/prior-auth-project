"""Shared enums and base types used across typed handoff schemas."""
from __future__ import annotations

from enum import Enum


class WorkflowStatus(str, Enum):
    """Overall status of a prior-auth case as it moves through the agent chain."""

    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SUSPENDED_LOW_CONFIDENCE = "SUSPENDED_LOW_CONFIDENCE"
    SUSPENDED_PHI_VIOLATION = "SUSPENDED_PHI_VIOLATION"
    SUSPENDED_POLICY_MISMATCH = "SUSPENDED_POLICY_MISMATCH"
    SUSPENDED_LATERALITY_CONFLICT = "SUSPENDED_LATERALITY_CONFLICT"
    SUSPENDED_EXTRACTION_REVIEW = "SUSPENDED_EXTRACTION_REVIEW"
    FAILED_VALIDATION = "FAILED_VALIDATION"
    ERROR = "ERROR"


class Laterality(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    BILATERAL = "bilateral"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class HandoffStatus(str, Enum):
    """Result of validating/executing a single agent-to-agent handoff."""

    OK = "OK"
    SUSPENDED = "SUSPENDED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    ERROR = "ERROR"
