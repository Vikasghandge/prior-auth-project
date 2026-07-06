# Prior Authorization AI Pipeline - Simple Overview

## 1. DATASETS - Detailed

### Doctor Notes Dataset (220 rows)

**What:** Raw doctor notes from actual patient visits, unstructured and messy

**Contains:**

- patient_id: Unique patient identifier
- policy_number: Insurance policy they're enrolled in
- contact_info: Phone, address (will be masked for privacy)
- specialty: Medical field (Orthopedics, Cardiology, Neurology, etc.)
- doctor_note: Actual text written by doctor (messy, informal, incomplete)

**Example Doctor Note:**

```
"Pt came in w/ severe knee pain x 3 months. Tried PT for 12 wks, NSAIDs, 
cortisone shot last month - minimal relief. X-ray shows moderate OA. 
Recommend total knee replacement. Failed conservative management."
```

**Why this matters:** This is the ONLY input doctors provide. Everything is extracted from this messy text. The pipeline must handle:

- Abbreviations (pt = patient, x = times, wks = weeks)
- Medical jargon (OA = osteoarthritis, NSAIDs = medications)
- Incomplete information (some doctors document poorly)
- Varying formats (no standardization across doctors)

**Pipeline challenge:** Turn this mess into structured data that insurance systems understand

---

### Policies Dataset (34 rows)

**What:** Insurance company coverage policies - the rules that determine what gets approved

**Contains:**

- policy_number: Which insurance plan
- specialty: What medical field this policy covers
- procedure: What specific treatment (e.g., "Total Knee Replacement")
- covered_diagnoses: Which diagnoses allow this procedure
- policy_document: Full text of policy requirements
- effective_date: When policy starts/ends

**Policy Example:**

```
Policy: "Total Knee Replacement (Orthopedics)"
Covered if patient has:
  ✓ Diagnosis: Primary osteoarthritis, severe
  ✓ X-ray or MRI confirmation of severe OA
  ✓ Failed conservative therapy (12+ weeks: PT, NSAIDs, injections)
  ✓ Patient age 55+
  
NOT covered if:
  ✗ Only mild OA symptoms
  ✗ No imaging evidence
  ✗ <12 weeks of therapy attempted
```

**Why this matters:** These are HARD REQUIREMENTS. If patient doesn't meet them, request is automatically DENIED. No exceptions.

**Real-world challenge:** Different insurers have different requirements for the same procedure. Same patient might be approved by one insurer, denied by another.

---

### ICD-10 Dataset (105 rows)

**What:** Standardized medical diagnosis codes used worldwide

**About ICD-10:**

- International Classification of Diseases, 10th revision
- Every diagnosis has a 5-7 character code
- Insurance companies require these codes to process claims
- Same diagnosis can have multiple codes based on specificity

**Contains:**

- icd10_code: The actual code (e.g., M17.11, E10.9)
- diagnosis: Plain English description
- specialty: Which medical field (Orthopedics, Cardiology, etc.)
- body_region: What part of body (knee, heart, brain)
- rare_disease_flag: If True, this diagnosis requires special handling
- confidence_tier: How certain we can match it from doctor's note

**ICD Code Breakdown (M17.11):**

```
M    = Musculoskeletal disease
17   = Osteoarthritis
.11  = Primary OA of right knee
```

**Examples:**

- M17.11: Primary osteoarthritis right knee
- E10.9: Type 1 diabetes
- I21.01: ST-elevation myocardial infarction (heart attack)

**Why this matters:**

- Insurers ONLY understand codes, not doctor's words
- "Knee arthritis" could be 5 different codes depending on severity
- Wrong code = wrong decision
- Rare diseases flagged for manual review (not auto-approved)

**Real-world challenge:** Doctor writes "bad knee" but could mean M17.11 (OA) or M19.91 (unspecified joint disorder). Pipeline must pick the right one.

---

### Form Templates Dataset (61 rows)

**What:** Blank forms that each insurance company requires filled out

**Contains:**

- template_id: Unique form identifier
- insurer_name: Which company (United Healthcare, Cigna, Aetna, etc.)
- specialty: What type of request (Orthopedics, Cardiology, etc.)
- section: Form section (Patient Info, Clinical History, Diagnosis, Procedures)
- field: Individual field name (patient_name, diagnosis, requested_procedure)
- required: Boolean - is this field mandatory to fill?
- field_type: Data type (text, number, date, dropdown)

**Form Example:**

```
Form: UnitedHealthcare Total Knee Replacement

Section 1 - PATIENT INFORMATION
  [REQUIRED] Patient ID: _________________
  [REQUIRED] Policy Number: _______________
  [REQUIRED] Date of Birth: _______________
  [OPTIONAL] Alternate Phone: _____________

Section 2 - CLINICAL HISTORY
  [REQUIRED] Diagnosis: ___________________
  [REQUIRED] ICD-10 Code: _________________
  [REQUIRED] Duration of Symptoms: ________
  [REQUIRED] Failed Treatments: ___________
  [REQUIRED] Imaging Results: _____________

Section 3 - REQUESTED PROCEDURE
  [REQUIRED] Procedure Name: ______________
  [REQUIRED] Reason for Procedure: ________
  [OPTIONAL] Alternative Procedures Considered: ____
```

**Why this matters:** Each insurer has different forms. Same information, different fields. Pipeline must map data to correct fields.

**Real-world challenge:** Insurer A requires fields that Insurer B doesn't care about. Pipeline must handle 61 different form variations.

---

### Edge Cases Dataset (44 rows)

**What:** Deliberately tricky test cases designed to catch pipeline errors

**Contains:**

- edge_case_id: Test case identifier
- trap: What the test case is checking (e.g., "Missing ICD code")
- specialty: Medical field
- expected_agent_behavior: What should happen (e.g., "Reject and escalate to human")
- severity: How bad if pipeline fails (critical/high/medium/low)

**Real Edge Cases (Examples):**

**Case 1: Fraud Detection**

```
Input: Patient age 25 requesting hip replacement (normal age 65+)
Trap: Age doesn't match typical diagnosis
Expected: Flag for review, don't auto-approve
Severity: CRITICAL
```

**Case 2: Conflicting Information**

