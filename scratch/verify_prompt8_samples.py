import os
import sys
import glob

# Ensure repo root is on sys.path
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")

from extractor import (
    extract_pdf_table,
    create_review_session,
    apply_and_validate_review_corrections,
    commit_reviewed_layout_to_profile_memory,
)

SAMPLE_DIR = r"c:\Users\sunil\pharma-pdf-extractor\Sample Invoices"
sample_files = glob.glob(os.path.join(SAMPLE_DIR, "*.pdf")) + glob.glob(os.path.join(SAMPLE_DIR, "*.PDF"))
sample_files = sorted(list(set(sample_files)))

print("=" * 120)
print("PROMPT 8 — REAL SAMPLE INVOICES & HUMAN REVIEW / LEARNING SIMULATION REPORT")
print("=" * 120)

results = []

for fpath in sample_files:
    fname = os.path.basename(fpath)
    print(f"\n>>> PROCESSING INVOICE: {fname}")
    try:
        metadata, headers, column_mappings, all_rows = extract_pdf_table(fpath)
        
        sup_name = metadata.get("supplier_name") or "Unknown"
        gstin = metadata.get("supplier_gstin") or "Unknown"
        doc_conf = metadata.get("confidence", 0.0)
        decision = metadata.get("classification", "UNKNOWN")
        drift = metadata.get("drift_report", {})
        layout_status = drift.get("drift_status", "UNKNOWN")
        
        session = create_review_session(metadata, headers, [], column_mappings, all_rows)
        unresolved = session.get("unresolved_columns", [])
        swaps = session.get("suspected_swaps", [])
        
        review_needed = (decision != "AUTO_ACCEPT")
        
        # Simulate human review workflow for review-required / unresolved files
        corrected_fields_list = []
        post_conf = doc_conf
        post_status = decision
        profile_action = "N/A (AUTO_ACCEPTED)" if not review_needed else "REVIEW_AWAITING_CONFIRMATION"
        
        if review_needed:
            # Simulated Review Correction:
            # Operator resolves unmapped columns or verifies valid mappings
            proposed_mappings = {}
            for h in headers:
                curr_map = column_mappings.get(h, {}).get("mapped_to")
                proposed_mappings[h] = curr_map
                
            # If there's an unresolved column with clear sample values (like HSN), reviewer sets it
            for unres_h in unresolved:
                # Check sample row values in unres column
                col_idx = headers.index(unres_h) if unres_h in headers else -1
                if col_idx >= 0:
                    samples = [row[col_idx] for row in all_rows[:3] if col_idx < len(row)]
                    # If sample looks like HSN code
                    if any(s.isdigit() and len(s) in (4, 6, 8) for s in samples):
                        if "hsnCode" not in proposed_mappings.values():
                            proposed_mappings[unres_h] = "hsnCode"
                            corrected_fields_list.append(f"{unres_h} -> hsnCode")

            # Apply and revalidate human review corrections
            val_res = apply_and_validate_review_corrections(session, proposed_mappings, reviewer_id="simulated_reviewer")
            post_conf = val_res.get("revalidated_confidence", doc_conf)
            post_status = val_res.get("status")
            
            # Commit reviewed layout
            commit_res = commit_reviewed_layout_to_profile_memory(val_res["updated_session"])
            profile_action = commit_res.get("action") or ("REJECTED: " + commit_res.get("reason", ""))

        results.append({
            "filename": fname,
            "supplier": sup_name[:22],
            "supplier_identity": session.get("supplier_identity") or gstin,
            "layout_status": layout_status,
            "orig_conf": f"{doc_conf:.1f}%",
            "orig_decision": decision,
            "review_required": "YES" if review_needed else "NO",
            "unresolved_count": len(unresolved),
            "corrected_fields": ", ".join(corrected_fields_list) if corrected_fields_list else "None (Verified existing)",
            "post_conf": f"{post_conf:.1f}%",
            "post_val": post_status,
            "profile_action": profile_action,
        })
        
        print(f"  Supplier: {sup_name} | Identity: {session.get('supplier_identity')}")
        print(f"  Original: [{decision}] {doc_conf:.1f}% | Review Needed: {review_needed}")
        print(f"  Unresolved Columns ({len(unresolved)}): {unresolved}")
        if review_needed:
            print(f"  Simulated Correction: {corrected_fields_list or 'Verified Existing Mappings'}")
            print(f"  Post-Correction: [{post_status}] {post_conf:.1f}% | Action: {profile_action}")

    except Exception as e:
        print(f"  ERROR processing {fname}: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 135)
print(f"{'Filename':<25} | {'Supplier':<18} | {'Orig Dec':<12} | {'Orig Conf':<9} | {'Review?':<7} | {'Post Val':<20} | {'Post Conf':<9} | {'Profile Action':<22}")
print("-" * 135)
for r in results:
    print(f"{r['filename']:<25} | {r['supplier']:<18} | {r['orig_decision']:<12} | {r['orig_conf']:<9} | {r['review_required']:<7} | {r['post_val']:<20} | {r['post_conf']:<9} | {r['profile_action']:<22}")
print("=" * 135)
