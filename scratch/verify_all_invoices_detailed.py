import os, sys, glob, re
sys.path.insert(0, os.getcwd())
import pandas as pd
from extractor import (
    extract_pdf_table, compute_row_accounting, ALIAS_DICT, SYSTEM_COLUMNS,
    _mapping_field
)

def run_detailed_verification():
    samples = sorted(glob.glob("Sample Invoices/*.[pP][dD][fF]"))
    print("================================================================================")
    print("      DETAILED VERIFICATION REPORT FOR ALL 9 SAMPLE PHARMA INVOICES")
    print("================================================================================")
    
    for s in samples:
        bname = os.path.basename(s)
        meta, hdrs, maps, rows = extract_pdf_table(s)
        
        # Build mapping summary
        known_hdrs = []
        inferred_hdrs = []
        unresolved_hdrs = []
        
        for h in hdrs:
            m = maps.get(h)
            if isinstance(m, dict):
                f = m.get("mapped_to")
                st = m.get("status")
                conf = m.get("confidence", 0)
                if st == "known_header":
                    known_hdrs.append(f"{h} -> {f}")
                elif st == "inferred":
                    inferred_hdrs.append(f"{h} -> {f} (conf: {conf:.0f}%)")
                else:
                    unresolved_hdrs.append(h)
            elif m:
                known_hdrs.append(f"{h} -> {m}")
            else:
                unresolved_hdrs.append(h)
                
        print(f"\n--------------------------------------------------------------------------------")
        print(f"INVOICE FILE: {bname}")
        print(f"--------------------------------------------------------------------------------")
        print(f"  Supplier Trade Name : {meta.get('supplier_name')}")
        print(f"  Supplier GSTIN      : {meta.get('supplier_gstin')}")
        print(f"  Invoice Number      : {meta.get('invoice_number')}")
        print(f"  Invoice Date        : {meta.get('invoice_date')}")
        print(f"  Row Count           : {len(rows)} product rows")
        print(f"  Total Columns       : {len(hdrs)}")
        print(f"  Physical Headers    : {hdrs}")
        print(f"  Known Headers ({len(known_hdrs)}): {', '.join(known_hdrs)}")
        if inferred_hdrs:
            print(f"  Inferred Fields ({len(inferred_hdrs)}): {', '.join(inferred_hdrs)}")
        if unresolved_hdrs:
            print(f"  Unresolved Fields ({len(unresolved_hdrs)}): {', '.join(unresolved_hdrs)}")
            
        if rows:
            # Show mapped fields for first row
            first_r = rows[0]
            row_dict = {}
            for idx, h in enumerate(hdrs):
                field = _mapping_field(maps, h)
                if field and idx < len(first_r):
                    row_dict[field] = first_r[idx]
            accounted = compute_row_accounting(row_dict)
            print(f"  Sample Row 1 Mapped Fields:")
            for k in ["itemName", "pack", "batchNo", "expiryDate", "quantity", "rate", "mrp", "hsnCode", "amount", "gstPercent", "netAmount"]:
                if k in accounted:
                    print(f"    - {k:15s}: {repr(accounted[k])}")

if __name__ == "__main__":
    run_detailed_verification()