```
Input: "Patient has severe osteoarthritis requiring surgery" 
       BUT only 1 week of physical therapy tried
Trap: Policy requires 12 weeks therapy, patient has only 1
Expected: DENIED (missing required criteria)
Severity: CRITICAL
```

**Case 3: Missing Critical Data**

```
Input: Doctor note mentions knee pain but NO imaging (X-ray/MRI)
Trap: Policy REQUIRES imaging confirmation
Expected: PENDING_REVIEW (missing required evidence)
Severity: CRITICAL
```

**Case 4: Rare Disease**

```
Input: Patient diagnosis = Ehlers-Danlos Syndrome (rare genetic disorder)
Trap: Rare disease flag = TRUE in ICD database
Expected: PENDING_REVIEW (manual expert review needed, not auto-approved)
Severity: HIGH
```

**Case 5: Policy Not Applicable**

```
Input: Patient has Aetna insurance but requesting procedure not in Aetna policy
Trap: Procedure not covered by patient's actual insurance
Expected: DENIED (policy mismatch)
Severity: CRITICAL
```

**Case 6: Ambiguous Diagnosis**

```
Input: Doctor writes "possible arthritis" or "suspected osteoarthritis"
Trap: Hedge language ("possible", "suspected") indicates uncertainty
Expected: Lower confidence score, escalate if too uncertain
Severity: MEDIUM
```

**Why edge cases matter:** These are attack points. If pipeline fails on any edge case, insurance gets sued. Edge cases test pipeline safety gates.

---

## 2. PHI MASKING LAYER (Privacy Protection)

### What it does

Removes ALL patient personal information before ANY AI processing happens. This is the FIRST step - happens before anything else touches the data.

**Removes these identifiers:**

- Names (patient, family members, doctors)
- Social Security Number (SSN)
- Phone numbers
- Email addresses
- Date of birth
- Medical Record Number (MRN)
- Street addresses
- Insurance member ID

**Replaces with:** Generic placeholders like [PATIENT_NAME], [SSN], [PHONE], etc.

### Why this matters

**Legal:** HIPAA (Health Insurance Portability and Accountability Act) requires healthcare data protection. Violating this = fines + lawsuits.

**Privacy:** Patients don't want their personal data exposed to AI models.

**Security:** If AI model data is ever leaked, hackers can't identify real people.

**Real example of PHI breach:**

- Company trains AI on real patient names and SSNs
- AI model gets leaked online
- Hackers match names + SSNs to public databases
- Identity theft happens
- Company pays $50 million in fines

### How it works

**Technology:** Regex (Regular Expression) pattern matching - simple text replacement, NO AI needed

**Order matters:** Some patterns mask BEFORE others to avoid conflicts:

1. First: Mask email addresses (email contains @ symbol)
2. Second: Mask phone numbers (phone has specific digits)
3. Third: Mask dates of birth (date patterns)
4. Last: Mask names (most complex pattern)

**Why order matters:**

```
Example: "john.smith@email.com is DOB 1960-05-15"

If we mask dates FIRST:
"john.smith@email.com is DOB [DOB]"

If we mask email SECOND:
"[EMAIL] is DOB [DOB]"

If we mask names LAST:
"[EMAIL] is DOB [DOB]"
✓ Correct - both masked

But if we did it wrong order, we might mask part of email as a date.
```

### Example (Real Patient Data)

**BEFORE masking (raw doctor note):**

```
Patient: John Smith
DOB: 1960-05-15
SSN: 123-45-6789
Phone: (555) 123-4567
Address: 123 Oak Street, Denver CO 80202
MRN: 987654

Patient called in with severe knee pain starting 3 months ago. 
Patient's wife (Mary Smith) worried about surgery. Discussed with 
Dr. Johnson (720-555-8901). X-ray ordered. Will follow up at 
jane@myemail.com.
```

**AFTER masking (what AI sees):**

```
Patient: [PATIENT_NAME]
DOB: [DOB]
SSN: [SSN]
Phone: [PHONE]
Address: [ADDRESS]
MRN: [MRN]

Patient called in with severe knee pain starting 3 months ago. 
Patient's wife ([FAMILY_NAME]) worried about surgery. Discussed with 
Dr. [DOCTOR_NAME] ([PHONE]). X-ray ordered. Will follow up at 
[EMAIL].
```

**What the AI sees:** No real identifiers, just medical facts. Can't identify real person even if model leaks.

### Output

Returns a "PHI Mask Result" object with:

- `masked_text`: The safe version to send to AI models
- `masked_fields`: List of what was masked (for audit logging)

### Audit Trail

Every masked field is logged:

```
{
  "masked_fields": [
    {"type": "PATIENT_NAME", "original": "John Smith"},
    {"type": "SSN", "original": "123-45-6789"},
    {"type": "DOB", "original": "1960-05-15"},
    {"type": "PHONE", "original": "(555) 123-4567"}
  ],
  "timestamp": "2024-01-15T10:30:00Z"
}
```

This audit trail proves we protected privacy if there's ever a legal question.

---

## 3. EXTRACTOR AGENT - Detailed

### What it does

Reads the messy doctor note (after PHI masking) and converts it into structured, organized medical data that insurance systems understand.

**This is CRITICAL because:**

- Insurance systems can't process free-form text
- Different doctors write differently
- Need consistent data format across all cases

### Input

Two pieces of information:

1. **Masked doctor note:** The raw medical text (with personal info removed)
2. **Medical specialty:** Type of medicine (Orthopedics, Cardiology, Neurology, etc.)

### Output

Structured JSON object with these fields:

```json
{
  "diagnosis": ["Primary osteoarthritis right knee"],
  "clinical_modifiers": ["severe", "chronic"],
  "symptoms": ["knee pain", "swelling", "limited range of motion"],
  "duration": "3 months",
  "failed_treatments": [
    "physical therapy 12 weeks",
    "NSAIDs (ibuprofen, naproxen)",
    "steroid injection",
    "weight loss management"
  ],
  "imaging": "X-ray: primary osteoarthritis right knee, moderate severity",
  "requested_procedure": ["total knee replacement"]
}
```

### How it works

**Step 1: Read and understand**

