import os, sys, glob, re
sys.path.insert(0, os.getcwd())
import pdfplumber
import pandas as pd
from rapidfuzz import process, fuzz
from extractor import (
    ALIAS_DICT, SYSTEM_COLUMNS, match_column_name, clean_text,
    parse_compound_qty, standardize_date, _to_float, is_serial_number_header,
    extract_pdf_table, extract_invoice_metadata
)

# Test script for updated extractor
def test_all_invoices():
    samples = sorted(glob.glob("Sample Invoices/*.[pP][dD][fF]"))
    print("==================================================================")
    print("TESTING METADATA AND EXTRACTION ON ALL SAMPLE INVOICES")
    print("==================================================================")
    for s in samples:
        bname = os.path.basename(s)
        meta = extract_invoice_metadata(s)
        meta_table, hdrs, maps, rows = extract_pdf_table(s)
        print(f"\n[FILE]: {bname}")
        print(f"  Supplier : {meta.get('supplier_name')} (GSTIN: {meta.get('supplier_gstin')}, Inv: {meta.get('invoice_number')})")
        print(f"  Rows     : {len(rows)} | Cols: {len(hdrs)}")
        print(f"  Headers  : {hdrs[:8]}...")
        print(f"  Mappings : {maps}")

if __name__ == "__main__":
    test_all_invoices()
