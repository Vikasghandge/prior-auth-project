"""Deterministic fallback extractor: used when Azure OpenAI isn't configured, and always
available so the workflow is fully runnable/testable offline. Operates ONLY on already
PHI-masked text.
"""
from __future__ import annotations

import re

_AGE_SEX_INLINE = re.compile(r"Patient:\s*(\d{1,4})\s*([A-Za-z])\b")
# Bare "64F"/"67M" at the very start of a note, with no "Patient:" label — the new dataset's
# notes are written this way (e.g. "64F severe right knee pain..."). Anchored to the start so
# it can't false-match an unrelated number+letter later in the note.
_AGE_SEX_BARE = re.compile(r"^\s*(\d{1,3})\s*([MF])\b", re.IGNORECASE)
_AGE_YEARS_OLD = re.compile(r"(\d{1,4})\s*[- ]?years?[- ]?old", re.IGNORECASE)

_TREATMENT_SENTENCE = re.compile(
    r"(?:Failed|Conservative management including)\s+(.*?)(?:\s+(?:over|was attempted|without|for)\b|[.\n])",
    re.IGNORECASE,
)
_WEEKS = re.compile(r"(\d{1,3})\s*weeks?", re.IGNORECASE)
_MONTHS = re.compile(r"(\d{1,3})\s*months?", re.IGNORECASE)

_IMAGING_SENTENCE = re.compile(
    r"([^.\n]*\b(?:X-ray|MRI|CT|HRCT|MRCP|imaging|echocardiogram|EMG|biopsy|angiography|"
    r"colonoscopy|enzyme assay|genetic (?:testing|confirmation)|antibody|autoantibody|"
    r"ceruloplasmin|copper|slit-lamp|serum|sweat chloride|confirmed by)\b[^.\n]*)",
    re.IGNORECASE,
)
_NO_IMAGING = re.compile(
    r"(no imaging|imaging.{0,20}pending|imaging workup is still pending|"
    r"has not been (?:performed|obtained|done)|not yet been (?:performed|obtained|done)|"
    r"has not yet been (?:performed|obtained|done))",
    re.IGNORECASE,
)

_PROCEDURE_SENTENCE = re.compile(
    r"(?:requests?(?: authorization for)?|recommends?|requesting|requiring)\s+(.*?)(?:[.\n]|$)",
    re.IGNORECASE,
)
# Fallback for the reverse phrasing the leading-trigger pattern above can't catch: "<procedure>
# recommended."/"<procedure> requested." with the trigger word AFTER the procedure name, not
# before it (e.g. "Angioplasty recommended.", "DBS evaluation requested."). The character class
# excludes '.', so a candidate match can't cross a sentence boundary and swallow unrelated
# earlier text — the leftmost successful match is always anchored to the start of the sentence
# actually containing the trigger word.
_PROCEDURE_TRAILING = re.compile(
    r"([A-Za-z][A-Za-z0-9 /,'-]{1,80}?)\s+(?:is\s+)?(?:requested|recommended)\b\.?",
    re.IGNORECASE,
)

_LATERALITY_WORDS = {
    "left": re.compile(r"\bleft\b", re.IGNORECASE),
    "right": re.compile(r"\bright\b", re.IGNORECASE),
    "bilateral": re.compile(r"\bbilateral\b", re.IGNORECASE),
}

_LEADING_PATIENT_TAG = re.compile(r"^Patient:\s*\d{1,4}\s*[A-Za-z]?\.?\s*", re.IGNORECASE)
_IDENTIFIER_LABELS = re.compile(
    r"\b(?:Name|DOB|MRN#?|residing at|phone|email|SSN)\s*:?\s*,?\s*", re.IGNORECASE
)
_REDACTION_TOKEN = re.compile(r"\[REDACTED_\w+\],?\s*")


