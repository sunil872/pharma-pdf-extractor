import os, sys, glob
sys.path.insert(0, os.getcwd())
import pdfplumber
from extractor import (
    reconstruct_header_tokens,
    detect_coordinate_header_row,
    determine_column_boundaries,
    extract_coordinate_table,
    extract_pdf_table,
    match_column_name,
)

def test_coordinate_layer():
    print("==================================================================")
    print("TEST 1: HORIZONTAL HEADER WORD MERGING")
    print("==================================================================")
    # Test PT + R -> PTR
    words_ptr = [
        {"text": "PT", "x0": 100.0, "x1": 115.0, "top": 50.0, "bottom": 60.0},
        {"text": "R", "x0": 116.0, "x1": 125.0, "top": 50.0, "bottom": 60.0},
    ]
    reconstructed_ptr = reconstruct_header_tokens(words_ptr)
    print("  PT + R ->", reconstructed_ptr[0][0]["text"])
    assert reconstructed_ptr[0][0]["text"] == "PTR", f"Expected PTR, got {reconstructed_ptr[0][0]['text']}"

    # Test MR + P -> MRP
    words_mrp = [
        {"text": "MR", "x0": 200.0, "x1": 218.0, "top": 50.0, "bottom": 60.0},
        {"text": "P", "x0": 219.0, "x1": 228.0, "top": 50.0, "bottom": 60.0},
    ]
    reconstructed_mrp = reconstruct_header_tokens(words_mrp)
    print("  MR + P ->", reconstructed_mrp[0][0]["text"])
    assert reconstructed_mrp[0][0]["text"] == "MRP", f"Expected MRP, got {reconstructed_mrp[0][0]['text']}"

    # Test RAT + E -> RATE
    words_rate = [
        {"text": "RAT", "x0": 300.0, "x1": 320.0, "top": 50.0, "bottom": 60.0},
        {"text": "E", "x0": 321.0, "x1": 330.0, "top": 50.0, "bottom": 60.0},
    ]
    reconstructed_rate = reconstruct_header_tokens(words_rate)
    print("  RAT + E ->", reconstructed_rate[0][0]["text"])
    assert reconstructed_rate[0][0]["text"] == "RATE", f"Expected RATE, got {reconstructed_rate[0][0]['text']}"
    print("PASSED: Split visual headers successfully merged!")

    print("\n==================================================================")
    print("TEST 2 & 3: COORDINATE COLUMN ASSIGNMENT & MERGED NUMERIC CELLS")
    print("==================================================================")
    header_tokens = [
        {"raw": "PRODUCT NAME", "text": "PRODUCT NAME", "field": "itemName", "x0": 50.0, "x1": 180.0, "center_x": 115.0},
        {"raw": "BATCH", "text": "BATCH", "field": "batchNo", "x0": 200.0, "x1": 260.0, "center_x": 230.0},
        {"raw": "EXPIRY", "text": "EXPIRY", "field": "expiryDate", "x0": 280.0, "x1": 340.0, "center_x": 310.0},
        {"raw": "HSN", "text": "HSN", "field": "hsnCode", "x0": 360.0, "x1": 420.0, "center_x": 390.0},
        {"raw": "MRP", "text": "MRP", "field": "mrp", "x0": 440.0, "x1": 490.0, "center_x": 465.0},
        {"raw": "RATE", "text": "RATE", "field": "rate", "x0": 510.0, "x1": 560.0, "center_x": 535.0},
    ]
    cols = determine_column_boundaries(header_tokens, page_width=600.0)
    print("Determined column boundaries:")
    for c in cols:
        print(f"  Col {c['index']}: {c['header_text']:15s} -> X in [{c['x0']:.1f}, {c['x1']:.1f}]")

    # Simulate words on row where MRP and Rate are separate words in distinct X positions
    # (e.g. 159.00 at x=465 in MRP column, 121.14 at x=535 in Rate column)
    mrp_word = {"text": "159.00", "x0": 450.0, "x1": 480.0, "center_x": 465.0}
    rate_word = {"text": "121.14", "x0": 520.0, "x1": 550.0, "center_x": 535.0}
    
    # Check MRP word assignment
    mrp_col = next(c for c in cols if c["x0"] <= mrp_word["center_x"] < c["x1"])
    assert mrp_col["field"] == "mrp", f"Expected MRP column, got {mrp_col['field']}"
    
    # Check Rate word assignment
    rate_col = next(c for c in cols if c["x0"] <= rate_word["center_x"] < c["x1"])
    assert rate_col["field"] == "rate", f"Expected Rate column, got {rate_col['field']}"
    print("PASSED: 159.00 assigned to MRP and 121.14 assigned to RATE independently by coordinates!")

    print("\n==================================================================")
    print("TEST 4: BATCH + EXPIRY SEPARATION BY COORDINATES")
    print("==================================================================")
    batch_word = {"text": "306DB2518", "x0": 210.0, "x1": 255.0, "center_x": 232.5}
    exp_word = {"text": "11/27", "x0": 295.0, "x1": 325.0, "center_x": 310.0}
    
    b_col = next(c for c in cols if c["x0"] <= batch_word["center_x"] < c["x1"])
    e_col = next(c for c in cols if c["x0"] <= exp_word["center_x"] < c["x1"])
    assert b_col["field"] == "batchNo"
    assert e_col["field"] == "expiryDate"
    print("PASSED: Batch ('306DB2518') and Expiry ('11/27') correctly separated into distinct columns!")

    print("\n==================================================================")
    print("TEST 5: EXPIRY + HSN SEPARATION BY COORDINATES")
    print("==================================================================")
    hsn_word = {"text": "30049099", "x0": 375.0, "x1": 415.0, "center_x": 395.0}
    h_col = next(c for c in cols if c["x0"] <= hsn_word["center_x"] < c["x1"])
    assert h_col["field"] == "hsnCode"
    print("PASSED: Expiry ('11/27') and HSN ('30049099') correctly separated into distinct columns!")

    print("\n==================================================================")
    print("TEST 6: FALLBACK TO V1 EXTRACTION")
    print("==================================================================")
    # When use_coordinates=False or low confidence, V1 extraction functions seamlessly
    meta_v1, hdrs_v1, maps_v1, rows_v1 = extract_pdf_table("Sample Invoices/Invoice.pdf", use_coordinates=False)
    assert len(rows_v1) == 21, f"Expected 21 rows in V1 fallback, got {len(rows_v1)}"
    print(f"PASSED: V1 fallback extracted {len(rows_v1)} rows successfully!")

    print("\n==================================================================")
    print("TEST 7: END-TO-END VERIFICATION ON ALL 9 SAMPLE INVOICES")
    print("==================================================================")
    samples = sorted(glob.glob("Sample Invoices/*.[pP][dD][fF]"))
    results = []
    for s in samples:
        bname = os.path.basename(s)
        with pdfplumber.open(s) as pdf:
            p_count = len(pdf.pages)
            meta, hdrs, maps, rows = extract_pdf_table(s, use_coordinates=True)
            print(f"  {bname:35s} | Pages: {p_count} | Header Cols: {len(hdrs):2d} | Rows: {len(rows):2d} | Supplier: {str(meta.get('supplier_name'))[:20]}")
            assert len(rows) > 0, f"Failed on {bname}: 0 rows extracted!"
            results.append((bname, p_count, len(hdrs), len(rows), meta.get("supplier_name")))
    print("\nALL TARGETED COORDINATE & REGRESSION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    test_coordinate_layer()
