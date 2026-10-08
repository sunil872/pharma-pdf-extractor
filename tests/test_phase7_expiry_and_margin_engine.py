"""
Unit and Integration Tests for MediAstra Phase 7:
- Advanced Multi-Format Expiry Date Normalizer (standardize_pharma_expiry_date)
- Near-Expiry & Short-Expiry Purchase Sentinel (analyze_expiry_shelf_life)
- Retail Pharmacy Margin & Purchase Price Variance (PPV) Solver (compute_purchase_margin_and_ppv)
- Integrated Row Accounting & Shelf-Life Proof
"""

import pytest
from datetime import datetime
from extractor import (
    standardize_pharma_expiry_date,
    standardize_date,
    analyze_expiry_shelf_life,
    compute_purchase_margin_and_ppv,
    solve_row_accounting_constraints,
)


def test_expiry_normalizer_numeric_formats():
    """Test standard and edge-case numerical date expressions."""
    # 1. MM/YY and MM-YY
    m1, iso1, meta1 = standardize_pharma_expiry_date("12/28")
    assert m1 == "12/2028"
    assert iso1 == "2028-12-31"
    assert meta1["is_valid"] is True

    m2, iso2, meta2 = standardize_pharma_expiry_date("06-27")
    assert m2 == "06/2027"
    assert iso2 == "2027-06-30"

    # 2. Leap year February vs Non-leap year February
    m_leap, iso_leap, _ = standardize_pharma_expiry_date("02/28")
    assert m_leap == "02/2028"
    assert iso_leap == "2028-02-29"  # 2028 is leap year

    m_non_leap, iso_non_leap, _ = standardize_pharma_expiry_date("02/27")
    assert m_non_leap == "02/2027"
    assert iso_non_leap == "2027-02-28"  # 2027 is non-leap year

    # 3. ISO format YYYY-MM
    m_iso, iso_iso, _ = standardize_pharma_expiry_date("2029-08")
    assert m_iso == "08/2029"
    assert iso_iso == "2029-08-31"

    # 4. DD/MM/YYYY
    m_full, iso_full, _ = standardize_pharma_expiry_date("15/09/2028")
    assert m_full == "09/2028"
    assert iso_full == "2028-09-30"

    # 5. Reverse YY/MM format (e.g. 28/11)
    m_rev, iso_rev, _ = standardize_pharma_expiry_date("28/11")
    assert m_rev == "11/2028"
    assert iso_rev == "2028-11-30"


def test_expiry_normalizer_textual_months():
    """Test text-based month tokens in distributor invoices."""
    cases = [
        ("DEC-28", "12/2028", "2028-12-31"),
        ("OCT/2027", "10/2027", "2027-10-31"),
        ("15-MAY-2029", "05/2029", "2029-05-31"),
        ("SEPT-26", "09/2026", "2026-09-30"),
        ("JAN 28", "01/2028", "2028-01-31"),
        ("AUG.2028", "08/2028", "2028-08-31"),
        ("MARCH 2030", "03/2030", "2030-03-31"),
    ]

    for raw, exp_mmyyyy, exp_iso in cases:
        formatted, iso_date, meta = standardize_pharma_expiry_date(raw)
        assert formatted == exp_mmyyyy, f"Failed for {raw}: got {formatted}, expected {exp_mmyyyy}"
        assert iso_date == exp_iso, f"Failed ISO for {raw}: got {iso_date}, expected {exp_iso}"
        assert meta["is_valid"] is True


def test_expiry_normalizer_glued_digits():
    """Test 4-digit and 6-digit compact glued expiry expressions."""
    # MMYY
    m1, _, _ = standardize_pharma_expiry_date("1228")
    assert m1 == "12/2028"

    m2, _, _ = standardize_pharma_expiry_date("0427")
    assert m2 == "04/2027"

    # MMYYYY
    m3, _, _ = standardize_pharma_expiry_date("122028")
    assert m3 == "12/2028"

    # YYYYMM
    m4, _, _ = standardize_pharma_expiry_date("202812")
    assert m4 == "12/2028"