def _find_age_sex(text: str) -> tuple[int | None, str | None]:
    m = _AGE_SEX_INLINE.search(text)
    if m:
        return int(m.group(1)), m.group(2).upper()
    m = _AGE_SEX_BARE.search(text)
    if m:
        return int(m.group(1)), m.group(2).upper()

    m = _AGE_YEARS_OLD.search(text)
    if m:
        age = int(m.group(1))
        if re.search(r"\bfemale\b|\bwoman\b", text, re.IGNORECASE):
            return age, "F"
        if re.search(r"\bmale\b|\bman\b", text, re.IGNORECASE):
            return age, "M"
        return age, "U"
    return None, None


def _find_laterality(text: str) -> str:
    hits = [name for name, pattern in _LATERALITY_WORDS.items() if pattern.search(text)]
    if "bilateral" in hits:
        return "bilateral"
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        # Both "left" and "right" mentioned in the same section — report unknown rather
        # than guessing which one applies.
        return "unknown"
    return "not_applicable"


def _find_conservative_weeks(text: str, treatment_sentence: str | None) -> int | None:
    """Duration is read ONLY from the treatment-failure sentence itself, never the whole note —
    otherwise an unrelated duration elsewhere (e.g. "pain for 18 months", describing how long the
    patient has had symptoms, not how long conservative therapy was tried) gets misread as the
    conservative-therapy duration. That's not a harmless mixup: a fabricated 72-week therapy
    duration can make a policy's minimum-conservative-therapy criterion look satisfied when the
    note never actually said so."""
    if treatment_sentence:
        m = _WEEKS.search(treatment_sentence)
        if m:
            return int(m.group(1))
        m = _MONTHS.search(treatment_sentence)
        if m:
            return int(m.group(1)) * 4
    if re.search(r"no conservative therapy|not been (?:tried|attempted|prescribed)|has not tried", text, re.IGNORECASE):
        return 0
    return None


def _treatment_sentence_match(text: str) -> re.Match | None:
    return _TREATMENT_SENTENCE.search(text)


def _treatment_sentence_span(text: str, match: re.Match) -> str:
    """The full sentence the treatment-failure clause sits in (not just the captured group),
    so a trailing duration like "...was attempted over 15 weeks without improvement." is still
    in scope even though it comes after the captured treatment-list group ends. Scoped to the
    next period only, not the next newline — notes in this dataset wrap a single sentence across
    multiple lines with no period at the line break, so treating '\\n' as a sentence end would
    cut the duration off if it happens to land on the next line."""
    end = match.end()
    stop = text.find(".", end)
    sentence_end = stop if stop != -1 else len(text)
    return text[match.start():sentence_end]


def _find_treatments(match: re.Match | None) -> list[str]:
    if not match:
        return []
    raw = match.group(1)
    parts = re.split(r",\s*(?:and\s+)?|\s+and\s+", raw)
    return [p.strip().rstrip(".") for p in parts if p.strip()]


def _find_imaging(text: str) -> str | None:
    if _NO_IMAGING.search(text):
        return None
    m = _IMAGING_SENTENCE.search(text)
    if m:
        return m.group(1).strip()
    return None


def _clean_diagnosis_section(diagnosis_section: str) -> str | None:
    """The diagnosis field is the full clinical narrative (not just the first clause) so the
    ICD Coder's keyword/fuzzy matcher sees disease names mentioned in later sentences too —
    e.g. "... with hepatic dysfunction. Wilson's disease confirmed by ..." must not lose the
    "Wilson's disease" sentence just because it comes after the first period.
    """
    cleaned = _REDACTION_TOKEN.sub("", diagnosis_section)
    cleaned = _IDENTIFIER_LABELS.sub("", cleaned)
    cleaned = _LEADING_PATIENT_TAG.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.")
    return cleaned or None



def _find_symptoms(text: str) -> list[str]:
    m = re.search(r"(?:presents with|complains of|experiencing|symptoms include|with)\s+(.*?)(?:for |[.\n]|$)", text, re.IGNORECASE)
    if not m:
        return []
    raw = m.group(1)
    parts = re.split(r",\s*(?:and\s+)?|\s+and\s+", raw)
    return [p.strip().rstrip(".") for p in parts if p.strip()]

