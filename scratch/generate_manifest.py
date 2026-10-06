import os
import sys
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
import hashlib
import json
from extractor import extract_pdf_table

samples_dir = r"c:\Users\sunil\pharma-pdf-extractor\Sample Invoices"
manifest_path = r"c:\Users\sunil\pharma-pdf-extractor\benchmark_manifest.json"
results_path = r"c:\Users\sunil\pharma-pdf-extractor\benchmark_results_v1.json"

files = [
    "INVOICE_7GU0X28XM.PDF",
    "INVOICE_7GX167AKM.PDF",
    "INVOICE_7HC0MTOZ2.PDF",
    "INVOICE_7HH0S5IPC.PDF",
    "Invoice.pdf",
    "PHUB_L22014.pdf",
    "SI26-000698.pdf",
    "Sunil_Medicare_Sample_Invoice.pdf",
    "invoice (1).pdf",
]

manifest_entries = []
results_entries = []

for fname in files:
    fpath = os.path.join(samples_dir, fname)
    if not os.path.exists(fpath):
        print(f"MISSING: {fname}")
        continue
    
    with open(fpath, "rb") as f:
        content = f.read()
        sha256 = hashlib.sha256(content).hexdigest()
    
    metadata, headers, column_mappings, all_rows = extract_pdf_table(fpath)
    val = metadata.get("validation", {})
    drift = metadata.get("drift_report", {})
    
    sup_name = metadata.get("supplier_name")
    gstin = metadata.get("supplier_gstin")
    identity_safety = metadata.get("identity_safety", {})
    
    # Ground truth key fields
    mapped_fields = sorted(list(set(v.get("mapped_to") for v in column_mappings.values() if v.get("mapped_to"))))
    
    manifest_item = {
        "filename": fname,
        "file_hash": sha256,
        "file_size_bytes": len(content),
        "expected_supplier_if_verified": sup_name or "NOT VERIFIED",
        "expected_gstin_if_verified": gstin or "NOT VERIFIED",
        "expected_row_count_if_verified": len(all_rows),
        "expected_key_fields": mapped_fields,
        "benchmark_version": "v1.0",
    }
    manifest_entries.append(manifest_item)
    
    results_item = {
        "filename": fname,
        "file_hash": sha256,
        "supplier_identity": identity_safety.get("supplier_key") or gstin or sup_name,
        "supplier_name": sup_name,
        "gstin": gstin,
        "identity_status": identity_safety.get("status", "UNKNOWN"),
        "layout_mapping": {k: v.get("mapped_to") for k, v in column_mappings.items()},
        "semantic_mapping": {k: v.get("mapped_to") for k, v in column_mappings.items() if v.get("mapped_to")},
        "row_count": len(all_rows),
        "confidence": metadata.get("confidence", 0.0),
        "decision": metadata.get("classification", metadata.get("decision")),
        "validation_summary": {
            "critical_mismatches": val.get("accounting_summary", {}).get("critical_mismatches", 0),
            "warnings_count": len(val.get("field_warnings", [])),
            "warnings": val.get("field_warnings", [])[:5],
        },
    }
    results_entries.append(results_item)

manifest_obj = {
    "benchmark_version": "1.0",
    "dataset_description": "Fixed 9-PDF MediAstra Pharma Benchmark Dataset",
    "sample_count": len(manifest_entries),
    "samples": manifest_entries,
}

results_obj = {
    "benchmark_version": "1.0",
    "total_invoices": len(results_entries),
    "results": results_entries,
}

with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest_obj, f, indent=2)

with open(results_path, "w", encoding="utf-8") as f:
    json.dump(results_obj, f, indent=2)

print(f"Generated {manifest_path} and {results_path} successfully.")
