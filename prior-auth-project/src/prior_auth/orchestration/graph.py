"""The orchestrator: Extractor -> ICD Coder -> [confidence gate] -> Policy RAG -> Form Filler.

A lightweight, dependency-free state machine rather than LangGraph/CrewAI/Foundry — chosen
so the whole workflow runs and is unit-testable without any external service, while each
agent stays a plain, swappable class (they could be re-wired into LangGraph nodes or
Foundry agents later without changing their internals).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from prior_auth.agents.extractor import ExtractorAgent
from prior_auth.agents.form_filler import FormFillerAgent
from prior_auth.agents.icd_coder import ICDCoderAgent
from prior_auth.agents.policy_rag import PolicyRAGAgent
from prior_auth.audit.trace_logger import make_event, save_trace
from prior_auth.orchestration.hitl_queue import HITLQueue
from prior_auth.schemas.case import PriorAuthCase
from prior_auth.schemas.common import HandoffStatus, Laterality, WorkflowStatus
from prior_auth.schemas.audit import AuditTrace


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _status_for_failed_handoff(handoff) -> WorkflowStatus:
    joined_errors = " ".join(handoff.errors).lower()
    if handoff.status == HandoffStatus.ERROR and "phi" in joined_errors:
        return WorkflowStatus.SUSPENDED_PHI_VIOLATION
    if handoff.status == HandoffStatus.VALIDATION_FAILED:
        return WorkflowStatus.FAILED_VALIDATION
    return WorkflowStatus.ERROR


class PriorAuthWorkflow:
    def __init__(self) -> None:
        self.extractor = ExtractorAgent()
        self.icd_coder = ICDCoderAgent()
        self.policy_rag = PolicyRAGAgent()
        self.form_filler = FormFillerAgent()
        self.hitl_queue = HITLQueue()

    def run(self, case_id: str, raw_note_text: str, specialty: str = "unknown",
            persist_trace: bool = True) -> tuple[PriorAuthCase, AuditTrace]:
        case = PriorAuthCase(case_id=case_id, raw_note_text=raw_note_text, specialty=specialty)
        trace = AuditTrace(case_id=case_id)
        step = 0

        # --- Step 1: Extractor (includes PHI masking) ---
        step += 1
        t0 = time.perf_counter()
        handoff = self.extractor.run(case, _now())
        trace.add(make_event(step, handoff, (time.perf_counter() - t0) * 1000, {"note_length": len(raw_note_text)}))

        if handoff.status != HandoffStatus.OK:
            return self._finalize(case, trace, _status_for_failed_handoff(handoff), handoff.errors, persist_trace)

        case.clinical_facts = handoff.payload
        facts = case.clinical_facts

        # --- Laterality-conflict business rule (independent of the ICD confidence gate) ---
        if (
            facts.laterality in (Laterality.LEFT, Laterality.RIGHT, Laterality.BILATERAL)
            and facts.requested_procedure_laterality in (Laterality.LEFT, Laterality.RIGHT, Laterality.BILATERAL)
            and facts.laterality != facts.requested_procedure_laterality
        ):
            reason = (
                f"Diagnosis documents laterality '{facts.laterality.value}' but the requested "
                f"procedure specifies '{facts.requested_procedure_laterality.value}' — suspended "
                f"for human review rather than guessing which side is correct."
            )
            self.hitl_queue.enqueue(case_id, reason, WorkflowStatus.SUSPENDED_LATERALITY_CONFLICT.value, _now())
            return self._finalize(case, trace, WorkflowStatus.SUSPENDED_LATERALITY_CONFLICT, [reason], persist_trace)

        # --- Step 2: ICD Coder (embeds the rare-disease confidence gate) ---
        step += 1
        t0 = time.perf_counter()
        handoff = self.icd_coder.run(facts, _now())
        trace.add(make_event(step, handoff, (time.perf_counter() - t0) * 1000,
                              {"diagnosis": facts.diagnosis, "laterality": facts.laterality.value}))

        if handoff.status == HandoffStatus.SUSPENDED:
            case.icd_result = handoff.payload
            self.hitl_queue.enqueue(case_id, handoff.errors[0], WorkflowStatus.SUSPENDED_LOW_CONFIDENCE.value, _now(),
                                     context={"icd10_code": handoff.payload.icd10_code, "confidence": handoff.confidence})
            return self._finalize(case, trace, WorkflowStatus.SUSPENDED_LOW_CONFIDENCE, handoff.errors, persist_trace)
        if handoff.status != HandoffStatus.OK:
            return self._finalize(case, trace, _status_for_failed_handoff(handoff), handoff.errors, persist_trace)

        case.icd_result = handoff.payload

        # --- Step 3: Policy RAG ---
        step += 1
        t0 = time.perf_counter()
        handoff = self.policy_rag.run(facts, _now())
        trace.add(make_event(step, handoff, (time.perf_counter() - t0) * 1000,
                              {"icd10_code": case.icd_result.icd10_code}))

        if handoff.status != HandoffStatus.OK:
            return self._finalize(case, trace, _status_for_failed_handoff(handoff), handoff.errors, persist_trace)

        case.policy_result = handoff.payload

        # --- Step 4: Form Filler ---
        step += 1
        t0 = time.perf_counter()
        handoff = self.form_filler.run(facts, case.icd_result, case.policy_result, _now())
        trace.add(make_event(step, handoff, (time.perf_counter() - t0) * 1000,
                              {"policy_id": case.policy_result.policy_id}))

        if handoff.status != HandoffStatus.OK:
            return self._finalize(case, trace, _status_for_failed_handoff(handoff), handoff.errors, persist_trace)

        case.form = handoff.payload

        if not case.form.is_valid:
            return self._finalize(case, trace, WorkflowStatus.FAILED_VALIDATION, case.form.validation_errors, persist_trace)
        if not case.policy_result.policy_match:
            reason = f"Policy {case.policy_result.policy_id} criteria not fully met: missing {case.policy_result.missing_items}"
            self.hitl_queue.enqueue(case_id, reason, WorkflowStatus.SUSPENDED_POLICY_MISMATCH.value, _now())
            return self._finalize(case, trace, WorkflowStatus.SUSPENDED_POLICY_MISMATCH, [reason], persist_trace)

        return self._finalize(case, trace, WorkflowStatus.COMPLETED, [], persist_trace)

    def _finalize(self, case: PriorAuthCase, trace: AuditTrace, status: WorkflowStatus,
                  errors: list[str], persist_trace: bool) -> tuple[PriorAuthCase, AuditTrace]:
        case.status = status
        case.suspension_reason = errors[0] if errors and status != WorkflowStatus.COMPLETED else None
        trace.final_status = status.value
        if persist_trace:
            save_trace(trace)
        return case, trace
