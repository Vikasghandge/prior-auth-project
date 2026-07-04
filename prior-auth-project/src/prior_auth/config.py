"""Central configuration: Azure OpenAI settings + the confidence-gate threshold."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

RARE_DISEASE_CONFIDENCE_THRESHOLD = 0.90

# General safety net: below this, ANY ICD coding candidate (not just flagged rare diseases) is
# suspended for human review rather than silently proceeding. Chosen empirically: scoring the
# matcher against all 90 labeled sample cases showed a clean split at this line — every prediction
# below ~0.70 was wrong (21/21), while raising the bar much higher starts catching correct
# predictions too (see data/doctor_notes calibration run). This is what stops a coverage gap (a
# diagnosis with no real match in the knowledge graph, e.g. a specialty that isn't represented)
# from silently producing a confident-looking wrong code instead of asking for a human.
GENERAL_ICD_CONFIDENCE_THRESHOLD = 0.70

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
