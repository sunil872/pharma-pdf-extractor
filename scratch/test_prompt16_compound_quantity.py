import os
import ast
import json
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


def test_A_integer_compound_23_plus_2():
    tok = tokenize_compound_quantity("23+2")
    assert tok["is_compound"] is True
    assert tok["left"] == 23.0
    assert tok["right"] == 2.0
    assert tok["left_raw"] == "23"
    assert tok["right_raw"] == "2"
    assert tok["operator"] == "+"
    assert tok["pattern"] == "quantity_plus_free_quantity"


def test_B_integer_compound_10_plus_2():
    tok = tokenize_compound_quantity("10+2")
    assert tok["is_compound"] is True
    assert tok["left"] == 10.0
    assert tok["right"] == 2.0
    billed, free = parse_compound_qty("10+2")
    assert billed == 10.0
    assert free == 2.0


def test_C_decimal_compound_2_500_plus_point_500():
    tok = tokenize_compound_quantity("2.500+.500")
    assert tok["is_compound"] is True
    assert tok["left"] == 2.5
    assert tok["right"] == 0.5
    assert tok["left_raw"] == "2.500"
    assert tok["right_raw"] == ".500"


def test_D_whitespace_around_plus_23_plus_2():
    tok = tokenize_compound_quantity("23 + 2")
    assert tok["is_compound"] is True
    assert tok["left"] == 23.0
    assert tok["right"] == 2.0


def test_E_whitespace_decimal_2_500_plus_point_500():
    tok = tokenize_compound_quantity("2.500 + .500")
    assert tok["is_compound"] is True
    assert tok["left"] == 2.5
    assert tok["right"] == 0.5


def test_F_zero_free_quantity_23_plus_0():
    tok = tokenize_compound_quantity("23+0")
    assert tok["is_compound"] is True
    assert tok["left"] == 23.0
    assert tok["right"] == 0.0


def test_G_zero_billed_quantity_0_plus_2():
    tok = tokenize_compound_quantity("0+2")
    assert tok["is_compound"] is True
    assert tok["left"] == 0.0
    assert tok["right"] == 2.0


def test_H_malformed_trailing_plus_23_plus():
    tok = tokenize_compound_quantity("23+")
    assert tok["is_compound"] is False
    assert tok["left"] is None
    assert tok["right"] is None


def test_I_free_only_plus_2():
    tok = tokenize_compound_quantity("+2")
    assert tok["is_compound"] is True
    assert tok["left"] == 0.0
    assert tok["right"] == 2.0
    assert tok["pattern"] == "free_only_quantity"


def test_J_malformed_double_plus_10_plus_plus_2():
    tok = tokenize_compound_quantity("10++2")
    assert tok["is_compound"] is False
    assert tok["left"] is None
    assert tok["right"] is None


def test_K_alphabetic_A_plus_B():
    tok = tokenize_compound_quantity("A+B")
    assert tok["is_compound"] is False
    tok2 = tokenize_compound_quantity("10+ABC")
    assert tok2["is_compound"] is False


def test_L_header_qty_plus_free_multi_token():
    phys_col = [{"index": 0, "header_raw": "Qty+Free", "header_text": "Qty+Free", "field": None, "x0": 10.0, "x1": 100.0, "center_x": 55.0}]
    row_groups = [[{"text": "23", "center_x": 30.0, "x0": 20.0, "x1": 40.0, "top": 50.0, "bottom": 60.0},
                   {"text": "2", "center_x": 80.0, "x0": 70.0, "x1": 90.0, "top": 50.0, "bottom": 60.0}]]
    log_cols, diag = detect_logical_subcolumns(phys_col, row_groups)
    assert len(log_cols) >= 1


def test_M_header_qty_free_multi_token():
    phys_col = [{"index": 0, "header_raw": "QTY FREE", "header_text": "QTY FREE", "field": None, "x0": 10.0, "x1": 100.0, "center_x": 55.0}]
    row_groups = [[{"text": "10", "center_x": 30.0, "x0": 20.0, "x1": 40.0, "top": 50.0, "bottom": 60.0},
                   {"text": "2", "center_x": 80.0, "x0": 70.0, "x1": 90.0, "top": 50.0, "bottom": 60.0}]]
    log_cols, diag = detect_logical_subcolumns(phys_col, row_groups)
    assert len(log_cols) >= 1


def test_N_coordinate_separated_qty_free():
    phys_col = [{"index": 0, "header_raw": "Qty Free", "header_text": "Qty Free", "field": None, "x0": 10.0, "x1": 100.0, "center_x": 55.0}]
    # 5 rows with distinct 2 clusters
    row_groups = [
        [{"text": "10", "center_x": 25.0, "x0": 20.0, "x1": 30.0, "top": 50.0 + i*10, "bottom": 58.0 + i*10},
         {"text": "1", "center_x": 75.0, "x0": 70.0, "x1": 80.0, "top": 50.0 + i*10, "bottom": 58.0 + i*10}]
        for i in range(5)
    ]
    log_cols, diag = detect_logical_subcolumns(phys_col, row_groups)
    assert len(log_cols) == 2
    assert log_cols[0]["field"] == "quantity"
    assert log_cols[1]["field"] == "freeQuantity"


