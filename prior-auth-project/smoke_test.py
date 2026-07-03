"""Smoke test: run all 6 new doctor notes through PriorAuthWorkflow."""
from prior_auth.utils.dataset_loaders import load_doctor_notes_xlsx, load_gold_standard_xlsx
from prior_auth.orchestration.graph import PriorAuthWorkflow
import json

workflow = PriorAuthWorkflow()
notes = load_doctor_notes_xlsx()
gold = {g["case_id"]: g for g in load_gold_standard_xlsx()}

print("=" * 70)
print("SMOKE TEST: Running 6 new doctor notes through the pipeline")
print("=" * 70)

for note in notes:
    case_id = note["case_id"]
    print(f"\n--- {case_id} ({note['specialty']}) ---")
    print(f"Note: {note['note_text'][:80]}...")

    try:
        case, trace = workflow.run(case_id, note["note_text"], specialty=note["specialty"], persist_trace=False)
        print(f"  Status: {case.status.value}")

        if case.clinical_facts:
            facts = case.clinical_facts
            print(f"  Diagnosis: {facts.diagnosis}")
            print(f"  Symptoms: {facts.symptoms}")
            print(f"  Symptom Duration: {facts.symptom_duration}")
            print(f"  Failed Treatments: {facts.failed_treatments}")
            print(f"  Imaging: {facts.imaging_evidence}")
            print(f"  Procedure: {facts.requested_procedure}")
            print(f"  Extraction Confidence: {facts.extraction_confidence}")
        else:
            print(f"  No clinical facts extracted")

        if case.icd_result:
            print(f"  ICD Code: {case.icd_result.icd10_code} ({case.icd_result.confidence})")

        if case.policy_result:
            print(f"  Policy: {case.policy_result.policy_id} match={case.policy_result.policy_match}")

        if case.suspension_reason:
            print(f"  Suspension: {case.suspension_reason}")

        # Gold comparison for PA001
        if case_id in gold and case.clinical_facts:
            print(f"\n  --- GOLD COMPARISON ({case_id}) ---")
            expected = gold[case_id]["expected"]
            print(f"  Expected diagnosis: {expected.get('diagnosis')}")
            print(f"  Got diagnosis:      {facts.diagnosis}")
            print(f"  Expected symptoms:  {expected.get('symptoms')}")
            print(f"  Got symptoms:       {facts.symptoms}")
            print(f"  Expected duration:  {expected.get('duration')}")
            print(f"  Got duration:       {facts.symptom_duration}")
            print(f"  Expected treatments: {expected.get('failed_treatments')}")
            print(f"  Got treatments:      {facts.failed_treatments}")
            print(f"  Expected imaging:   {expected.get('imaging')}")
            print(f"  Got imaging:        {facts.imaging_evidence}")
            print(f"  Expected procedure: {expected.get('requested_procedure')}")
            print(f"  Got procedure:      {facts.requested_procedure}")

    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")

print("\n" + "=" * 70)
print("SMOKE TEST COMPLETE")
print("=" * 70)
