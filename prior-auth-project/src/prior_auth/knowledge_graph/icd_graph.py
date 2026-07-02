"""Mini ICD-10 knowledge graph (NetworkX) + keyword/fuzzy matcher used by the ICD Coder agent.

Deliberately NOT an LLM call: coding confidence must be deterministic and explainable so the
confidence gate (rare-disease threshold 0.90) behaves consistently across runs.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import networkx as nx

_DEFAULT_DATA_PATH = Path(__file__).resolve().parents[3] / "data" / "icd10_kg" / "icd10_codes.json"

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


def _containment_score(query_lower: str, target_lower: str) -> float:
    """1.0 if `target_lower` (a keyword phrase or description) appears verbatim in the query
    (or vice versa) at a word boundary; otherwise the longest-common-substring length relative
    to the target, which behaves like a "partial ratio" fuzzy match without a rapidfuzz dependency.
    """
    if _word_boundary_contains(query_lower, target_lower) or _word_boundary_contains(target_lower, query_lower):
        return 1.0
    matcher = SequenceMatcher(None, query_lower, target_lower)
    match = matcher.find_longest_match(0, len(query_lower), 0, len(target_lower))
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

    def codes(self) -> list[dict]:
        return [
            data for _, data in self.graph.nodes(data=True) if data.get("kind") == "code"
        ]

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
                score = 0.90 + 0.07 * min(1.0, best_match_len / 35)
            else:
                score = 0.15 * token_recall + 0.85 * best_fuzzy
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