- Takes masked doctor note
- AI (Claude) reads and understands medical language
- Identifies key medical concepts

**Step 2: Extract medical facts**

- **Diagnosis:** What disease/condition does patient have? (Must be EXPLICIT, not inferred)
- **Clinical modifiers:** Severity descriptors (mild, moderate, severe, chronic, acute)
- **Symptoms:** What does patient complain about? (pain, swelling, fever, etc.)
- **Duration:** How long has patient had this? (3 weeks, 6 months, 2 years)
- **Failed treatments:** What already tried that didn't work? (medication, therapy, injections)
- **Imaging:** Any X-rays, MRIs, CT scans mentioned? What do they show?
- **Requested procedure:** What treatment is doctor asking for?

**Step 3: Critical rule - ONLY extract explicit facts**

- **EXTRACT:** "Patient has severe knee arthritis"
- **DON'T EXTRACT:** "Patient probably has arthritis" (not certain)
- **DON'T INVENT:** Doctor didn't mention imaging? Don't guess there's an X-ray
- **DON'T INFER:** Doctor didn't say "severe" explicitly? Don't add it

### Real-world examples

#### Example 1: Orthopedics (Knee Surgery)

**Raw doctor note:**

```
65-year-old with chronic severe knee pain x 6 months. Initially treated with 
physical therapy (12 weeks), NSAIDs (ibuprofen 400mg daily), and steroid injection 
2 months ago. Patient reports minimal improvement despite compliance. X-ray confirms 
advanced primary OA of right knee. MRI shows cartilage loss and meniscal tear. 
Recommending right total knee replacement.
```

**Extracted (what goes to next agents):**

```json
{
  "diagnosis": ["Primary osteoarthritis right knee", "Meniscal tear right knee"],
  "clinical_modifiers": ["chronic", "severe", "advanced"],
  "symptoms": ["knee pain", "limited mobility"],
  "duration": "6 months",
  "failed_treatments": [
    "physical therapy 12 weeks",
    "NSAIDs (ibuprofen 400mg daily)",
    "steroid injection"
  ],
  "imaging": "X-ray: advanced primary OA right knee. MRI: cartilage loss, meniscal tear",
  "requested_procedure": ["total knee replacement right knee"]
}
```

#### Example 2: Cardiology (Heart Surgery)

**Raw doctor note:**

```
55-year-old male with chest pain. Multiple cardiac catheterizations show severe 
left main coronary artery disease (90% stenosis), RCA 75% blockage, LAD 85% blockage. 
Trialed on maximum medical therapy: aspirin, atorvastatin, lisinopril, metoprolol. 
Patient remains symptomatic with angina episodes 2-3x weekly despite medications. 
EF 35%. Recommending coronary artery bypass graft (CABG).
```

**Extracted:**

```json
{
  "diagnosis": [
    "Coronary artery disease left main severe",
    "Right coronary artery disease",
    "Left anterior descending disease",
    "Systolic heart failure (EF 35%)"
  ],
  "clinical_modifiers": ["severe", "symptomatic"],
  "symptoms": ["chest pain", "angina"],
  "duration": "ongoing",
  "failed_treatments": [
    "aspirin",
    "atorvastatin",
    "lisinopril",
    "metoprolol",
    "cardiac catheterization"
  ],
  "imaging": "Cardiac catheterization: left main 90% stenosis, RCA 75%, LAD 85%. EF 35%",
  "requested_procedure": ["coronary artery bypass graft (CABG)"]
}
```

### Technology

**Uses:** Claude AI (large language model)

- Understands medical language and abbreviations
- Extracts concepts accurately
- Knows what's medical jargon vs casual language

**NOT using:** Database lookup or rule-based system - AI needed because doctor notes are too varied

### Critical rules

✅ **Only extract EXPLICIT facts** - If doctor said it, extract it
✅ **Normalize language** - "knee arthritis" = "osteoarthritis knee"
✅ **Separate severity from diagnosis** - "severe arthritis" → diagnosis: "arthritis", modifier: "severe"
✅ **List format matters** - diagnosis[], symptoms[], failed_treatments[] must be JSON arrays
✅ **Never include masked PHI** - Output should be completely safe, no personal data

### Why this matters for pipeline

- **Next step (ICD Coder)** receives clean, structured diagnosis list to code
- **Next step (Policy RAG)** receives clear symptoms and failed treatments to match against policy requirements
- **Insurance companies** need standard formats, not free-form text

---

## 4. ICD CODING AGENT - Detailed

### What it does

Converts doctor's diagnosis words into standardized medical diagnosis codes. This is MANDATORY for insurance systems - they only understand codes, not English.

**Why this matters:**

- Insurance databases run on codes, not words
- Different doctors use different words for same disease
- ICD codes ensure consistency worldwide
- Wrong code = wrong insurance decision

### Input

List of diagnoses from Extractor agent:

```
["Primary osteoarthritis right knee", "Meniscal tear right knee", "Knee swelling"]
```

### Output

Structured object with ICD mappings:

```json
{
  "mappings": [
    {
      "diagnosis": "Primary osteoarthritis right knee",
      "icd10_code": "M17.11",
      "confidence": 0.95,
      "confidence_level": "HIGH",
      "rare_disease": false,
      "status": "mapped"
    },
    {
      "diagnosis": "Meniscal tear right knee",
      "icd10_code": "M23.201",
      "confidence": 0.88,
      "confidence_level": "HIGH",
      "rare_disease": false,
      "status": "mapped"
    },
    {
      "diagnosis": "Knee swelling",
      "icd10_code": "M25.461",
      "confidence": 0.72,
      "confidence_level": "MEDIUM",
      "rare_disease": false,
      "status": "mapped"
    }
  ]
}
```

### How it works - Three Matching Strategies

**Strategy 1: Exact/Near-Exact Match**

- Looks for exact word match or very close
- Example: "Osteoarthritis right knee" → M17.11 (95% match)
- Fastest, most confident

**Strategy 2: Fuzzy Token Matching**

- Breaks diagnosis into words and matches words
- Example: "OA of the knee joint" → matches "osteoarthritis" + "knee" → M17.11
- Handles doctor abbreviations and variations
- Slower but catches variations

