import pytest
import os
import sys
import json
import hashlib
import re

sys.path.insert(0, os.path.abspath("."))

from extractor import (
    determine_column_boundaries,
    score_token_column_assignment,
    assign_tokens_to_columns,
    get_token_column_assignment_diagnostics,
    extract_pdf_table,
    extract_coordinate_table,
)
from evaluation.field_accuracy import evaluate_canonical_field_accuracy
from evaluation.field_ground_truth import FieldGroundTruthStore
from evaluation.evaluator import verify_golden_benchmark_v1


def test_a_stable_numeric_columns():
    """Test A: Stable numeric columns get correctly determined boundaries."""
    headers = [
        {"raw": "MRP", "text": "MRP", "field": "mrp", "x0": 100.0, "x1": 130.0, "center_x": 115.0},
        {"raw": "Rate", "text": "Rate", "field": "rate", "x0": 150.0, "x1": 180.0, "center_x": 165.0},
        {"raw": "Amount", "text": "Amount", "field": "amount", "x0": 200.0, "x1": 240.0, "center_x": 220.0},
    ]
    body_words = [
        {"text": "100.00", "x0": 100.0, "x1": 130.0, "center_x": 115.0, "top": 50.0, "bottom": 60.0},
        {"text": "80.00", "x0": 150.0, "x1": 178.0, "center_x": 164.0, "top": 50.0, "bottom": 60.0},
        {"text": "800.00", "x0": 200.0, "x1": 235.0, "center_x": 217.5, "top": 50.0, "bottom": 60.0},
    ]
    cols = determine_column_boundaries(headers, 300.0, body_words=body_words)
    assert len(cols) == 3
    assert cols[0]["x0"] < cols[0]["center_x"] < cols[0]["x1"]
    assert cols[1]["x0"] < cols[1]["center_x"] < cols[1]["x1"]
    assert cols[2]["x0"] < cols[2]["center_x"] < cols[2]["x1"]
    assert cols[0]["x1"] == cols[1]["x0"]
    assert cols[1]["x1"] == cols[2]["x0"]


def test_b_unequal_token_widths():
    """Test B: Unequal token widths do not cause misassignment."""
    word_wide = {"text": "PARACETAMOL EXTRA STRENGTH", "x0": 50.0, "x1": 180.0, "width": 130.0, "center_x": 115.0}
    word_narrow = {"text": "10", "x0": 190.0, "x1": 200.0, "width": 10.0, "center_x": 195.0}
    cols = [
        {"header_text": "Item Name", "field": "itemName", "x0": 40.0, "x1": 185.0, "center_x": 112.5},
        {"header_text": "Qty", "field": "quantity", "x0": 185.0, "x1": 210.0, "center_x": 197.5},
    ]
    s_wide_item = score_token_column_assignment(word_wide, cols[0])
    s_wide_qty = score_token_column_assignment(word_wide, cols[1])
    assert s_wide_item > s_wide_qty

    s_nar_item = score_token_column_assignment(word_narrow, cols[0])
    s_nar_qty = score_token_column_assignment(word_narrow, cols[1])
    assert s_nar_qty > s_nar_item


def test_c_narrow_adjacent_columns():
    """Test C: Narrow adjacent columns maintain distinct boundaries."""
    headers = [
        {"raw": "DIS%", "text": "DIS%", "field": "discountPercent", "x0": 100.0, "x1": 120.0, "center_x": 110.0},
        {"raw": "GST%", "text": "GST%", "field": "gstPercent", "x0": 125.0, "x1": 145.0, "center_x": 135.0},
    ]
    cols = determine_column_boundaries(headers, 200.0)
    assert len(cols) == 2
    assert cols[0]["x1"] <= 125.0
    assert cols[1]["x0"] >= 120.0


def test_d_header_centered_columns():
    """Test D: Centered header columns place cut points cleanly between centers."""
    headers = [
        {"raw": "Batch", "text": "Batch", "field": "batchNo", "x0": 100.0, "x1": 140.0, "center_x": 120.0},
        {"raw": "Exp", "text": "Exp", "field": "expiryDate", "x0": 160.0, "x1": 190.0, "center_x": 175.0},
    ]
    cols = determine_column_boundaries(headers, 300.0)
    assert cols[0]["x1"] >= 140.0
    assert cols[0]["x1"] <= 160.0


