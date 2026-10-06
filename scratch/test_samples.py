import os, sys, glob
sys.path.insert(0, os.getcwd())
from extractor import extract_pdf_table

samples = sorted(glob.glob("Sample Invoices/*.[pP][dD][fF]"))
print(f"Testing {len(samples)} sample invoices:")
for s in samples:
    meta, hdrs, maps, rows = extract_pdf_table(s)
    bname = os.path.basename(s)
    sname = str(meta.get("supplier_name") or "None")
    print(f"  {bname:35s} | Supplier: {sname:25s} | Rows: {len(rows):2d} | Cols: {len(hdrs):2d}")
print("All sample invoices parsed successfully!")
