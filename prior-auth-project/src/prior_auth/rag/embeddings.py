"""Azure OpenAI embedding client for the Policy RAG retriever.

Design constraints, in order:
1. NEVER break the offline path — any missing config or API failure makes callers fall
   back to keyword retrieval, silently and per-call.
2. Reproducible — every embedding is cached on disk keyed by (deployment, text hash), so
   the same corpus/query always yields the same vector (and repeat runs cost nothing).
3. Only ever called with already-PHI-masked text; the PHI boundary is enforced upstream
   (same contract as agents/llm_client.py).
"""
from __future__ import annotations

import hashlib
import json
import math
import threading

from prior_auth.config import get_azure_config
from prior_auth.utils.paths import LOGS_ROOT

_CACHE_PATH = LOGS_ROOT / "embedding_cache.json"

# The api-version in .env may target chat models or contain typos; embeddings are stable on
# this GA version, so it is tried as a fallback before giving up.
_FALLBACK_API_VERSION = "2024-02-01"


class EmbeddingClient:
    def __init__(self) -> None:
        self._cfg = get_azure_config()
        self._client = None
        self._client_failed = False
        self._lock = threading.Lock()
        self._cache: dict[str, list[float]] = {}
        self._cache_dirty = False
        if _CACHE_PATH.exists():
            try:
                self._cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            except Exception:
                self._cache = {}

    @property
    def is_available(self) -> bool:
        return self._cfg.embeddings_configured and not self._client_failed

    def _key(self, text: str) -> str:
        raw = f"{self._cfg.embedding_deployment}|{text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _get_client(self):
        if self._client is not None:
            return self._client
        from openai import AzureOpenAI  # imported lazily so offline runs never need it

        self._client = AzureOpenAI(
            azure_endpoint=self._cfg.endpoint,
            api_key=self._cfg.api_key,
            api_version=self._cfg.api_version or _FALLBACK_API_VERSION,
        )
        return self._client

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        try:
            response = client.embeddings.create(model=self._cfg.embedding_deployment, input=texts)
        except Exception:
            # Retry once on the GA embeddings api-version (handles a chat-oriented or
            # malformed AZURE_OPENAI_API_VERSION without requiring a .env change).
            from openai import AzureOpenAI

            client = AzureOpenAI(
                azure_endpoint=self._cfg.endpoint,
                api_key=self._cfg.api_key,
                api_version=_FALLBACK_API_VERSION,
            )
            response = client.embeddings.create(model=self._cfg.embedding_deployment, input=texts)
            self._client = client  # keep the working client for subsequent calls
        return [item.embedding for item in response.data]

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        """Vectors for `texts` (cache-first). Returns None on any failure — the caller
        falls back to keyword-only retrieval for that call."""
        if not self.is_available:
            return None
        with self._lock:
            missing = [t for t in texts if self._key(t) not in self._cache]
            if missing:
                try:
                    vectors = self._call_api(missing)
                except Exception:
                    # One hard failure disables the client for this process so a dead
                    # network doesn't add a timeout to every single case.
                    self._client_failed = True
                    return None
                for text, vec in zip(missing, vectors):
                    self._cache[self._key(text)] = vec
                self._cache_dirty = True
                self._flush()
            return [self._cache[self._key(t)] for t in texts]

    def _flush(self) -> None:
        if not self._cache_dirty:
            return
        try:
            _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _CACHE_PATH.write_text(json.dumps(self._cache), encoding="utf-8")
            self._cache_dirty = False
        except Exception:
            pass  # cache is an optimization, never a failure source


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


_client_singleton: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = EmbeddingClient()
    return _client_singleton
