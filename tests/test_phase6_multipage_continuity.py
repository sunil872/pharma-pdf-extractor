"""
Unit and Integration Tests for MediAstra Phase 6:
- Multi-Page Invoice Continuity & Header Suppression (extractor.py)
- Running Subtotal & Brought/Carried-Forward (B/F & C/F) Row Filtering (extractor.py)
- Invoice-Level Grand Total Mathematical Reconciliation Solver (extractor.py)
"""

import pytest
from extractor import (
    filter_continuation_header_and_subtotal_rows,
    reconcile_invoice_grand_totals,
    compute_global_validation_and_confidence,
)


def test_filter_repeated_continuation_headers():
    """Test suppression of repeated table headers across continuation pages."""
    headers = ["S.No", "Item Description", "Pack", "Batch", "Exp", "Qty", "Rate", "Amount"]
    rows = [
        ["1", "TELMA 40MG TABLET", "15'S", "TL1001", "12/28", "10", "140.00", "1400.00"],
        ["2", "AMARYL 1MG TABLET", "30'S", "AM2002", "06/27", "20", "88.80", "1776.00"],
        # Repeated Header on Page 2
        ["S.No", "Item Description", "Pack", "Batch", "Exp", "Qty", "Rate", "Amount"],
        ["3", "PAN 40MG TABLET", "10'S", "PN3003", "09/27", "15", "110.00", "1650.00"],
        ["4", "AUGMENTIN 625 DUO", "10'S", "AG4004", "04/26", "5", "180.00", "900.00"],
    ]

    filtered_rows, audit_log = filter_continuation_header_and_subtotal_rows(rows, headers=headers)

    assert len(filtered_rows) == 4
    assert len(audit_log) == 1
    assert audit_log[0]["reason"] == "REPEATED_HEADER_ROW"
    assert "TELMA 40MG TABLET" in filtered_rows[0][1]
    assert "PAN 40MG TABLET" in filtered_rows[2][1]


def test_filter_brought_forward_and_carried_forward_rows():
    """Test suppression of running B/F and C/F accumulator rows."""
    headers = ["Item Name", "Pack", "Batch", "Exp", "Qty", "Rate", "Amount"]
    rows = [
        ["GLYCOMET GP 1MG", "15'S", "GL101", "10/27", "20", "75.00", "1500.00"],
        # Carried forward at bottom of Page 1
        ["TOTAL C/F", "", "", "", "", "", "1500.00"],
        # Brought forward at top of Page 2
        ["TOTAL B/F", "", "", "", "", "", "1500.00"],
        ["CREMAFFIN PLUS", "200ML", "CR202", "05/26", "10", "190.00", "1900.00"],
        # Alternative phrasing
        ["AMT B/F", "", "", "", "", "", "3400.00"],
        ["BALANCE C/F", "", "", "", "", "", "3400.00"],
        ["CALPOL 500MG", "15'S", "CP303", "08/28", "30", "15.00", "450.00"],
    ]

    filtered_rows, audit_log = filter_continuation_header_and_subtotal_rows(rows, headers=headers)

    assert len(filtered_rows) == 3
    assert len(audit_log) == 4
    assert all(entry["reason"] == "RUNNING_BF_CF_ROW" for entry in audit_log)
    assert filtered_rows[0][0] == "GLYCOMET GP 1MG"
    assert filtered_rows[1][0] == "CREMAFFIN PLUS"
    assert filtered_rows[2][0] == "CALPOL 500MG"


def test_filter_running_page_subtotals_and_page_chrome():
    """Test suppression of page subtotals and pagination footer chrome."""
    headers = ["Item Name", "Batch", "Qty", "Amount"]
    rows = [
        ["DOLO 650MG", "DL01", "50", "1500.00"],
        ["PAGE 1 TOTAL", "", "", "1500.00"],
        ["Page 2 of 3 (Continued)", "", "", ""],
        ["Continued on next page...", "", "", ""],
        ["SUB TOTAL", "", "", "1500.00"],
        ["AZITHRAL 500MG", "AZ02", "20", "2200.00"],
    ]

    filtered_rows, audit_log = filter_continuation_header_and_subtotal_rows(rows, headers=headers)

    assert len(filtered_rows) == 2
    assert filtered_rows[0][0] == "DOLO 650MG"
    assert filtered_rows[1][0] == "AZITHRAL 500MG"
    reasons = [entry["reason"] for entry in audit_log]
    assert "PAGE_SUBTOTAL_ROW" in reasons
    assert "PAGE_CONTINUATION_CHROME" in reasons