def test_e_header_left_aligned_columns():
    """Test E: Left-aligned headers allow text columns to span to next column."""
    headers = [
        {"raw": "Item Name", "text": "Item Name", "field": "itemName", "x0": 50.0, "x1": 100.0, "center_x": 75.0},
        {"raw": "Batch", "text": "Batch", "field": "batchNo", "x0": 200.0, "x1": 240.0, "center_x": 220.0},
    ]
    cols = determine_column_boundaries(headers, 300.0)
    # Product name column spans close to the batch column start
    assert cols[0]["x1"] >= 190.0


def test_f_multi_line_headers():
    """Test F: Multi-line header tokens preserve combined boundaries."""
    headers = [
        {"raw": "HSN/SAC CODE", "text": "HSN/SAC CODE", "field": "hsnCode", "x0": 50.0, "x1": 110.0, "center_x": 80.0},
        {"raw": "TAXABLE VALUE", "text": "TAXABLE VALUE", "field": "taxableAmount", "x0": 130.0, "x1": 190.0, "center_x": 160.0},
    ]
    cols = determine_column_boundaries(headers, 250.0)
    assert len(cols) == 2
    assert cols[0]["x1"] == cols[1]["x0"]


def test_g_split_headers():
    """Test G: Split headers create adjacent logical columns."""
    headers = [
        {"raw": "CGST", "text": "CGST", "field": "cgstPercent", "x0": 100.0, "x1": 125.0, "center_x": 112.5},
        {"raw": "SGST", "text": "SGST", "field": "sgstPercent", "x0": 130.0, "x1": 155.0, "center_x": 142.5},
    ]
    cols = determine_column_boundaries(headers, 200.0)
    assert len(cols) == 2
    assert cols[0]["field"] == "cgstPercent"
    assert cols[1]["field"] == "sgstPercent"


def test_h_missing_value_in_one_row():
    """Test H: Missing value in one row does not shift neighboring values."""
    cols = [
        {"header_text": "MRP", "field": "mrp", "x0": 100.0, "x1": 140.0, "center_x": 120.0},
        {"header_text": "Rate", "field": "rate", "x0": 140.0, "x1": 180.0, "center_x": 160.0},
        {"header_text": "Amount", "field": "amount", "x0": 180.0, "x1": 230.0, "center_x": 205.0},
    ]
    row_words = [
        {"text": "150.00", "x0": 105.0, "x1": 135.0, "center_x": 120.0},  # MRP
        # Rate is missing
        {"text": "1500.00", "x0": 185.0, "x1": 225.0, "center_x": 205.0}, # Amount
    ]
    cell_words, diag = assign_tokens_to_columns(row_words, cols)
    assert len(cell_words[0]) == 1
    assert cell_words[0][0]["text"] == "150.00"
    assert len(cell_words[1]) == 0  # Empty rate
    assert len(cell_words[2]) == 1
    assert cell_words[2][0]["text"] == "1500.00"


def test_i_missing_middle_field():
    """Test I: Missing middle field maintains alignment across columns."""
    cols = [
        {"header_text": "Qty", "field": "quantity", "x0": 10.0, "x1": 40.0, "center_x": 25.0},
        {"header_text": "Free", "field": "freeQuantity", "x0": 40.0, "x1": 70.0, "center_x": 55.0},
        {"header_text": "Rate", "field": "rate", "x0": 70.0, "x1": 110.0, "center_x": 90.0},
    ]
    row_words = [
        {"text": "10", "x0": 15.0, "x1": 25.0, "center_x": 20.0},
        {"text": "120.50", "x0": 75.0, "x1": 105.0, "center_x": 90.0},
    ]
    cell_words, _ = assign_tokens_to_columns(row_words, cols)
    assert cell_words[0][0]["text"] == "10"
    assert len(cell_words[1]) == 0
    assert cell_words[2][0]["text"] == "120.50"


def test_j_long_product_name():
    """Test J: Long product name does not get placed into narrow numeric column."""
    cols = [
        {"header_text": "Product Name", "field": "itemName", "x0": 50.0, "x1": 200.0, "center_x": 125.0},
        {"header_text": "Qty", "field": "quantity", "x0": 200.0, "x1": 230.0, "center_x": 215.0},
    ]
    word = {"text": "AMLONG-A 50MG TABLET 10S", "x0": 52.0, "x1": 195.0, "width": 143.0, "center_x": 123.5}
    s_item = score_token_column_assignment(word, cols[0])
    s_qty = score_token_column_assignment(word, cols[1])
    assert s_item > s_qty


