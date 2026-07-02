"""Policy retrieval + deterministic criteria checking for Agent 3 (Policy RAG).

Retrieval is keyword/fuzzy based (no embeddings needed for a ~30-doc corpus); criteria
checking is rule-based against the de-identified `ExtractedClinicalFacts` so the confidence
score is explainable and reproducible, matching the ICD Coder's design philosophy.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from prior_auth.schemas.extraction import ExtractedClinicalFacts

_DEFAULT_DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "insurer_policies" / "policies.json"


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


_MIN_MEANINGFUL_MATCH_CHARS = 6


def _containment_score(query_lower: str, target_lower: str) -> float:
    """1.0 if `target_lower` appears verbatim in the query (or vice versa) at a word
    boundary; otherwise the longest-common-substring length relative to the *target's*
    length. Normalizing by the target (a short keyword phrase) rather than the combined
    length of both strings keeps long diagnosis narratives from diluting the score, matching
    the ICD Coder's `_containment_score` (see icd_graph.py) — including the same fix for a
    short target scoring high on a purely coincidental few-character overlap."""
    if (
        re.search(r"\b" + re.escape(target_lower) + r"\b", query_lower)
        or re.search(r"\b" + re.escape(query_lower) + r"\b", target_lower)
    ):
        return 1.0
    matcher = SequenceMatcher(None, query_lower, target_lower)
    match = matcher.find_longest_match(0, len(query_lower), 0, len(target_lower))
    if match.size < _MIN_MEANINGFUL_MATCH_CHARS:
        return 0.0
    return match.size / max(1, len(target_lower))


@dataclass
class CriteriaEvaluation:
    matched_criteria: list[str]
    missing_items: list[str]
    confidence: float
    policy_match: bool


class PolicyRAG:
    def __init__(self, data_path: Path | None = None) -> None:
        self.data_path = data_path or _DEFAULT_DATA_PATH
        with open(self.data_path, "r", encoding="utf-8") as f:
            self.policies: list[dict] = json.load(f)

    def retrieve(self, facts: ExtractedClinicalFacts, top_k: int = 3) -> list[tuple[dict, float]]:
        query = f"{facts.diagnosis} {facts.requested_procedure}"
        query_tokens = _tokenize(query)
        query_lower = query.lower()

        scored: list[tuple[dict, float]] = []
        for policy in self.policies:
            corpus_terms = policy["procedure_keywords"] + policy["diagnosis_keywords"]
            corpus_tokens = _tokenize(" ".join(corpus_terms))
            overlap = len(query_tokens & corpus_tokens) / max(1, len(corpus_tokens))
            fuzzy = max(_containment_score(query_lower, term.lower()) for term in corpus_terms)
            score = round(min(1.0, 0.6 * overlap + 0.4 * fuzzy), 4)
            scored.append((policy, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]

    def evaluate_criteria(self, policy: dict, facts: ExtractedClinicalFacts) -> CriteriaEvaluation:
        matched: list[str] = []
        missing: list[str] = []

        haystack = " ".join(
            filter(None, [facts.diagnosis, facts.imaging_evidence, facts.requested_procedure])
        ).lower()

        for criterion in policy["criteria"]:
            check = criterion["check"]
            met = False

            if check == "severity_keywords":
                met = any(kw.lower() in haystack for kw in criterion["value"])
            elif check == "min_conservative_weeks":
                weeks = facts.conservative_therapy_duration_weeks
                met = weeks is not None and weeks >= criterion["value"]
            elif check == "imaging_required":
                met = bool(facts.imaging_evidence)
            else:
                met = False

            if met:
                matched.append(criterion["id"])
            else:
                missing.append(criterion["description"])

        total = len(policy["criteria"])
        match_ratio = len(matched) / total if total else 0.0
        confidence = round(match_ratio, 4)
        policy_match = len(missing) == 0

        return CriteriaEvaluation(
            matched_criteria=matched,
            missing_items=missing,
            confidence=confidence,
            policy_match=policy_match,
        )


_rag_singleton: PolicyRAG | None = None


def get_policy_rag() -> PolicyRAG:
    global _rag_singleton
    if _rag_singleton is None:
        _rag_singleton = PolicyRAG()
    return _rag_singleton
