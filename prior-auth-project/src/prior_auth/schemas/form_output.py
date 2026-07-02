"""Schemas for Agent 4 (Form Filler) output."""
from __future__ import annotations

from pydantic import BaseModel, Field


class FormField(BaseModel):
    name: str
    value: str
    required: bool = True


class PriorAuthForm(BaseModel):
    case_id: str
    form_template_id: str
    fields: list[FormField] = Field(default_factory=list)
    icd10_code: str
    procedure_code: str
    policy_id: str
    validation_errors: list[str] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.validation_errors) == 0
