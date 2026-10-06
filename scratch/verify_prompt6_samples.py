import sys, os
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
import glob
from extractor import extract_pdf_table

def audit_prompt6_all_samples():
    pdf_dir = "Sample Invoices"
    pdf_files = sorted(list(set(glob.glob(os.path.join(pdf_dir, "*.pdf")) + glob.glob(os.path.join(pdf_dir, "*.PDF")))))
    
    print("=" * 85)
    print(f"PROMPT 6 GLOBAL VALIDATION AUDIT — ALL {len(pdf_files)} SAMPLE INVOICE PDFS")
    print("=" * 85)
    
    summary_rows = []
    
    for pdf_path in pdf_files:
        basename = os.path.basename(pdf_path)
        metadata, headers, column_mappings, rows = extract_pdf_table(pdf_path)
        val = metadata.get("validation", {})
        
        doc_conf = metadata.get("confidence", 0.0)
        classification = metadata.get("classification", "UNKNOWN")
        drift = metadata.get("drift_report", {}).get("drift_status", "UNKNOWN")
        sig_hash = metadata.get("layout_signature", {}).get("signature_hash", "N/A")
        
        acct = val.get("accounting_summary", {})
        acct_health = acct.get("accounting_health", 1.0)
        crit_mismatches = acct.get("critical_mismatches", 0)
        
        print(f"\n>>> INVOICE: {basename}")
        print(f"  Supplier: {metadata.get('supplier_name')} (GSTIN: {metadata.get('supplier_gstin')})")
        print(f"  Classification: [{classification}] | Confidence: {doc_conf:.1f}% | Layout Drift: {drift} (Sig: {sig_hash})")
        print(f"  Logical Columns ({len(headers)}): {headers}")
        print(f"  Product Rows: {len(rows)} | Accounting Health: {acct_health:.0%} (Critical Mismatches: {crit_mismatches})")
        print("  Mapped Fields:")
        for h, info in column_mappings.items():
            f = info.get("mapped_to")
            status = info.get("status")
            print(f"    {h:20} -> {str(f):15} (status={status})")
            
        summary_rows.append({
            "file": basename,
            "supplier": metadata.get("supplier_name"),
            "cols": len(headers),
            "rows": len(rows),
            "conf": doc_conf,
            "classification": classification,
            "drift": drift,
            "acct_health": acct_health,
        })
        
    print("\n" + "=" * 85)
    print("SUMMARY TABLE — PROMPT 6 GLOBAL VALIDATION RESULTS")
    print("=" * 85)
    print(f"{'Filename':30} | {'Supplier':22} | {'Cols':4} | {'Rows':4} | {'Conf':5} | {'Classification':15} | {'Drift'}")
    print("-" * 85)
    for r in summary_rows:
        print(f"{r['file']:30} | {str(r['supplier'])[:22]:22} | {r['cols']:4d} | {r['rows']:4d} | {r['conf']:4.1f}% | {r['classification']:15} | {r['drift']}")

if __name__ == "__main__":
    audit_prompt6_all_samples()
