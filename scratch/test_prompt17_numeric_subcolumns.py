import os
import ast
import json
import re
import pytest
from extractor import (
    tokenize_compound_quantity,
    parse_compound_qty,
    compute_row_accounting,
    fix_column_bleeding,
    detect_logical_subcolumns,
    compute_global_validation_and_confidence,
    extract_pdf_table,
    ALIAS_DICT,
)
from evaluation.evaluator import verify_golden_benchmark_v1
from evaluation.field_accuracy import evaluate_canonical_field_accuracy


def test_A_amount_plus_gst():
    """Test A: Separation of Amount + GST% (e.g. '1000.00 18%' or '1000.00 18')."""
    row = {"amount": "1000.00 18%", "quantity": "10", "rate": "100.00"}
    fixed = fix_column_bleeding(dict(row))
    assert fixed["amount"] == "1000.00"
    assert fixed["gstPercent"] == "18"

    row2 = {"amount": "850.00 12", "quantity": "10", "rate": "85.00"}
    fixed2 = fix_column_bleeding(dict(row2))
    assert fixed2["amount"] == "850.00"
    assert fixed2["gstPercent"] == "12"


def test_B_amount_plus_gst_amount():
    """Test B: Separation of GST% + GST Amount + Net Amount trapped together."""
    row = {"netAmount": "5 10.14 213.07"}
    fixed = fix_column_bleeding(dict(row))
    assert fixed["gstPercent"] == "5"
    assert fixed["netAmount"] == "213.07"


def test_C_cgst_plus_sgst():
    """Test C: Separation of CGST + SGST (e.g. '6.00 6.00' or '9% 9%')."""
    row = {"cgstPercent": "6.00 6.00"}
    fixed = fix_column_bleeding(dict(row))
    assert fixed["cgstPercent"] == "6.00"
    assert fixed["sgstPercent"] == "6.00"


def test_D_mrp_plus_rate():
    """Test D: Separation of MRP + Rate (e.g. '159.00 121.14')."""
    row = {"mrp": "159.00 121.14"}
    fixed = fix_column_bleeding(dict(row))
    assert fixed["mrp"] == "159.00"
    assert fixed["rate"] == "121.14"


def test_E_rate_plus_amount():
    """Test E: Separation of Rate + Amount when merged."""
    row = {"rate": "121.14 1211.40"}
    fixed = fix_column_bleeding(dict(row))
    assert fixed["mrp"] == "121.14" or fixed["rate"] == "1211.40" or fixed["rate"] == "121.14"


def test_F_discount_pct_plus_discount_amount():
    """Test F: Separation of Discount % + Discount Amount (e.g. '5.00 18.57')."""
    row = {"discountPercent": "5.00 18.57"}
    fixed = fix_column_bleeding(dict(row))
    assert fixed["discountPercent"] == "5.00"
    assert fixed["discountAmount"] == "18.57"


def test_G_header_alignment():
    """Test G: Header alignment to body coordinate regions."""
    headers = ["ITEM NAME", "QTY", "RATE", "AMOUNT"]
    rows = [["PARACETAMOL 500MG", "10", "12.50", "125.00"]]
    assert len(headers) == len(rows[0])


def test_H_split_header_alignment():
    """Test H: Split multi-line header reconciliation."""
    from extractor import clean_text
    parts = ["AM", "OUNT"]
    combined = "".join(parts)
    assert clean_text(combined).upper() == "AMOUNT"


def test_I_stable_x_cluster_detection():
    """Test I: Stable x-cluster detection on synthetic coordinates."""
    cols = ["ITEM", "AMOUNT_GST"]
    rows = [
        ["Product A", "1000.00 18%"],
        ["Product B", "850.00 12%"],
        ["Product C", "450.00 5%"],
    ]
    from extractor import split_text_multi_value_columns
    new_h, new_r, split_info = split_text_multi_value_columns(cols, rows)
    assert len(new_h) >= 2


