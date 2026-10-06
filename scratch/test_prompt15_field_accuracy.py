"""
Unit and Integration Test Suite for Prompt 15:
Canonical Field-Level Ground Truth, Extraction Accuracy & Error Attribution
Tests A through Y (25 required test cases).
"""

import os
import json
import pytest
import math

from evaluation.field_ground_truth import (
    CANONICAL_FIELDS,
    CRITICAL_FIELDS,
    FINANCIAL_FIELDS,
    FieldPresenceState,
    RowClassification,
    AccountingStatus,
    AutoAcceptSafety,
    FieldGroundTruthCell,
    FieldGroundTruthRow,
    FieldGroundTruthDocument,
    FieldGroundTruthStore,
)
from evaluation.field_accuracy import (
    MatchType,
    normalize_text,
    normalize_date,
    parse_numeric,
    compare_text_field,
    compare_numeric_field,
    compare_date_field,
    compare_percentage_field,
    compare_integer_field,
    compare_field_value,
    detect_quantity_free_swap,
    detect_rate_mrp_swap,
    detect_batch_expiry_swap,
    detect_expiry_hsn_swap,
    detect_amount_gst_swap,
    detect_compound_quantity_collapsed,
    validate_row_accounting,
    evaluate_extracted_row,
    evaluate_canonical_field_accuracy,
)
from evaluation.evaluator import verify_golden_benchmark_v1
from evaluation.models import RootCause, DatasetCategory


SAMPLE_DIR = "Sample Invoices"
GOLDEN_MANIFEST = "evaluation/golden_manifest_v1.json"
FIELD_GT_MANIFEST = "evaluation/field_ground_truth_manifest.json"


