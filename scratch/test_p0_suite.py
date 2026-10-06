import os, sys
sys.path.insert(0, os.getcwd())
import json
import pandas as pd
from extractor import (
    ALIAS_DICT,
    compute_row_accounting,
    fix_column_bleeding,
    parse_compound_qty,
    standardize_date,
    _normalize_cell,
    _normalize_row,
    _merge_continuation_rows,
    _to_float,
    extract_pdf_table,
)
import app

def test_all():
    print("=== TEST 1: ALIAS_DICT MRP ALIASES ===")
    mrp_aliases = ALIAS_DICT["mrp"]
    print("mrp aliases:", mrp_aliases)
    assert "m r p" in mrp_aliases, "'m r p' missing"
    assert "m.r.p." in mrp_aliases, "'m.r.p.' missing"
    print("PASSED: MRP aliases independently present!")

    print("\n=== TEST 2: TEMPLATES.JSON VALIDITY & 36CGBPA3297A1ZW ===")
    with open("templates.json", "r") as f:
        tpls = json.load(f)
    assert "36CGBPA3297A1ZW" in tpls
    assert tpls["36CGBPA3297A1ZW"]["Net Amount"] == "netAmount"
    print("PASSED: templates.json valid and Net Amount correctly mapped to netAmount!")

    print("\n=== TEST 3A: MULTI-LINE PRODUCT NAME ===")
    cell = "Augmentin 625 Duo\nTablet"
    norm = _normalize_cell(cell, is_item_name=True)
    print("Normalized multi-line item name:", norm)
    assert norm == "Augmentin 625 Duo Tablet"

    # Row normalization with item_idx
    row = ["1", "Augmentin 625 Duo\nTablet", "BATCH01", "10.00\n20.00"]
    norm_row = _normalize_row(row, item_idx=1)
    print("Normalized row:", norm_row)
    assert norm_row[1] == "Augmentin 625 Duo Tablet"
    assert norm_row[3] == "10.00"  # non-item cell only takes line 1 when not join_lines
    print("PASSED: Multi-line product name preserved!")

    print("\n=== TEST 3B: CONTINUATION ROW MERGE FOR PRODUCT NAME ===")
    rows = [
        ["1", "Augmentin 625 Duo", "BATCH01", "11/26", "10", "100.00"],
        ["", "Tablet 10s Strip", "", "", "", ""],
    ]
    merged = _merge_continuation_rows(rows, item_idx=1)
    print("Merged rows:", merged)
    assert "Augmentin 625 Duo Tablet 10s Strip" in merged[0][1]
    print("PASSED: Continuation row merged into product name!")

    print("\n=== TEST 4B: COMPOUND QUANTITY 10+2 ===")
    billed, free = parse_compound_qty("10+2")
    print("10+2 -> billed:", billed, "free:", free)
    assert billed == 10.0 and free == 2.0
    print("PASSED: Compound quantity 10+2!")

    print("\n=== TEST 4C: DECIMAL COMPOUND QUANTITY 2.500+.500 ===")
    billed, free = parse_compound_qty("2.500+.500")
    print("2.500+.500 -> billed:", billed, "free:", free)
    assert billed == 2.5 and free == 0.5
    print("PASSED: Decimal compound quantity 2.500+.500!")

    print("\n=== TEST 4D: MERGED NUMERIC CELL '159.00 121.14' ===")
    bleeding_row = {"mrp": "159.00 121.14", "rate": None}
    fixed = fix_column_bleeding(bleeding_row)
    print("Fixed bleeding row:", fixed)
    assert fixed["mrp"] == "159.00" and fixed["rate"] == "121.14"
    print("PASSED: Merged numeric cell split successfully!")

    print("\n=== TEST 4E: AMOUNT MISMATCH VALIDATION & PRESERVATION ===")
    # Extracted amount 1510.65 != qty 10 * rate 167.85 (=1678.50)
    mismatch_row = {
        "quantity": 10.0,
        "rate": 167.85,
        "amount": 1510.65,
        "discountPercent": 0.0,
        "gstPercent": 12.0,
    }
    accounted = compute_row_accounting(mismatch_row)
    print("Accounted row with mismatch:", accounted)
    # Extracted amount MUST be preserved
    assert accounted["amount"] == 1510.65, "Extracted amount was overwritten!"
    assert "validation_discrepancies" in accounted
    discrepancies = accounted["validation_discrepancies"]
    assert any(d["field"] == "amount" and d["status"] == "MISMATCH" for d in discrepancies)
    print("PASSED: Extracted amount preserved and discrepancy recorded!")

    print("\n=== TEST 4F: MISSING FINANCIAL VALUE (DERIVATION) ===")
    missing_row = {
        "quantity": 5.0,
        "rate": 200.0,
        "amount": None,  # Missing
        "discountPercent": 10.0,
        "gstPercent": 18.0,
        "taxableAmount": None,
        "netAmount": None,
    }
    derived = compute_row_accounting(missing_row)
    print("Derived row:", derived)
    assert derived["amount"] == 1000.0  # 5 * 200
    assert derived["taxableAmount"] == 900.0  # 1000 * 0.9
    assert derived["netAmount"] == 1062.0  # 900 * 1.18
    print("PASSED: Missing financial values derived accurately!")

    print("\n=== TEST 4G: EXPLICIT ZERO FINANCIAL VALUE ===")
    zero_row = {
        "quantity": 10.0,
        "rate": 0.0,  # Explicit free sample
        "amount": 0.0,
        "discountPercent": 0.0,
        "gstPercent": 0.0,
        "taxableAmount": 0.0,
        "netAmount": 0.0,
    }
    zero_accounted = compute_row_accounting(zero_row)
    print("Zero accounted row:", zero_accounted)
    assert zero_accounted["rate"] == 0.0
    assert zero_accounted["amount"] == 0.0
    assert zero_accounted["netAmount"] == 0.0
    assert not zero_accounted.get("validation_discrepancies")
    print("PASSED: Explicit zero preserved cleanly!")

    print("\n=== TEST 4H: CGST + SGST INVOICE ===")
    cgst_sgst_row = {
        "quantity": 10.0,
        "rate": 50.0,
        "amount": 500.0,
        "discountPercent": 0.0,
        "taxableAmount": 500.0,
        "cgstPercent": 6.0,
        "sgstPercent": 6.0,
        "gstPercent": None,  # Total GST missing
    }
    cgst_accounted = compute_row_accounting(cgst_sgst_row)
    print("CGST+SGST accounted row:", cgst_accounted)
    assert cgst_accounted["gstPercent"] == 12.0
    assert cgst_accounted["cgstPercent"] == 6.0
    assert cgst_accounted["sgstPercent"] == 6.0
    assert cgst_accounted["netAmount"] == 560.0
    print("PASSED: CGST + SGST handled and total GST derived!")

    print("\n=== TEST 4I: INVOICE WITH ONLY GST/IGST ===")
    igst_row = {
        "quantity": 10.0,
        "rate": 50.0,
        "amount": 500.0,
        "discountPercent": 0.0,
        "taxableAmount": 500.0,
        "gstPercent": 18.0,
        "cgstPercent": None,
        "sgstPercent": None,
    }
    igst_accounted = compute_row_accounting(igst_row)
    print("Flat GST / IGST accounted row:", igst_accounted)
    assert igst_accounted["gstPercent"] == 18.0
    # CGST and SGST should NOT be artificially invented as 9.0 and 9.0!
    assert igst_accounted.get("cgstPercent") is None or igst_accounted.get("cgstPercent") == 0
    assert igst_accounted["netAmount"] == 590.0
    print("PASSED: Flat GST/IGST preserved without artificial CGST/SGST split!")

    print("\n=== TEST 4J: DUPLICATE LEGITIMATE PRODUCT LINES IN DATAFRAME ===")
    headers = ["Product Name", "Pack", "Batch", "Exp", "Qty", "Rate", "Amount"]
    rows = [
        ["Paracetamol 650mg Tab", "10s", "BATCH99", "12/26", "10", "20.00", "200.00"],
        ["Paracetamol 650mg Tab", "10s", "BATCH99", "12/26", "10", "20.00", "200.00"],  # Exact same SKU billed twice
        ["Amoxicillin 500mg Cap", "10s", "BATCH88", "10/26", "5", "50.00", "250.00"],
    ]
    mappings = {
        "Product Name": "itemName",
        "Pack": "pack",
        "Batch": "batchNo",
        "Exp": "expiryDate",
        "Qty": "quantity",
        "Rate": "rate",
        "Amount": "amount",
    }
    df = app.build_clean_dataframe(headers, rows, mappings)
    print("DataFrame rows:", len(df))
    print(df[["itemName", "batchNo", "quantity", "rate", "amount"]])
    assert len(df) == 3, f"Expected 3 rows, got {len(df)} (duplicate was deleted!)"
    print("PASSED: Duplicate product lines preserved!")

    print("\nALL UNIT & INTEGRATION CHECKS PASSED!")

if __name__ == "__main__":
    test_all()