def _find_symptom_duration(diagnosis_section: str) -> str | None:
    m = re.search(r"\bfor\s+(\d+\s+(?:months?|weeks?|days?|years?))\b", diagnosis_section, re.IGNORECASE)
    if m:
        return m.group(1)
    return None

def regex_extract(masked_text: str) -> dict:
    """Best-effort structured extraction from de-identified note text.

    Missing/invalid fields are simply absent (or left as parsed-but-invalid, e.g. an
    out-of-range age) so that Pydantic validation surfaces the failure rather than the
    extractor silently guessing — matching the "fail gracefully" requirement.
    """
    age, sex = _find_age_sex(masked_text)
    fields: dict = {}
    if age is not None:
        fields["age"] = age
    if sex is not None:
        fields["sex"] = sex

    # Split the note into a "diagnosis section" and the trailing procedure-request clause so
    # laterality can be read independently for each — this is what lets us catch a note that
    # documents one side but requests the procedure for the other (see edge cases EDGE-0006..10).
    procedure_match = _PROCEDURE_SENTENCE.search(masked_text)
    if procedure_match:
        diagnosis_section = masked_text[: procedure_match.start()]
        procedure_text = procedure_match.group(1)
    else:
        trailing_matches = list(_PROCEDURE_TRAILING.finditer(masked_text))
        if trailing_matches:
            trailing_match = trailing_matches[-1]
            diagnosis_section = masked_text[: trailing_match.start()]
            procedure_text = trailing_match.group(1)
        else:
            diagnosis_section = masked_text
            procedure_text = ""

    diagnosis = _clean_diagnosis_section(diagnosis_section)
    if diagnosis:
        fields["diagnosis"] = diagnosis

    fields["laterality"] = _find_laterality(diagnosis_section)
    
    symptoms = _find_symptoms(diagnosis_section)
    if symptoms:
        fields["symptoms"] = symptoms
        
    symptom_duration = _find_symptom_duration(diagnosis_section)
    if symptom_duration:
        fields["symptom_duration"] = symptom_duration

    fields["requested_procedure_laterality"] = (
        _find_laterality(procedure_text) if procedure_text else "not_applicable"
    )

    treatment_match = _treatment_sentence_match(masked_text)
    treatments = _find_treatments(treatment_match)
    fields["failed_treatments"] = treatments

    treatment_sentence = _treatment_sentence_span(masked_text, treatment_match) if treatment_match else None
    weeks = _find_conservative_weeks(masked_text, treatment_sentence)
    if weeks is not None:
        fields["conservative_therapy_duration_weeks"] = weeks

    imaging = _find_imaging(masked_text)
    fields["imaging_evidence"] = imaging

    if procedure_text:
        fields["requested_procedure"] = procedure_text.strip().rstrip(".")

    # Confidence reflects how many *critical* fields were successfully parsed out.
    critical = ["age", "sex", "diagnosis", "requested_procedure"]
    found = sum(1 for c in critical if fields.get(c) not in (None, ""))
    optional_bonus = 0.05 * sum(1 for v in (treatments, weeks, imaging) if v)
    fields["extraction_confidence"] = round(min(0.99, 0.5 + 0.1 * found + optional_bonus), 4)

    return fields


# ---------------------------------------------------------------------------
# Structured-output enrichment
#
# Runs after the base extraction (regex OR LLM) so both paths emit the same normalized,
# structured shape. It never *removes* signal: the full narrative extracted into `diagnosis`
# is preserved in `diagnosis_narrative` (which the downstream matchers read), and the free-text
# `imaging_evidence` is kept alongside the structured `imaging` object. Only additive/normalizing.
# ---------------------------------------------------------------------------

