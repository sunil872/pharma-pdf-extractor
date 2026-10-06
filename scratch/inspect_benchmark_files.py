import os
import sys
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
import hashlib
import json
from extractor import extract_pdf_table

samples_dir = r"c:\Users\sunil\pharma-pdf-extractor\Sample Invoices"
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

results = []

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
    
    res = {
        "filename": fname,
        "file_hash": sha256,
        "file_size": len(content),
        "supplier_name": metadata.get("supplier_name"),
        "gstin": metadata.get("supplier_gstin"),
        "identity_source": metadata.get("identity_safety", {}).get("status") or ("EXACT_GSTIN" if metadata.get("supplier_gstin") else "NAME"),
        "row_count": len(all_rows),
        "columns_count": len(headers),
        "logical_columns_count": len(metadata.get("logical_columns", [])),
        "column_mappings": {k: v.get("mapped_to") for k, v in column_mappings.items() if v.get("mapped_to")},
        "confidence": metadata.get("confidence", 0.0),
        "decision": metadata.get("classification", metadata.get("decision")),
        "validation_errors": val.get("accounting_summary", {}).get("critical_mismatches", 0),
        "validation_warnings": len(val.get("field_warnings", [])),
    }
    results.append(res)
    print(f"Processed: {fname} | Hash: {sha256[:12]} | Supplier: {res['supplier_name']} | Rows: {res['row_count']} | Conf: {res['confidence']}% | Decision: {res['decision']}")

with open("scratch/temp_benchmark_inspect.json", "w") as f:
    json.dump(results, f, indent=2)