def test_reconcile_invoice_grand_totals_balanced():
    """Test invoice-level mathematical reconciliation solver on a perfectly balanced invoice."""
    line_items = [
        {
            "itemName": "TELMA 40MG",
            "quantity": 10.0,
            "freeQuantity": 0.0,
            "rate": 100.0,
            "discountPercent": 10.0,
            "gstPercent": 12.0,
            "cgstPercent": 6.0,
            "sgstPercent": 6.0,
            "amount": 1000.0,
            "taxableAmount": 900.0,
            "netAmount": 1008.0,  # 900 + 108 GST
        },
        {
            "itemName": "AMARYL 1MG",
            "quantity": 20.0,
            "freeQuantity": 2.0,
            "rate": 50.0,
            "discountPercent": 0.0,
            "gstPercent": 12.0,
            "cgstPercent": 6.0,
            "sgstPercent": 6.0,
            "amount": 1000.0,
            "taxableAmount": 1000.0,
            "netAmount": 1120.0,  # 1000 + 120 GST
        },
    ]

    metadata = {
        "taxable_amount": 1900.0,
        "gst_amount": 228.0,
        "tcs_amount": 1.50,
        "round_off": 0.50,
        "grand_total": 2130.00,  # 1008 + 1120 + 1.50 + 0.50 = 2130.00
    }

    recon = reconcile_invoice_grand_totals(line_items, metadata=metadata)

    assert recon["is_reconciled"] is True
    assert recon["reconciliation_status"] == "RECONCILED_BALANCED"
    assert recon["calculated_line_totals"]["sum_taxable_amount"] == 1900.0
    assert recon["calculated_line_totals"]["sum_total_gst"] == 228.0
    assert recon["calculated_line_totals"]["sum_net_amount"] == 2128.0
    assert recon["deltas"]["grand_total_delta"] == 0.0
    assert len(recon["suspicious_lines"]) == 0


def test_reconcile_invoice_grand_totals_minor_rounding_variance():
    """Test minor rounding tolerance (e.g. ₹0.35 rounding difference)."""
    line_items = [
        {
            "itemName": "PANTOCID 40MG",
            "quantity": 5.0,
            "rate": 123.45,
            "discountPercent": 0.0,
            "gstPercent": 12.0,
            "taxableAmount": 617.25,
            "netAmount": 691.32,
        }
    ]

    metadata = {
        "taxable_amount": 617.25,
        "gst_amount": 74.07,
        "grand_total": 691.00,  # Stated rounded down to nearest rupee
    }

    recon = reconcile_invoice_grand_totals(line_items, metadata=metadata)

    assert recon["is_reconciled"] is True
    assert recon["reconciliation_status"] in ("RECONCILED_BALANCED", "MINOR_ROUNDING_VARIANCE")
    assert recon["deltas"]["grand_total_delta"] <= 1.0


def test_reconcile_invoice_grand_totals_unreconciled_mismatch():
    """Test detection of an unresolved mismatch (e.g. a missed line item of ₹500)."""
    line_items = [
        {
            "itemName": "AUGMENTIN 625",
            "quantity": 10.0,
            "rate": 150.0,
            "discountPercent": 0.0,
            "gstPercent": 12.0,
            "taxableAmount": 1500.0,
            "netAmount": 1680.0,
        }
    ]

    # Stated invoice grand total is ₹2,500.00 (a line item was not parsed)
    metadata = {
        "taxable_amount": 2232.14,
        "gst_amount": 267.86,
        "grand_total": 2500.00,
    }

    recon = reconcile_invoice_grand_totals(line_items, metadata=metadata)

    assert recon["is_reconciled"] is False
    assert recon["reconciliation_status"] == "UNRECONCILED_MISMATCH"
    assert recon["deltas"]["grand_total_delta"] == 820.0  # 2500 - 1680


def test_compute_global_validation_includes_grand_total_reconciliation():
    """Test that compute_global_validation_and_confidence includes the grand total reconciliation ledger."""
    headers = ["Item Name", "Qty", "Rate", "Amount"]
    logical_columns = [
        {"header_text": "Item Name", "field": "itemName", "x0": 10, "x1": 200, "status": "clean"},
        {"header_text": "Qty", "field": "quantity", "x0": 210, "x1": 260, "status": "clean"},
        {"header_text": "Rate", "field": "rate", "x0": 270, "x1": 340, "status": "clean"},
        {"header_text": "Amount", "field": "amount", "x0": 350, "x1": 450, "status": "clean"},
    ]
    column_mappings = {
        "Item Name": {"mapped_to": "itemName", "status": "known_header"},
        "Qty": {"mapped_to": "quantity", "status": "known_header"},
        "Rate": {"mapped_to": "rate", "status": "known_header"},
        "Amount": {"mapped_to": "amount", "status": "known_header"},
    }
    rows = [
        ["BECOSULES CAPSULE", "10", "45.00", "450.00"],
        ["ZINGOVIT TABLET", "20", "60.00", "1200.00"],
    ]
    metadata = {
        "supplier_name": "APOLLO DISTRIBUTORS",
        "supplier_gstin": "27APOLL1234F1Z1",
        "grand_total": 1650.00,
    }

    val_res = compute_global_validation_and_confidence(
        headers, logical_columns, column_mappings, rows, metadata=metadata
    )

    assert "grand_total_reconciliation" in val_res
    recon = val_res["grand_total_reconciliation"]
    assert recon["is_reconciled"] is True
    assert recon["reconciliation_status"] == "RECONCILED_BALANCED"
    assert recon["calculated_line_totals"]["sum_gross_amount"] == 1650.0
    assert recon["calculated_line_totals"]["line_count"] == 2