**Strategy 3: Semantic Fallback**

- Uses AI embeddings to find conceptually similar diagnoses
- Example: "Knee joint degeneration" → semantically similar to "osteoarthritis" → M17.11
- Last resort when exact/fuzzy doesn't work
- Handles completely different wording

### Technology Stack

**PubMedBERT:** Medical-specific AI embedding model

- Trained on millions of medical papers
- Understands medical concepts better than general AI
- Creates numerical "embeddings" (vectors) for each diagnosis
- Embeddings capture medical meaning

**FAISS:** Vector search library

- Fast similarity search in embeddings
- Compares new diagnosis against 105 known ICD codes
- Returns top matches with similarity scores
- What you'd use if searching Google for similar images

**How similarity works:**

```
Diagnosis: "Knee arthritis" → embedding vector
ICD M17.11: "Primary osteoarthritis right knee" → embedding vector

Compare vectors → similarity score 0.95
(on scale 0.0 to 1.0, where 1.0 = identical meaning)
```

### Confidence Scoring

**Confidence formula:** How certain are we this is the right code?

```
Similarity Score      Confidence Level    Meaning
─────────────────────────────────────────────────────────────
≥ 0.82               HIGH                Very confident, auto-approved
0.65 - 0.81          MEDIUM              Reasonably confident, may need review
< 0.65               LOW                 Uncertain, send to human reviewer
```

### Safety Gates (When to escalate)

**Gate 1: Rare Disease Flag**

- If diagnosis marked as rare in ICD dataset → Always escalate to human
- Example: "Ehlers-Danlos Syndrome" (genetic connective tissue disorder)
- Why? Rare diseases need medical expert judgment, not automation

**Gate 2: Low Confidence**

- If confidence < 0.70 → Send for human review
- Example: "Possible arthritis" (hedge language) → confidence drops 15%
- Why? Don't want wrong code affecting insurance decision

**Gate 3: Hedge Language Detection**

- Phrases like "suspected", "possible", "likely", "rule out" → lower confidence by 15%
- Example: "Suspected osteoarthritis" → confidence 0.95 × 0.85 = 0.81 (still HIGH)
- Example: "Possible Lyme disease" → confidence 0.70 × 0.85 = 0.60 (now LOW, escalated!)
- Why? Doctor's uncertainty should transfer to ICD confidence

### Real examples

#### Example 1: Perfect Match (HIGH confidence)

**Input diagnosis:** "Primary osteoarthritis right knee"

```
Similarity match against M17.11: 0.97
Confidence: HIGH
Rare disease: NO
Hedge language: NO
Final confidence: 0.97 → AUTO-APPROVED
```

**Output:**

```json
{
  "icd10_code": "M17.11",
  "confidence": 0.97,
  "confidence_level": "HIGH",
  "status": "mapped"
}
```

#### Example 2: Fuzzy Match (MEDIUM confidence)

**Input diagnosis:** "OA of the knee, right side"

```
Matches on: "OA" (osteoarthritis), "knee", "right"
Similarity against M17.11: 0.74
Confidence: MEDIUM
Rare disease: NO
Hedge language: NO
Final confidence: 0.74 → Manual review optional but allowed
```

**Output:**

```json
{
  "icd10_code": "M17.11",
  "confidence": 0.74,
  "confidence_level": "MEDIUM",
  "status": "mapped"
}
```

#### Example 3: Hedge Language (confidence drops)

**Input diagnosis:** "Suspected osteoarthritis right knee"

```
Base similarity against M17.11: 0.95
Hedge language detected: "suspected" → multiply by 0.85
Final confidence: 0.95 × 0.85 = 0.81 → HIGH (still above 0.82 threshold)
```

**Output:**

```json
{
  "icd10_code": "M17.11",
  "confidence": 0.81,
  "confidence_level": "HIGH",
  "status": "mapped"
}
```

#### Example 4: Too Uncertain (LOW confidence, escalated)

**Input diagnosis:** "Possible connective tissue disorder"

```
Connective tissue disorders have multiple possible codes
Similarity is unclear which type: 0.58
Confidence: LOW
Hedge language: "possible" → multiply by 0.85
Final confidence: 0.58 × 0.85 = 0.49 → VERY LOW
Rare disease: YES (connective tissue disorders are rare)
Status: review_required
```

**Output:**

```json
{
  "icd10_code": null,
  "confidence": 0.49,
  "confidence_level": "LOW",
  "rare_disease": true,
  "status": "review_required"  ← Escalated to human
}
```

### Status values

- **"mapped"**: Successfully coded, ready to use
- **"unmapped"**: Could not find any matching code
- **"review_required"**: Found code but confidence too low or rare disease flag set

### Deduplication

If pipeline finds same diagnosis twice:

```
Input diagnoses: 
  ["Osteoarthritis right knee", "OA right knee"]

Output (deduplicated):
  [{"diagnosis": "Osteoarthritis right knee", "icd10_code": "M17.11", ...}]
  
Keeps only one, discards duplicate
```

Why? Insurance only pays once per diagnosis, so don't code same thing twice.

---

## 5. POLICY RAG AGENT - Very Important (Your Focus Area)

### What RAG means

**RAG = Retrieval-Augmented Generation**

Breaking it down:

- **Retrieval:** Find relevant policy sections related to patient's request
- **Augmentation:** Give those sections to AI model as context
- **Generation:** AI uses those specific sections to make decision (not making things up)

### What it does

Reads insurance policy document and checks if patient meets coverage requirements.

**Critical rule:** This is where DENIALS happen. If policy requires something and patient doesn't have it → DENIED (no exceptions, no appeals).

### Input

Three pieces of information:

1. **Patient clinical facts** (from Extractor + ICD Coder)
2. **Insurance policy document** (text from Policies dataset)
3. **Policy number** (which insurance plan applies)

### Output

Structured analysis with:

