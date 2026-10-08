"""
Unit tests for MediAstra Phase 2:
- Row Reconstruction Engine
- Wrapped Product Name Merging & Continuation Rows
- Sub-table & Return Adjustment Segregation
"""

import pytest
from extractor import (
    reconstruct_logical_rows,
    segment_invoice_sections,
    merge_wrapped_continuation_rows,
    _is_genuine_product_row,
)


# =============================================================================
# 1. Wrapped Product Name & Continuation Row Merging Tests
# =============================================================================

def test_merge_wrapped_medicine_name_continuation():
    """
    Test when a medicine name wraps across two physical rows:
    Row 1: ["1", "AMARYL 1 MG", "5NG006", "01/28", "10", "88.80", "888.00"]
    Row 2: ["", "TABLET (30'S PACK)", "", "", "", "", ""]
    Should merge Row 2's description into Row 1's itemName -> "AMARYL 1 MG TABLET (30'S PACK)"
    """
    headers = ["S.No", "Product Name", "Batch", "Expiry", "Qty", "Rate", "Amount"]
    mappings = {
        "S.No": {"mapped_to": "serialNumber"},
        "Product Name": {"mapped_to": "itemName"},
        "Batch": {"mapped_to": "batchNo"},
        "Expiry": {"mapped_to": "expiryDate"},
        "Qty": {"mapped_to": "quantity"},
        "Rate": {"mapped_to": "rate"},
        "Amount": {"mapped_to": "amount"},
    }
    raw_rows = [
        ["1", "AMARYL 1 MG", "5NG006", "01/28", "10", "88.80", "888.00"],
        ["", "TABLET (30'S PACK)", "", "", "", "", ""],
        ["2", "ASTYMIN FORTE", "F26C116", "12/27", "4+1", "305.10", "1220.40"],
        ["", "CAPSULES 30'S", "", "", "", "", ""],
    ]

    reconstructed = merge_wrapped_continuation_rows(raw_rows, headers, mappings)

    assert len(reconstructed) == 2
    assert reconstructed[0][1] == "AMARYL 1 MG TABLET (30'S PACK)"
    assert reconstructed[0][4] == "10"
    assert reconstructed[1][1] == "ASTYMIN FORTE CAPSULES 30'S"
    assert reconstructed[1][4] == "4+1"


def test_merge_orphan_composition_continuation():
    """Test merging salt composition continuation row into item name."""
    headers = ["Item Description", "Batch", "Exp", "Qty", "Rate", "Amount"]
    mappings = {
        "Item Description": {"mapped_to": "itemName"},
        "Batch": {"mapped_to": "batchNo"},
        "Exp": {"mapped_to": "expiryDate"},
        "Qty": {"mapped_to": "quantity"},
        "Rate": {"mapped_to": "rate"},
        "Amount": {"mapped_to": "amount"},
    }
    raw_rows = [
        ["EXTRALUBE EYE DROPS 10ML", "EXAS0108", "07/27", "4.50+.50", "98.31", "442.40"],
        ["CARBOXYMETHYLCELLULOSE SODIUM 0.5%", "", "", "", "", ""],
    ]

    reconstructed = merge_wrapped_continuation_rows(raw_rows, headers, mappings)

    assert len(reconstructed) == 1
    assert "EXTRALUBE EYE DROPS 10ML" in reconstructed[0][0]
    assert "CARBOXYMETHYLCELLULOSE SODIUM 0.5%" in reconstructed[0][0]


# =============================================================================
# 2. Sub-Table & Return Adjustment Segregation Tests (Divya Pharma Style)
# =============================================================================

def test_segregate_returns_adjusted_section():
    """
    Test Divya Pharma style invoice with embedded 'Returns Adjusted In This Invoice' sub-table.
    """
    headers = ["Qty", "Sch Qty", "Pack", "Item Description", "Batch", "Exp Date", "MRP", "PTR", "Amount"]
    raw_rows = [
        ["5", "0", "400 GM", "FITLIVON XP POWDER 400GM", "RN260132", "01-28", "1465.00", "1116.18", "5580.90"],
        ["Returns Adjusted In This Invoice", "", "", "", "", "", "", "", ""],
        ["Credit Note No : 2600067329877 Date :29-Sep-26 Total Amount: 444.00", "", "", "", "", "", "", "", ""],
        ["1", "0.5", "10'S", "COMBISAFE TAB", "C2425048", "01-27", "300.00", "205.71", ""],
        ["1", "0", "10'S", "FERRILIP TAB", "XTFG25002", "02-27", "268.73", "184.28", ""],
        ["1", "0", "5GM", "LACRYL PF EYE GEL", "H016", "05-27", "185.50", "127.20", ""],
    ]

    sections = segment_invoice_sections(raw_rows, headers)

    assert "purchase_items" in sections
    assert "returns_adjusted" in sections
    assert len(sections["purchase_items"]) == 1
    assert sections["purchase_items"][0][3] == "FITLIVON XP POWDER 400GM"

    assert len(sections["returns_adjusted"]) == 3
    assert sections["returns_adjusted"][0][3] == "COMBISAFE TAB"
    assert sections["returns_adjusted"][1][3] == "FERRILIP TAB"
    assert sections["returns_adjusted"][2][3] == "LACRYL PF EYE GEL"


# =============================================================================
# 3. Full Logical Row Reconstruction Pipeline
# =============================================================================

def test_reconstruct_logical_rows_complete_pipeline():
    """
    Test full end-to-end logical row reconstruction from noisy extracted raw rows.
    """
    headers = ["R.N", "Qty.", "Pack", "Product", "Batch", "Exp", "Rate", "Amount"]
    mappings = {
        "R.N": {"mapped_to": "rackNo"},
        "Qty.": {"mapped_to": "quantity"},
        "Pack": {"mapped_to": "pack"},
        "Product": {"mapped_to": "itemName"},
        "Batch": {"mapped_to": "batchNo"},
        "Exp": {"mapped_to": "expiryDate"},
        "Rate": {"mapped_to": "rate"},
        "Amount": {"mapped_to": "amount"},
    }
    raw_rows = [
        ["24B", "10", "30'S", "AMARYL 1 MG TABLET", "5NG006", "1/28", "88.80", "888.00"],
        ["", "", "", "(GLIMEPIRIDE 1MG)", "", "", "", ""],  # continuation line
        ["13B", "9.50+.50", "15'S", "ATOCOR 10MG TAB.", "E2601218", "4/28", "60.62", "575.89"],
        ["-- Remark: Bank details --", "", "", "", "", "", "", ""],  # footer leak
    ]

    clean_rows = reconstruct_logical_rows(raw_rows, headers, mappings)

    assert len(clean_rows) == 2
    assert "AMARYL 1 MG TABLET (GLIMEPIRIDE 1MG)" in clean_rows[0]["itemName"]
    assert clean_rows[0]["quantity"] == 10.0
    assert clean_rows[1]["quantity"] == 9.50
    assert clean_rows[1]["freeQuantity"] == 0.50
    assert clean_rows[1]["rate"] == 60.62
    assert clean_rows[1]["amount"] == 575.89
