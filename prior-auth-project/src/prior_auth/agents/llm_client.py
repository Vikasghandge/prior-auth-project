"""Thin Azure OpenAI wrapper used only by the Extractor's LLM path.

Only ever called with already-PHI-masked text (see `PHIMaskingBoundaryError` usage in
extractor.py) — this module has no knowledge of PHI itself, that guarantee is enforced
by the caller.
"""
from __future__ import annotations

import json

from openai import AzureOpenAI

from prior_auth.config import get_azure_config


class LLMNotConfiguredError(RuntimeError):
    """Raised when Azure OpenAI credentials are absent; callers should fall back to the
    deterministic regex extractor rather than crash the workflow."""


def call_llm_json(system_prompt: str, user_prompt: str) -> dict:
    cfg = get_azure_config()
    if not cfg.is_configured:
        raise LLMNotConfiguredError("Azure OpenAI is not configured; use the offline extractor.")

    client = AzureOpenAI(
        azure_endpoint=cfg.endpoint,
        api_key=cfg.api_key,
        api_version=cfg.api_version or "2024-02-01",
    )
    response = client.chat.completions.create(
        model=cfg.deployment,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    return json.loads(content)
