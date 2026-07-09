"""Central configuration: Azure OpenAI settings + the confidence-gate threshold."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# Global ICD confidence gate: ANY top candidate below this — rare disease or not — suspends the
# workflow for human review rather than proceeding to Policy RAG. A single strict bar rather than
# a rare-disease-only carve-out, so a wrong code is never let through just because the underlying
# condition wasn't flagged rare.
ICD_CONFIDENCE_THRESHOLD = 0.90

# Below this, the Critique Agent (Agent 5, read-only QA) adds an advisory warning about an
# upstream agent's confidence to its report. Warn-only by design: the critique never rejects
# or re-routes a case on low confidence — the ICD gates above already own that behavior.
CRITIQUE_CONFIDENCE_WARN_THRESHOLD = 0.75

# Extraction defaults to the deterministic offline path (see agents/rule_extractor.py) so the
# workflow is always runnable/testable without live credentials or API cost. Set
# PRIOR_AUTH_USE_LLM_EXTRACTION=true to route the Extractor through Azure OpenAI instead.
USE_LLM_EXTRACTION = os.getenv("PRIOR_AUTH_USE_LLM_EXTRACTION", "false").strip().lower() == "true"


# Policy retrieval upgrades to hybrid chunk-embedding + keyword search whenever an Azure
# embedding deployment is configured (set to "false" to force the pure keyword path). The
# deterministic criteria checks are unaffected either way — embeddings only influence WHICH
# policy is pulled off the shelf, never whether its rules are met.
USE_EMBEDDING_RETRIEVAL = os.getenv("PRIOR_AUTH_USE_EMBEDDING_RETRIEVAL", "true").strip().lower() == "true"

# ICD coding upgrades to hybrid embedding + keyword matching the same way (independent
# switch from the Policy RAG one above). Embeddings only influence the blended confidence
# score used to RANK candidates; the rare-disease (0.90) and general (0.70) confidence gates,
# hedge-language dampening, and laterality penalty all still apply on top, unchanged.
USE_ICD_EMBEDDING_MATCHING = os.getenv("PRIOR_AUTH_USE_ICD_EMBEDDINGS", "true").strip().lower() == "true"


@dataclass(frozen=True)
class AzureOpenAIConfig:
    endpoint: str | None = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key: str | None = os.getenv("AZURE_OPENAI_API_KEY")
    api_version: str | None = os.getenv("AZURE_OPENAI_API_VERSION")
    deployment: str | None = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AZURE_OPENAI_DEPLOYMENT")
    # Both spellings accepted: AZURE_OPENA_... (a common typo) kept as a fallback.
    embedding_deployment: str | None = (
        os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME")
        or os.getenv("AZURE_OPENA_EMBEDDING_DEPLOYMENT_NAME")
    )

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.api_key and self.deployment)

    @property
    def embeddings_configured(self) -> bool:
        return bool(self.endpoint and self.api_key and self.embedding_deployment)


def get_azure_config() -> AzureOpenAIConfig:
    return AzureOpenAIConfig()
