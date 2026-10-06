import sys, os
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
import glob
import pdfplumber
from extractor import extract_pdf_table, ALIAS_DICT

def run_all_samples_audit():
    pdf_dir = "Sample Invoices"
    pdf_files = sorted(glob.glob(os.path.join(pdf_dir, "*.pdf")) + glob.glob(os.path.join(pdf_dir, "*.PDF")))
    
    print("=" * 80)
    print(f"PROMPT 5 AUDIT ON ALL {len(pdf_files)} SAMPLE INVOICE PDFS")
    print("=" * 80)
    
    results = []
    
    for pdf_path in pdf_files:
        basename = os.path.basename(pdf_path)
        print(f"\n>>> PROCESSING: {basename}")
        try:
            metadata, headers, column_mappings, rows = extract_pdf_table(pdf_path, debug=True)
            
            # Map canonical fields
            mapped_fields = {h: info.get("mapped_to") for h, info in column_mappings.items()}
            
            unresolved = [h for h, info in column_mappings.items() if info.get("status") == "unresolved"]
            ambiguous = [h for h, info in column_mappings.items() if info.get("status") == "ambiguous"]
            inferred = [h for h, info in column_mappings.items() if info.get("status") == "inferred"]
            known = [h for h, info in column_mappings.items() if info.get("status") == "known_header"]
            
            print(f"  Supplier: {metadata.get('supplier_name')} (GSTIN: {metadata.get('supplier_gstin')})")
            print(f"  Logical Columns Count: {len(headers)}")
            print(f"  Logical Headers: {headers}")
            print(f"  Rows Extracted: {len(rows)}")
            print(f"  Known Mapped ({len(known)}): {known}")
            print(f"  Inferred Mapped ({len(inferred)}): {[(h, mapped_fields[h]) for h in inferred]}")
            print(f"  Ambiguous ({len(ambiguous)}): {ambiguous}")
            print(f"  Unresolved ({len(unresolved)}): {unresolved}")
            
            if rows:
                print("  Sample First Row:")
                for h in headers:
                    idx = headers.index(h)
                    val = rows[0][idx] if idx < len(rows[0]) else ""
                    print(f"    {h:20} -> {str(mapped_fields.get(h)):15} | val = {val!r}")
            
            results.append({
                "file": basename,
                "supplier": metadata.get("supplier_name"),
                "cols": len(headers),
                "headers": headers,
                "rows": len(rows),
                "inferred": len(inferred),
                "ambiguous": len(ambiguous),
                "unresolved": len(unresolved),
            })
        except Exception as e:
            print(f"  ERROR processing {basename}: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 80)
    print("SUMMARY TABLE OF ALL SAMPLE INVOICES")
    print("=" * 80)
    print(f"{'Filename':25} | {'Supplier':25} | {'Cols':4} | {'Rows':4} | {'Inferred':8} | {'Status'}")
    print("-" * 80)
    for r in results:
        status = "OK" if r["rows"] > 0 and r["cols"] >= 4 else "WARN"
        print(f"{r['file']:25} | {str(r['supplier'])[:25]:25} | {r['cols']:4d} | {r['rows']:4d} | {r['inferred']:8d} | {status}")

if __name__ == "__main__":
    run_all_samples_audit()
