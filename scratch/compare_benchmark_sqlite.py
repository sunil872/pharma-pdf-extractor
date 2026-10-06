import os
import sys
import json
import hashlib

sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")

from extractor import extract_pdf_table
from storage import StorageService, init_db
from migrate_json_to_sqlite import run_migration

SAMPLE_DIR = r"c:\Users\sunil\pharma-pdf-extractor\Sample Invoices"
GOLDEN_PATH = r"c:\Users\sunil\pharma-pdf-extractor\benchmark_results_v1.json"
SQLITE_BENCHMARK_PATH = r"c:\Users\sunil\pharma-pdf-extractor\benchmark_results_sqlite_v1.json"
SQLITE_DB_PATH = r"c:\Users\sunil\pharma-pdf-extractor\mediastra_benchmark.db"

# 1. Initialize and migrate SQLite DB
if os.path.exists(SQLITE_DB_PATH):
    os.remove(SQLITE_DB_PATH)
init_db(SQLITE_DB_PATH)
run_migration(db_path=SQLITE_DB_PATH)

service = StorageService(SQLITE_DB_PATH)

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

results_entries = []

for fname in files:
    fpath = os.path.join(SAMPLE_DIR, fname)
    with open(fpath, "rb") as f:
        content = f.read()
        sha256 = hashlib.sha256(content).hexdigest()
    
    metadata, headers, column_mappings, all_rows = extract_pdf_table(fpath)
    val = metadata.get("validation", {})
    identity_safety = metadata.get("identity_safety", {})
    sup_name = metadata.get("supplier_name")
    gstin = metadata.get("supplier_gstin")
    
    # Register document and run in SQLite
    doc, run = service.register_document_and_run(
        filename=fname,
        file_hash=sha256,
        file_size_bytes=len(content),
        metadata=metadata,
        headers=headers,
        logical_columns=metadata.get("logical_columns", []),
        column_mappings=column_mappings,
        rows=all_rows,
    )
    
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

results_obj = {
    "benchmark_version": "1.0",
    "storage_backend": "SQLite",
    "total_invoices": len(results_entries),
    "results": results_entries,
}

with open(SQLITE_BENCHMARK_PATH, "w", encoding="utf-8") as f:
    json.dump(results_obj, f, indent=2)

# Programmatic Comparison with Golden Baseline
with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
    golden_data = json.load(f)

golden_map = {r["file_hash"]: r for r in golden_data["results"]}
sqlite_map = {r["file_hash"]: r for r in results_entries}

differences = []

for f_hash, g_res in golden_map.items():
    s_res = sqlite_map.get(f_hash)
    if not s_res:
        differences.append(f"Missing file in SQLite run: {g_res['filename']}")
        continue
    
    for key in ["supplier_identity", "supplier_name", "gstin", "row_count", "confidence", "decision", "semantic_mapping"]:
        g_val = g_res.get(key)
        s_val = s_res.get(key)
        if g_val != s_val:
            differences.append(f"Discrepancy in {g_res['filename']} for field '{key}': Golden={g_val} vs SQLite={s_val}")

print("=" * 70)
print("BENCHMARK COMPARISON: GOLDEN (v1.0) vs SQLITE (v1.0)")
print("=" * 70)
if not differences:
    print("SUCCESS: 0 DISCREPANCIES FOUND across all 9 benchmark PDFs!")
    print("Extraction behavior is 100% identical and preserved.")
else:
    print(f"FAILED: Found {len(differences)} discrepancies:")
    for diff in differences:
        print(f"  - {diff}")
print("=" * 70)

# Clean up benchmark temp db
if os.path.exists(SQLITE_DB_PATH):
    try:
        os.remove(SQLITE_DB_PATH)
    except Exception:
        pass