```json
{
  "policy_summary": "Total Knee Replacement covered if: 1) X-ray confirms severe OA, 
                     2) Failed 12+ weeks conservative therapy, 3) Age 55+",
  
  "met_criteria": [
    "Radiographic confirmation: X-ray shows primary OA",
    "Diagnosis matches covered condition: M17.11",
    "Conservative therapy: 14 weeks documented (PT, NSAIDs, injection)"
  ],
  
  "missing_criteria": [
    "Patient age 62, policy requires 55+ ✓ Requirement MET"
  ],
  
  "supporting_policy_sections": [
    "Section 3.2.1: 'TKR approved for primary OA with radiographic confirmation'",
    "Section 3.2.3: 'Minimum 12 weeks conservative management required'"
  ],
  
  "retrieval_confidence": "HIGH"
}
```

### How it works - Two Phase Process

#### PHASE 1: Policy Retrieval (Finding Relevant Sections)

**Step 1: Exact Policy Lookup**

- Takes patient's policy_number
- Looks in database: `policies_df[policies_df["policy_number"] == policy_number]`
- Retrieves full policy document (e.g., "Cigna Total Knee Replacement Policy v2024.01")

**Step 2: Chunk the Policy Document**

- Policy documents are LONG (could be 50+ pages)
- AI can't read it all at once
- Split into chunks: max 500 characters per chunk
- Example: Each chunk = 1 paragraph or section

**Step 3: Semantic Search**

- Create a question: "Does patient meet requirements for total knee replacement?"
- Use AI embeddings (SentenceTransformers model: pritamdeka/S-PubMedBert-MS-MARCO)
- Compare question against all policy chunks
- Find top-5 most relevant chunks

**How semantic search works:**

```
Question: "What are requirements for TKR approval?"
    ↓
Convert to embedding (numerical vector that captures meaning)
    ↓
Compare against every policy chunk embedding
    ↓
Return chunks most similar to question

Example:
Policy Chunk 1: "Patient must have failed conservative therapy" → similarity 0.89 ✓ RELEVANT
Policy Chunk 2: "Insurance does not cover cosmetic procedures" → similarity 0.12 ✗ NOT RELEVANT
Policy Chunk 3: "Radiographic confirmation required for OA cases" → similarity 0.91 ✓ RELEVANT
```

**Step 4: Confidence Scoring**

- Each retrieved chunk gets a confidence score (similarity)
- Scale: 0.0 to 1.0 (1.0 = identical meaning)

```
Similarity Score      Retrieval Confidence
──────────────────────────────────────────
≥ 0.82               HIGH - Trust this section
0.65 - 0.81          MEDIUM - This section might be relevant
< 0.65               LOW - Probably not relevant, might be noise
```

**Step 5: Safety Gate**

- If ALL retrieved chunks are "LOW" confidence:
  - Raise error: "Policy guidance unclear"
  - Escalate to human reviewer
  - Don't auto-decide on ambiguous policy interpretation

#### PHASE 2: Policy Analysis (Checking Requirements)

**What LLM does:**

- Reads top-5 retrieved policy sections
- Reads patient's extracted clinical facts
- Compares patient facts against policy requirements
- Lists what's MET and what's MISSING

**System prompt tells LLM:**

```
"You are an insurance policy analyst. Your job:
1. Read the patient's clinical facts
2. Read the relevant policy sections provided (these are EXCERPTS, not full policy)
3. Compare facts against requirements
4. Output ONLY what's in provided policy sections (no guessing, no hallucinations)
5. List clearly: what requirements are met, what are missing
6. Cite direct quotes from policy sections as evidence
7. Never make final approval decision - just analyze"
```

**Why AI needed here:**

- Policy language is complex ("Failed conservative therapy" could mean different things)
- Medical facts are complex (patient has clinical modifiers, failed treatments list)
- Need human-like judgment to match policy language to patient facts

### Real example - Detailed walkthrough

#### Scenario: 62-year-old requesting total knee replacement

**Patient facts (from Extractor):**

```
Diagnosis: Primary osteoarthritis right knee
Age: 62
Failed treatments: PT (14 weeks), NSAIDs, steroid injection
Imaging: X-ray shows moderate-to-severe OA
Requested procedure: Total knee replacement (TKR)
```

**Policy document (Cigna TKR Policy):**

```
SECTION 1: COVERAGE CRITERIA
Cigna covers total knee replacement if ALL of the following are met:

1.1 Diagnosis Requirement:
  - Patient must have primary osteoarthritis (M17.xx codes)
  - Diagnosis must be confirmed by imaging (X-ray or MRI)
  
1.2 Conservative Therapy Requirement:
  - Patient must have failed minimum 12 weeks of conservative management
  - Conservative management includes: physical therapy, NSAIDs, steroid injections
  - Documentation of patient compliance required
  
1.3 Age Requirement:
  - Patient must be age 55 or older
  - Exceptions: Age 50-54 if radiographic evidence of severe OA (Kellgren-Lawrence 4)
  
1.4 Exclusions:
  - Patients with active infection
  - Patients with uncontrolled diabetes
  - Patients with BMI > 40 without weight loss plan

SECTION 2: REQUIRED DOCUMENTATION
  - X-ray or MRI imaging
  - Medical notes documenting conservative therapy
  - Prescriptions for NSAIDs and/or injections
```

**Step 1: Policy Lookup**

- Policy number: P-001 (Cigna)
- Retrieve: "Cigna_TKR_Policy_2024.01.pdf"

**Step 2: Chunk Policy**

```
Chunk 1 (0-500 chars): "COVERAGE CRITERIA... Primary osteoarthritis..."
Chunk 2 (500-1000): "...12 weeks conservative management..."
Chunk 3 (1000-1500): "...Age requirement 55 or older..."
Chunk 4 (1500-2000): "...Exclusions: active infection..."
Chunk 5 (2000-2500): "...REQUIRED DOCUMENTATION..."
... (more chunks)
```

**Step 3: Semantic Search**

- Question: "Does patient meet requirements for TKR?"

```
Chunk 1: similarity 0.94 ✓ HIGH (diagnosis requirement)
Chunk 2: similarity 0.92 ✓ HIGH (conservative therapy)
Chunk 3: similarity 0.87 ✓ HIGH (age requirement)
Chunk 4: similarity 0.63 ✗ MEDIUM (exclusions, probably not relevant)
Chunk 5: similarity 0.79 ✓ HIGH (documentation)

Retrieve top-5: Chunks 1, 2, 3, 5, and chunk 4 as backup
```

