"""
Unit tests for MediAstra Phase 1:
- Pharma Scheme Normalizer & Robust Quantity Parser
- Candidate-Based Accounting Constraint Solver
"""

import pytest
from extractor import (
    normalize_scheme_text,
    tokenize_compound_quantity,
    parse_compound_qty,
    parse_quantity_scheme,
    normalize_quantity_value,
    solve_row_accounting_constraints,
    compute_row_accounting,
    validate_cross_field_accounting,
)


# =============================================================================
# 1. Scheme Normalizer & Compound Quantity Tokenizer Tests
# =============================================================================

def test_standard_schemes():
    """Test classic integer promotional schemes (e.g. 10+2, 4+1, 23+2)."""
    assert parse_compound_qty("10+2") == (10.0, 2.0)
    assert parse_compound_qty("4+1") == (4.0, 1.0)
    assert parse_compound_qty("23+2") == (23.0, 2.0)
    assert parse_compound_qty("1+0") == (1.0, 0.0)
    assert parse_compound_qty("0+2") == (0.0, 2.0)


def test_fractional_schemes_mohit_style():
    """Test fractional and decimal schemes from Mohit Pharma style invoices."""
    # 9.50+.50 -> 9.50 billed, 0.50 free
    billed, free, meta = parse_quantity_scheme("9.50+.50")
    assert billed == 9.50
    assert free == 0.50
    assert meta["is_compound"] is True

    # 5.40+.60 -> 5.40 billed, 0.60 free
    billed, free, meta = parse_quantity_scheme("5.40+.60")
    assert billed == 5.40
    assert free == 0.60

    # 2.50+.50
    billed, free, meta = parse_quantity_scheme("2.50+.50")
    assert billed == 2.50
    assert free == 0.50

    # 2.500+.500
    billed, free, meta = parse_quantity_scheme("2.500+.500")
    assert billed == 2.50
    assert free == 0.50

    # .500+.250
    billed, free, meta = parse_quantity_scheme(".500+.250")
    assert billed == 0.50
    assert free == 0.25


def test_schemes_with_whitespace_and_units():
    """Test schemes with spaces, tabs, and unit suffixes."""
    # Whitespace around operators
    assert parse_compound_qty("10 + 2") == (10.0, 2.0)
    assert parse_compound_qty("9.50 + .50") == (9.50, 0.50)
    assert parse_compound_qty("  4 + 1  ") == (4.0, 1.0)

    # Unit suffixes (Nos, TAB, 'S)
    assert parse_compound_qty("10+2 Nos") == (10.0, 2.0)
    assert parse_compound_qty("10+2 NOS.") == (10.0, 2.0)
    assert parse_compound_qty("4+1'S") == (4.0, 1.0)
    assert parse_compound_qty("10 + 2 TAB") == (10.0, 2.0)


def test_free_only_schemes():
    """Test free-only tokens like +2, + 2, +.50."""
    billed, free, meta = parse_quantity_scheme("+2")
    assert billed == 0.0
    assert free == 2.0
    assert meta["is_compound"] is True

    billed, free, meta = parse_quantity_scheme("+.50")
    assert billed == 0.0
    assert free == 0.50


def test_ocr_character_repair_in_schemes():
    """Test OCR letter confusion repair within numeric scheme patterns."""
    # Letter 'O' / 'o' instead of '0'
    assert parse_compound_qty("10+O") == (10.0, 0.0)
    assert parse_compound_qty("O+2") == (0.0, 2.0)
    assert parse_compound_qty("9.5O+.5O") == (9.50, 0.50)

    # Letter 'l' or 'I' instead of '1'
    assert parse_compound_qty("4+l") == (4.0, 1.0)
    assert parse_compound_qty("l0+2") == (10.0, 2.0)

    # Letter 'Z' / 'z' instead of '2'
    assert parse_compound_qty("10+Z") == (10.0, 2.0)


def test_reject_non_numeric_and_malformed_expressions():
    """Test that text strings with plus or invalid characters are safely rejected."""
    tok = tokenize_compound_quantity("ASTYMIN+FORTE")
    assert tok["is_compound"] is False

    tok = tokenize_compound_quantity("10+ABC")
    assert tok["is_compound"] is False

    tok = tokenize_compound_quantity("++")
    assert tok["is_compound"] is False

    tok = tokenize_compound_quantity("+")
    assert tok["is_compound"] is False


def test_normalize_quantity_value():
    """Test normalize_quantity_value helper with various clean and dirty inputs."""
    assert normalize_quantity_value("6.500") == 6.5
    assert normalize_quantity_value("2.00") == 2
    assert normalize_quantity_value(".500") == 0.5
    assert normalize_quantity_value("10+2", is_free=False) == 10
    assert normalize_quantity_value("10+2", is_free=True) == 2
    assert normalize_quantity_value("9.50+.50", is_free=False) == 9.5
    assert normalize_quantity_value("9.50+.50", is_free=True) == 0.5


