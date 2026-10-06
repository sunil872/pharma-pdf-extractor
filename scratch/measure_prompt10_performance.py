import os
import sys
import time
import json

sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")

from storage import StorageService, init_db
from extractor import extract_pdf_table
from migrate_json_to_sqlite import run_migration

SAMPLE_DIR = r"c:\Users\sunil\pharma-pdf-extractor\Sample Invoices"
DB_PATH = r"c:\Users\sunil\pharma-pdf-extractor\mediastra_perf.db"

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

# 1. DB Init Time
t0 = time.perf_counter()
init_db(DB_PATH)
t_init = (time.perf_counter() - t0) * 1000.0

# 2. Migration Time
t0 = time.perf_counter()
mig_res = run_migration(db_path=DB_PATH)
t_mig = (time.perf_counter() - t0) * 1000.0

service = StorageService(DB_PATH)

# 3. Supplier Lookup Time (100 iterations)
t0 = time.perf_counter()
for _ in range(100):
    sup = service.find_supplier_by_gstin("36AAZFP3596K1Z5")
t_sup_lookup = (time.perf_counter() - t0) / 100.0 * 1000.0

# 4. Profile Lookup Time (100 iterations)
t0 = time.perf_counter()
for _ in range(100):
    profiles = service.export_supplier_profiles_dict()
t_prof_lookup = (time.perf_counter() - t0) / 100.0 * 1000.0

# 5. Profile Update Time (10 iterations)
t0 = time.perf_counter()
for i in range(10):
    service.save_or_update_supplier_profile_memory(
        supplier_key="36AAZFP3596K1Z5",
        supplier_name="MOHIT PHARMA",
        gstin="36AAZFP3596K1Z5",
        headers=["Item", "Amount"],
        logical_columns=[{"header": "Item"}, {"header": "Amount"}],
        resolved_mappings={"Item": {"mapped_to": "itemName"}, "Amount": {"mapped_to": "amount"}},
        rows=[["A", "100"]],
        validation_result={"classification": "AUTO_ACCEPT", "document_confidence": 95.0, "accounting_summary": {"critical_mismatches": 0}},
    )
t_prof_update = (time.perf_counter() - t0) / 10.0 * 1000.0

# 6. Benchmark PDFs Processing Time
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

t0 = time.perf_counter()
for fname in files:
    fpath = os.path.join(SAMPLE_DIR, fname)
    extract_pdf_table(fpath)
t_benchmark_total = time.perf_counter() - t0

perf_report = {
    "db_init_ms": round(t_init, 2),
    "migration_ms": round(t_mig, 2),
    "supplier_lookup_ms": round(t_sup_lookup, 3),
    "profile_dict_export_ms": round(t_prof_lookup, 3),
    "profile_update_ms": round(t_prof_update, 2),
    "benchmark_9_pdfs_total_sec": round(t_benchmark_total, 2),
    "avg_sec_per_pdf": round(t_benchmark_total / len(files), 3),
}

print(json.dumps(perf_report, indent=2))

if os.path.exists(DB_PATH):
    try:
        os.remove(DB_PATH)
    except Exception:
        pass
