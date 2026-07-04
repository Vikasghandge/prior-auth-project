"""Agent 6: Insurance Company (Payer).

Everything upstream is the PROVIDER side. This agent simulates the payer's internal
administrative review of the submitted authorization package: member eligibility, plan
status, procedure coverage, provider network, authorization requirements, package
completeness, clinical-decision consistency, and a deterministic duplicate check —
then issues the FINAL authorization decision (APPROVED / DENIED / PENDING_REVIEW).

Strictly a validator: it never re-extracts, re-codes, re-retrieves, rewrites the form,
or modifies any upstream output. All checks run against a local synthetic payer
directory (dataset/payer/payer_directory.json) — no external API.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from prior_auth.schemas.common import WorkflowStatus
from prior_auth.schemas.critique import CritiqueReport
from prior_auth.schemas.extraction import ExtractedClinicalFacts
from prior_auth.schemas.form_output import PriorAuthForm
from prior_auth.schemas.handoff import Handoff
from prior_auth.schemas.icd_coding import ICDCodingResult
from prior_auth.schemas.insurance import InsuranceDecision, PayerDecision
from prior_auth.schemas.policy_check import PolicyCheckResult
from prior_auth.utils.paths import PROJECT_ROOT

_PAYER_DIRECTORY_PATH = PROJECT_ROOT / "dataset" / "payer" / "payer_directory.json"


def _submission_fingerprint(facts: ExtractedClinicalFacts) -> str:
    """Deterministic identity of a request for duplicate detection: same patient profile +
    same diagnosis + same procedure = same fingerprint, regardless of case id."""
    raw = f"{facts.age}|{facts.sex}|{facts.diagnosis.lower()}|{facts.requested_procedure.lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class InsuranceCompanyAgent:
    name = "Insurance Company"

    def __init__(self) -> None:
        with open(_PAYER_DIRECTORY_PATH, "r", encoding="utf-8") as f:
            self.directory: dict = json.load(f)

    def run(
        self,
        facts: ExtractedClinicalFacts,
        icd_result: ICDCodingResult,
        policy_result: PolicyCheckResult,
        form: PriorAuthForm,
        critique: CritiqueReport,
        provider_decision: WorkflowStatus,
        timestamp: datetime,
    ) -> Handoff[InsuranceDecision]:
        overrides = self.directory.get("case_overrides", {}).get(facts.case_id, {})
        failed: list[str] = []
        warnings: list[str] = []

        # --- 1. Member eligibility ------------------------------------------------------
        member = dict(self.directory["default_member"])
        member_status = overrides.get("member_status", member["member_status"])
        plan_id = overrides.get("plan_id", member["plan_id"])
        plan = self.directory["plans"].get(plan_id, self.directory["plans"]["PLAN-GOLD-PPO"])
        if member_status != "ACTIVE":
            failed.append(f"Member is not eligible (status: {member_status})")

        # --- 3. Policy validation (plan active + form/policy agreement) -----------------
        policy_status = plan["status"]
        if policy_status != "ACTIVE":
            failed.append(f"Member's plan {plan_id} is {policy_status}, not ACTIVE")
        if form.policy_id != policy_result.policy_id:
            failed.append(
                f"Policy on the form ({form.policy_id}) does not match the policy selected "
                f"during clinical review ({policy_result.policy_id})"
            )

        # --- 2. Coverage verification ---------------------------------------------------
        procedure = facts.requested_procedure.strip()
        not_covered = {p.lower() for p in plan.get("non_covered_procedures", [])}
        covered = procedure.lower() not in not_covered and not overrides.get("force_not_covered", False)
        coverage_status = "COVERED" if covered else "NOT_COVERED"
        if not covered:
            failed.append(f"Procedure {procedure!r} is not covered under plan {plan_id}")

        # --- 4. Provider validation (simulated network directory) -----------------------
        network = self.directory["provider_network"]
        provider_status = overrides.get(
            "provider_status",
            network["specialties"].get(facts.specialty, network["default_status"]),
        )
        if provider_status != "IN_NETWORK":
            failed.append(f"Referring provider ({facts.specialty}) is {provider_status}")

        # --- 5. Authorization requirements ----------------------------------------------
        authorization_required = bool(plan.get("requires_prior_authorization", True))
        requirements_met = True
        if authorization_required and form is None:  # defensive; form is always present here
            requirements_met = False
            failed.append("Plan requires prior authorization but no completed form was submitted")
        if plan.get("requires_referral") and facts.specialty in ("", "Unknown"):
            requirements_met = False
            failed.append("Plan requires a documented referral; no referring specialty was identified")
        if plan.get("requires_precertification"):
            # Pre-certification is satisfied in this system by a passing critique report.
            if critique.status.value == "FAIL":
                requirements_met = False
                failed.append("Pre-certification requires a clean QA report; the critique failed")

        # --- 6. Clinical decision consistency --------------------------------------------
        # The provider-side decision must agree with the Policy RAG findings it was based on.
        clinical_consistent = True
        if provider_decision == WorkflowStatus.COMPLETED and not policy_result.policy_match:
            clinical_consistent = False
            failed.append(
                "Provider submitted as clinically approved, but the policy criteria review "
                "shows unmet requirements"
            )

        # --- 7. Package completeness ------------------------------------------------------
        package_complete = True
        missing_items = [
            name for name, present in (
                ("diagnosis", bool(facts.diagnosis)),
                ("ICD-10 code", bool(form.icd10_code)),
                ("procedure", bool(procedure)),
                ("policy reference", bool(form.policy_id)),
                ("clinical justification", bool(icd_result.rationale and policy_result.rationale)),
            ) if not present
        ]
        if missing_items:
            package_complete = False
            failed.append(f"Authorization package incomplete: missing {', '.join(missing_items)}")
        if not facts.imaging_evidence:
            warnings.append("No imaging evidence attached — payer may request records post-approval")

        # --- 8. Fraud / duplicate check (deterministic) -----------------------------------
        fingerprint = _submission_fingerprint(facts)
        known = {
            entry["fingerprint"]
            for entry in self.directory.get("recent_authorizations", [])
            if entry.get("case_id") != facts.case_id  # resubmitting the same case is not fraud
        }
        duplicate = fingerprint in known or bool(overrides.get("force_duplicate", False))
        fraud_check = "DUPLICATE_SUSPECTED" if duplicate else "CLEAR"
        if duplicate:
            warnings.append(
                "A recent authorization with the same patient profile, diagnosis and procedure "
                "already exists — routed for manual review as a possible duplicate"
            )

        # --- 9. Final payer decision (business rules, in precedence order) ----------------
        hard_denial = (
            member_status != "ACTIVE"
            or policy_status != "ACTIVE"
            or not covered
            or provider_status != "IN_NETWORK"
        )
        provider_side_clean = provider_decision == WorkflowStatus.COMPLETED

        if hard_denial:
            final = PayerDecision.DENIED
            reason = "Coverage or policy requirements were not satisfied: " + "; ".join(failed[:2])
        elif duplicate:
            final = PayerDecision.PENDING_REVIEW
            reason = "Possible duplicate authorization request — manual payer review required."
        elif critique.status.value == "FAIL":
            final = PayerDecision.PENDING_REVIEW
            reason = "The independent QA review reported package defects — manual payer review required."
        elif not provider_side_clean or failed or not requirements_met or not clinical_consistent:
            final = PayerDecision.PENDING_REVIEW
            reason = (
                failed[0] if failed
                else "Provider-side review did not fully clear the case — additional payer review required."
            )
        else:
            final = PayerDecision.APPROVED
            reason = "All payer-side validation checks passed."

        # Deterministic confidence: perfect run = 0.99; each failed check −0.15, warning −0.03.
        confidence = max(0.0, round(0.99 - 0.15 * len(failed) - 0.03 * len(warnings), 4))

        decision = InsuranceDecision(
            case_id=facts.case_id,
            member_status=member_status,
            policy_status=policy_status,
            coverage_status=coverage_status,
            provider_status=provider_status,
            authorization_required=authorization_required,
            requirements_met=requirements_met,
            fraud_check=fraud_check,
            package_complete=package_complete,
            clinical_decision_consistent=clinical_consistent,
            final_decision=final,
            reason=reason,
            checks_failed=failed,
            warnings=warnings,
            confidence=confidence,
        )

        # Like the Critique Agent, the payer reviewer always completes (OK handoff): its
        # verdict lives in the payload, and failures are surfaced on the handoff for the
        # audit trace — it never suspends/fails the provider-side workflow record.
        handoff = Handoff.ok(self.name, facts.case_id, decision, confidence, timestamp)
        handoff.errors = failed
        return handoff
