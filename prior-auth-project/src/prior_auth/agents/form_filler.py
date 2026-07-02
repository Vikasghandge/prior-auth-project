"""Agent 4: Form Filler.

Picks a form template by matching the requested procedure against each template's
`procedure_keywords`, then populates + Pydantic-validates the typed `PriorAuthForm`.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from prior_auth.schemas.common import Laterality
from prior_auth.schemas.extraction import ExtractedClinicalFacts
from prior_auth.schemas.form_output import FormField, PriorAuthForm
from prior_auth.schemas.handoff import Handoff
from prior_auth.schemas.icd_coding import ICDCodingResult
from prior_auth.schemas.policy_check import PolicyCheckResult

_TEMPLATES_PATH = Path(__file__).resolve().parents[3] / "data" / "form_templates" / "templates.json"
_MIN_TEMPLATE_SCORE = 0.3

# Fields that must always carry a real value — an empty result here means extraction/coding
# genuinely failed to populate something the form cannot be submitted without.
# "failed_treatments" / "imaging_evidence" are informational: legitimately empty (e.g. no
# conservative therapy was tried) is exactly the signal the Policy RAG criteria check needs,
# not a form defect.
_HARD_REQUIRED_FIELDS = {"patient_age", "patient_sex", "diagnosis_code", "procedure_code", "policy_id"}


class FormFillerAgent:
    name = "Form Filler"

    def __init__(self) -> None:
        with open(_TEMPLATES_PATH, "r", encoding="utf-8") as f:
            self.templates: list[dict] = json.load(f)

    def _best_template(self, requested_procedure: str) -> tuple[dict, float] | None:
        query = requested_procedure.lower()
        best: tuple[dict, float] | None = None
        for template in self.templates:
            score = max(
                (1.0 if kw in query or query in kw else SequenceMatcher(None, query, kw).ratio())
                for kw in template["procedure_keywords"]
            )
            if best is None or score > best[1]:
                best = (template, score)
        return best

    def _field_builders(self, facts: ExtractedClinicalFacts, icd_result: ICDCodingResult,
                         policy_result: PolicyCheckResult, procedure_code: str) -> dict:
        return {
            "patient_age": lambda: str(facts.age),
            "patient_sex": lambda: facts.sex,
            "laterality": lambda: facts.laterality.value,
            "diagnosis_code": lambda: icd_result.icd10_code,
            "procedure_code": lambda: procedure_code,
            "failed_treatments": lambda: ", ".join(facts.failed_treatments) if facts.failed_treatments else "None documented",
            "imaging_evidence": lambda: facts.imaging_evidence or "Not provided",
            "policy_id": lambda: policy_result.policy_id,
            "human_review_flag": lambda: "false",
        }

    def _populate_fields(self, required_fields: list[str], builders: dict) -> tuple[list[FormField], list[str]]:
        fields: list[FormField] = []
        errors: list[str] = []
        for field_name in required_fields:
            builder = builders.get(field_name)
            value = builder() if builder else ""
            is_hard_required = field_name in _HARD_REQUIRED_FIELDS
            if is_hard_required and not value:
                errors.append(f"Required field '{field_name}' could not be populated")
            if field_name == "laterality" and value == Laterality.UNKNOWN.value:
                errors.append("Laterality could not be determined unambiguously from the note")
            fields.append(FormField(name=field_name, value=value or "UNSPECIFIED", required=is_hard_required))
        return fields, errors

    def _consistency_errors(self, facts: ExtractedClinicalFacts, icd_result: ICDCodingResult) -> list[str]:
        errors = []
        if (
            facts.requested_procedure_laterality != Laterality.NOT_APPLICABLE
            and facts.laterality != Laterality.NOT_APPLICABLE
            and facts.requested_procedure_laterality != facts.laterality
        ):
            errors.append(
                f"Laterality conflict: diagnosis documents '{facts.laterality.value}' but the "
                f"requested procedure specifies '{facts.requested_procedure_laterality.value}'"
            )
        if not icd_result.laterality_match:
            errors.append(
                f"ICD-10 code {icd_result.icd10_code} laterality does not match documented diagnosis laterality"
            )
        return errors

    def run(
        self,
        facts: ExtractedClinicalFacts,
        icd_result: ICDCodingResult,
        policy_result: PolicyCheckResult,
        timestamp: datetime,
    ) -> Handoff[PriorAuthForm]:
        match = self._best_template(facts.requested_procedure)
        if match is None or match[1] < _MIN_TEMPLATE_SCORE:
            return Handoff.failed(
                self.name, facts.case_id,
                [f"No matching form template found for requested procedure: {facts.requested_procedure!r}"],
                timestamp,
            )

        template, _score = match
        procedure_code = "PROC-" + policy_result.policy_id.split("-")[-1]
        builders = self._field_builders(facts, icd_result, policy_result, procedure_code)

        fields, validation_errors = self._populate_fields(template["required_fields"], builders)
        validation_errors += self._consistency_errors(facts, icd_result)

        form = PriorAuthForm(
            case_id=facts.case_id,
            form_template_id=template["template_id"],
            fields=fields,
            icd10_code=icd_result.icd10_code,
            procedure_code=procedure_code,
            policy_id=policy_result.policy_id,
            validation_errors=validation_errors,
        )
        confidence = 1.0 if form.is_valid else round(1.0 - 0.15 * len(validation_errors), 4)
        return Handoff.ok(self.name, facts.case_id, form, max(0.0, confidence), timestamp)
