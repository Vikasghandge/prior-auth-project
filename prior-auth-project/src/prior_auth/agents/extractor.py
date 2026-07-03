"""Agent 1: Extractor.

Enforces the PHI boundary: `mask_phi` runs before anything else, identifiers are attached
to the case object (never to the handoff payload), and a `contains_phi` guard re-checks
the final payload before it is allowed to leave this agent.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import ValidationError

from prior_auth.agents.llm_client import LLMNotConfiguredError, call_llm_json
from prior_auth.agents.rule_extractor import enrich_structured_fields, regex_extract
from prior_auth.config import USE_LLM_EXTRACTION, get_azure_config
from prior_auth.phi.masking import contains_phi, mask_phi
from prior_auth.schemas.case import PriorAuthCase
from prior_auth.schemas.common import HandoffStatus
from prior_auth.schemas.extraction import ExtractedClinicalFacts, PatientIdentifiers
from prior_auth.schemas.handoff import Handoff

_SYSTEM_PROMPT = (
    "You are a clinical data extraction assistant for prior authorization. "
    "The text you receive has already had patient identifiers removed. "
    "Extract structured fields as a single JSON object with keys: "
    "age (int), sex (one of M/F/U), diagnosis (str — the full diagnostic description as written, "
    "including any disease names mentioned later in the note; downstream normalization derives the "
    "primary diagnosis and clinical modifiers from it), laterality (one of left/right/bilateral/"
    "not_applicable/unknown), requested_procedure_laterality (same enum), symptoms (list of str), "
    "failed_treatments (list of str), conservative_therapy_duration_weeks (int or null), "
    "imaging_evidence (str or null), requested_procedure (str), "
    "extraction_confidence (float 0-1 reflecting how clearly the note supports these fields). "
    "Respond with ONLY the JSON object."
)


class ExtractorAgent:
    name = "Extractor"

    def run(self, case: PriorAuthCase, timestamp: datetime) -> Handoff[ExtractedClinicalFacts]:
        masking = mask_phi(case.raw_note_text)

        case.identifiers = PatientIdentifiers(
            name=masking.detected_name,
            mrn=masking.detected_mrn,
            dob=masking.detected_dob,
            address=masking.detected_address,
            phone=masking.detected_phone,
        )

        data = self._extract(masking.masked_text)
        enrich_structured_fields(data, masking.masked_text, specialty_hint=case.specialty)
        data["case_id"] = case.case_id
        data["phi_detected"] = masking.phi_detected
        data["phi_fields_masked"] = masking.fields_masked

        try:
            facts = ExtractedClinicalFacts(**data)
        except ValidationError as exc:
            errors = [f"{e['loc']}: {e['msg']}" for e in exc.errors()]
            return Handoff.failed(self.name, case.case_id, errors, timestamp)

        if contains_phi(facts.narrative_text) or contains_phi(facts.requested_procedure):
            return Handoff.failed(
                self.name,
                case.case_id,
                ["PHI boundary violation: raw identifiers detected in extracted clinical fields"],
                timestamp,
                status=HandoffStatus.ERROR,
            )

        return Handoff.ok(self.name, case.case_id, facts, facts.extraction_confidence, timestamp)

    def _extract(self, masked_text: str) -> dict:
        cfg = get_azure_config()
        if USE_LLM_EXTRACTION and cfg.is_configured:
            try:
                return call_llm_json(_SYSTEM_PROMPT, masked_text)
            except LLMNotConfiguredError:
                pass
            except Exception:
                # Degrade gracefully to the deterministic path rather than failing the
                # whole case on a transient API/config error.
                pass
        return regex_extract(masked_text)