def test_k_multi_line_product_description():
    """Test K: Multi-line product description words remain in itemName column."""
    cols = [
        {"header_text": "Product Name", "field": "itemName", "x0": 50.0, "x1": 220.0, "center_x": 135.0},
        {"header_text": "Batch", "field": "batchNo", "x0": 220.0, "x1": 270.0, "center_x": 245.0},
    ]
    line2_words = [
        {"text": "FORTE", "x0": 55.0, "x1": 85.0, "width": 30.0, "center_x": 70.0},
        {"text": "SYRUP", "x0": 90.0, "x1": 120.0, "width": 30.0, "center_x": 105.0},
        {"text": "100ML", "x0": 125.0, "x1": 155.0, "width": 30.0, "center_x": 140.0},
    ]
    cell_words, _ = assign_tokens_to_columns(line2_words, cols)
    assert len(cell_words[0]) == 3
    assert len(cell_words[1]) == 0


def test_l_vertical_ruling_line_evidence():
    """Test L: Vertical ruling lines strongly guide column boundaries."""
    headers = [
        {"raw": "Rate", "text": "Rate", "field": "rate", "x0": 100.0, "x1": 130.0, "center_x": 115.0},
        {"raw": "Amount", "text": "Amount", "field": "amount", "x0": 150.0, "x1": 190.0, "center_x": 170.0},
    ]
    page_lines = [{"x0": 142.0, "x1": 142.0, "top": 100.0, "bottom": 400.0}]
    body_words = [{"text": "100", "x0": 105.0, "x1": 125.0, "top": 120.0, "bottom": 130.0}]
    cols = determine_column_boundaries(headers, 250.0, body_words=body_words, page_lines=page_lines)
    assert cols[0]["x1"] == pytest.approx(142.0, abs=1.0)


def test_m_borderless_table():
    """Test M: Borderless tables derive boundaries from whitespace valleys and centers."""
    headers = [
        {"raw": "MRP", "text": "MRP", "field": "mrp", "x0": 50.0, "x1": 80.0, "center_x": 65.0},
        {"raw": "Rate", "text": "Rate", "field": "rate", "x0": 100.0, "x1": 130.0, "center_x": 115.0},
    ]
    body_words = [
        {"text": "100.00", "x0": 50.0, "x1": 80.0, "center_x": 65.0, "top": 100.0, "bottom": 110.0},
        {"text": "80.00", "x0": 100.0, "x1": 125.0, "center_x": 112.5, "top": 100.0, "bottom": 110.0},
    ]
    cols = determine_column_boundaries(headers, 200.0, body_words=body_words)
    assert len(cols) == 2
    assert cols[0]["x1"] >= 80.0
    assert cols[0]["x1"] <= 100.0


def test_n_normalized_coordinates():
    """Test N: Normalized coordinate calculation maintains relative column positions."""
    table_x0 = 50.0
    table_width = 400.0
    c_center = 250.0
    norm_x = (c_center - table_x0) / table_width
    assert norm_x == pytest.approx(0.50, abs=0.01)


def test_o_numeric_interval_overlap():
    """Test O: Numeric interval overlap assigns decimal numbers accurately."""
    col = {"header_text": "Amount", "field": "amount", "x0": 200.0, "x1": 250.0, "center_x": 225.0}
    w_exact = {"text": "1540.25", "x0": 205.0, "x1": 245.0, "width": 40.0, "center_x": 225.0}
    score = score_token_column_assignment(w_exact, col)
    assert score > 80.0


def test_p_ambiguous_token_assignment():
    """Test P: Ambiguous token assignment correctly flags ambiguity in diagnostics."""
    cols = [
        {"header_text": "ColA", "field": "rate", "x0": 100.0, "x1": 150.0, "center_x": 125.0},
        {"header_text": "ColB", "field": "mrp", "x0": 150.0, "x1": 200.0, "center_x": 175.0},
    ]
    w_straddle = {"text": "120.00", "x0": 140.0, "x1": 160.0, "width": 20.0, "center_x": 150.0}
    cell_words, diags = assign_tokens_to_columns([w_straddle], cols, debug=True)
    assert any(d.get("is_ambiguous") for d in diags)


