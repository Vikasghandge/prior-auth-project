"""Policy retrieval + deterministic criteria checking for Agent 3 (Policy RAG).

Retrieval is HYBRID: each policy is split into small chunks (procedure keywords, diagnosis
keywords, one chunk per criterion) which are embedded via Azure OpenAI and compared to the
query by cosine similarity, blended with the original keyword/fuzzy score. If embeddings
are not configured (or the API fails), retrieval silently degrades to the pure keyword
path, so the workflow stays fully runnable offline. Criteria checking is rule-based against
the de-identified `ExtractedClinicalFacts` either way, so pass/fail decisions stay
explainable and reproducible — embeddings only influence WHICH policy is retrieved.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from prior_auth.utils.paths import LEGACY_DATA_ROOT, LOGS_ROOT, PROJECT_ROOT

from prior_auth.config import USE_EMBEDDING_RETRIEVAL
from prior_auth.rag.embeddings import cosine_similarity, get_embedding_client
from prior_auth.schemas.extraction import ExtractedClinicalFacts

_DEFAULT_DATA_PATH = LEGACY_DATA_ROOT / "insurer_policies" / "policies.json"

# Blend weights for hybrid retrieval. Keyword keeps the larger share: it is exact,
# auditable evidence, while the semantic score is the tie-breaker that catches synonyms
# and paraphrases ("knee arthroplasty" ~ "knee replacement").
_KEYWORD_WEIGHT = 0.55
_SEMANTIC_WEIGHT = 0.45
# text-embedding-3 cosine similarities for related/unrelated clinical text typically span
# ~0.15..0.70 — rescale that band to 0..1 so the semantic term is comparable to the
# keyword score before blending.
_COS_FLOOR, _COS_CEIL = 0.15, 0.70


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
        # Chunking: split every policy document into small, individually-searchable pieces.
        # Chunk granularity mirrors the document's own structure — what the policy covers
        # (procedure), who it applies to (diagnosis), and each requirement — so a semantic
        # hit can be traced back to the exact part of the policy that matched.
        self._policy_chunks: list[list[str]] = [self._build_chunks(p) for p in self.policies]
        # Diagnostics for the most recent retrieve() call: mode + best-matching chunk.
        self.last_retrieval: dict = {"mode": "keyword", "best_chunk": None}

    @staticmethod
    def _build_chunks(policy: dict) -> list[str]:
        title = policy["title"]
        chunks = [
            f"{title}. Procedure covered: {', '.join(policy['procedure_keywords'])}",
            f"{title}. Applicable diagnosis: {', '.join(policy['diagnosis_keywords'])}",
        ]
        chunks.extend(
            f"{title}. Requirement: {criterion['description']}" for criterion in policy["criteria"]
        )
        return chunks

    def _semantic_scores(self, query: str) -> tuple[list[float], list[str]] | None:
        """Per-policy semantic score = best cosine similarity of the query against any of
        that policy's chunks (plus which chunk won). None when embeddings are unavailable."""
        if not USE_EMBEDDING_RETRIEVAL:
            return None
        client = get_embedding_client()
        if not client.is_available:
            return None
        flat_chunks = [chunk for chunks in self._policy_chunks for chunk in chunks]
        vectors = client.embed([query] + flat_chunks)
        if vectors is None:
            return None
        query_vec, chunk_vecs = vectors[0], vectors[1:]

        scores: list[float] = []
        best_chunks: list[str] = []
        i = 0
        for chunks in self._policy_chunks:
            sims = [cosine_similarity(query_vec, chunk_vecs[i + j]) for j in range(len(chunks))]
            best_idx = max(range(len(sims)), key=sims.__getitem__)
            # Rescale the raw cosine into the same 0..1 band as the keyword score.
            scaled = max(0.0, min(1.0, (sims[best_idx] - _COS_FLOOR) / (_COS_CEIL - _COS_FLOOR)))
            scores.append(scaled)
            best_chunks.append(chunks[best_idx])
            i += len(chunks)
        return scores, best_chunks

    def retrieve(self, facts: ExtractedClinicalFacts, top_k: int = 3) -> list[tuple[dict, float]]:
        query = f"{facts.narrative_text} {facts.requested_procedure}"
        query_tokens = _tokenize(query)
        query_lower = query.lower()

        keyword_scores: list[float] = []
        for policy in self.policies:
            corpus_terms = policy["procedure_keywords"] + policy["diagnosis_keywords"]
            corpus_tokens = _tokenize(" ".join(corpus_terms))
            overlap = len(query_tokens & corpus_tokens) / max(1, len(corpus_tokens))
            fuzzy = max(_containment_score(query_lower, term.lower()) for term in corpus_terms)
            keyword_scores.append(min(1.0, 0.6 * overlap + 0.4 * fuzzy))

        semantic = self._semantic_scores(query)
        scored: list[tuple[dict, float]] = []
        if semantic is not None:
            semantic_scores, best_chunks = semantic
            for policy, kw, sem in zip(self.policies, keyword_scores, semantic_scores):
                scored.append((policy, round(min(1.0, _KEYWORD_WEIGHT * kw + _SEMANTIC_WEIGHT * sem), 4)))
            top_idx = max(range(len(scored)), key=lambda i: scored[i][1])
            self.last_retrieval = {"mode": "hybrid (chunk embeddings + keyword)", "best_chunk": best_chunks[top_idx]}
        else:
            scored = [(policy, round(kw, 4)) for policy, kw in zip(self.policies, keyword_scores)]
            self.last_retrieval = {"mode": "keyword", "best_chunk": None}

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]

    def evaluate_criteria(self, policy: dict, facts: ExtractedClinicalFacts) -> CriteriaEvaluation:
        matched: list[str] = []
        missing: list[str] = []

        haystack = " ".join(
            filter(None, [facts.narrative_text, facts.imaging_evidence, facts.requested_procedure])
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
