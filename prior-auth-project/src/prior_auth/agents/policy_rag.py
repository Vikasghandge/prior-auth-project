"""Agent 3: Policy RAG."""
from __future__ import annotations

from datetime import datetime

from prior_auth.phi.masking import contains_phi
from prior_auth.rag.retriever import get_policy_rag
from prior_auth.schemas.extraction import ExtractedClinicalFacts
from prior_auth.schemas.handoff import Handoff
from prior_auth.schemas.common import HandoffStatus
from prior_auth.schemas.policy_check import PolicyCheckResult


class PolicyRAGAgent:
    name = "Policy RAG"

    def run(self, facts: ExtractedClinicalFacts, timestamp: datetime) -> Handoff[PolicyCheckResult]:
        # Re-assert the PHI boundary at this agent too: it must never receive raw identifiers,
        # even if an upstream bug let one slip through.
        if contains_phi(facts.diagnosis) or contains_phi(facts.requested_procedure):
            return Handoff.failed(
                self.name, facts.case_id,
                ["PHI boundary violation: raw identifiers detected in Policy RAG input"],
                timestamp, status=HandoffStatus.ERROR,
            )

        rag = get_policy_rag()
        top_matches = rag.retrieve(facts, top_k=1)
        if not top_matches:
            return Handoff.failed(self.name, facts.case_id, ["No matching insurer policy found"], timestamp)

        policy, retrieval_score = top_matches[0]
        evaluation = rag.evaluate_criteria(policy, facts)
        confidence = round(0.3 * retrieval_score + 0.7 * evaluation.confidence, 4)

        result = PolicyCheckResult(
            case_id=facts.case_id,
            policy_id=policy["policy_id"],
            policy_title=policy["title"],
            policy_match=evaluation.policy_match,
            matched_criteria=evaluation.matched_criteria,
            missing_items=evaluation.missing_items,
            confidence=confidence,
            rationale=(
                f"Retrieved policy {policy['policy_id']} (retrieval_score={retrieval_score:.2f}); "
                f"{len(evaluation.matched_criteria)}/{len(policy['criteria'])} criteria met."
            ),
        )
        return Handoff.ok(self.name, facts.case_id, result, confidence, timestamp)