def test_expiry_shelf_life_sentinel():
    """Test expiry risk classification and shelf life calculations."""
    ref_date = "2026-10-01"

    # 1. Expired Medicine (e.g. Expired in Dec 2025)
    res_exp = analyze_expiry_shelf_life("12/2025", reference_date=ref_date)
    assert res_exp["has_valid_expiry"] is True
    assert res_exp["shelf_life_months"] <= 0
    assert res_exp["risk_category"] == "EXPIRED_STOCK"
    assert res_exp["risk_level"] == "CRITICAL"
    assert res_exp["is_short_expiry"] is True

    # 2. Critical Short Expiry (< 3 months, e.g. Dec 2026 -> 2 months)
    res_crit = analyze_expiry_shelf_life("12/2026", reference_date=ref_date)
    assert res_crit["shelf_life_months"] == 2
    assert res_crit["risk_category"] == "CRITICAL_SHORT_EXPIRY"
    assert res_crit["risk_level"] == "HIGH_RISK"
    assert res_crit["is_short_expiry"] is True

    # 3. Short Expiry Warning (3-6 months, e.g. Feb 2027 -> 4 months)
    res_short = analyze_expiry_shelf_life("02/2027", reference_date=ref_date)
    assert res_short["shelf_life_months"] == 4
    assert res_short["risk_category"] == "SHORT_EXPIRY_RISK"
    assert res_short["risk_level"] == "MEDIUM_RISK"
    assert res_short["is_short_expiry"] is True

    # 4. Optimal Shelf Life (>= 12 months, e.g. Dec 2028 -> 26 months)
    res_opt = analyze_expiry_shelf_life("12/2028", reference_date=ref_date)
    assert res_opt["shelf_life_months"] == 26
    assert res_opt["risk_category"] == "OPTIMAL_SHELF_LIFE"
    assert res_opt["risk_level"] == "OPTIMAL"
    assert res_opt["is_short_expiry"] is False


def test_purchase_margin_and_ppv_solver():
    """Test retail margin calculations and price inversion alerts."""
    # 1. Standard DPCO margin (MRP 100, Rate 80 -> 20%)
    m1 = compute_purchase_margin_and_ppv({
        "mrp": 100.0,
        "rate": 80.0,
        "quantity": 10.0,
        "freeQuantity": 0.0,
        "netAmount": 896.0,  # 800 + 12% GST
    })
    assert m1["retail_margin_percent"] == 20.0
    assert m1["margin_classification"] == "STANDARD_RETAIL_MARGIN"
    assert m1["scheme_value_benefit_rs"] == 0.0
    assert m1["effective_cost_per_unit"] == 89.60

    # 2. Scheme Free Goods Valuation (10 + 2 scheme)
    m2 = compute_purchase_margin_and_ppv({
        "mrp": 100.0,
        "rate": 80.0,
        "quantity": 10.0,
        "freeQuantity": 2.0,
        "netAmount": 896.0,
    })
    assert m2["total_units_received"] == 12.0
    assert m2["scheme_value_benefit_rs"] == 160.0  # 2 * 80
    assert m2["effective_cost_per_unit"] == 74.67  # 896 / 12 units

    # 3. Low Retail Margin Warning (< 10%)
    m3 = compute_purchase_margin_and_ppv({
        "mrp": 100.0,
        "rate": 95.0,
        "quantity": 1.0,
    })
    assert m3["retail_margin_percent"] == 5.0
    assert m3["margin_classification"] == "LOW_RETAIL_MARGIN"

    # 4. Price Inversion Error (Rate > MRP)
    m4 = compute_purchase_margin_and_ppv({
        "mrp": 100.0,
        "rate": 115.0,
        "quantity": 1.0,
    })
    assert m4["margin_classification"] == "PRICE_INVERSION_ERROR"


def test_end_to_end_row_accounting_with_phase7():
    """Test that solve_row_accounting_constraints enriches row with expiry and margin data."""
    raw_row = {
        "itemName": "TELMA 40MG TABLET",
        "pack": "15'S",
        "batchNo": "TL908",
        "expiryDate": "DEC-28",
        "quantity": "10+2",
        "rate": "140.00",
        "mrp": "180.00",
        "discountPercent": "5.0",
        "gstPercent": "12.0",
    }

    solved = solve_row_accounting_constraints(raw_row)

    # Validate Expiry Normalization
    assert solved["expiryDate"] == "12/2028"
    assert solved["_iso_expiry_date"] == "2028-12-31"
    assert solved["_shelf_life"]["has_valid_expiry"] is True
    assert solved["_shelf_life"]["risk_category"] == "OPTIMAL_SHELF_LIFE"

    # Validate Quantities and Candidate Accounting
    assert solved["quantity"] == 10.0
    assert solved["freeQuantity"] == 2.0
    assert solved["rate"] == 140.00
    assert solved["amount"] == 1400.00
    assert solved["taxableAmount"] == 1330.00
    assert solved["netAmount"] == 1489.60

    # Validate Margin Intelligence
    assert solved["_margin_metrics"]["retail_margin_percent"] == 22.22  # (180-140)/180
    assert solved["_margin_metrics"]["scheme_value_benefit_rs"] == 280.00  # 2 * 140
    assert solved["_margin_metrics"]["total_units_received"] == 12.0
