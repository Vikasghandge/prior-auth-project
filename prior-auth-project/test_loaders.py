from prior_auth.utils.dataset_loaders import (
    load_doctor_notes_xlsx, load_icd_csv, load_policies_from_dir,
    load_form_template, load_gold_standard_xlsx, load_edge_cases_xlsx,
)
import json

print("=== Doctor Notes ===")
notes = load_doctor_notes_xlsx()
print(f"Loaded {len(notes)} notes")
for n in notes[:2]:
    print(f"  {n['case_id']} ({n['specialty']}): {n['note_text'][:60]}...")

print("\n=== ICD Codes ===")
icds = load_icd_csv()
print(f"Loaded {len(icds)} codes")
for i in icds[:2]:
    print(f"  {i['code']} ({i['specialty']}): {i['description']} kw={i['keywords'][:3]}")

print("\n=== Policies ===")
pols = load_policies_from_dir()
print(f"Loaded {len(pols)} policies")
for p in pols:
    print(f"  {p['policy_id']}: {len(p['criteria'])} criteria, proc_kw={p['procedure_keywords']}")

print("\n=== Form Template ===")
tmpl = load_form_template()
print(f"Loaded {len(tmpl)} templates, fields={tmpl[0]['fields']}")

print("\n=== Gold Standard ===")
gold = load_gold_standard_xlsx()
print(f"Loaded {len(gold)} gold records")
for g in gold:
    print(f"  {g['case_id']}: {list(g['expected'].keys())}")

print("\n=== Edge Cases ===")
edges = load_edge_cases_xlsx()
print(f"Loaded {len(edges)} edge cases")
for e in edges:
    print(f"  {e['case_id']}: {e['edge_case']} - {e['description']}")