class TestPrompt15FieldAccuracy:

    # A. golden manifest integrity
    def test_case_a_golden_manifest_integrity(self):
        is_valid, details = verify_golden_benchmark_v1(manifest_path=GOLDEN_MANIFEST, samples_dir=SAMPLE_DIR)
        assert is_valid is True, f"Golden benchmark v1 integrity failure: {details}"

    # B. field presence states
    def test_case_b_field_presence_states(self):
        store = FieldGroundTruthStore(manifest_path=FIELD_GT_MANIFEST)
        matrix = store.get_presence_matrix()
        assert len(matrix) == 9
        for fname, f_dict in matrix.items():
            assert "itemName" in f_dict
            assert f_dict["itemName"] == "YES"
            assert "quantity" in f_dict

    # C. UNKNOWN handling (must not penalize as extraction error)
    def test_case_c_unknown_handling(self):
        cell = FieldGroundTruthCell(field_name="discountPercent", state=FieldPresenceState.UNKNOWN, value=None)
        m_type, reason = compare_field_value("discountPercent", cell, "10.0")
        assert m_type == MatchType.IGNORED
        assert reason is None

    # D. NOT_PRESENT handling
    def test_case_d_not_present_handling(self):
        cell = FieldGroundTruthCell(field_name="cgstPercent", state=FieldPresenceState.NOT_PRESENT, value=None)
        m_type, reason = compare_field_value("cgstPercent", cell, 2.5)
        assert m_type == MatchType.IGNORED

    # E. numeric normalization
    def test_case_e_numeric_normalization(self):
        m_type = compare_numeric_field(159.00, "159.0", "rate")
        assert m_type in (MatchType.EXACT, MatchType.TOLERANCE)
        m_type_comma = compare_numeric_field(1590.50, "1,590.50", "amount")
        assert m_type_comma in (MatchType.EXACT, MatchType.TOLERANCE)

    # F. date normalization
    def test_case_f_date_normalization(self):
        assert normalize_date("11/27") == "11/27"
        assert normalize_date("11-27") == "11/27"
        assert normalize_date("0 8 - 2 6") == "08/26"
        assert normalize_date("8/27") == "08/27"
        m_type = compare_date_field("08/27", "8/27")
        assert m_type in (MatchType.EXACT, MatchType.NORMALIZED)

    # G. compound quantity
    def test_case_g_compound_quantity_detection(self):
        err = detect_compound_quantity_collapsed({"quantity": 23.0, "freeQuantity": ""}, "1BECOSULES CAP. 23+2 20`S")
        assert err is not None
        assert "Compound quantity" in err
        assert "free quantity 2.0 was lost" in err

    # H. monetary tolerance
    def test_case_h_monetary_tolerance(self):
        # Within tolerance (0.05 abs tol)
        m_type_close = compare_numeric_field(100.00, 100.02, "rate")
        assert m_type_close == MatchType.TOLERANCE

        # Outside tolerance: 1678.50 vs 1510.65 must be treated as materially different
        m_type_diff = compare_numeric_field(1678.50, 1510.65, "amount")
        assert m_type_diff == MatchType.MISMATCH

    # I. field mismatch
    def test_case_i_field_mismatch(self):
        cell = FieldGroundTruthCell(field_name="rate", state=FieldPresenceState.KNOWN, value=120.00)
        m_type, reason = compare_field_value("rate", cell, 450.00)
        assert m_type == MatchType.MISMATCH
        assert reason is not None

    # J. missing field
    def test_case_j_missing_field(self):
        cell = FieldGroundTruthCell(field_name="batchNo", state=FieldPresenceState.KNOWN, value="ARA26007")
        m_type, reason = compare_field_value("batchNo", cell, None)
        assert m_type == MatchType.MISSING
        assert "missing" in reason.lower()

    # K. extra field (unmapped in ground truth)
    def test_case_k_extra_field(self):
        cell = FieldGroundTruthCell(field_name="company", state=FieldPresenceState.KNOWN, value=None)
        m_type, reason = compare_field_value("company", cell, "ABBOT")
        assert m_type == MatchType.UNEXPECTED

    # L. row classification (FULLY_CORRECT)
    def test_case_l_row_classification_fully_correct(self):
        gt_row = FieldGroundTruthRow(
            row_index=0,
            cells={
                "itemName": FieldGroundTruthCell(field_name="itemName", value="TELPRES 40 TABS"),
                "quantity": FieldGroundTruthCell(field_name="quantity", value=5.0),
                "rate": FieldGroundTruthCell(field_name="rate", value=74.27),
                "amount": FieldGroundTruthCell(field_name="amount", value=371.35),
            }
        )
        pred = {"itemName": "TELPRES 40 TABS", "quantity": 5.0, "rate": 74.27, "amount": 371.35}
        eval_res = evaluate_extracted_row(pred, gt_row)
        assert eval_res.classification == RowClassification.FULLY_CORRECT

    # M. partial row correctness
    def test_case_m_partial_row_correctness(self):
        gt_row = FieldGroundTruthRow(
            row_index=0,
            cells={
                "itemName": FieldGroundTruthCell(field_name="itemName", value="TELPRES 40 TABS"),
                "quantity": FieldGroundTruthCell(field_name="quantity", value=5.0),
                "rate": FieldGroundTruthCell(field_name="rate", value=74.27),
                "amount": FieldGroundTruthCell(field_name="amount", value=371.35),
                "hsnCode": FieldGroundTruthCell(field_name="hsnCode", value="30049099"),
            }
        )
        # HSN mismatch, but all critical fields match
        pred = {"itemName": "TELPRES 40 TABS", "quantity": 5.0, "rate": 74.27, "amount": 371.35, "hsnCode": "1234"}
        eval_res = evaluate_extracted_row(pred, gt_row)
        assert eval_res.classification == RowClassification.PARTIALLY_CORRECT

    # N. critical field error
    def test_case_n_critical_field_error(self):
        gt_row = FieldGroundTruthRow(
            row_index=0,
            cells={
                "itemName": FieldGroundTruthCell(field_name="itemName", value="TELPRES 40 TABS"),
                "quantity": FieldGroundTruthCell(field_name="quantity", value=5.0),
                "rate": FieldGroundTruthCell(field_name="rate", value=74.27),
                "amount": FieldGroundTruthCell(field_name="amount", value=371.35),
            }
        )
        # Amount incorrect
        pred = {"itemName": "TELPRES 40 TABS", "quantity": 5.0, "rate": 74.27, "amount": 999.99}
        eval_res = evaluate_extracted_row(pred, gt_row)
        assert eval_res.classification == RowClassification.CRITICAL_FIELD_ERROR
        assert len(eval_res.critical_errors) > 0

    # O. accounting consistency
    def test_case_o_accounting_consistency(self):
        # Qty = 10, Rate = 20, Amount = 200
        st, note = validate_row_accounting({"quantity": 10.0, "rate": 20.0, "amount": 200.0})
        assert st == AccountingStatus.ACCOUNTING_CONSISTENT

    # P. accounting insufficiency
    def test_case_p_accounting_insufficiency(self):
        st, note = validate_row_accounting({"quantity": 10.0, "rate": None, "amount": None})
        assert st == AccountingStatus.INSUFFICIENT_DATA

    # Q. error taxonomy
    def test_case_q_error_taxonomy(self):
        gt_row = FieldGroundTruthRow(
            row_index=0,
            cells={
                "quantity": FieldGroundTruthCell(field_name="quantity", value=10.0),
                "freeQuantity": FieldGroundTruthCell(field_name="freeQuantity", value=2.0),
                "itemName": FieldGroundTruthCell(field_name="itemName", value="TEST DRUG"),
                "rate": FieldGroundTruthCell(field_name="rate", value=50.0),
                "amount": FieldGroundTruthCell(field_name="amount", value=500.0),
            }
        )
        # Swapped qty and free
        pred = {"quantity": 2.0, "freeQuantity": 10.0, "itemName": "TEST DRUG", "rate": 50.0, "amount": 500.0}
        eval_res = evaluate_extracted_row(pred, gt_row)
        assert eval_res.root_cause == RootCause.SEMANTIC_MAPPING
        assert any("swapped" in err.lower() for err in eval_res.detected_high_risk_errors)

    # R. confidence buckets
    def test_case_r_confidence_buckets(self):
        summary = evaluate_canonical_field_accuracy()
        assert len(summary.confidence_buckets) == 7
        total_bucket_docs = sum(b.total_documents for b in summary.confidence_buckets)
        assert total_bucket_docs == 9

    # S. AUTO_ACCEPT safety
    def test_case_s_auto_accept_safety(self):
        summary = evaluate_canonical_field_accuracy()
        auto_accept_docs = [d for d in summary.document_reports if d.decision == "AUTO_ACCEPT"]
        assert len(auto_accept_docs) >= 3
        safe_count = sum(1 for d in auto_accept_docs if d.auto_accept_safety == AutoAcceptSafety.AUTO_ACCEPT_SAFE)
        unsafe_count = sum(1 for d in auto_accept_docs if d.auto_accept_safety == AutoAcceptSafety.AUTO_ACCEPT_UNSAFE)
        assert safe_count >= 3
        assert unsafe_count == 0  # 100% AUTO_ACCEPT safety precision (0 false accepts)

    # T. canonical benchmark immutability
    def test_case_t_canonical_benchmark_immutability(self):
        with open(GOLDEN_MANIFEST, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest["immutable"] is True
        assert manifest["benchmark_version"] == "v1.0"

    # U. no ground-truth self-copying
    def test_case_u_no_ground_truth_self_copying(self):
        store = FieldGroundTruthStore(manifest_path=FIELD_GT_MANIFEST)
        doc = store.get_document("SI26-000698.pdf")
        assert doc is not None
        row1 = doc.get_row(0)
        # Ground truth has freeQuantity=2.0 for 23+2, extractor predicts ''
        assert row1.get_cell("freeQuantity").value == 2.0
        assert row1.get_cell("quantity").value == 23.0

    # V. supplier identity preservation
    def test_case_v_supplier_identity_preservation(self):
        summary = evaluate_canonical_field_accuracy()
        expected_suppliers = {
            "INVOICE_7GU0X28XM.PDF": "PRAPTI MEDICARE",
            "INVOICE_7GX167AKM.PDF": "MOHIT PHARMA",
            "INVOICE_7HC0MTOZ2.PDF": "PASHUPATI MEDICAL DISTRIBUTORS",
            "INVOICE_7HH0S5IPC.PDF": "GAJANAND MEDICAL AGENCIES",
            "Invoice.pdf": "JP LOGISTICS",
            "PHUB_L22014.pdf": "SHRI AJAY MEDICAL AGENCIES",
            "SI26-000698.pdf": "CAPITA MediHub",
            "Sunil_Medicare_Sample_Invoice.pdf": "SUNIL MEDICARE",
            "invoice (1).pdf": "SRI HARSHA PHARMA",
        }
        for d in summary.document_reports:
            assert d.supplier_name == expected_suppliers[d.filename]

    # W. 9-document canonical count
    def test_case_w_9_document_canonical_count(self):
        summary = evaluate_canonical_field_accuracy()
        assert summary.total_documents == 9
        assert len(summary.document_reports) == 9

    # X. 148 physical row count
    def test_case_x_148_physical_row_count(self):
        with open(GOLDEN_MANIFEST, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest["total_expected_rows"] == 148

    # Y. 147 clean-row count
    def test_case_y_147_clean_row_count(self):
        summary = evaluate_canonical_field_accuracy()
        assert summary.total_clean_rows == 147