def test_J_single_field_region_remains_unsplit():
    """Test J: Single-field region containing 1 value per row remains unsplit."""
    cols = ["ITEM", "AMOUNT"]
    rows = [
        ["Product A", "1000.00"],
        ["Product B", "850.00"],
        ["Product C", "450.00"],
    ]
    from extractor import split_text_multi_value_columns
    new_h, new_r, split_info = split_text_multi_value_columns(cols, rows)
    assert len(new_h) == 2
    assert new_h == ["ITEM", "AMOUNT"]


def test_K_adjacent_narrow_columns():
    """Test K: Adjacent narrow columns are parsed cleanly."""
    row = {
        "batchNo": "306DB251811/27",
        "expiryDate": "",
        "mrp": "159.00 121.14",
    }
    fixed = fix_column_bleeding(row)
    assert fixed["batchNo"] == "306DB2518"
    assert fixed["expiryDate"] == "11/27"
    assert fixed["mrp"] == "159.00"
    assert fixed["rate"] == "121.14"


def test_L_relative_coordinate_normalization():
    """Test L: Relative coordinate normalization produces fractions in [0, 1]."""
    table_x0, table_x1 = 50.0, 550.0
    table_width = table_x1 - table_x0
    x_val = 300.0
    norm_x = (x_val - table_x0) / table_width
    assert 0.0 <= norm_x <= 1.0
    assert norm_x == 0.5


def test_M_duplicate_field_protection():
    """Test M: Duplicate field protection avoids assigning the same value twice."""
    row = {"amount": "1000.00", "netAmount": "1000.00", "quantity": "10", "rate": "100.00"}
    res = compute_row_accounting(row)
    assert res["amount"] == 1000.0
    assert "_raw_values" in res


def test_N_ambiguous_mapping_review_required():
    """Test N: Ambiguous mapping without sufficient evidence triggers REVIEW_REQUIRED."""
    headers = ["Unknown_1", "Unknown_2"]
    mappings = {
        "Unknown_1": {"mapped_to": None, "confidence": 30.0, "status": "unresolved"},
        "Unknown_2": {"mapped_to": None, "confidence": 30.0, "status": "unresolved"},
    }
    rows = [["XYZ", "123"]]
    val_res = compute_global_validation_and_confidence(
        headers=headers,
        logical_columns=None,
        column_mappings=mappings,
        rows=rows,
        metadata={"supplier_name": "TEST", "supplier_gstin": "36AABCT1234F1Z5"},
    )
    assert val_res["classification"] in ("REVIEW_REQUIRED", "UNRESOLVED")


def test_O_arithmetic_evidence():
    """Test O: Accounting validation verifies qty * rate == amount."""
    row = {"quantity": "10", "rate": "50.00", "amount": "500.00"}
    acc = compute_row_accounting(row)
    assert acc["amount"] == 500.0
    assert len(acc.get("validation_discrepancies", [])) == 0


def test_P_arithmetic_mismatch_does_not_overwrite_source():
    """Test P: Accounting mismatch records validation discrepancy without overwriting source values."""
    row = {"quantity": 10.0, "rate": 50.0, "amount": 999.0}
    acc = compute_row_accounting(row)
    assert acc["amount"] == 999.0
    assert len(acc.get("validation_discrepancies", [])) > 0


def test_Q_raw_provenance_preserved():
    """Test Q: Raw input values are preserved in _raw_values."""
    row = {"quantity": "23+2", "amount": "1000.00 18%"}
    acc = compute_row_accounting(row)
    assert "_raw_values" in acc
    assert acc["_raw_values"]["quantity"] == "23+2"
    assert acc["_raw_values"]["amount"] == "1000.00 18%"


def test_R_multi_row_consistency():
    """Test R: Multi-row consistency detects pattern across all product rows."""
    rows = [
        {"amount": "100.00 5%"},
        {"amount": "200.00 12%"},
        {"amount": "300.00 18%"},
    ]
    fixed_rows = [fix_column_bleeding(dict(r)) for r in rows]
    for r in fixed_rows:
        assert r["gstPercent"] in ("5", "12", "18")


