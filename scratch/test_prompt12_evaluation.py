"""
MediAstra Pharma PDF Purchase Import Engine - Prompt 12 Comprehensive Test Suite
Tests evaluation dataset manifest, ground truth loader, field/row/mapping metrics,
root-cause classification, confidence calibration, safety analysis, and reporting.
"""

import hashlib
import json
import os
import shutil
import tempfile
import pytest

from evaluation.ground_truth import GroundTruthStore, GOLDEN_BENCHMARK_GROUND_TRUTH
from evaluation.models import (
    CANONICAL_FIELDS,
    ColumnMappingEvaluation,
    ConfidenceBucketResult,
    DatasetCategory,
    DiagnosticErrorContext,
    DifficultLayoutFlag,
    EvaluationManifestItem,
    FieldMetricResult,
    GroundTruthDocument,
    GroundTruthRow,
    NUMERIC_FIELD_TOLERANCES,
    RootCause,
    RowMetricResult,
    SupplierLayoutStat,
)
from evaluation.evaluator import InvoiceEvaluator
from evaluation.report_generator import EvaluationReportGenerator


@pytest.fixture
def temp_eval_dir():
    temp_dir = tempfile.mkdtemp(prefix="mediastra_eval_test_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestPrompt12EvaluationSuite:
    """Test suite for Prompt 12 evaluation framework (Cases A through Z)."""

    # A. Manifest creation
    def test_case_a_manifest_creation(self, temp_eval_dir):
        manifest_file = os.path.join(temp_eval_dir, "manifest.json")
        item = EvaluationManifestItem(
            document_id="doc_001",
            filename="test_inv.pdf",
            file_path="Sample Invoices/test_inv.pdf",
            sha256="abc123hash",
            dataset_category=DatasetCategory.GOLDEN,
            supplier_name="MED SUPPLIER",
            gstin="36AASFP4005A1ZJ",
            expected_row_count=10,
            ground_truth_available=True,
        )
        data = {"manifest_version": "1.0", "documents": [item.to_dict()]}
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        evaluator = InvoiceEvaluator(manifest_path=manifest_file)
        assert len(evaluator.manifest_items) == 1
        assert evaluator.manifest_items[0].document_id == "doc_001"
        assert evaluator.manifest_items[0].dataset_category == DatasetCategory.GOLDEN

    # B. SHA-256 validation
    def test_case_b_sha256_validation(self, temp_eval_dir):
        test_file = os.path.join(temp_eval_dir, "sample.bin")
        content = b"TEST PDF DATA FOR HASH CHECK"
        with open(test_file, "wb") as f:
            f.write(content)
        expected_hash = hashlib.sha256(content).hexdigest()

        evaluator = InvoiceEvaluator()
        computed = evaluator.compute_sha256(test_file)
        assert computed == expected_hash

    # C. Dataset category handling
    def test_case_c_dataset_category_handling(self):
        cats = [
            DatasetCategory.GOLDEN,
            DatasetCategory.REAL,
            DatasetCategory.SYNTHETIC,
            DatasetCategory.EDGE_CASE,
        ]
        for cat in cats:
            item = EvaluationManifestItem(
                document_id="d1",
                filename="f1.pdf",
                file_path="p1",
                sha256="h1",
                dataset_category=cat,
            )
            d = item.to_dict()
            assert d["dataset_category"] == cat.value
            loaded = EvaluationManifestItem.from_dict(d)
            assert loaded.dataset_category == cat

    # D. Ground-truth loading
    def test_case_d_ground_truth_loading(self, temp_eval_dir):
        gt_file = os.path.join(temp_eval_dir, "gt.json")
        doc = GroundTruthDocument(
            document_id="doc_gt_1",
            filename="inv1.pdf",
            rows=[
                GroundTruthRow(row_index=0, fields={"itemName": "PARACETAMOL", "rate": 50.0}),
                GroundTruthRow(row_index=1, fields={"itemName": "AMOXICILLIN", "rate": 120.0}),
            ],
            column_mappings={"ITEM": "itemName", "PRICE": "rate"},
        )
        store = GroundTruthStore(ground_truth_file=gt_file)
        store.save_ground_truth(doc)

        # Reload store
        store_reloaded = GroundTruthStore(ground_truth_file=gt_file)
        retrieved = store_reloaded.get_ground_truth("doc_gt_1")
        assert retrieved is not None
        assert retrieved.filename == "inv1.pdf"
        assert len(retrieved.rows) == 2
        assert retrieved.rows[0].fields["itemName"] == "PARACETAMOL"

    # E. Missing ground-truth handling
    def test_case_e_missing_ground_truth_handling(self):
        store = GroundTruthStore()
        result = store.get_ground_truth("non_existent_id_xyz")
        assert result is None

    # F. Exact field matching
    def test_case_f_exact_field_matching(self):
        evaluator = InvoiceEvaluator()
        exact, norm, tol = evaluator.compare_field_values("itemName", "PARACETAMOL 500", "PARACETAMOL 500")
        assert exact is True
        assert norm is True
        assert tol is False

    # G. Normalized field matching
    def test_case_g_normalized_field_matching(self):
        evaluator = InvoiceEvaluator()
        exact, norm, tol = evaluator.compare_field_values("expiryDate", "12-2026", "12/2026")
        assert exact is False
        assert norm is True

        exact2, norm2, _ = evaluator.compare_field_values("itemName", "  paracetamol   tab  ", "PARACETAMOL TAB")
        assert exact2 is False
        assert norm2 is True

    # H. Numeric tolerance matching
    def test_case_h_numeric_tolerance_matching(self):
        evaluator = InvoiceEvaluator()
        # Rate with 0.02 difference (within 0.05 abs_tol)
        exact, norm, tol = evaluator.compare_field_values("rate", 120.52, 120.50)
        assert exact is False
        assert tol is True

        # Quantity with 0.005 difference (within 0.01)
        exact_q, norm_q, tol_q = evaluator.compare_field_values("quantity", 10.005, 10.0)
        assert tol_q is True

        # Quantity with 0.5 difference (exceeds 0.01)
        _, _, tol_large = evaluator.compare_field_values("quantity", 10.5, 10.0)
        assert tol_large is False

    # I. Missing field handling
    def test_case_i_missing_field_handling(self):
        evaluator = InvoiceEvaluator()
        ext_rows = [{"itemName": "AZITHRAL"}]
        gt_rows = [GroundTruthRow(row_index=0, fields={"itemName": "AZITHRAL", "mrp": 150.0})]

        metrics = evaluator.evaluate_field_level(ext_rows, gt_rows)
        assert metrics["mrp"].missing_predictions == 1
        assert metrics["itemName"].exact_matches == 1

    # J. Unexpected field handling
    def test_case_j_unexpected_field_handling(self):
        evaluator = InvoiceEvaluator()
        ext_rows = [{"itemName": "AZITHRAL", "company": "ALEMBIC"}]
        gt_rows = [GroundTruthRow(row_index=0, fields={"itemName": "AZITHRAL"})]

        metrics = evaluator.evaluate_field_level(ext_rows, gt_rows)
        assert metrics["itemName"].exact_matches == 1
        assert metrics["company"].unexpected_predictions == 1

    # K. Row matching
    def test_case_k_row_matching(self):
        evaluator = InvoiceEvaluator()
        ext_rows = [
            {"itemName": "PAN D CAPSULE", "batchNo": "PD100", "rate": 80.0},
            {"itemName": "TELMA 40MG", "batchNo": "TL200", "rate": 110.0},
        ]
        gt_rows = [
            GroundTruthRow(row_index=0, fields={"itemName": "PAN D CAPSULE", "batchNo": "PD100"}),
            GroundTruthRow(row_index=1, fields={"itemName": "TELMA 40MG", "batchNo": "TL200"}),
        ]
        res = evaluator.evaluate_row_level(ext_rows, gt_rows)
        assert res.matched_rows == 2
        assert res.missing_rows == 0
        assert res.extra_rows == 0
        assert res.row_accuracy == 1.0

    # L. Duplicate-row detection
    def test_case_l_duplicate_row_detection(self):
        evaluator = InvoiceEvaluator()
        ext_rows = [
            {"itemName": "PAN D", "batchNo": "B1", "rate": 50.0},
            {"itemName": "PAN D", "batchNo": "B1", "rate": 50.0},  # duplicate
            {"itemName": "TELMA", "batchNo": "B2", "rate": 70.0},
        ]
        res = evaluator.evaluate_row_level(ext_rows, [])
        assert res.duplicate_rows == 1

    # M. Split-row detection
    def test_case_m_split_row_detection(self):
        evaluator = InvoiceEvaluator()
        ext_rows = [
            {"itemName": "PRODUCT PART 1"},
            {"itemName": "PRODUCT PART 2"},
            {"itemName": "ANOTHER PRODUCT"},
        ]
        res = evaluator.evaluate_row_level(ext_rows, [], expected_count=2)
        assert res.split_rows == 1

    # N. Merged-row detection
    def test_case_n_merged_row_detection(self):
        evaluator = InvoiceEvaluator()
        ext_rows = [
            {"itemName": "COMBINED PRODUCT 1 & 2"},
        ]
        res = evaluator.evaluate_row_level(ext_rows, [], expected_count=2)
        assert res.merged_rows == 1

    # O. Mapping accuracy
    def test_case_o_mapping_accuracy(self):
        evaluator = InvoiceEvaluator()
        pred = {"ITEM": "itemName", "RATE": "rate", "MRP": "mrp"}
        gt = {"ITEM": "itemName", "RATE": "rate", "MRP": "mrp"}
        evals = evaluator.evaluate_column_mappings("doc1", pred, gt)
        assert len(evals) == 3
        assert all(e.is_correct for e in evals)

    # P. Confusion matrix generation
    def test_case_p_confusion_matrix_generation(self):
        evaluator = InvoiceEvaluator()
        pred = {"ITEM": "itemName", "PRICE": "mrp"}  # PRICE was expected to be rate
        gt = {"ITEM": "itemName", "PRICE": "rate"}
        evals = evaluator.evaluate_column_mappings("doc1", pred, gt)
        incorrect = [e for e in evals if not e.is_correct]
        assert len(incorrect) == 1
        assert incorrect[0].expected_canonical == "rate"
        assert incorrect[0].predicted_canonical == "mrp"

    # Q. Error category classification
    def test_case_q_error_category_classification(self):
        evaluator = InvoiceEvaluator()
        # Split header
        rc_header = evaluator.classify_mapping_error("PT R", "rate", "rate")
        assert rc_header == RootCause.HEADER_RECONSTRUCTION

        # Logical sub-column
        rc_subcol = evaluator.classify_mapping_error("PACK QTY FREE", "quantity", "quantity")
        assert rc_subcol == RootCause.LOGICAL_SUBCOLUMN_SPLIT

        # Semantic confusion
        rc_semantic = evaluator.classify_mapping_error("RATE", "mrp", "rate")
        assert rc_semantic == RootCause.SEMANTIC_MAPPING

    # R. Supplier statistics
    def test_case_r_supplier_statistics(self):
        manifest_items = [
            EvaluationManifestItem("d1", "f1.pdf", "Sample Invoices/INVOICE_7GU0X28XM.PDF", "c26b45256359ae1674a2c8b1010fe545da32d142b305944de57e2f04a8625b1e", DatasetCategory.GOLDEN, supplier_name="SUPPLIER A", expected_row_count=11),
        ]
        evaluator = InvoiceEvaluator()
        results = evaluator.run_evaluation(manifest_items)
        assert len(results["supplier_statistics"]) > 0
        stat = results["supplier_statistics"][0]
        assert "supplier_name" in stat
        assert "auto_accept_pct" in stat
        assert "avg_confidence" in stat

    # S. Layout statistics
    def test_case_s_layout_statistics(self):
        evaluator = InvoiceEvaluator()
        manifest_items = [
            EvaluationManifestItem("d1", "f1.pdf", "Sample Invoices/INVOICE_7GU0X28XM.PDF", "c26b45256359ae1674a2c8b1010fe545da32d142b305944de57e2f04a8625b1e", DatasetCategory.GOLDEN, supplier_name="PRAPTI"),
        ]
        div = evaluator.compute_layout_diversity(manifest_items, [{"supplier_name": "PRAPTI", "layout_profile_id": "layout_1"}])
        assert div["unique_suppliers_count"] == 1
        assert div["unique_layout_profiles_count"] == 1

    # T. Confidence bucket analysis
    def test_case_t_confidence_bucket_analysis(self):
        evaluator = InvoiceEvaluator()
        sample_docs = [
            {"confidence": 92.0, "is_correct": True, "decision": "AUTO_ACCEPT"},
            {"confidence": 94.0, "is_correct": False, "decision": "AUTO_ACCEPT"},
            {"confidence": 65.0, "is_correct": True, "decision": "REVIEW_REQUIRED"},
        ]
        buckets = evaluator.evaluate_confidence_calibration(sample_docs)
        b_90_95 = next(b for b in buckets if b.bucket_name == "90-95")
        assert b_90_95.total_documents == 2
        assert b_90_95.correct_documents == 1
        assert b_90_95.empirical_accuracy == 0.5

    # U. AUTO_ACCEPT safety analysis
    def test_case_u_auto_accept_safety_analysis(self):
        evaluator = InvoiceEvaluator()
        sample_docs = [
            {"decision": "AUTO_ACCEPT", "field_error_count": 0, "row_error_count": 0},
            {"decision": "AUTO_ACCEPT", "field_error_count": 1, "erroneous_fields": ["mrp"], "row_error_count": 0},
            {"decision": "REVIEW_REQUIRED", "field_error_count": 0, "row_error_count": 0},
        ]
        safety = evaluator.analyze_auto_accept_safety(sample_docs)
        assert safety["total_auto_accept"] == 2
        assert safety["fully_correct"] == 1
        assert safety["precision"] == 0.5
        assert safety["error_rate"] == 0.5

    # V. REVIEW_REQUIRED analysis
    def test_case_v_review_required_analysis(self):
        evaluator = InvoiceEvaluator()
        sample_docs = [
            {"decision": "REVIEW_REQUIRED", "validation_warnings": ["Total taxable amount mismatch"], "low_confidence_fields": ["rate"]},
        ]
        rev = evaluator.analyze_review_required(sample_docs)
        assert rev["total_review_required"] == 1
        assert len(rev["top_warning_triggers"]) == 1
        assert rev["top_warning_triggers"][0]["warning"] == "Total taxable amount mismatch"

    # W. UNRESOLVED analysis
    def test_case_w_unresolved_analysis(self):
        evaluator = InvoiceEvaluator()
        sample_docs = [
            {"decision": "UNRESOLVED", "likely_root_cause": "LOGICAL_SUBCOLUMN_SPLIT", "missing_evidence": ["rate_column"]},
        ]
        unres = evaluator.analyze_unresolved(sample_docs)
        assert unres["total_unresolved"] == 1
        assert unres["ranked_root_causes"][0]["root_cause"] == "LOGICAL_SUBCOLUMN_SPLIT"

    # X. Human correction analysis
    def test_case_x_human_correction_analysis(self):
        evaluator = InvoiceEvaluator()
        history = [
            {"original_field": "rate", "corrected_field": "mrp"},
            {"original_field": "rate", "corrected_field": "mrp"},
            {"original_field": "quantity", "corrected_field": "freeQuantity"},
        ]
        corr = evaluator.analyze_human_corrections(history)
        assert corr["total_corrections"] == 3
        assert corr["repeated_mapping_patterns"][0]["pattern"] == "rate -> mrp"
        assert corr["repeated_mapping_patterns"][0]["count"] == 2

    # Y. Report generation
    def test_case_y_report_generation(self, temp_eval_dir):
        evaluator = InvoiceEvaluator()
        manifest_items = [
            EvaluationManifestItem("d1", "INVOICE_7GU0X28XM.PDF", "Sample Invoices/INVOICE_7GU0X28XM.PDF", "c26b45256359ae1674a2c8b1010fe545da32d142b305944de57e2f04a8625b1e", DatasetCategory.GOLDEN, supplier_name="PRAPTI MEDICARE", expected_row_count=11),
        ]
        results = evaluator.run_evaluation(manifest_items)
        reporter = EvaluationReportGenerator(base_eval_dir=temp_eval_dir)
        json_path = reporter.save_json_results(results)
        md_path = reporter.generate_markdown_report(results)

        assert os.path.exists(json_path)
        assert os.path.exists(md_path)
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "# MediAstra Pharma PDF Extractor" in content
            assert "Dataset Summary" in content

    # Z. Deterministic evaluation output
    def test_case_z_deterministic_evaluation_output(self):
        evaluator = InvoiceEvaluator()
        manifest_items = [
            EvaluationManifestItem("d1", "INVOICE_7GU0X28XM.PDF", "Sample Invoices/INVOICE_7GU0X28XM.PDF", "c26b45256359ae1674a2c8b1010fe545da32d142b305944de57e2f04a8625b1e", DatasetCategory.GOLDEN, supplier_name="PRAPTI MEDICARE", expected_row_count=11),
        ]
        r1 = evaluator.run_evaluation(manifest_items)
        r2 = evaluator.run_evaluation(manifest_items)

        assert r1["total_documents_evaluated"] == r2["total_documents_evaluated"]
        assert r1["decision_breakdown"] == r2["decision_breakdown"]
        assert r1["row_metrics"]["matched_rows"] == r2["row_metrics"]["matched_rows"]
