import os
import sys
import json

# Set utf-8 stdout
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from extractor import extract_pdf_table

files_to_inspect = [
    "Sample Invoices/PHUB_L22014.pdf",
    "Sample Invoices/Invoice.pdf",
    "Sample Invoices/INVOICE_7HC0MTOZ2.PDF",
    "Sample Invoices/INVOICE_7GX167AKM.PDF",
]

for fpath in files_to_inspect:
    full_p = os.path.join(PROJECT_ROOT, fpath)
    print("=" * 80)
    print("INSPECTING:", fpath)
    print("=" * 80)
    metadata, headers, column_mappings, all_rows = extract_pdf_table(full_p)
    val = metadata.get("validation", {})
    print("Decision:", metadata.get("classification"))
    print("Confidence:", metadata.get("confidence"))
    print("Accounting Summary:", json.dumps(val.get("accounting_summary", {}), indent=2))
    print("Field Warnings:", json.dumps(val.get("field_warnings", []), indent=2))
    print("Drift Report:", json.dumps(val.get("drift_report", {}), indent=2))
    print("Identity Safety:", json.dumps(metadata.get("identity_safety", {}), indent=2))
    print("Grand Total Reconciliation:", json.dumps(metadata.get("grand_total_reconciliation", {}), indent=2))
