"""
MediAstra Pharma PDF Purchase Import Engine - Prompt 13 Comprehensive Test Suite
Tests targeted repairs: Header token joining, column boundaries, sub-column splitting,
auxiliary column classification, AUTO_ACCEPT safety gating, and confidence semantics.
"""

import json
import os
import shutil
import tempfile
import pytest

from extractor import (
    extract_pdf_table,
    reconstruct_header_tokens,
    determine_column_boundaries,
    detect_logical_subcolumns,
    compute_global_validation_and_confidence,
    check_duplicate_field_assignments,
    validate_supplier_identity_safety,
    ALIAS_DICT,
)
from evaluation.models import (
    RootCause,
    DatasetCategory,
    EvaluationManifestItem,
    GroundTruthDocument,
    GroundTruthRow,
)
from evaluation.evaluator import InvoiceEvaluator
from evaluation.report_generator import EvaluationReportGenerator


@pytest.fixture
def temp_dir():
    t_dir = tempfile.mkdtemp(prefix="mediastra_p13_test_")
    yield t_dir
    shutil.rmtree(t_dir, ignore_errors=True)


class TestPrompt13TargetedRepairsSuite:
    """Test suite for Prompt 13 targeted improvements (Cases A through W)."""

    # A. MR + P -> MRP
    def test_case_a_mrp_header_joining(self):
        words = [
            {"text": "MR", "x0": 100.0, "x1": 115.0, "top": 50.0, "bottom": 60.0},
            {"text": "P", "x0": 116.0, "x1": 122.0, "top": 50.0, "bottom": 60.0},
        ]
        reconstructed = reconstruct_header_tokens(words)
        assert len(reconstructed) == 1
        line = reconstructed[0]
        assert len(line) == 1
        assert line[0]["text"] == "MRP"

    # B. PT + R -> PTR
    def test_case_b_ptr_header_joining(self):
        words = [
            {"text": "PT", "x0": 150.0, "x1": 165.0, "top": 50.0, "bottom": 60.0},
            {"text": "R", "x0": 166.0, "x1": 172.0, "top": 50.0, "bottom": 60.0},
        ]
        reconstructed = reconstruct_header_tokens(words)
        assert len(reconstructed) == 1
        line = reconstructed[0]
        assert len(line) == 1
        assert line[0]["text"] == "PTR"

    # C. RAT + E -> RATE
    def test_case_c_rate_header_joining(self):
        words = [
            {"text": "RAT", "x0": 200.0, "x1": 218.0, "top": 50.0, "bottom": 60.0},
            {"text": "E", "x0": 219.0, "x1": 225.0, "top": 50.0, "bottom": 60.0},
        ]
        reconstructed = reconstruct_header_tokens(words)
        assert len(reconstructed) == 1
        line = reconstructed[0]
        assert len(line) == 1
        assert line[0]["text"] == "RATE"

    # D. Separated header fragments remain separate when gap is large
    def test_case_d_separated_header_fragments_remain_separate(self):
        words = [
            {"text": "QTY", "x0": 100.0, "x1": 120.0, "top": 50.0, "bottom": 60.0},
            {"text": "RATE", "x0": 145.0, "x1": 170.0, "top": 50.0, "bottom": 60.0},  # 25pt gap
        ]
        reconstructed = reconstruct_header_tokens(words)
        assert len(reconstructed) == 1
        line = reconstructed[0]
        assert len(line) == 2
        assert line[0]["text"] == "QTY"
        assert line[1]["text"] == "RATE"

    # E. Physical column with QTY + FREE
    def test_case_e_physical_column_qty_free(self):
        phys_cols = [{
            "index": 0, "header_raw": "QTY FREE", "header_text": "QTY FREE",
            "field": None, "x0": 100.0, "x1": 200.0, "center_x": 150.0
        }]
        row_groups = [
            [{"text": "10.0", "x0": 110.0, "x1": 130.0, "center_x": 120.0}, {"text": "1.0", "x0": 160.0, "x1": 180.0, "center_x": 170.0}],
            [{"text": "20.0", "x0": 110.0, "x1": 130.0, "center_x": 120.0}, {"text": "2.0", "x0": 160.0, "x1": 180.0, "center_x": 170.0}],
            [{"text": "5.0", "x0": 110.0, "x1": 130.0, "center_x": 120.0}, {"text": "0.0", "x0": 160.0, "x1": 180.0, "center_x": 170.0}],
            [{"text": "15.0", "x0": 110.0, "x1": 130.0, "center_x": 120.0}, {"text": "1.0", "x0": 160.0, "x1": 180.0, "center_x": 170.0}],
        ]
        logical_cols, diag = detect_logical_subcolumns(phys_cols, row_groups)
        assert len(logical_cols) == 2
        assert logical_cols[0]["field"] == "quantity"
        assert logical_cols[1]["field"] == "freeQuantity"

    # F. Physical column with AMOUNT + GST
    def test_case_f_physical_column_amount_gst(self):
        phys_cols = [{
            "index": 0, "header_raw": "AMOUNT GST", "header_text": "AMOUNT GST",
            "field": None, "x0": 200.0, "x1": 320.0, "center_x": 260.0
        }]
        row_groups = [
            [{"text": "1500.00", "x0": 210.0, "x1": 250.0, "center_x": 230.0}, {"text": "12%", "x0": 280.0, "x1": 305.0, "center_x": 292.0}],
            [{"text": "450.50", "x0": 210.0, "x1": 250.0, "center_x": 230.0}, {"text": "12%", "x0": 280.0, "x1": 305.0, "center_x": 292.0}],
            [{"text": "820.00", "x0": 210.0, "x1": 250.0, "center_x": 230.0}, {"text": "18%", "x0": 280.0, "x1": 305.0, "center_x": 292.0}],
            [{"text": "120.00", "x0": 210.0, "x1": 250.0, "center_x": 230.0}, {"text": "5%", "x0": 280.0, "x1": 305.0, "center_x": 292.0}],
        ]
        logical_cols, diag = detect_logical_subcolumns(phys_cols, row_groups)
        assert len(logical_cols) == 2
        assert logical_cols[0]["field"] == "amount"
        assert logical_cols[1]["field"] == "gstPercent"

    # G. Physical column with CGST + SGST
    def test_case_g_physical_column_cgst_sgst(self):
        phys_cols = [{
            "index": 0, "header_raw": "CGST SGST", "header_text": "CGST SGST",
            "field": None, "x0": 300.0, "x1": 420.0, "center_x": 360.0
        }]
        row_groups = [
            [{"text": "6.00%", "x0": 310.0, "x1": 340.0, "center_x": 325.0}, {"text": "6.00%", "x0": 370.0, "x1": 400.0, "center_x": 385.0}],
            [{"text": "9.00%", "x0": 310.0, "x1": 340.0, "center_x": 325.0}, {"text": "9.00%", "x0": 370.0, "x1": 400.0, "center_x": 385.0}],
            [{"text": "2.50%", "x0": 310.0, "x1": 340.0, "center_x": 325.0}, {"text": "2.50%", "x0": 370.0, "x1": 400.0, "center_x": 385.0}],
            [{"text": "6.00%", "x0": 310.0, "x1": 340.0, "center_x": 325.0}, {"text": "6.00%", "x0": 370.0, "x1": 400.0, "center_x": 385.0}],
        ]
        logical_cols, diag = detect_logical_subcolumns(phys_cols, row_groups)
        assert len(logical_cols) == 2
        assert logical_cols[0]["field"] == "cgstPercent"
        assert logical_cols[1]["field"] == "sgstPercent"

    # H. Auxiliary serial-number column is not counted as canonical extraction failure
    def test_case_h_auxiliary_serial_number_column(self):
        evaluator = InvoiceEvaluator()
        rc = evaluator.classify_mapping_error("S.No.", None, None)
        assert rc == RootCause.AUXILIARY_COLUMN

        rc_sr = evaluator.classify_mapping_error("SR NO", None, None)
        assert rc_sr == RootCause.AUXILIARY_COLUMN

    # I. Genuinely incorrect boundary is still classified as an error
    def test_case_i_genuinely_incorrect_boundary_error(self):
        evaluator = InvoiceEvaluator()
        rc = evaluator.classify_mapping_error("RATE", None, "rate")
        assert rc == RootCause.TRUE_COLUMN_BOUNDARY_ERROR

    # J. Missing source field is different from extraction failure
    def test_case_j_missing_source_field_handling(self):
        evaluator = InvoiceEvaluator()
        # Invoice has 2 fields in ground truth: itemName and quantity. Source does not have MRP.
        gt_rows = [GroundTruthRow(row_index=0, fields={"itemName": "PARACETAMOL", "quantity": 10.0})]
        ext_rows = [{"itemName": "PARACETAMOL", "quantity": 10.0}]

        metrics = evaluator.evaluate_field_level(ext_rows, gt_rows)
        # MRP was not in source/ground-truth, so total_ground_truth for MRP is 0
        assert metrics["mrp"].total_ground_truth == 0
        assert metrics["mrp"].missing_predictions == 0
        assert metrics["itemName"].precision == 1.0

    # K. Ambiguous required field blocks AUTO_ACCEPT
    def test_case_k_ambiguous_field_blocks_auto_accept(self):
        headers = ["PRODUCT", "QTY"]
        logical_cols = [
            {"header_text": "PRODUCT", "field": "itemName", "status": "clean"},
            {"header_text": "QTY", "field": "quantity", "status": "ambiguous"},  # Ambiguous sub-column
        ]
        col_mappings = {
            "PRODUCT": {"mapped_to": "itemName", "status": "known_header"},
            "QTY": {"mapped_to": "quantity", "status": "ambiguous"},
        }
        rows = [["PARACETAMOL 500", "10"]]
        res = compute_global_validation_and_confidence(headers, logical_cols, col_mappings, rows)
        assert res["classification"] != "AUTO_ACCEPT"
        assert any("ambiguity" in b.lower() for b in res.get("auto_accept_blockers", []))

    # L. Valid arithmetic evidence permits AUTO_ACCEPT
    def test_case_l_valid_arithmetic_permits_auto_accept(self):
        headers = ["PRODUCT NAME", "PACK", "BATCH", "EXPIRY", "QTY", "RATE", "AMOUNT"]
        logical_cols = [
            {"header_text": h, "field": ALIAS_DICT.get(h, h), "status": "clean"} for h in headers
        ]
        col_mappings = {
            "PRODUCT NAME": {"mapped_to": "itemName", "status": "known_header"},
            "PACK": {"mapped_to": "pack", "status": "known_header"},
            "BATCH": {"mapped_to": "batchNo", "status": "known_header"},
            "EXPIRY": {"mapped_to": "expiryDate", "status": "known_header"},
            "QTY": {"mapped_to": "quantity", "status": "known_header"},
            "RATE": {"mapped_to": "rate", "status": "known_header"},
            "AMOUNT": {"mapped_to": "amount", "status": "known_header"},
        }
        rows = [
            ["AMOXICILLIN 500MG", "10 TAB", "AM100", "12/26", "10.0", "50.00", "500.00"],
            ["PARACETAMOL 650MG", "15 TAB", "PC200", "08/25", "20.0", "30.00", "600.00"],
            ["AZITHROMYCIN 500", "3 TAB", "AZ300", "11/26", "5.0", "120.00", "600.00"],
            ["CETIRIZINE 10MG", "10 TAB", "CT400", "05/27", "10.0", "20.00", "200.00"],
            ["PANTOPRAZOLE 40", "10 TAB", "PT500", "09/26", "15.0", "80.00", "1200.00"],
        ]
        meta = {"supplier_name": "GENERIC PHARMA DISTRIBUTORS", "supplier_gstin": "36AAAFP1234A1Z1", "supplier_confidence": 1.0}
        res = compute_global_validation_and_confidence(headers, logical_cols, col_mappings, rows, metadata=meta)
        assert res["classification"] == "AUTO_ACCEPT"
        assert res["document_confidence"] >= 80.0
        assert len(res.get("auto_accept_blockers", [])) == 0

    # M. Failed critical validation blocks AUTO_ACCEPT
    def test_case_m_failed_critical_validation_blocks_auto_accept(self):
        headers = ["PRODUCT NAME", "QTY", "RATE", "AMOUNT"]
        logical_cols = [{"header_text": h, "field": h, "status": "clean"} for h in headers]
        col_mappings = {
            "PRODUCT NAME": {"mapped_to": "itemName", "status": "known_header"},
            "QTY": {"mapped_to": "quantity", "status": "known_header"},
            "RATE": {"mapped_to": "rate", "status": "known_header"},
            "AMOUNT": {"mapped_to": "amount", "status": "known_header"},
        }
        # Math error: 10 * 50 = 500 != 9999.00
        rows = [["AMOXICILLIN", "10.0", "50.00", "9999.00"]]
        res = compute_global_validation_and_confidence(headers, logical_cols, col_mappings, rows)
        assert res["classification"] != "AUTO_ACCEPT"

    # N. Duplicate canonical mapping blocks AUTO_ACCEPT
    def test_case_n_duplicate_canonical_mapping_blocks_auto_accept(self):
        headers = ["PRODUCT", "QTY_1", "QTY_2"]
        logical_cols = [{"header_text": h, "field": h, "status": "clean"} for h in headers]
        col_mappings = {
            "PRODUCT": {"mapped_to": "itemName", "status": "known_header"},
            "QTY_1": {"mapped_to": "quantity", "status": "known_header"},
            "QTY_2": {"mapped_to": "quantity", "status": "known_header"},  # Duplicate quantity
        }
        rows = [["PRODUCT A", "10", "10"]]
        res = compute_global_validation_and_confidence(headers, logical_cols, col_mappings, rows)
        assert res["classification"] != "AUTO_ACCEPT"
        assert any("duplicate" in b.lower() for b in res.get("auto_accept_blockers", []))

    # O. Unresolved logical sub-column blocks AUTO_ACCEPT
    def test_case_o_unresolved_logical_subcolumn_blocks_auto_accept(self):
        headers = ["PRODUCT", "COMPOSITE_COL"]
        logical_cols = [
            {"header_text": "PRODUCT", "field": "itemName", "status": "clean"},
            {"header_text": "COMPOSITE_COL", "field": None, "status": "ambiguous"},
        ]
        col_mappings = {
            "PRODUCT": {"mapped_to": "itemName", "status": "known_header"},
            "COMPOSITE_COL": {"mapped_to": "quantity", "status": "ambiguous"},
        }
        rows = [["PRODUCT A", "10 5%"]]
        res = compute_global_validation_and_confidence(headers, logical_cols, col_mappings, rows)
        assert res["classification"] != "AUTO_ACCEPT"

    # P. Supplier identity safety still works
    def test_case_p_supplier_identity_safety(self):
        # Low confidence supplier name requires review
        safety = validate_supplier_identity_safety("UNKNOWN TRADERS", "", name_confidence=0.50)
        assert safety["is_safe_to_attach"] is False
        assert "review" in safety["status"].lower() or "review" in safety["details"].lower()

    # Q. Layout/profile safety still works
    def test_case_q_layout_profile_safety(self):
        evaluator = InvoiceEvaluator()
        manifest_items = [
            EvaluationManifestItem("d1", "f1.pdf", "Sample Invoices/INVOICE_7GU0X28XM.PDF", "c26b45256359ae1674a2c8b1010fe545da32d142b305944de57e2f04a8625b1e", DatasetCategory.GOLDEN, supplier_name="PRAPTI"),
        ]
        div = evaluator.compute_layout_diversity(manifest_items, [{"supplier_name": "PRAPTI", "layout_profile_id": "layout_1"}])
        assert div["unique_suppliers_count"] == 1

    # R. Confidence bucket with no ground truth is excluded from accuracy
    def test_case_r_confidence_bucket_no_ground_truth_excluded(self):
        evaluator = InvoiceEvaluator()
        sample_docs = [
            {"confidence": 92.0, "is_correct": False, "ground_truth_available": False, "decision": "AUTO_ACCEPT"},
        ]
        buckets = evaluator.evaluate_confidence_calibration(sample_docs)
        b_90_95 = next(b for b in buckets if b.bucket_name == "90-95")
        assert b_90_95.total_documents == 1
        assert b_90_95.sample_count == 1
        assert b_90_95.unknown_count == 1
        assert b_90_95.correct_documents == 0
        assert b_90_95.incorrect_documents == 0
        assert b_90_95.empirical_accuracy == 0.0

    # S. One-document confidence bucket reports sample size correctly
    def test_case_s_one_document_confidence_bucket_sample_size(self):
        evaluator = InvoiceEvaluator()
        sample_docs = [
            {"confidence": 85.0, "is_correct": True, "ground_truth_available": True, "decision": "REVIEW_REQUIRED"},
        ]
        buckets = evaluator.evaluate_confidence_calibration(sample_docs)
        b_80_90 = next(b for b in buckets if b.bucket_name == "80-90")
        assert b_80_90.sample_count == 1
        assert b_80_90.correct_documents == 1
        assert b_80_90.empirical_accuracy == 1.0

    # T. Golden benchmark remains unchanged
    def test_case_t_golden_benchmark_unchanged(self):
        manifest_path = "benchmark_manifest.json"
        assert os.path.exists(manifest_path)
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["samples"]) == 9

    # U. No supplier-specific hardcoding
    def test_case_u_no_supplier_specific_hardcoding(self):
        extractor_path = "extractor.py"
        with open(extractor_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "if supplier ==" not in content
        assert "if supplier_name ==" not in content
        assert "if filename ==" not in content

    # V. Repeated extraction remains deterministic
    def test_case_v_repeated_extraction_deterministic(self):
        fpath = "Sample Invoices/INVOICE_7GX167AKM.PDF"
        m1, h1, map1, rows1 = extract_pdf_table(fpath)
        m2, h2, map2, rows2 = extract_pdf_table(fpath)
        assert len(rows1) == len(rows2)
        assert m1["confidence"] == m2["confidence"]
        assert m1["classification"] == m2["classification"]

    # W. Full regression compatibility
    def test_case_w_full_regression_compatibility(self):
        fpath = "Sample Invoices/SI26-000698.pdf"
        meta, headers, mappings, rows = extract_pdf_table(fpath)
        assert len(rows) == 6
        assert meta["classification"] == "AUTO_ACCEPT"

    # X. Continuation and amount-in-words footer suppression (e.g. invoice (1).pdf)
    def test_case_x_continuation_and_amount_in_words_footer_suppression(self):
        fpath = "Sample Invoices/invoice (1).pdf"
        if os.path.exists(fpath):
            meta, headers, mappings, rows = extract_pdf_table(fpath)
            # Must extract exactly the 39 genuine medicines without leaking 'Rs. Ninety Five Thousand...' footer
            assert len(rows) == 39
            for r in rows:
                joined = " ".join(str(c) for c in r if c).lower()
                assert "thousand" not in joined
                assert "hundred and" not in joined
                assert "continue page" not in joined
                assert "seven only" not in joined
