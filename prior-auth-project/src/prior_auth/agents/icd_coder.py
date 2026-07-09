"""Agent 2: ICD Coder.

Applies the confidence gate directly at the handoff boundary: any top candidate below the
global threshold produces a SUSPENDED handoff rather than OK, so the orchestrator only has to
check `handoff.status`, not re-derive the rule itself. The gate applies to every diagnosis —
rare or common — a wrong code is equally costly either way.
"""
from __future__ import annotations

import re
from datetime import datetime

from prior_auth.knowledge_graph.icd_graph import get_graph
from prior_auth.orchestration.confidence_gate import is_low_confidence, low_confidence_reason
from prior_auth.schemas.common import Laterality
from prior_auth.schemas.extraction import ExtractedClinicalFacts
from prior_auth.schemas.handoff import Handoff
from prior_auth.schemas.icd_coding import ICDCodingResult

_VALID_LATERALITY = {e.value for e in Laterality}

# A candidate diagnosis_text dominated by symptom/complaint language rather than naming an
# actual condition (e.g. "persistent hip pain for 14 months", "difficulty walking") must never
# be surfaced as the clinical diagnosis. A real diagnosis name is trusted first (disease-
# indicating keyword or suffix beats everything below); only once that check comes up empty do
# we look for the symptom-only tells (a bare complaint noun, or a duration clause with nothing
# else naming a condition).
_DISEASE_KEYWORDS = {
    "disease", "syndrome", "failure", "stenosis", "fracture", "cancer", "tumor", "tumour",
    "arthritis", "sclerosis", "carcinoma", "neoplasm", "disorder", "deficiency", "insufficiency",
    "regurgitation", "prolapse", "aneurysm", "infarction", "embolism", "thrombosis",
}
_DISEASE_SUFFIXES = ("itis", "osis", "algia", "emia", "opathy", "trophy", "oma", "plasia")
_SYMPTOM_WORDS = {
    "pain", "ache", "aches", "aching", "discomfort", "difficulty", "numbness", "weakness",
    "tingling", "swelling", "tenderness", "fatigue", "soreness",
}
_DURATION_CLAUSE = re.compile(r"\bfor\s+(?:the\s+)?(?:past\s+)?\d+\s*(?:day|week|month|year)s?\b", re.IGNORECASE)


def _is_symptom_only_phrase(text: str) -> bool:
    words = re.findall(r"[a-z]+", text.lower())
    if not words:
        return False
    if any(w in _DISEASE_KEYWORDS for w in words):
        return False
    if any(w.endswith(_DISEASE_SUFFIXES) for w in words):
        return False
    if any(w in _SYMPTOM_WORDS for w in words):
        return True
    return bool(_DURATION_CLAUSE.search(text))


class ICDCoderAgent:
    name = "ICD Coder"

    def run(self, facts: ExtractedClinicalFacts, timestamp: datetime) -> Handoff[ICDCodingResult]:
        graph = get_graph()
        # The match query combines two complementary signals:
        # - the full diagnosis narrative (not the normalized primary `diagnosis`), so disease
        #   names appearing later in the note — e.g. rare-disease "... confirmed by ..."
        #   sentences — still reach the keyword/fuzzy/semantic matcher;
        # - the requested procedure, which often carries the only body-part-specific detail
        #   (e.g. "total knee replacement" vs "total hip replacement") when the narrative itself
        #   is generic ("degenerative joint disease").
        match_query = f"{facts.narrative_text} {facts.requested_procedure}".strip()
        candidates = graph.match(match_query, facts.symptoms, laterality=facts.laterality.value, top_k=5)

        if not candidates:
            return Handoff.failed(self.name, facts.case_id, ["No ICD-10 candidates found in knowledge graph"], timestamp)

        top = candidates[0]
        top_laterality = top.laterality if top.laterality in _VALID_LATERALITY else Laterality.NOT_APPLICABLE.value

        # diagnosis_text must always name the clinical diagnosis, never a symptom/complaint
        # phrase. The Extractor's normalized `diagnosis` is used by default; if it turns out to
        # be symptom-only wording (e.g. the note never separates "chief complaint" from
        # "diagnosis"), fall back to the matched code's own description — which, by construction,
        # always names an actual condition.
        diagnosis_text = facts.diagnosis
        if _is_symptom_only_phrase(diagnosis_text):
            diagnosis_text = top.description

        result = ICDCodingResult(
            case_id=facts.case_id,
            diagnosis_text=diagnosis_text,
            icd10_code=top.code,
            code_description=top.description,
            laterality=Laterality(top_laterality),
            laterality_match=top.laterality_match,
            is_rare_disease=top.is_rare_disease,
            confidence=top.score,
            rationale=(
                f"The diagnosis was matched with ICD-10 code {top.code} ({top.description}) "
                f"using {graph.last_match_mode} matching. Confidence: {top.score:.2f}."
            ),
        )

        if is_low_confidence(result):
            return Handoff.suspended(
                self.name,
                facts.case_id,
                result,
                result.confidence,
                low_confidence_reason(result),
                timestamp,
            )

        return Handoff.ok(self.name, facts.case_id, result, result.confidence, timestamp)