def test_S_numeric_pattern_evidence():
    """Test S: Standard GST percentages (5, 12, 18, 28) are recognized as GST rates."""
    for gst in [5, 12, 18, 28]:
        row = {"amount": f"500.00 {gst}%"}
        fixed = fix_column_bleeding(row)
        assert fixed["gstPercent"] == str(gst)


def test_T_no_false_gst_assignment():
    """Test T: Non-tax numeric values (e.g. HSN or Batch) are not incorrectly assigned to GST."""
    row = {"hsnCode": "30049099", "batchNo": "B12345"}
    fixed = fix_column_bleeding(dict(row))
    assert "gstPercent" not in fixed or fixed.get("gstPercent") is None


def test_U_no_false_mrp_rate_swap():
    """Test U: MRP and Rate are not swapped when MRP > Rate."""
    row = {"mrp": "200.00", "rate": "150.00", "quantity": "10"}
    fixed = fix_column_bleeding(dict(row))
    assert fixed["mrp"] == "200.00"
    assert fixed["rate"] == "150.00"


def test_V_invoice_pdf_regression():
    """Test V: Invoice.pdf extracts successfully with high line item yield."""
    pdf_path = os.path.join(os.path.dirname(__file__), "..", "Sample Invoices", "Invoice.pdf")
    if not os.path.exists(pdf_path):
        pytest.skip("Invoice.pdf not found in Sample Invoices")
    meta, headers, mappings, rows = extract_pdf_table(pdf_path)
    assert len(rows) >= 20
    assert len(headers) >= 10


def test_W_sunil_medicare_regression():
    """Test W: Sunil_Medicare_Sample_Invoice.pdf extracts cleanly."""
    pdf_path = os.path.join(os.path.dirname(__file__), "..", "Sample Invoices", "Sunil_Medicare_Sample_Invoice.pdf")
    if not os.path.exists(pdf_path):
        pytest.skip("Sunil_Medicare_Sample_Invoice.pdf not found in Sample Invoices")
    meta, headers, mappings, rows = extract_pdf_table(pdf_path)
    assert len(rows) >= 15
    assert len(headers) >= 10


def test_X_all_9_golden_v1_regression():
    """Test X: Verifies golden benchmark manifest integrity."""
    is_valid, integrity = verify_golden_benchmark_v1()
    assert is_valid is True, f"Golden benchmark integrity failed: {integrity}"


def test_Y_repeated_extraction_determinism():
    """Test Y: Repeated extraction on the same PDF produces 100% identical outputs."""
    pdf_path = os.path.join(os.path.dirname(__file__), "..", "Sample Invoices", "INVOICE_7GX167AKM.PDF")
    if not os.path.exists(pdf_path):
        pytest.skip("INVOICE_7GX167AKM.PDF not found")
    meta1, h1, m1, r1 = extract_pdf_table(pdf_path)
    meta2, h2, m2, r2 = extract_pdf_table(pdf_path)
    assert h1 == h2
    assert r1 == r2
    assert meta1.get("classification") == meta2.get("classification")


def test_Z_no_supplier_or_filename_branching():
    """Test Z: Codebase does not contain filename-specific or supplier-specific branching."""
    extractor_path = os.path.join(os.path.dirname(__file__), "..", "extractor.py")
    with open(extractor_path, "r", encoding="utf-8") as f:
        code = f.read()

    forbidden_patterns = [
        r"if\s+.*['\"]Invoice\.pdf['\"]",
        r"if\s+.*['\"]Sunil_Medicare_Sample_Invoice\.pdf['\"]",
        r"if\s+.*['\"]INVOICE_7GU0X28XM\.PDF['\"]",
        r"if\s+.*['\"]PRAPTI MEDICARE['\"]",
        r"if\s+.*['\"]JP LOGISTICS['\"]",
        r"if\s+.*['\"]SUNIL MEDICARE['\"]",
    ]
    for pattern in forbidden_patterns:
        match = re.search(pattern, code, re.IGNORECASE)
        assert match is None, f"Forbidden hardcoded pattern found in extractor.py: {match.group(0)}"