# =============================================================================
# 2. Candidate-Based Accounting Constraint Solver Tests
# =============================================================================

def test_mohit_pharma_gross_line_amount():
    """
    Test Mohit Pharma invoice Row 1:
    - Qty = 10, Rate = 88.80, Dis = 10.00, SGST = 2.50, CGST = 2.50, Amount = 888.00
    - Amount is GROSS (10 * 88.80 = 888.00).
    """
    row = {
        "itemName": "AMARYL 1 MG TABLET",
        "quantity": "10",
        "rate": "88.80",
        "discountPercent": "10.00",
        "cgstPercent": "2.50",
        "sgstPercent": "2.50",
        "amount": "888.00",
    }
    result = compute_row_accounting(row)

    assert result["quantity"] == 10.0
    assert result["rate"] == 88.80
    assert result["amount"] == 888.00
    assert result["discountPercent"] == 10.00
    assert result["gstPercent"] == 5.00
    assert result["taxableAmount"] == 799.20
    assert result["netAmount"] == 839.16

    proof = result.get("_accounting_proof", {})
    assert proof.get("detected_amount_semantics") == "GROSS"
    assert proof.get("accounting_status") in ("EXACT_MATCH", "ROUNDING_DIFF")
    assert proof.get("accounting_confidence", 0) >= 0.95


def test_mohit_pharma_scheme_row():
    """
    Test Mohit Pharma invoice Row 4 (ATOCOR 10MG TAB):
    - Qty = 9.50+.50, Rate = 60.62, Dis = 12.00, SGST = 2.50, CGST = 2.50, Amount = 575.89
    - Billed Qty = 9.50, Free Qty = 0.50
    - Gross = 9.50 * 60.62 = 575.89
    """
    row = {
        "itemName": "ATOCOR 10MG TAB.",
        "quantity": "9.50+.50",
        "rate": "60.62",
        "discountPercent": "12.00",
        "cgstPercent": "2.50",
        "sgstPercent": "2.50",
        "amount": "575.89",
    }
    result = compute_row_accounting(row)

    assert result["quantity"] == 9.50
    assert result["freeQuantity"] == 0.50
    assert result["rate"] == 60.62
    assert result["amount"] == 575.89
    assert result["taxableAmount"] == 506.78
    assert result["netAmount"] == 532.12

    proof = result.get("_accounting_proof", {})
    assert proof.get("detected_amount_semantics") == "GROSS"
    assert proof.get("accounting_confidence", 0) >= 0.95


def test_taxable_as_displayed_amount():
    """
    Test invoice where displayed Amount is Taxable (Amount = Gross - Discount).
    - Qty = 10, Rate = 100.00, Discount = 10.00%, Amount = 900.00, GST = 5.00%
    """
    row = {
        "quantity": "10",
        "rate": "100.00",
        "discountPercent": "10.00",
        "gstPercent": "5.00",
        "amount": "900.00",
    }
    result = compute_row_accounting(row)

    assert result["amount"] == 900.00
    assert result["taxableAmount"] == 900.00
    assert result["netAmount"] == 945.00
    proof = result.get("_accounting_proof", {})
    assert proof.get("detected_amount_semantics") == "TAXABLE_PRE_GST"


def test_net_post_gst_as_displayed_amount():
    """
    Test invoice where displayed Amount is GST-inclusive Net (Taxable + GST).
    - Qty = 10, Rate = 100.00, Discount = 0, GST = 18.00%, Amount = 1180.00
    """
    row = {
        "quantity": "10",
        "rate": "100.00",
        "discountPercent": "0",
        "gstPercent": "18.00",
        "amount": "1180.00",
    }
    result = compute_row_accounting(row)

    assert result["amount"] == 1180.00
    assert result["taxableAmount"] == 1000.00
    assert result["netAmount"] == 1180.00
    proof = result.get("_accounting_proof", {})
    assert proof.get("detected_amount_semantics") == "NET_POST_GST"


def test_solve_missing_rate_from_amount_and_qty():
    """Test solving missing rate when amount and quantity are present."""
    row = {
        "quantity": "10",
        "rate": None,
        "amount": "888.00",
        "discountPercent": "10.00",
    }
    result = compute_row_accounting(row)

    assert result["rate"] == 88.80
    assert result["amount"] == 888.00


def test_flag_mathematical_mismatch():
    """Test flagging severe OCR errors with low confidence and clear mismatch status."""
    row = {
        "quantity": "10",
        "rate": "88.80",
        "amount": "8880.00",  # Extra zero from OCR noise
        "discountPercent": "0",
    }
    result = compute_row_accounting(row)

    proof = result.get("_accounting_proof", {})
    assert proof.get("accounting_status") == "MATHEMATICAL_MISMATCH"
    assert proof.get("accounting_confidence", 1.0) < 0.70
    assert len(result.get("validation_discrepancies", [])) > 0
