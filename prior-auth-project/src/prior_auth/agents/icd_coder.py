"""Agent 2: ICD Coder.

Applies the special rule directly at the handoff boundary: a rare-disease top candidate
with confidence below the gate threshold produces a SUSPENDED handoff rather than OK, so
the orchestrator only has to check `handoff.status`, not re-derive the rule itself.
"""
from __future__ import annotations

from datetime import datetime

from prior_auth.config import RARE_DISEASE_CONFIDENCE_THRESHOLD
from prior_auth.knowledge_graph.icd_graph import get_graph
from prior_auth.orchestration.confidence_gate import is_rare_disease_low_confidence
from prior_auth.schemas.common import Laterality
from prior_auth.schemas.extraction import ExtractedClinicalFacts
from prior_auth.schemas.handoff import Handoff
from prior_auth.schemas.icd_coding import ICDCandidate, ICDCodingResult

_VALID_LATERALITY = {e.value for e in Laterality}


class ICDCoderAgent:
    name = "ICD Coder"

    def run(self, facts: ExtractedClinicalFacts, timestamp: datetime) -> Handoff[ICDCodingResult]:
        graph = get_graph()
        candidates = graph.match(facts.diagnosis, facts.symptoms, laterality=facts.laterality.value, top_k=5)

        if not candidates:
            return Handoff.failed(self.name, facts.case_id, ["No ICD-10 candidates found in knowledge graph"], timestamp)

        top = candidates[0]
        top_laterality = top.laterality if top.laterality in _VALID_LATERALITY else Laterality.NOT_APPLICABLE.value

        result = ICDCodingResult(
            case_id=facts.case_id,
            diagnosis_text=facts.diagnosis,
            icd10_code=top.code,
            code_description=top.description,
            laterality=Laterality(top_laterality),
            laterality_match=top.laterality_match,
            is_rare_disease=top.is_rare_disease,
            confidence=top.score,
            alternative_codes=[
                ICDCandidate(code=c.code, description=c.description, score=c.score) for c in candidates[1:4]
            ],
            rationale=(
                f"Top match against ICD-10 KG node {top.code} ({top.description}) via keyword/fuzzy "
                f"similarity, confidence={top.score:.3f}."
            ),
        )

        if is_rare_disease_low_confidence(result):
            return Handoff.suspended(
                self.name,
                facts.case_id,
                result,
                result.confidence,
                f"Rare disease candidate '{result.code_description}' has coding confidence "
                f"{result.confidence:.2f}, below the {RARE_DISEASE_CONFIDENCE_THRESHOLD:.2f} gate "
                f"threshold — suspended for human coding review.",
                timestamp,
            )

        return Handoff.ok(self.name, facts.case_id, result, result.confidence, timestamp)
