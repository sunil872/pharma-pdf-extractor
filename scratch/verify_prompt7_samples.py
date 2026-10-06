import os
import sys
import glob

# Ensure repo root is on sys.path
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")

from extractor import (
    extract_pdf_table,
    load_supplier_profiles,
)

SAMPLE_DIR = r"c:\Users\sunil\pharma-pdf-extractor\Sample Invoices"
sample_files = glob.glob(os.path.join(SAMPLE_DIR, "*.pdf")) + glob.glob(os.path.join(SAMPLE_DIR, "*.PDF"))
sample_files = sorted(list(set(sample_files)))

print("=" * 110)
print("PROMPT 7 — VERIFICATION REPORT ON ALL 9 SAMPLE INVOICES")
print("=" * 110)

results = []
for fpath in sample_files:
    fname = os.path.basename(fpath)
    print(f"\n>>> PROCESSING INVOICE: {fname}")
    try:
        metadata, headers, column_mappings, all_rows = extract_pdf_table(fpath)
        
        sup_name = metadata.get("supplier_name") or "Unknown"
        gstin = metadata.get("supplier_gstin") or "Unknown"
        sup_key = sup_name if sup_name != "Unknown" else gstin
        
        val_info = metadata.get("validation", {})
        doc_conf = metadata.get("confidence", 0.0)
        classification = metadata.get("classification", "UNKNOWN")
        
        drift = metadata.get("drift_report", {})
        match_status = drift.get("drift_status", "UNKNOWN")
        layout_id = drift.get("matched_layout_id") or "N/A"
        is_cross = drift.get("is_cross_supplier_layout", False)
        
        mem_action = metadata.get("profile_memory", {})
        was_updated = mem_action.get("updated", False)
        update_action = mem_action.get("action") or mem_action.get("reason", "N/A")
        
        results.append({
            "filename": fname,
            "supplier": sup_name[:24],
            "supplier_key": sup_key[:18],
            "layout_id": layout_id[:16],
            "match_status": match_status,
            "is_cross_prior": "YES" if is_cross else "NO",
            "confidence": f"{doc_conf:.1f}%",
            "decision": classification,
            "profile_updated": "YES" if was_updated else "NO",
            "update_reason": update_action,
        })
        
        print(f"  Supplier: {sup_name} (GSTIN: {gstin})")
        print(f"  Layout Status: {match_status} (Layout ID: {layout_id})")
        print(f"  Decision: [{classification}] | Confidence: {doc_conf:.1f}%")
        print(f"  Memory Action: Updated={was_updated} ({update_action})")
        
    except Exception as e:
        print(f"  ERROR processing {fname}: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 110)
print(f"{'Filename':<26} | {'Supplier':<22} | {'Layout Status':<15} | {'Conf':<6} | {'Decision':<15} | {'Prof Updated':<12}")
print("-" * 110)
for r in results:
    print(f"{r['filename']:<26} | {r['supplier']:<22} | {r['match_status']:<15} | {r['confidence']:<6} | {r['decision']:<15} | {r['profile_updated']:<12}")
print("=" * 110)