# Ordered so the most specific/severe qualifier wins when several co-occur.
_SEVERITY_TERMS = [
    "severe", "advanced", "end-stage", "moderate", "mild", "acute", "chronic",
    "metastatic", "locally advanced", "refractory", "progressive",
]

# Words pulled OUT of the primary diagnosis (they live in clinical_modifiers instead).
_DX_MODIFIER = re.compile(
    r"\b(?:a|an|the|mild|moderate|severe|advanced|chronic|acute|end[- ]stage|metastatic|"
    r"refractory|progressive|locally[- ]advanced|left|right|bilateral)\b",
    re.IGNORECASE,
)

_DURATION = re.compile(r"(\d{1,3})\s*[- ]?(week|month|year)s?", re.IGNORECASE)

# Whole-word procedure abbreviations preserved in their canonical casing.
_PROC_ABBREV = {
    "tavr": "TAVR", "tavi": "TAVI", "pci": "PCI", "cabg": "CABG", "tka": "TKA",
    "tkr": "TKR", "thr": "THR", "tha": "THA", "acl": "ACL", "mri": "MRI",
    "ct": "CT", "emg": "EMG", "dmt": "DMT", "dbs": "DBS",
}

# (search-keyword, canonical modality label) — first hit wins.
_MODALITY_MAP = [
    ("x-ray", "X-ray"), ("x ray", "X-ray"), ("hrct", "HRCT"), ("mrcp", "MRCP"),
    ("mri", "MRI"), ("ct", "CT"), ("echocardiogram", "Echocardiogram"),
    ("angiography", "Angiography"), ("colonoscopy", "Colonoscopy"), ("emg", "EMG"),
    ("biopsy", "Biopsy"), ("ultrasound", "Ultrasound"), ("slit-lamp", "Slit-lamp exam"),
    ("enzyme assay", "Enzyme assay"), ("sweat chloride", "Sweat chloride test"),
    ("ceruloplasmin", "Serum copper studies"), ("genetic", "Genetic testing"),
    ("antibody", "Antibody panel"), ("autoantibody", "Antibody panel"),
]

# Note-level department / physician signals -> canonical specialty.
_DEPARTMENT_SPECIALTY = [
    ("cardiology", "Cardiology"), ("cardiac", "Cardiology"),
    ("orthopedics", "Orthopedics"), ("orthopaedics", "Orthopedics"), ("orthopedic", "Orthopedics"),
    ("neurology", "Neurology"), ("neurologist", "Neurology"),
    ("gastroenterology", "Gastroenterology"), ("gastroenterologist", "Gastroenterology"),
    ("hepatology", "Gastroenterology"),
    ("oncology", "Oncology"), ("oncologist", "Oncology"),
    # --- Expansion: 10 additional specialties (appended so no existing match order changes) ---
    ("pulmonology", "Pulmonology"), ("pulmonologist", "Pulmonology"),
    ("rheumatology", "Rheumatology"), ("rheumatologist", "Rheumatology"),
    ("endocrinology", "Endocrinology"), ("endocrinologist", "Endocrinology"),
    ("nephrology", "Nephrology"), ("nephrologist", "Nephrology"),
    ("dermatology", "Dermatology"), ("dermatologist", "Dermatology"),
    ("urology", "Urology"), ("urologist", "Urology"),
    ("psychiatry", "Psychiatry"), ("psychiatrist", "Psychiatry"),
    ("otolaryngology", "Ent"), ("otolaryngologist", "Ent"), (" ent ", "Ent"),
    ("ophthalmology", "Ophthalmology"), ("ophthalmologist", "Ophthalmology"),
    ("infectious disease", "Infectious_disease"),
    ("pain management", "General"), ("occupational medicine", "General"), ("internal medicine", "General"),
]

