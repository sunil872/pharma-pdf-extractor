import os
import sys
import json

sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")

from batch_processor import process_batch, export_batch_results
from storage import StorageService, init_db

SAMPLE_DIR = r"c:\Users\sunil\pharma-pdf-extractor\Sample Invoices"
GOLDEN_PATH = r"c:\Users\sunil\pharma-pdf-extractor\benchmark_results_v1.json"
DB_PATH = r"c:\Users\sunil\pharma-pdf-extractor\mediastra_batch_benchmark.db"

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
init_db(DB_PATH)
service = StorageService(DB_PATH)

batch_res = process_batch(SAMPLE_DIR, storage_service=service)

with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
    golden_data = json.load(f)

golden_map = {r["filename"]: r for r in golden_data["results"]}
batch_map = {d.filename: d for d in batch_res.document_results}

differences = []

for fname, g_res in golden_map.items():
    b_res = batch_map.get(fname)
    if not b_res:
        differences.append(f"Missing file in batch: {fname}")
        continue
    
    if b_res.file_hash != g_res["file_hash"]:
        differences.append(f"Hash mismatch in {fname}: Golden={g_res['file_hash']} vs Batch={b_res.file_hash}")
    
    if b_res.row_count != g_res["row_count"]:
        differences.append(f"Row count mismatch in {fname}: Golden={g_res['row_count']} vs Batch={b_res.row_count}")
        
    if b_res.decision != g_res["decision"]:
        differences.append(f"Decision mismatch in {fname}: Golden={g_res['decision']} vs Batch={b_res.decision}")
        
    if abs(b_res.confidence - g_res["confidence"]) > 0.001:
        differences.append(f"Confidence mismatch in {fname}: Golden={g_res['confidence']} vs Batch={b_res.confidence}")
        
    if b_res.supplier_name != g_res["supplier_name"]:
        differences.append(f"Supplier mismatch in {fname}: Golden={g_res['supplier_name']} vs Batch={b_res.supplier_name}")

print("=" * 70)
print("PROMPT 11 BATCH BENCHMARK INTEGRITY VERIFICATION")
print("=" * 70)
print(f"Total PDFs Processed: {batch_res.total_documents}")
print(f"Total Rows Extracted: {batch_res.total_rows}")
print(f"AUTO_ACCEPT:          {batch_res.auto_accept_count}")
print(f"REVIEW_REQUIRED:      {batch_res.review_required_count}")
print(f"UNRESOLVED:           {batch_res.unresolved_count}")
print(f"FAILED:               {batch_res.failed_count}")
print(f"Total Duration:       {batch_res.total_duration_sec:.2f}s")
print("-" * 70)
if not differences:
    print("SUCCESS: 0 DISCREPANCIES! Golden benchmark preserved 100% in batch execution.")
else:
    print(f"FAILED: Found {len(differences)} discrepancies:")
    for d in differences:
        print(f"  - {d}")
print("=" * 70)

if os.path.exists(DB_PATH):
    try:
        os.remove(DB_PATH)
    except Exception:
        pass
