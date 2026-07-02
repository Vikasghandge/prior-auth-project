"""Generates the synthetic 'regular' doctor-notes dataset (Level 2+ volume/accuracy testing).

Rare-disease cases and the named trap suite are hand-authored instead (see
data/doctor_notes/rare_disease/cases.json and data/edge_cases/edge_cases.json) because
they need precisely tuned wording to exercise the confidence gate and PHI boundary —
this generator only produces the higher-volume "normal" specialty caseload.

Deterministic (seeded) so the dataset is reproducible; re-run to regenerate.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parents[3] / "data"
POLICIES_PATH = DATA_ROOT / "insurer_policies" / "policies.json"
ICD_CODES_PATH = DATA_ROOT / "icd10_kg" / "icd10_codes.json"
NOTES_ROOT = DATA_ROOT / "doctor_notes"

random.seed(42)

# policy_id -> list of representative ICD-10 codes (with laterality variants where applicable)
POLICY_TO_ICD: dict[str, list[str]] = {
    "POL-ORTHO-TKR-001": ["M17.11", "M17.12", "M17.10"],
    "POL-ORTHO-THR-002": ["M16.11", "M16.12"],
    "POL-ORTHO-RCR-003": ["M75.101", "M75.102"],
    "POL-ORTHO-LSF-004": ["M51.26", "M54.16"],
    "POL-ORTHO-ACL-005": ["S83.511A", "S83.512A"],
    "POL-ORTHO-MEN-006": ["S83.241A", "S83.242A"],
    "POL-CARD-PCI-007": ["I25.10", "I20.0"],
    "POL-CARD-CABG-008": ["I25.10"],
    "POL-CARD-PACE-009": ["I49.9"],
    "POL-CARD-ABL-010": ["I48.91"],
    "POL-CARD-TAVR-011": ["I35.0"],
    "POL-ONC-CHEMO-012": ["C50.911", "C50.912", "C34.91", "C18.9"],
    "POL-ONC-RT-013": ["C71.9", "C34.92"],
    "POL-ONC-PET-014": ["C90.00", "C82.90"],
    "POL-ONC-TARG-015": ["C91.00", "C64.1"],
    "POL-NEURO-MS-016": ["G35"],
    "POL-NEURO-EPI-017": ["G40.909"],
    "POL-NEURO-MIG-018": ["G43.909"],
    "POL-NEURO-DBS-019": ["G20"],
    "POL-GI-BIO-020": ["K50.90", "K51.90"],
    "POL-GI-BAR-021": ["K76.0"],
    "POL-GI-ERCP-022": ["K80.20"],
    "POL-GI-LIVER-023": ["K74.60"],
    "POL-GEN-PT-031": ["M54.16"],
    "POL-GEN-DME-KNEE-032": ["M17.10"],
}

LATERALITY_BY_SUFFIX = {"11": "right", "12": "left", "101": "right", "102": "left",
                         "511A": "right", "512A": "left", "241A": "right", "242A": "left",
                         "1": "right", "2": "left"}


def _diagnosis_phrase_for_icd(record: dict) -> str:
    """Derive the note's diagnosis wording from the TARGET ICD code's own keywords rather than
    the policy's diagnosis_keywords — guarantees the generated note text and the gold ICD-10
    code are lexically consistent (a policy's wording doesn't always match its mapped code's
    KG entry, e.g. "morbid obesity" was never a good match for a fatty-liver code).
    """
    non_lateral = [kw for kw in record["keywords"] if not any(w in kw for w in ("left", "right", "bilateral"))]
    candidates = non_lateral or record["keywords"]
    return max(candidates, key=len)


def _laterality_for_code(code: str) -> str:
    if code.endswith(("11", "101", "511A", "241A")):
        return "right"
    if code.endswith(("12", "102", "512A", "242A")):
        return "left"
    return "not_applicable"


TREATMENT_POOL = ["NSAIDs", "physical therapy", "corticosteroid injection", "activity modification",
                   "bracing", "antiarrhythmic medication", "beta-blockers", "disease-modifying medication",
                   "preventive medication trial", "dietary and lifestyle modification", "immunomodulator therapy"]


def _render_note(age: int, sex: str, diagnosis_phrase: str, laterality: str, weeks: int | None,
                  treatments: list[str], imaging_present: bool, severity_word: str | None,
                  procedure_phrase: str, specialty: str) -> str:
    lat_str = f"{laterality} " if laterality in ("left", "right", "bilateral") else ""
    sev_str = f"{severity_word} " if severity_word else ""
    sex_letter = sex
    lines = [f"Patient: {age}{sex_letter} presenting with {sev_str}{lat_str}{diagnosis_phrase}."]
    if treatments:
        weeks_str = f" over approximately {weeks} weeks" if weeks is not None else ""
        lines.append(f"Conservative management including {', '.join(treatments)} was attempted{weeks_str} without adequate improvement.")
    else:
        lines.append("No conservative therapy has been documented yet.")
    if imaging_present:
        lines.append(f"Imaging studies confirm findings consistent with {diagnosis_phrase}.")
    else:
        lines.append("Imaging workup is still pending.")
    lines.append(f"Referring {specialty.replace('_', ' ')} physician requests authorization for {procedure_phrase}.")
    return "\n".join(lines)


def _build_case(case_id: str, policy: dict, icd_code: str, icd_record: dict, variant: str) -> dict:
    laterality = _laterality_for_code(icd_code)
    age = random.randint(28, 82)
    sex = random.choice(["M", "F"])
    diagnosis_phrase = _diagnosis_phrase_for_icd(icd_record)
    procedure_phrase = policy["procedure_keywords"][0]

    severity_criterion = next((c for c in policy["criteria"] if c["check"] == "severity_keywords"), None)
    weeks_criterion = next((c for c in policy["criteria"] if c["check"] == "min_conservative_weeks"), None)
    imaging_criterion = next((c for c in policy["criteria"] if c["check"] == "imaging_required"), None)

    severity_word = random.choice(severity_criterion["value"]) if severity_criterion else None
    required_weeks = weeks_criterion["value"] if weeks_criterion else None

    if variant == "approve":
        weeks = (required_weeks + random.randint(1, 6)) if required_weeks else None
        treatments = random.sample(TREATMENT_POOL, k=min(2, len(TREATMENT_POOL)))
        imaging_present = True if imaging_criterion else random.choice([True, False])
        keep_severity = True
    elif variant == "trap_conservative":
        weeks = max(0, required_weeks - random.randint(4, required_weeks)) if required_weeks else 0
        treatments = random.sample(TREATMENT_POOL, k=1) if weeks else []
        imaging_present = True if imaging_criterion else random.choice([True, False])
        keep_severity = True
    else:  # "varied" — random natural variety, not guaranteed to pass
        weeks = random.choice([None, 2, required_weeks or 6, (required_weeks or 6) + 10])
        treatments = random.sample(TREATMENT_POOL, k=random.randint(0, 2))
        imaging_present = random.choice([True, False])
        keep_severity = random.choice([True, False])

    note_text = _render_note(
        age=age, sex=sex, diagnosis_phrase=diagnosis_phrase, laterality=laterality, weeks=weeks,
        treatments=treatments, imaging_present=imaging_present,
        severity_word=severity_word if keep_severity else None,
        procedure_phrase=procedure_phrase, specialty=policy["specialty"],
    )

    gold = {
        "age": age,
        "sex": sex,
        "diagnosis": (f"{severity_word} " if (severity_word and keep_severity) else "") + f"{laterality + ' ' if laterality in ('left','right') else ''}{diagnosis_phrase}".strip(),
        "laterality": laterality,
        "failed_treatments": treatments,
        "conservative_therapy_duration_weeks": weeks,
        "imaging_evidence": f"findings consistent with {diagnosis_phrase}" if imaging_present else None,
        "requested_procedure": procedure_phrase,
        "icd10_code": icd_code,
        "policy_id": policy["policy_id"],
        "variant": variant,
    }
    return {"case_id": case_id, "specialty": policy["specialty"], "note_text": note_text, "gold": gold}


def generate() -> dict[str, list[dict]]:
    with open(POLICIES_PATH, "r", encoding="utf-8") as f:
        policies = {p["policy_id"]: p for p in json.load(f)}
    with open(ICD_CODES_PATH, "r", encoding="utf-8") as f:
        icd_records = {r["code"]: r for r in json.load(f)}

    by_specialty: dict[str, list[dict]] = {}
    counter = 0
    for policy_id, codes in POLICY_TO_ICD.items():
        policy = policies[policy_id]
        for variant in ("approve", "trap_conservative", "varied"):
            code = random.choice(codes)
            counter += 1
            case_id = f"GEN-{counter:04d}"
            case = _build_case(case_id, policy, code, icd_records[code], variant)
            by_specialty.setdefault(case["specialty"], []).append(case)

    return by_specialty


def write_dataset() -> None:
    by_specialty = generate()
    total = 0
    for specialty, cases in by_specialty.items():
        out_dir = NOTES_ROOT / specialty
        out_dir.mkdir(parents=True, exist_ok=True)
        with open(out_dir / "cases.json", "w", encoding="utf-8") as f:
            json.dump(cases, f, indent=2)
        total += len(cases)
    print(f"Generated {total} synthetic notes across {len(by_specialty)} specialties.")


if __name__ == "__main__":
    write_dataset()