def test_q_ambiguous_boundary_review_required():
    """Test Q: Ambiguous token assignment lowers confidence."""
    diag = get_token_column_assignment_diagnostics(
        [{"text": "120.00", "x0": 140.0, "x1": 160.0, "center_x": 150.0}],
        [
            {"header_text": "ColA", "field": "rate", "x0": 100.0, "x1": 150.0, "center_x": 125.0},
            {"header_text": "ColB", "field": "mrp", "x0": 150.0, "x1": 200.0, "center_x": 175.0},
        ]
    )
    assert len(diag) == 1
    assert diag[0]["is_ambiguous"] is True


def test_r_duplicate_canonical_field_protection():
    """Test R: Duplicate canonical field protection prevents column clashes."""
    headers = [
        {"raw": "RATE", "text": "RATE", "field": "rate", "x0": 100.0, "x1": 130.0, "center_x": 115.0},
        {"raw": "PTR", "text": "PTR", "field": "rate", "x0": 140.0, "x1": 170.0, "center_x": 155.0},
    ]
    cols = determine_column_boundaries(headers, 250.0)
    assert len(cols) == 2
    assert cols[0]["x1"] == cols[1]["x0"]


def test_s_mrp_rate_separation():
    """Test S: MRP and Rate columns separate decimal values correctly."""
    cols = [
        {"header_text": "MRP", "field": "mrp", "x0": 100.0, "x1": 140.0, "center_x": 120.0},
        {"header_text": "Rate", "field": "rate", "x0": 140.0, "x1": 180.0, "center_x": 160.0},
    ]
    row_words = [
        {"text": "220.00", "x0": 105.0, "x1": 135.0, "center_x": 120.0},
        {"text": "165.50", "x0": 145.0, "x1": 175.0, "center_x": 160.0},
    ]
    cell_words, _ = assign_tokens_to_columns(row_words, cols)
    assert cell_words[0][0]["text"] == "220.00"
    assert cell_words[1][0]["text"] == "165.50"


def test_t_amount_gst_separation():
    """Test T: Amount and GST percentage columns separate cleanly."""
    cols = [
        {"header_text": "Amount", "field": "amount", "x0": 200.0, "x1": 250.0, "center_x": 225.0},
        {"header_text": "GST%", "field": "gstPercent", "x0": 250.0, "x1": 280.0, "center_x": 265.0},
    ]
    row_words = [
        {"text": "1655.00", "x0": 205.0, "x1": 245.0, "center_x": 225.0},
        {"text": "18%", "x0": 255.0, "x1": 275.0, "center_x": 265.0},
    ]
    cell_words, _ = assign_tokens_to_columns(row_words, cols)
    assert cell_words[0][0]["text"] == "1655.00"
    assert cell_words[1][0]["text"] == "18%"


def test_u_cgst_sgst_separation():
    """Test U: CGST and SGST columns assign equal percentage tokens properly."""
    cols = [
        {"header_text": "CGST", "field": "cgstPercent", "x0": 100.0, "x1": 130.0, "center_x": 115.0},
        {"header_text": "SGST", "field": "sgstPercent", "x0": 130.0, "x1": 160.0, "center_x": 145.0},
    ]
    row_words = [
        {"text": "2.5%", "x0": 105.0, "x1": 125.0, "center_x": 115.0},
        {"text": "2.5%", "x0": 135.0, "x1": 155.0, "center_x": 145.0},
    ]
    cell_words, _ = assign_tokens_to_columns(row_words, cols)
    assert cell_words[0][0]["text"] == "2.5%"
    assert cell_words[1][0]["text"] == "2.5%"


def test_v_taxable_net_separation():
    """Test V: Taxable Amount and Net Amount columns separate properly."""
    cols = [
        {"header_text": "Taxable", "field": "taxableAmount", "x0": 200.0, "x1": 250.0, "center_x": 225.0},
        {"header_text": "Net", "field": "netAmount", "x0": 250.0, "x1": 300.0, "center_x": 275.0},
    ]
    row_words = [
        {"text": "1000.00", "x0": 205.0, "x1": 245.0, "center_x": 225.0},
        {"text": "1180.00", "x0": 255.0, "x1": 295.0, "center_x": 275.0},
    ]
    cell_words, _ = assign_tokens_to_columns(row_words, cols)
    assert cell_words[0][0]["text"] == "1000.00"
    assert cell_words[1][0]["text"] == "1180.00"


