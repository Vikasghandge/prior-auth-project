"""Mini ICD-10 knowledge graph (NetworkX) + hybrid keyword/fuzzy + embedding matcher used by
the ICD Coder agent.

Coding confidence must stay deterministic and explainable so the confidence gate (a single
global 0.90 threshold applied to every diagnosis) behaves consistently across runs — so this
is NOT an LLM call. Embeddings
(when configured) blend into the ranking score the same way as the Policy RAG hybrid retriever:
they help find semantically-equivalent phrasing the keyword matcher misses (e.g. "osteoarthritis
of the right knee" naturally rephrased vs. the code's own "right knee" keyword), but hedge-language
dampening, the laterality penalty, and the confidence gates themselves are unchanged and still
run deterministically on top of the blended score.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from prior_auth.utils.paths import LEGACY_DATA_ROOT, LOGS_ROOT, PROJECT_ROOT

import networkx as nx

from prior_auth.config import USE_ICD_EMBEDDING_MATCHING
from prior_auth.rag.embeddings import cosine_similarity, get_embedding_client

_DEFAULT_DATA_PATH = LEGACY_DATA_ROOT / "icd10_kg" / "icd10_codes.json"

# Blend weights for the hybrid ICD fallback path (used only when no keyword/description phrase
# matched verbatim — the confident-shortcut branch above already handles exact matches and is
# left alone). Unlike Policy RAG's hybrid blend, semantic similarity gets the LARGER share here:
# by construction, any code reaching this branch already failed to produce strong keyword
# evidence (that's why the shortcut didn't fire), so a weak keyword score in this branch reflects
# phrasing mismatch, not diagnostic irrelevance — while embeddings are exactly what recognize a
# paraphrased/reordered clinical description ("osteoarthritis of the right knee" vs. the code's
# own "right knee" keyword) that the fuzzy matcher misses.
# Calibrated empirically: 0.30/0.70 under-trusted strong semantic matches (a clearly-identifiable
# common diagnosis phrased in natural language capped out around 0.73 confidence instead of the
# ~0.85-0.90 a human would assign on sight), while going further than 0.15/0.85 starts pushing
# genuine knowledge-graph coverage gaps (no real match for the diagnosis at all) over the 0.70
# general safety threshold. 0.15/0.85 is the empirical ceiling that fixes the former without
# breaking the latter — see the coverage-gap test cases in doctor_notes/failure_modes.
_KW_WEIGHT = 0.15
_SEM_WEIGHT = 0.85
# text-embedding-3 cosine similarities for related/unrelated clinical text typically span
# ~0.15..0.70 — rescale that band to 0..1 so the semantic term is comparable to the keyword
# score before blending (matches rag/retriever.py's calibration).
_COS_FLOOR, _COS_CEIL = 0.15, 0.70

_STOPWORDS = {
    "a", "an", "the", "of", "with", "for", "and", "or", "in", "on", "to", "is", "are",
    "patient", "has", "shows", "confirmed", "confirms", "documented", "advanced",
}

# Hedging language dampens coding confidence: a coder should not assign full confidence to a
# diagnosis that the note itself frames as unconfirmed. This is what lets a rare-disease case
# read as clinically clear yet still land under the 0.90 confidence gate.
_HEDGE_PATTERNS = [
    "suspected", "suspicious for", "possible", "probable", "pending confirmation",
    "pending confirmatory", "rule out", "r/o", "concern for", "presumed", "query",
    "awaiting genetic", "awaiting confirmatory",
]
_HEDGE_DAMPENING = 0.85

# A single word can be long enough (>=8 chars) to pass the "distinctive phrase" length check
# below while still being medically generic — a descriptor ("degenerative", "bilateral") or a
# bare organ name ("pancreas", "gallbladder") rather than a diagnosis-specific term. Letting
# those trigger the verbatim-match confidence shortcut is how a knee note ends up confidently
# (and wrongly) coded as hip disease, or a benign pancreas mention as pancreatic cancer — so
# they're excluded from the shortcut regardless of length/uniqueness and fall back to the
# graduated token-recall + fuzzy score instead.
_GENERIC_SHORTCUT_BLOCKLIST = {
    "bilateral", "unilateral", "degenerative", "chronic", "acute", "advanced", "unspecified",
    "progressive", "recurrent", "severe", "mild", "moderate", "persistent", "intermittent",
    "pancreas", "gallbladder", "colon", "liver", "kidney", "lung", "brain", "heart", "spleen",
    "thyroid", "prostate", "stomach", "bladder", "breast", "ovary",
}

# A keyword like "left hip" or "right knee" is a *side + body part* locator, not a diagnosis —
# many different conditions occur in the left hip. It's excluded from the shortcut for the same
# reason as the blocklist above, but structurally rather than by name: a keyword's diagnostic
# specificity has to come from the disease/finding word(s), not merely from pairing a laterality
# word with an anatomy word. (Laterality itself is already handled separately via the dedicated
# `laterality` field/penalty below — it doesn't need to double as a confidence signal here too.)
# This is also what closes the loophole where a short 2-word phrase like "left hip" can pass the
# blocklist AND the doc-count uniqueness check yet still score high by fuzzy coincidence against
# an unrelated note that merely shares the word "left".
_LATERALITY_WORDS = {"left", "right", "bilateral"}


def _is_bare_laterality_locator(keyword: str) -> bool:
    words = keyword.lower().split()
    return len(words) == 2 and words[0] in _LATERALITY_WORDS


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def _has_hedge_language(text: str) -> bool:
    lowered = text.lower()
    return any(pattern in lowered for pattern in _HEDGE_PATTERNS)


def _word_boundary_contains(haystack: str, needle: str) -> bool:
    """Substring containment, but anchored to word boundaries so a short keyword/abbreviation
    (e.g. "ms", "als", "cf") can't false-positive-match inside an unrelated longer word
    (e.g. "ms" inside "symptoms", "als" inside "also")."""
    return re.search(r"\b" + re.escape(needle) + r"\b", haystack) is not None


_MIN_MEANINGFUL_MATCH_CHARS = 6


def _containment_score(query_lower: str, target_lower: str) -> float:
    """1.0 if `target_lower` (a keyword phrase or description) appears verbatim in the query
    (or vice versa) at a word boundary; otherwise the longest-common-substring length relative
    to the target, which behaves like a "partial ratio" fuzzy match without a rapidfuzz dependency.

    A short target (e.g. an 8-character word like "dementia") can share a purely coincidental
    substring with unrelated text — "replacement" contains "ement", which also sits inside
    "dementia" — and score deceptively high purely because the ratio's denominator is small, not
    because the overlap means anything. Matches shorter than a meaningful floor don't count at
    all, so a handful of coincidentally shared letters can no longer outscore a real match.
    """
    if _word_boundary_contains(query_lower, target_lower) or _word_boundary_contains(target_lower, query_lower):
        return 1.0
    matcher = SequenceMatcher(None, query_lower, target_lower)
    match = matcher.find_longest_match(0, len(query_lower), 0, len(target_lower))
    if match.size < _MIN_MEANINGFUL_MATCH_CHARS:
        return 0.0
    return match.size / max(1, len(target_lower))


@dataclass
class Candidate:
    code: str
    description: str
    score: float
    laterality: str
    laterality_match: bool
    is_rare_disease: bool
    category: str


class ICD10KnowledgeGraph:
    def __init__(self, data_path: Path | None = None) -> None:
        self.data_path = data_path or _DEFAULT_DATA_PATH
        self.graph = nx.DiGraph()
        self._load()
        # Diagnostics for the most recent match() call, surfaced in the ICD Coder's rationale.
        self.last_match_mode = "keyword"

    def _load(self) -> None:
        with open(self.data_path, "r", encoding="utf-8") as f:
            records = json.load(f)

        for rec in records:
            category = rec["category"]
            if not self.graph.has_node(category):
                self.graph.add_node(category, kind="category")
            self.graph.add_node(rec["code"], kind="code", **rec)
            self.graph.add_edge(category, rec["code"])

        # A keyword phrase shared across several codes (e.g. "malignant neoplasm", "lysosomal
        # storage") is not distinctive evidence for any ONE of them — track corpus-wide
        # frequency so match() can tell a code-specific phrase from a generic category term.
        self._keyword_doc_count = Counter(
            kw.lower() for rec in records for kw in rec["keywords"]
        )
        # One embedding chunk per code (each code is already an atomic diagnostic unit, unlike
        # a multi-criterion policy document) — description first so it dominates the embedding,
        # keywords appended for synonym coverage.
        self._code_order = [rec["code"] for rec in records]
        self._chunk_texts = [
            f"{rec['description']}. {' '.join(rec['keywords'])}" for rec in records
        ]

    def codes(self) -> list[dict]:
        return [
            data for _, data in self.graph.nodes(data=True) if data.get("kind") == "code"
        ]

    def _semantic_scores(self, query_text: str) -> dict[str, float] | None:
        """Per-code semantic score (query vs. that code's chunk), rescaled into the 0..1 band.
        Returns None when embeddings are unavailable so the caller falls back to pure keyword
        matching — the exact same fallback discipline as the Policy RAG hybrid retriever."""
        if not USE_ICD_EMBEDDING_MATCHING:
            return None
        client = get_embedding_client()
        if not client.is_available:
            return None
        vectors = client.embed([query_text] + self._chunk_texts)
        if vectors is None:
            return None
        query_vec, chunk_vecs = vectors[0], vectors[1:]
        scores: dict[str, float] = {}
        for code, chunk_vec in zip(self._code_order, chunk_vecs):
            sim = cosine_similarity(query_vec, chunk_vec)
            scores[code] = max(0.0, min(1.0, (sim - _COS_FLOOR) / (_COS_CEIL - _COS_FLOOR)))
        return scores

    def match(
        self,
        diagnosis_text: str,
        symptoms: list[str] | None = None,
        laterality: str = "not_applicable",
        top_k: int = 5,
    ) -> list[Candidate]:
        query_text = diagnosis_text + " " + " ".join(symptoms or [])
        query_tokens = _tokenize(query_text)
        query_lower = diagnosis_text.lower()
        hedged = _has_hedge_language(diagnosis_text)

        semantic_scores = self._semantic_scores(query_text)
        self.last_match_mode = "hybrid keyword and semantic" if semantic_scores is not None else "keyword"

        scored: list[Candidate] = []
        for node in self.codes():
            node_tokens = _tokenize(" ".join(node["keywords"]) + " " + node["description"])
            token_recall = len(query_tokens & node_tokens) / max(1, len(query_tokens))

            # Only a phrase that is BOTH multi-word and unique to this one code (or the full
            # description, always code-specific by construction) can earn the confident-match
            # shortcut below. A single generic word (e.g. "tremor") or a phrase shared across
            # several related codes (e.g. "lysosomal storage", "malignant neoplasm") must not
            # out-rank a real code-specific match elsewhere.
            distinctive_targets = [
                kw for kw in node["keywords"]
                if (len(kw.split()) >= 2 or len(kw) >= 8)
                and kw.lower() not in _GENERIC_SHORTCUT_BLOCKLIST
                and not _is_bare_laterality_locator(kw)
                and self._keyword_doc_count[kw.lower()] == 1
            ] + [node["description"]]
            best_fuzzy = 0.0
            best_match_len = 0
            for target in distinctive_targets:
                s = _containment_score(query_lower, target.lower())
                if s > best_fuzzy:
                    best_fuzzy = s
                    best_match_len = len(target)

            if best_fuzzy >= 0.999:
                # A defining keyword/description phrase appears verbatim in the query — treat
                # this as a confident match regardless of how much other narrative surrounds it
                # (token_recall alone would otherwise dilute long real-world notes unfairly).
                # Longer/more specific matched phrases nudge the score higher, so a
                # disease-specific phrase outranks a short phrase shared across several
                # related conditions (e.g. "lysosomal storage" appears for several disorders).
                # This confident shortcut is exact-match evidence, stronger than any embedding
                # similarity, so it is kept as-is rather than blended with the semantic score.
                score = 0.90 + 0.07 * min(1.0, best_match_len / 35)
            else:
                kw_score = 0.15 * token_recall + 0.85 * best_fuzzy
                sem_score = semantic_scores.get(node["code"], 0.0) if semantic_scores is not None else None
                score = _KW_WEIGHT * kw_score + _SEM_WEIGHT * sem_score if sem_score is not None else kw_score
            if hedged:
                score *= _HEDGE_DAMPENING

            node_laterality = node.get("laterality", "not_applicable")
            laterality_match = True
            if node_laterality in ("left", "right", "bilateral") and laterality in ("left", "right", "bilateral"):
                if node_laterality != laterality:
                    laterality_match = False
                    score *= 0.5

            score = round(min(1.0, score), 4)
            scored.append(
                Candidate(
                    code=node["code"],
                    description=node["description"],
                    score=score,
                    laterality=node_laterality,
                    laterality_match=laterality_match,
                    is_rare_disease=bool(node.get("rare_disease", False)),
                    category=node["category"],
                )
            )

        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:top_k]


_graph_singleton: ICD10KnowledgeGraph | None = None


def get_graph() -> ICD10KnowledgeGraph:
    global _graph_singleton
    if _graph_singleton is None:
        _graph_singleton = ICD10KnowledgeGraph()
    return _graph_singleton