# Fallback: infer from diagnosis / procedure vocabulary when no department is named.
_SPECIALTY_KEYWORDS = [
    ("Cardiology", ["coronary", "aortic", "cardiac", "tavr", "pci", "myocard", "angina",
                    "echocardiogram", "valve"]),
    ("Oncology", ["neoplasm", "malignan", "cancer", "tumor", "carcinoma", "chemotherap",
                  "metasta", "lymphoma", "leukemia"]),
    ("Gastroenterology", ["bowel", "colitis", "crohn", "colonoscopy", "hepatic", "liver",
                          "wilson", "mrcp", "biliary", "pancrea", "biologic"]),
    ("Neurology", ["sclerosis", "amyotrophic", "seizure", "epilep", "radiculopathy", "tremor",
                   "parkinson", "migraine", "neuropath", "demyelinat", "disease-modifying"]),
    ("Orthopedics", ["osteoarthritis", "arthroplasty", "joint", "knee", "hip", "spine",
                     "replacement", "degenerative", "physical therapy"]),
    # --- Expansion: fallback keyword pools for the 10 additional specialties ---
    ("Pulmonology", ["copd", "emphysema", "asthma", "pulmonary", "bronch", "sleep apnea", "cpap",
                      "respiratory failure", "oxygen therapy"]),
    ("Rheumatology", ["rheumatoid", "lupus", "ankylosing spondylitis", "psoriatic arthritis",
                       "gout", "scleroderma", "sjogren", "fibromyalgia"]),
    ("Endocrinology", ["diabetes", "thyroid", "hyperparathyroidism", "adrenal", "cushing",
                        "insulin", "glucose"]),
    ("Nephrology", ["renal", "kidney", "dialysis", "nephro", "glomerul", "ckd", "esrd"]),
    ("Dermatology", ["psoriasis", "eczema", "dermatitis", "hidradenitis", "skin"]),
    ("Urology", ["prostat", "bladder", "urinary", "urolog", "erectile", "incontinence"]),
    ("Psychiatry", ["depress", "bipolar", "schizophreni", "anxiety", "psychiatric", "ptsd"]),
    ("Ent", ["sinus", "tonsil", "hearing loss", "cochlear", "otitis", "nasal"]),
    ("Ophthalmology", ["macular", "glaucoma", "cataract", "retin", "vision"]),
    ("Infectious_disease", ["hiv", "hepatitis", "sepsis", "osteomyelitis", "tuberculosis"]),
]


def _strip_dx_modifiers(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _DX_MODIFIER.sub(" ", text)).strip(" ,.-")


def _normalize_diagnosis(narrative: str, full_text: str) -> str | None:
    """Reduce the diagnosis narrative to the primary disease name, dropping severity/laterality
    qualifiers and surrounding framing. Best-effort and display-only (matchers use the narrative),
    so an imperfect reduction never affects the workflow."""
    cand: str | None = None

    m = re.search(r"presenting with\s+(.+?)(?:[.\n;,]| who\b| and was\b|$)", full_text, re.IGNORECASE)
    if m:
        cand = m.group(1)

    if not cand:
        # Rare-disease phrasing puts the disease before "confirmed by ..." (often a later sentence).
        for sentence in re.split(r"(?<=[.\n])\s+", narrative):
            cm = re.search(r"([A-Za-z][A-Za-z0-9'\- ]+?)\s+confirmed\b", sentence)
            if cm:
                cand = cm.group(1)
                break

    if not cand:
        cand = re.split(r"(?<=[.\n])\s+", narrative.strip(), maxsplit=1)[0]

    cand = _strip_dx_modifiers(cand)
    if not cand or len(cand) < 3:
        return None
    return cand[0].upper() + cand[1:]


def _extract_severity(text: str) -> str | None:
    low = text.lower()
    for term in _SEVERITY_TERMS:
        # Treat internal spaces/hyphens interchangeably ("end-stage" == "end stage") in one pass,
        # avoiding a nested character class.
        pattern = r"\b" + re.sub(r"[ -]+", "[ -]", term) + r"\b"
        if re.search(pattern, low):
            return term
    return None


