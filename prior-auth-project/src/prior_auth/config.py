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

# Extraction defaults to the deterministic offline path (see agents/rule_extractor.py) so the
# workflow is always runnable/testable without live credentials or API cost. Set
# PRIOR_AUTH_USE_LLM_EXTRACTION=true to route the Extractor through Azure OpenAI instead.
USE_LLM_EXTRACTION = os.getenv("PRIOR_AUTH_USE_LLM_EXTRACTION", "false").strip().lower() == "true"


@dataclass(frozen=True)
class AzureOpenAIConfig:
    endpoint: str | None = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key: str | None = os.getenv("AZURE_OPENAI_API_KEY")
    api_version: str | None = os.getenv("AZURE_OPENAI_API_VERSION")
    deployment: str | None = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME") or os.getenv("AZURE_OPENAI_DEPLOYMENT")

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.api_key and self.deployment)


def get_azure_config() -> AzureOpenAIConfig:
    return AzureOpenAIConfig()