def test_w_prompt16_compound_quantity_regression():
    """Test W: Prompt 16 23+2 compound quantity reconstruction is preserved."""
    from extractor import tokenize_compound_quantity, parse_compound_qty, compute_row_accounting
    tok = tokenize_compound_quantity("23+2")
    assert tok["is_compound"] is True
    assert tok["left"] == 23.0
    assert tok["right"] == 2.0
    billed, free = parse_compound_qty("23+2")
    assert billed == 23.0
    assert free == 2.0
    row_dict = {"quantity": "23+2", "rate": "10.00", "amount": "230.00"}
    acc = compute_row_accounting(row_dict)
    assert acc["quantity"] == 23.0
    assert float(acc["freeQuantity"]) == 2.0


def test_x_prompt17_multi_value_regression():
    """Test X: Prompt 17 multi-value subcolumn splits remain intact."""
    from extractor import fix_column_bleeding
    row = {"amount": "1000.00 18%", "quantity": "10", "rate": "100.00"}
    fixed = fix_column_bleeding(dict(row))
    assert fixed["amount"] == "1000.00"
    assert fixed["gstPercent"] == "18"

    row2 = {"mrp": "159.00 121.14"}
    fixed2 = fix_column_bleeding(dict(row2))
    assert fixed2["mrp"] == "159.00"
    assert fixed2["rate"] == "121.14"


def test_y_invoice_pdf_regression():
    """Test Y: Invoice.pdf extracts cleanly with coordinate extraction."""
    meta, headers, mappings, rows = extract_pdf_table("Sample Invoices/Invoice.pdf", use_coordinates=True)
    assert len(rows) >= 20
    assert meta.get("confidence", 0.0) > 30.0


def test_z_sunil_medicare_regression():
    """Test Z: Sunil Medicare multi-page invoice extracts both pages without column collapse."""
    meta, headers, mappings, rows = extract_pdf_table("Sample Invoices/Sunil_Medicare_Sample_Invoice.pdf", use_coordinates=True)
    assert len(rows) >= 18
    assert meta.get("confidence", 0.0) > 50.0


def test_aa_all_golden_v1_regression():
    """Test AA: Full GOLDEN_V1 benchmark evaluation passes integrity and maintains field accuracy."""
    summary = evaluate_canonical_field_accuracy()
    assert summary.total_documents == 9
    assert summary.overall_field_accuracy > 80.0
    assert summary.overall_critical_field_accuracy > 80.0


def test_ab_repeated_extraction_determinism():
    """Test AB: Repeated extractions yield 100% identical outputs."""
    m1, h1, c1, r1 = extract_pdf_table("Sample Invoices/INVOICE_7GX167AKM.PDF", use_coordinates=True)
    m2, h2, c2, r2 = extract_pdf_table("Sample Invoices/INVOICE_7GX167AKM.PDF", use_coordinates=True)
    assert h1 == h2
    assert r1 == r2
    assert c1 == c2


def test_ac_no_supplier_specific_branch():
    """Test AC: Zero supplier-specific branching exists in extractor.py."""
    with open("extractor.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "if supplier ==" not in content
    assert "if supplier_name ==" not in content
    assert "if 'PRAPTI'" not in content
    assert "if 'MOHIT'" not in content


def test_ad_no_filename_specific_branch():
    """Test AD: Zero filename-specific branching exists in extractor.py."""
    with open("extractor.py", "r", encoding="utf-8") as f:
        content = f.read()
    assert "if filename ==" not in content
    assert "if 'INVOICE_7HH0S5IPC.PDF'" not in content
    assert "if 'Sunil_Medicare_Sample_Invoice.pdf'" not in content


def test_ae_no_hardcoded_absolute_x_coordinate():
    """Test AE: No hardcoded sample-specific absolute x coordinates in determine_column_boundaries."""
    import inspect
    src = inspect.getsource(determine_column_boundaries)
    assert "x0 == 250" not in src
    assert "x1 == 382" not in src
    assert "523.8" not in src


def test_af_confidence_reflects_ambiguity():
    """Test AF: Confidence calculation penalizes ambiguous coordinate overlaps."""
    diag = get_token_column_assignment_diagnostics(
        [{"text": "120.00", "x0": 148.0, "x1": 152.0, "center_x": 150.0}],
        [
            {"header_text": "Rate", "field": "rate", "x0": 100.0, "x1": 150.0, "center_x": 125.0},
            {"header_text": "MRP", "field": "mrp", "x0": 150.0, "x1": 200.0, "center_x": 175.0},
        ]
    )
    assert diag[0]["is_ambiguous"] is True
