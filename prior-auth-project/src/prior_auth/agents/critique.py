"""Agent 5: Critique.

Independent, fully deterministic QA verifier that runs after the Form Filler. It receives
the outputs of every upstream agent plus the orchestrator's (prospective) decision and
checks that the completed authorization package is internally consistent, complete, valid,
and PHI-safe — WITHOUT modifying anything, re-running any agent, or influencing the
decision. Pure validation logic; no LLM calls, so every verdict is reproducible and
explainable from the report alone.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import ValidationError

from prior_auth.config import CRITIQUE_CONFIDENCE_WARN_THRESHOLD
from prior_auth.phi.masking import contains_phi
from prior_auth.schemas.common import WorkflowStatus
from prior_auth.schemas.critique import CritiqueChecks, CritiqueReport, CritiqueStatus
from prior_auth.schemas.extraction import ExtractedClinicalFacts
from prior_auth.schemas.form_output import PriorAuthForm
from prior_auth.schemas.handoff import Handoff
from prior_auth.schemas.icd_coding import ICDCodingResult
from prior_auth.schemas.policy_check import PolicyCheckResult

# Deterministic scoring: a failed check family costs 15 points, a warning costs 3.
_ERROR_CHECK_PENALTY = 15
_WARNING_PENALTY = 3

# The Form Filler writes "UNSPECIFIED" when a builder produced nothing — for QA purposes
# that is an absent value, not a filled one.
_EMPTY_SENTINELS = {"", "UNSPECIFIED"}


class CritiqueAgent:
    name = "Critique Agent"

    def run(
        self,
        facts: ExtractedClinicalFacts,
        icd_result: ICDCodingResult,
        policy_result: PolicyCheckResult,
        form: PriorAuthForm,
        decision: WorkflowStatus,
        timestamp: datetime,
    ) -> Handoff[CritiqueReport]:
        checks = CritiqueChecks()
        errors: list[str] = []
        warnings: list[str] = []
        form_values = {f.name: f.value for f in form.fields}

        # --- 1. Form completeness: every required field carries a real value -----------
        missing_required = [
            f.name for f in form.fields if f.required and f.value.strip() in _EMPTY_SENTINELS
        ]
        if missing_required:
            checks.required_fields = False
            errors.append(f"Required form fields missing or unfilled: {', '.join(missing_required)}")

        # --- 2. Cross-agent consistency: form values must match the Extractor ----------
        extractor_expectations = {
            "patient_age": str(facts.age),
            "patient_sex": facts.sex,
            "laterality": facts.laterality.value,
            "failed_treatments": ", ".join(facts.failed_treatments) if facts.failed_treatments else "None documented",
            "imaging_evidence": facts.imaging_evidence or "Not provided",
        }
        for field_name, expected in extractor_expectations.items():
            if field_name in form_values and form_values[field_name] != expected:
                checks.extractor_match = False
                errors.append(
                    f"Form field '{field_name}' ({form_values[field_name]!r}) does not match "
                    f"Extractor output ({expected!r})"
                )

        # --- 3. ICD consistency: coder's code must appear unchanged in the form --------
        if form.icd10_code != icd_result.icd10_code:
            checks.icd_match = False
            errors.append(
                f"Form ICD-10 code {form.icd10_code!r} does not match ICD Coder output {icd_result.icd10_code!r}"
            )
        if "diagnosis_code" in form_values and form_values["diagnosis_code"] != icd_result.icd10_code:
            checks.icd_match = False
            errors.append(
                f"Form field 'diagnosis_code' ({form_values['diagnosis_code']!r}) does not match "
                f"ICD Coder output ({icd_result.icd10_code!r})"
            )

        # --- 4. Procedure consistency ---------------------------------------------------
        # The Form Filler derives procedure_code as "PROC-" + the policy id suffix; verify
        # that derivation held and that the form body agrees with the header.
        if "procedure_code" in form_values and form_values["procedure_code"] != form.procedure_code:
            checks.procedure_match = False
            errors.append(
                f"Form field 'procedure_code' ({form_values['procedure_code']!r}) does not match "
                f"form header procedure code ({form.procedure_code!r})"
            )
        expected_proc_code = "PROC-" + policy_result.policy_id.split("-")[-1]
        if form.procedure_code != expected_proc_code:
            checks.procedure_match = False
            errors.append(
                f"Form procedure code {form.procedure_code!r} is not derived from the selected "
                f"policy {policy_result.policy_id!r} (expected {expected_proc_code!r})"
            )
        if not facts.requested_procedure or not facts.requested_procedure.strip():
            checks.procedure_match = False
            errors.append("No requested procedure present in the extracted clinical facts")

        # --- 5. Policy consistency: RAG's selected policy is the one on the form -------
        if form.policy_id != policy_result.policy_id:
            checks.policy_match = False
            errors.append(
                f"Form policy {form.policy_id!r} does not match Policy RAG selection {policy_result.policy_id!r}"
            )
        if "policy_id" in form_values and form_values["policy_id"] != policy_result.policy_id:
            checks.policy_match = False
            errors.append(
                f"Form field 'policy_id' ({form_values['policy_id']!r}) does not match "
                f"Policy RAG selection ({policy_result.policy_id!r})"
            )

        # --- 6. Decision consistency: the decision must follow from the evidence -------
        # In this workflow the decision rule is deterministic: an invalid form can only be
        # FAILED_VALIDATION; unmet policy criteria can only be SUSPENDED_POLICY_MISMATCH;
        # COMPLETED requires both a valid form and fully met policy criteria.
        expected_decision = (
            WorkflowStatus.FAILED_VALIDATION if not form.is_valid
            else WorkflowStatus.SUSPENDED_POLICY_MISMATCH if not policy_result.policy_match
            else WorkflowStatus.COMPLETED
        )
        if decision != expected_decision:
            checks.decision_match = False
            errors.append(
                f"Decision {decision.value!r} is inconsistent with the package evidence "
                f"(form valid={form.is_valid}, policy met={policy_result.policy_match} "
                f"implies {expected_decision.value!r})"
            )

        # --- 7. Required documents / evidence -------------------------------------------
        document_requirements = [
            ("diagnosis", bool(facts.diagnosis and facts.diagnosis.strip())),
            ("ICD-10 code", bool(icd_result.icd10_code)),
            ("requested procedure", bool(facts.requested_procedure and facts.requested_procedure.strip())),
            ("policy reference", bool(policy_result.policy_id)),
            ("clinical justification", bool(icd_result.rationale and policy_result.rationale)),
        ]
        missing_documents = [name for name, present in document_requirements if not present]
        if missing_documents:
            checks.documents_complete = False
            errors.append(f"Required evidence missing from package: {', '.join(missing_documents)}")
        if not facts.imaging_evidence:
            # Imaging is legitimately absent for some cases (e.g. pending workup) — that is a
            # reviewable gap, not an inconsistency, so it warns rather than fails.
            warnings.append("No imaging evidence documented in the package")

        # --- 8. Confidence review (warn only — never reject on low confidence) ---------
        confidence_sources = [
            ("Extractor", facts.extraction_confidence),
            ("ICD Coder", icd_result.confidence),
            ("Policy RAG", policy_result.confidence),
        ]
        for agent_name, confidence in confidence_sources:
            if confidence is not None and confidence < CRITIQUE_CONFIDENCE_WARN_THRESHOLD:
                warnings.append(
                    f"{agent_name} confidence {confidence:.2f} is below the "
                    f"{CRITIQUE_CONFIDENCE_WARN_THRESHOLD:.2f} review threshold"
                )

        # --- 9. Schema validation: the whole package round-trips its own schemas -------
        # The Form Filler's own validation errors are package defects too — the QA report
        # restates them so the critique is a complete account of why the package isn't clean.
        if form.validation_errors:
            checks.schema_valid = False
            errors.extend(f"Form validation: {e}" for e in form.validation_errors)
        for label, model in (
            ("ExtractedClinicalFacts", facts),
            ("ICDCodingResult", icd_result),
            ("PolicyCheckResult", policy_result),
            ("PriorAuthForm", form),
        ):
            try:
                type(model).model_validate(model.model_dump())
            except ValidationError as exc:
                checks.schema_valid = False
                errors.append(f"{label} failed schema re-validation: {exc.errors()[0]['msg']}")

        # --- 10. PHI safety: no raw identifiers in any AI-generated field --------------
        phi_surfaces = [
            ("form field '" + f.name + "'", f.value) for f in form.fields
        ] + [
            ("extracted diagnosis", facts.diagnosis),
            ("diagnosis narrative", facts.diagnosis_narrative),
            ("requested procedure", facts.requested_procedure),
            ("ICD rationale", icd_result.rationale),
            ("policy rationale", policy_result.rationale),
        ]
        phi_hits = [label for label, text in phi_surfaces if text and contains_phi(text)]
        if phi_hits:
            checks.phi_safe = False
            errors.append(f"PHI violation: raw identifiers detected in {', '.join(phi_hits)}")

        # --- Deterministic score + verdict ----------------------------------------------
        failed_checks = sum(1 for passed in checks.model_dump().values() if not passed)
        quality_score = max(0, min(100, 100 - _ERROR_CHECK_PENALTY * failed_checks - _WARNING_PENALTY * len(warnings)))

        if errors:
            status = CritiqueStatus.FAIL
            summary = (
                f"The authorization package failed {failed_checks} validation check"
                f"{'s' if failed_checks != 1 else ''}: " + "; ".join(errors[:3])
                + ("…" if len(errors) > 3 else "")
            )
        elif warnings:
            status = CritiqueStatus.PASS_WITH_WARNINGS
            summary = (
                "The authorization package is internally consistent; "
                f"{len(warnings)} advisory warning{'s' if len(warnings) != 1 else ''} noted for the reviewer."
            )
        else:
            status = CritiqueStatus.PASS
            summary = "The completed authorization package passed all validation checks and is internally consistent."

        report = CritiqueReport(
            case_id=facts.case_id,
            status=status,
            quality_score=quality_score,
            checks=checks,
            warnings=warnings,
            errors=errors,
            summary=summary,
        )

        # The verifier itself always completes (OK handoff); its verdict lives in the report
        # and its errors are surfaced on the handoff for the audit trace + UI. It never
        # produces a SUSPENDED/FAILED handoff, so it can never alter the workflow decision.
        handoff = Handoff.ok(self.name, facts.case_id, report, quality_score / 100, timestamp)
        handoff.errors = errors
        return handoff