**Step 4: LLM Comparison**

```
LLM reads:
- Patient facts: 62 years old, OA confirmed on X-ray, 14 weeks PT/NSAIDs/injection
- Retrieved policy sections (Chunks 1, 2, 3, 5)

LLM analyzes:
1. Diagnosis match? 
   Patient: M17.11 (primary OA)
   Policy: Requires M17.xx
   Result: ✓ MET

2. Imaging confirmation?
   Patient: X-ray shows OA
   Policy: Requires X-ray or MRI
   Result: ✓ MET

3. Conservative therapy?
   Patient: 14 weeks (PT 12 wks + NSAIDs + injection)
   Policy: Requires minimum 12 weeks
   Result: ✓ MET

4. Age?
   Patient: 62 years old
   Policy: Requires 55+
   Result: ✓ MET

5. Exclusions?
   Patient: No active infection, controlled health, BMI 28
   Policy: No active infections, controlled diabetes, BMI ≤ 40
   Result: ✓ No exclusions apply
```

**LLM Output:**

```json
{
  "policy_summary": "Cigna TKR policy requires: (1) Primary OA diagnosis confirmed by imaging, 
                     (2) 12+ weeks failed conservative therapy, (3) Age 55+",
  
  "met_criteria": [
    "Diagnosis matches covered condition: M17.11 (primary OA) per Section 1.1",
    "Radiographic confirmation present: X-ray confirms OA severity per Section 1.1",
    "Conservative therapy documented: 14 weeks (PT, NSAIDs, steroid injection) 
     exceeds 12-week minimum per Section 1.2",
    "Age requirement satisfied: 62 years old exceeds 55-year minimum per Section 1.3",
    "No exclusion criteria apply per Section 1.4"
  ],
  
  "missing_criteria": [],  ← NONE! All requirements met
  
  "supporting_policy_sections": [
    "Section 1.1: 'Primary osteoarthritis (M17.xx codes) with imaging confirmation'",
    "Section 1.2: 'Minimum 12 weeks conservative management... physical therapy, NSAIDs, 
                   steroid injections'",
    "Section 1.3: 'Patient must be age 55 or older'"
  ],
  
  "retrieval_confidence": "HIGH"
}
```

### What happens next

**If missing_criteria is EMPTY:**

- Move to next agent (Form Filler)
- Later, Reviewer can APPROVE
- No automatic denial

**If missing_criteria has items:**

- Example: "Policy requires 12 weeks therapy, patient only has 6 weeks"
- This triggers automatic DENIAL in Reviewer agent
- No exceptions, no appeals

### Example 2: DENIAL scenario

**Patient facts:**

```
Diagnosis: Primary OA right knee
Age: 52 (below 55 requirement!)
Failed treatments: PT (6 weeks) ← Below 12-week requirement!
Imaging: X-ray shows moderate OA
```

**LLM analysis:**

```json
{
  "met_criteria": [
    "Diagnosis matches: M17.11 ✓",
    "Imaging present: X-ray ✓"
  ],
  
  "missing_criteria": [
    "Age requirement: Patient is 52, policy requires 55+ (unless severe OA evidence)",
    "Conservative therapy duration: Patient has 6 weeks, policy requires minimum 12 weeks"
  ],
  
  "supporting_policy_sections": [
    "Section 1.2: 'minimum 12 weeks of conservative management'",
    "Section 1.3: 'Patient must be age 55 or older'"
  ]
}
```

**Result:** missing_criteria has 2 items → Later, Reviewer sees this → Automatic DENIED

### Technology stack

**SentenceTransformers (PubMedBERT):**

- Medical-specific embedding model
- Converts text to numerical vectors
- Understands medical language

**FAISS (Facebook AI Similarity Search):**

- Fast vector similarity search
- Finds most relevant policy chunks instantly
- Even works with thousands of chunks

**Claude (LLM):**

- Reads policy chunks + patient facts
- Performs logical comparison
- Explains reasoning in plain English
- Only uses provided policy sections (no hallucination)

---

## 6. FORM FILLER AGENT

### What it does

Takes all outputs from previous agents (extracted facts, ICD codes, policy analysis) and assembles them into a complete prior authorization form that insurance companies understand.

**This is the assembly step:** Organizing all the work from previous agents into one standardized document.

### Input

Five pieces of information combined:

1. **Patient extracted data** (from Extractor Agent)
2. **ICD coding output** (from ICD Coder Agent)
3. **Policy analysis** (from Policy RAG Agent)
4. **Form template** (from Forms dataset)
5. **Patient identifiers** (policy number, specialty)

### Output

Complete Prior Authorization Form object:

```json
{
  "patient_id": "P-001",
  "policy_number": "P-001",
  "contact_information": {
    "phone": "[PHONE]",
    "email": "[EMAIL]",
    "address": "[ADDRESS]"
  },
  
  "specialty": "Orthopedics",
  "insurer_name": "Cigna",
  "form_template_id": "cigna_tkr_v2024",
  
  "clinical_data": {
    "diagnosis": ["Primary osteoarthritis right knee"],
    "clinical_modifiers": ["severe", "chronic"],
    "symptoms": ["knee pain", "swelling"],
    "duration": "6 months",
    "failed_treatments": [
      "physical therapy 12 weeks",
      "NSAIDs",
      "steroid injection"
    ],
    "imaging": "X-ray: primary OA right knee",
    "requested_procedure": ["total knee replacement"]
  },
  
  "icd_coding_output": {
    "mappings": [
      {
        "diagnosis": "Primary osteoarthritis right knee",
        "icd10_code": "M17.11",
        "confidence": 0.95,
        "status": "mapped"
      }
    ]
  },
  
  "policy_analysis": {
    "policy_summary": "TKR approved if: X-ray confirms, 12 weeks therapy, age 55+",
    "met_criteria": [
      "Radiographic confirmation present",
      "Conservative therapy: 12 weeks",
      "Age requirement met"
    ],
    "missing_criteria": []
  }
}
```

### How it works

**Step 1: Lookup form template**

