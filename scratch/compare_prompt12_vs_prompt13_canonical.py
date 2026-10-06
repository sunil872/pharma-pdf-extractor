import os
import sys
sys.path.insert(0, os.path.abspath("."))
import json
import hashlib
from extractor import extract_pdf_table

# Load golden manifest v1
with open("evaluation/golden_manifest_v1.json", "r", encoding="utf-8") as f:
    golden_manifest = json.load(f)

# Load baseline results from benchmark_results_v1.json (Prompt 9-12 baseline)
with open("benchmark_results_v1.json", "r", encoding="utf-8") as f:
    prompt12_baseline = json.load(f)

baseline_by_filename = {r["filename"]: r for r in prompt12_baseline["results"]}

sample_dir = "Sample Invoices"
results_prompt13 = []

print("=" * 90)
print("CANONICAL 9-PDF GOLDEN BENCHMARK: PROMPT 12 BASELINE VS PROMPT 13 CURRENT EXTRACTION")
print("=" * 90)
print(f"{'Filename':32s} | {'SHA Match':9s} | {'Rows (P12->P13)':16s} | {'Decision (P12->P13)':26s} | {'Confidence (P12->P13)':20s}")
print("-" * 90)

total_rows_p12 = 0
total_rows_p13 = 0
auto_accept_p12 = 0
auto_accept_p13 = 0
review_required_p12 = 0
review_required_p13 = 0
unresolved_p12 = 0
unresolved_p13 = 0

doc_comparisons = []

for doc in golden_manifest["documents"]:
    fname = doc["filename"]
    expected_sha = doc["sha256"]
    fpath = os.path.join(sample_dir, fname)
    
    with open(fpath, "rb") as fp:
        actual_sha = hashlib.sha256(fp.read()).hexdigest()
    
    sha_ok = (actual_sha == expected_sha)
    
    base_res = baseline_by_filename.get(fname, {})
    p12_rows = base_res.get("row_count", 0)
    p12_dec = base_res.get("decision", "UNKNOWN")
    p12_conf = base_res.get("confidence", 0.0)
    
    total_rows_p12 += p12_rows
    if p12_dec == "AUTO_ACCEPT": auto_accept_p12 += 1
    elif p12_dec == "REVIEW_REQUIRED": review_required_p12 += 1
    elif p12_dec == "UNRESOLVED": unresolved_p12 += 1
    
    # Run Prompt 13 extraction
    meta, headers, mappings, rows = extract_pdf_table(fpath)
    p13_rows = len(rows)
    p13_dec = meta.get("classification")
    p13_conf = meta.get("confidence")
    p13_supp = meta.get("supplier_name")
    
    total_rows_p13 += p13_rows
    if p13_dec == "AUTO_ACCEPT": auto_accept_p13 += 1
    elif p13_dec == "REVIEW_REQUIRED": review_required_p13 += 1
    elif p13_dec == "UNRESOLVED": unresolved_p13 += 1
    
    print(f"{fname:32s} | {str(sha_ok):9s} | {p12_rows:2d} -> {p13_rows:2d} ({doc['expected_rows']:2d} exp) | {p12_dec:15s} -> {p13_dec:10s} | {p12_conf:5.1f}% -> {p13_conf:5.1f}%")
    
    doc_comparisons.append({
        "filename": fname,
        "sha256": actual_sha,
        "sha_verified": sha_ok,
        "supplier_name": p13_supp,
        "expected_rows": doc["expected_rows"],
        "p12_rows": p12_rows,
        "p13_rows": p13_rows,
        "p12_decision": p12_dec,
        "p13_decision": p13_dec,
        "p12_confidence": p12_conf,
        "p13_confidence": p13_conf,
        "mappings": mappings,
        "rows": rows,
    })

print("=" * 90)
print(f"TOTAL ROWS:         {total_rows_p12} -> {total_rows_p13}")
print(f"AUTO_ACCEPT:        {auto_accept_p12} -> {auto_accept_p13}")
print(f"REVIEW_REQUIRED:    {review_required_p12} -> {review_required_p13}")
print(f"UNRESOLVED:         {unresolved_p12} -> {unresolved_p13}")
print("=" * 90)

# Save evaluation comparison JSON
with open("evaluation/results/prompt14_benchmark_comparison.json", "w", encoding="utf-8") as f:
    json.dump({
        "comparison_title": "Prompt 12 vs Prompt 13 Canonical 9-PDF Benchmark",
        "benchmark_manifest": "evaluation/golden_manifest_v1.json",
        "total_documents": 9,
        "sha256_all_verified": all(d["sha_verified"] for d in doc_comparisons),
        "summary": {
            "p12_total_rows": total_rows_p12,
            "p13_total_rows": total_rows_p13,
            "p12_auto_accept": auto_accept_p12,
            "p13_auto_accept": auto_accept_p13,
            "p12_review_required": review_required_p12,
            "p13_review_required": review_required_p13,
            "p12_unresolved": unresolved_p12,
            "p13_unresolved": unresolved_p13,
        },
        "documents": [
            {k: v for k, v in d.items() if k != "rows"} for d in doc_comparisons
        ]
    }, f, indent=2)
print("Saved comparison to evaluation/results/prompt14_benchmark_comparison.json")