def test_O_raw_provenance_preserved():
    row = {
        "itemName": "PARACETAMOL 500MG",
        "quantity": "23+2",
        "rate": 10.0,
        "amount": 230.0,
    }
    accounted = compute_row_accounting(row)
    assert accounted["quantity"] == 23.0
    assert float(accounted["freeQuantity"]) == 2.0
    assert accounted["_raw_values"]["quantity"] == "23+2"
    assert "_compound_provenance" in accounted
    assert "quantity" in accounted["_compound_provenance"]
    assert "freeQuantity" in accounted["_compound_provenance"]


def test_P_free_quantity_not_silently_discarded():
    row = {
        "itemName": "AMOXICILLIN 250MG",
        "quantity": "10+2",
        "rate": 50.0,
        "amount": 500.0,
    }
    accounted = compute_row_accounting(row)
    assert accounted["quantity"] == 10.0
    assert float(accounted["freeQuantity"]) == 2.0


def test_Q_low_confidence_malformed_compound_requires_review():
    row = {
        "itemName": "CETIRIZINE 10MG",
        "quantity": "10+ABC",
        "rate": 5.0,
    }
    accounted = compute_row_accounting(row)
    # Malformed quantity should record discrepancy
    assert any(d.get("status") == "UNRESOLVED_COMPOUND" for d in accounted.get("validation_discrepancies", []))


def test_R_high_confidence_compound_quantity_maps_correctly():
    row = {
        "itemName": "PANTOPRAZOLE 40MG",
        "quantity": "2.500+.500",
        "rate": 100.0,
        "amount": 250.0,
    }
    accounted = compute_row_accounting(row)
    assert accounted["quantity"] == 2.5
    assert float(accounted["freeQuantity"]) == 0.5


def test_S_auto_accept_blocked_when_compound_is_malformed():
    headers = ["Product", "Qty", "Rate", "Amount"]
    mappings = {
        "Product": {"mapped_to": "itemName", "status": "known_header"},
        "Qty": {"mapped_to": "quantity", "status": "known_header"},
        "Rate": {"mapped_to": "rate", "status": "known_header"},
        "Amount": {"mapped_to": "amount", "status": "known_header"},
    }
    rows = [["MEDICINE A", "23+", "10.0", "230.0"]]
    res = compute_global_validation_and_confidence(headers, None, mappings, rows, metadata={"supplier_name": "TEST", "supplier_gstin": "36AABCT1234F1Z5"})
    assert res["classification"] != "AUTO_ACCEPT"
    assert any("compound quantity" in b.lower() for b in res["auto_accept_blockers"])


def test_T_unrelated_plus_not_falsely_split():
    row = {
        "itemName": "CALCIUM + VITAMIN D3",
        "quantity": 10.0,
        "rate": 20.0,
        "amount": 200.0,
    }
    accounted = compute_row_accounting(row)
    assert accounted["itemName"] == "CALCIUM + VITAMIN D3"
    assert accounted["quantity"] == 10.0


def test_U_decimal_precision_preserved():
    tok = tokenize_compound_quantity("2.500+.500")
    assert tok["left_raw"] == "2.500"
    assert tok["right_raw"] == ".500"
    assert tok["left"] == 2.5
    assert tok["right"] == 0.5


def test_V_capita_benchmark_compound_quantity():
    fpath = "Sample Invoices/SI26-000698.pdf"
    if not os.path.exists(fpath):
        pytest.skip("Benchmark PDF not found")
    meta, hdrs, maps, rows = extract_pdf_table(fpath)
    assert len(rows) == 6
    # Check row 0
    r_dict = {maps[h]["mapped_to"]: rows[0][i] for i, h in enumerate(hdrs) if h in maps and maps[h].get("mapped_to")}
    acc = compute_row_accounting(r_dict)
    assert acc["quantity"] == 23.0
    assert float(acc["freeQuantity"]) == 2.0
    assert acc["_raw_values"]["quantity"] == "23+2"


def test_W_benchmark_regression_all_9_documents():
    is_valid, integrity = verify_golden_benchmark_v1()
    assert is_valid is True, f"Integrity failed: {integrity}"
    rep = evaluate_canonical_field_accuracy()
    assert rep.overall_field_accuracy >= 72.0
    assert rep.total_correct_cells >= 1440


def test_X_repeated_extraction_determinism():
    fpath = "Sample Invoices/SI26-000698.pdf"
    if not os.path.exists(fpath):
        pytest.skip("Benchmark PDF not found")
    meta1, hdrs1, maps1, rows1 = extract_pdf_table(fpath)
    meta2, hdrs2, maps2, rows2 = extract_pdf_table(fpath)
    assert hdrs1 == hdrs2
    assert rows1 == rows2
    assert maps1 == maps2


def test_Y_no_supplier_specific_branching():
    with open("extractor.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename="extractor.py")

    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test_src = ast.unparse(node.test)
            # Ensure no supplier or filename specific hardcoded branching
            for forbidden in ["CAPITA", "PRAPTI", "MOHIT", "PASHUPATI", "GAJANAND", "SHRI AJAY", "SUNIL MEDICARE", "SRI HARSHA", "SI26-000698", "PHUB_L22014"]:
                assert forbidden not in test_src, f"Hardcoded branch detected in extractor.py: {test_src}"