- Takes: patient specialty (e.g., "Orthopedics") + insurer name (e.g., "Cigna")
- Looks in forms dataset: `forms_df[(forms_df["specialty"]=="Orthopedics") & (forms_df["insurer_name"]=="Cigna")]`
- Gets template_id (e.g., "cigna_tkr_v2024")

**Step 2: Map data to form fields**

- Form template specifies required fields and field types
- Maps extracted data to matching form fields
- Example mapping:
  ```
  Template field: "patient_id" → Data: "P-001"
  Template field: "diagnosis" → Data: ["Primary osteoarthritis right knee"]
  Template field: "icd_code" → Data: "M17.11"
  Template field: "failed_treatments" → Data: [PT, NSAIDs, injection]
  ```

**Step 3: Embed policy analysis**

- Includes full policy_analysis from Policy Agent
- Insurance reviewers will read this to understand why patient meets/doesn't meet criteria
- Provides transparency

**Step 4: Embed ICD output**

- Includes confidence scores and status for each diagnosis
- Insurance reviewers will see if codes were high/medium/low confidence
- If code is low confidence or flagged for review, reviewer will notice

### Why this agent is deterministic (no AI)

This agent doesn't need AI because:

- No complex decision-making, just data assembly
- No natural language processing, just mapping
- Template already defined, just fill in the blanks
- Like filling out a form on a website

### Output ready for next stage

By the time Form Filler is done:

- ✓ All required fields populated
- ✓ Clinical facts structured
- ✓ ICD codes included
- ✓ Policy analysis embedded
- ✓ Ready for quality check (Critique Agent)
- ✓ Ready for final review (Reviewer Agent)

---

## 7. CRITIQUE AGENT - Quality Assurance

### What it does

Quality control check on the completed form. Makes sure form is complete, consistent, and doesn't have data contradictions.

**Key principle:** This agent is the QA gate. It doesn't approve/deny decisions - it verifies the form can be safely reviewed.

### What it DOES check

✅ **Mandatory fields present?**

- patient_id (must exist)
- policy_number (must exist)
- specialty (must exist)
- diagnosis[] (must have at least one)
- icd_coding_output.mappings[] (must have at least one successful ICD code)

✅ **Internal consistency:**

- Do all diagnoses have matching ICD codes?
- Are modifiers consistent with diagnosis? (e.g., "severe arthritis" but ICD code for "mild"?)
- Do symptoms match diagnosis? (e.g., "chest pain" with diagnosis "knee arthritis"?)
- Are procedure requests consistent with diagnosis? (e.g., requesting knee surgery for heart condition?)

✅ **No data contradictions:**

- "Failed 14 weeks of therapy" but duration says "1 week"?
- "No imaging" but policy requires imaging?
- Patient age 25 but diagnosis typically age 65+?

### What it DOES NOT check

❌ **Medical necessity:** "Is this procedure actually needed?" - That's Policy Agent's job
❌ **Policy compliance:** "Does patient meet insurance criteria?" - That's Policy Agent and Reviewer's job
❌ **Final authorization:** "Should this be approved?" - That's Reviewer Agent's job

Critique ONLY validates form integrity, not medical/policy decisions.

### Input

Complete Prior Authorization Form from Form Filler Agent

### Output

Critique Report:

```json
{
  "result": "PASS" | "FAIL",
  "severity": "non-critical" | "critical",
  "issues": [
    "Issue 1: Explain what's wrong",
    "Issue 2: Explain what's wrong"
  ],
  "recommendations": [
    "Fix recommendation 1",
    "Fix recommendation 2"
  ]
}
```

### Three output scenarios

#### Scenario 1: PASS (Form is good)

```json
{
  "result": "PASS",
  "severity": "non-critical",
  "issues": [],
  "recommendations": ["Form is complete and consistent. Ready for reviewer."]
}
```

**What happens next:** Form goes to Reviewer Agent for final decision

---

#### Scenario 2: FAIL (non-critical - fixable)

```json
{
  "result": "FAIL",
  "severity": "non-critical",
  "issues": [
    "ICD code confidence is MEDIUM (0.71) - should verify code accuracy",
    "Duration says '6 months' but failed treatment lists '12 weeks' - clarify total duration"
  ],
  "recommendations": [
    "Recommend human review of medium-confidence ICD code before proceeding",
    "Suggest asking doctor to clarify exact duration of symptoms"
  ]
}
```

**What happens next:** Form still goes to Reviewer, but reviewer sees the warnings

---

#### Scenario 3: FAIL (critical - structural problem)

```json
{
  "result": "FAIL",
  "severity": "critical",
  "issues": [
    "CRITICAL: No ICD code assigned despite diagnosis present",
    "CRITICAL: Missing patient_id field - cannot identify patient",
    "CRITICAL: Diagnosis 'knee arthritis' but policy analysis shows missing criteria"
  ],
  "recommendations": [
    "CRITICAL: Cannot proceed - ICD code required",
    "CRITICAL: Patient identification required before processing"
  ]
}
```

**What happens next:** Form BLOCKED. Goes to human for manual investigation.

### Technology

**Uses:** Claude AI (LLM) - understands medical concepts and can detect logical contradictions

---

## 8. REVIEWER AGENT (Final Decision) - Detailed

### What it does

Makes the FINAL authorization decision: **APPROVED ✅** | **DENIED ❌** | **PENDING_REVIEW ⚠️**

This is the last automated step before escalation to human review. Critical principle: **Deterministic hard rules fire first.** AI judgment only for borderline cases.

### Decision Process (Two Phases)

#### PHASE 1: Three Deterministic Hard Rules

These are automatic gates with NO EXCEPTIONS.

##### Rule 1: Critique Critical Failure

```
IF critique.result == "FAIL" AND critique.severity == "critical"
  decision = "PENDING_REVIEW"
  reason = "Form has structural problems, escalate to human"
```

- **When fired:** Missing patient_id, no ICD codes, missing policy_number, unresolvable contradictions
- **Decision:** PENDING_REVIEW (human must fix form first)

##### Rule 2: Missing Required Policy Criteria (HARD GATE - Most Important)

```
IF policy_analysis.missing_criteria is not empty
  decision = "DENIED"
  reason = "Required criteria not met: {list all missing}"
```