def _extract_duration_weeks(text: str) -> int | None:
    m = _DURATION.search(text)
    if not m:
        return None
    value, unit = int(m.group(1)), m.group(2).lower()
    return value if unit == "week" else value * 4 if unit == "month" else value * 52


def _titlecase_token(token: str) -> str:
    key = re.sub(r"[^a-z0-9]", "", token.lower())
    if key in _PROC_ABBREV:
        return _PROC_ABBREV[key]
    # A token already written in all caps (e.g. an abbreviation we don't know, like "IVIG")
    # is deliberate clinical shorthand — preserve it rather than mangling it to "Ivig".
    if len(token) >= 2 and token.isupper():
        return token
    return token[:1].upper() + token[1:].lower() if token else token


def _normalize_procedure(raw: str) -> str:
    """Canonical casing only (uppercase known abbreviations, title-case the rest). No tokens are
    dropped, so the downstream case-insensitive template/policy matching is unchanged."""
    raw = re.sub(r"\s{2,}", " ", raw.strip().rstrip("."))
    if not raw:
        return raw
    return " ".join(_titlecase_token(w) for w in raw.split(" "))


def _imaging_finding(text: str) -> str | None:
    m = re.search(r"consistent with\s+(.+)$", text, re.IGNORECASE)
    if m:
        return "Findings consistent with " + m.group(1).strip(" .")
    return text.strip(" .")[:200] or None


def _structure_imaging(imaging_evidence: str | None) -> dict:
    if not imaging_evidence:
        return {"modality": None, "finding": None}
    low = imaging_evidence.lower()
    modality = "Imaging"
    for keyword, label in _MODALITY_MAP:
        if re.search(r"\b" + re.escape(keyword) + r"\b", low):
            modality = label
            break
    return {"modality": modality, "finding": _imaging_finding(imaging_evidence)}


def _infer_specialty(text: str, diagnosis: str = "", procedure: str = "", hint: str | None = None) -> str:
    low_text = text.lower()
    for keyword, specialty in _DEPARTMENT_SPECIALTY:
        if re.search(r"\b" + keyword + r"\b", low_text):
            return specialty

    blob = f"{text} {diagnosis} {procedure}".lower()
    for specialty, keywords in _SPECIALTY_KEYWORDS:
        if any(kw in blob for kw in keywords):
            return specialty

    if hint:
        hint_low = hint.lower()
        for keyword, specialty in _DEPARTMENT_SPECIALTY:
            if keyword in hint_low:
                return specialty
    return "Unknown"


def enrich_structured_fields(data: dict, masked_text: str, specialty_hint: str | None = None) -> dict:
    """Add the normalized/structured fields expected by downstream agents, in place.

    Preserves the full narrative (as `diagnosis_narrative`) and the free-text `imaging_evidence`
    so no downstream matcher loses signal; only normalizes `diagnosis`/`requested_procedure` and
    layers on `specialty`, `clinical_modifiers`, and structured `imaging`.
    """
    narrative = data.get("diagnosis") or ""
    data["diagnosis_narrative"] = narrative

    primary = _normalize_diagnosis(narrative, masked_text)
    if primary:
        data["diagnosis"] = primary

    laterality = data.get("laterality", "not_applicable")
    if laterality not in ("left", "right", "bilateral"):
        laterality = "not_applicable"
    data["clinical_modifiers"] = {
        "severity": _extract_severity(narrative),
        "laterality": laterality,
        "duration_weeks": _extract_duration_weeks(masked_text),
    }

    data["imaging"] = _structure_imaging(data.get("imaging_evidence"))

    if data.get("requested_procedure"):
        data["requested_procedure"] = _normalize_procedure(data["requested_procedure"])

    data["specialty"] = _infer_specialty(
        masked_text,
        diagnosis=narrative,
        procedure=data.get("requested_procedure", ""),
        hint=specialty_hint,
    )
    return data