- **When fired:** Policy requires 12 weeks therapy but patient has only 6 weeks, policy requires age 55+ but patient is 52, etc.
- **Decision:** DENIED (automatic, no appeals, no exceptions)
- **Why:** This is insurance law. If policy explicitly requires something and patient doesn't have it, they don't qualify. Simple as that.

**Example:**

```
Policy: "TKR requires 12 weeks conservative therapy"
Patient: "6 weeks of physical therapy"
Missing: "6+ additional weeks of therapy"
Decision: DENIED
```

##### Rule 3: Mandatory Fields Missing

```
IF patient_id is empty OR policy_number is empty OR 
   diagnosis[].length == 0 OR icd_mappings[].length == 0
  decision = "PENDING_REVIEW"
  reason = "Cannot decide without complete patient and diagnostic information"
```

- **When fired:** No patient ID, no policy number, no diagnosis, no ICD codes
- **Decision:** PENDING_REVIEW (escalate to human)
- **Why:** Can't make decision without basic patient info

#### PHASE 2: AI Holistic Judgment

**Only reached if ALL three hard rules pass.** This is the borderline case judgment.

**Claude reads:**

- Clinical facts from extracted data
- Policy requirements from policy analysis
- ICD confidence levels
- Critique notes and warnings
- Full case context

**Claude outputs ONLY:**

- **APPROVED:** Clear match, all criteria met, approve with reasoning
- **PENDING_REVIEW:** Ambiguous, complex, or rare disease, escalate with explanation

**Claude CANNOT output DENIED** - that's hard rules' job

### Real Examples

#### Example 1: APPROVED (All criteria clearly met)

**Patient:**

- Age 62, OA right knee (M17.11), 14 weeks PT/NSAIDs/injection, X-ray shows severe OA, requesting TKR

**Policy requires:**

- Diagnosis in covered list ✓
- 12 weeks conservative therapy ✓ (has 14 weeks)
- Age 55+ ✓
- Imaging confirmation ✓

**Hard rules check:** All pass → proceed to LLM

**LLM decision:** APPROVED

```json
{
  "decision": "APPROVED",
  "reasoning": "Patient meets all required criteria: 
    (1) Diagnosis (M17.11) matches covered conditions
    (2) Radiographic confirmation on X-ray
    (3) 14 weeks documented conservative therapy exceeds 12-week minimum
    (4) Age 62 exceeds 55-year requirement
    Authorization is medically appropriate and policy-compliant.",
  "rule_triggered": null
}
```

---

#### Example 2: DENIED (Rule 2 - Missing criteria)

**Patient:**

- Age 62, OA right knee, only 6 weeks PT ← BELOW REQUIREMENT!

**Policy requires:**

- 12 weeks conservative therapy ← MISSING!

**Hard rules check:** Rule 2 fires → Automatic DENIED

```json
{
  "decision": "DENIED",
  "reasoning": "Authorization denied. Required policy criteria not met: 
    Patient has 6 weeks of documented conservative therapy, 
    policy requires minimum 12 weeks of physical therapy, 
    NSAIDs, and/or steroid injections.",
  "rule_triggered": "MISSING_POLICY_CRITERIA"
}
```

---

#### Example 3: PENDING_REVIEW (Rare disease complexity)

**Patient:**

- Ehlers-Danlos Syndrome (rare genetic disorder), meets policy criteria technically, ICD confidence MEDIUM

**Hard rules check:** All pass → proceed to LLM

**LLM decision:** PENDING_REVIEW (borderline/complex case)

```json
{
  "decision": "PENDING_REVIEW",
  "reasoning": "Patient meets policy criteria technically. However, 
    Ehlers-Danlos Syndrome is a rare genetic connective tissue disorder. 
    Surgical intervention in rare genetic disorders requires specialist 
    medical judgment for appropriateness. Recommend escalation to 
    rheumatology specialist before final authorization.",
  "rule_triggered": null
}
```

### Output Paths

**APPROVED ✅ →**

- Insurance system processes claim
- Patient notified: "Your authorization is APPROVED"
- Provider notified: "Surgery authorized"

**DENIED ❌ →**

- Patient notified: "Your request was DENIED because [specific criterion]"
- Provider notified: "Request denied"
- Patient can appeal outside pipeline

**PENDING_REVIEW ⚠️ →**

- Sent to manual review queue
- Human reviewer reads full form + AI reasoning
- Timeline: 5-7 business days

### Technology

**Deterministic Hard Rules:**

- Pure logic, no AI
- Three specific rules
- Handles 80% of cases automatically

**Claude (for judgment):**

- Reads full context
- Performs holistic reasoning
- Explains in plain English
- Can output APPROVED or PENDING_REVIEW only

---

## 9. END-TO-END FLOW (Simple)

```
Doctor Note (raw text)
         ↓
[PHI Masking] → Removes personal info
         ↓
[Extractor] → Pulls medical facts (diagnosis, symptoms, etc.)
         ↓
[ICD Coder] → Converts to medical codes
         ↓
[Policy RAG] → Checks policy requirements
         ↓
[Form Filler] → Assembles form
         ↓
[Critique] → Quality check
         ↓
[Reviewer] → Final decision (APPROVED/DENIED/PENDING_REVIEW)
         ↓
[Audit Log] → Records everything (compliance + accountability)
         ↓
Patient + Doctor + Insurance notified
```

---

## 10. KEY SAFETY FEATURES

✅ **100% Audit Logging:** Every decision recorded with reasoning
✅ **Deterministic Hard Rules:** Denials decided automatically (no AI bias)
✅ **Escalation to Human:** Ambiguous cases go to human reviewer (not auto-approved)
✅ **PHI Protected:** Personal data never exposed to AI models
✅ **Edge Case Testing:** 44 deliberate tricky cases catch errors

---

## FOR YOUR PRESENTATION

**Quick Summary:**

- **Input:** Doctor's unstructured note + patient info
- **Process:** 8 agents (extract → code → policy check → form → QA → review)
- **Output:** APPROVED/DENIED/PENDING_REVIEW with full reasoning
- **Safety:** 100% auditable, deterministic hard rules, human escalation for ambiguous cases
- **Privacy:** PHI masked before any AI processing
