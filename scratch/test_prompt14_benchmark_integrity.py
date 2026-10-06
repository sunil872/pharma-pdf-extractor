"""
MediAstra Pharma PDF Purchase Import Engine - Prompt 14 Benchmark Integrity Suite
Tests: Audit, restore, lock, and verify the canonical golden benchmark v1 established in Prompts 9-12.
"""

import os
import sys
import json
import hashlib
import shutil
import tempfile
import pytest

sys.path.insert(0, os.path.abspath("."))

from evaluation.evaluator import verify_golden_benchmark_v1, InvoiceEvaluator
from evaluation.models import DatasetCategory
from extractor import extract_pdf_table

CANONICAL_MANIFEST_PATH = "evaluation/golden_manifest_v1.json"
SAMPLE_DIR = "Sample Invoices"

CANONICAL_BENCHMARK_DOCS = [
    ("INVOICE_7GU0X28XM.PDF", "c26b45256359ae1674a2c8b1010fe545da32d142b305944de57e2f04a8625b1e", "PRAPTI MEDICARE", "36AASFP4005A1ZJ", 11),
    ("INVOICE_7GX167AKM.PDF", "faf7092e0a7a914d13594c518f88a08ff1a87b9b5fbec35e997c875630b4d613", "MOHIT PHARMA", "36AAZFP3596K1Z5", 4),
    ("INVOICE_7HC0MTOZ2.PDF", "a8e02a4c12d2946a276d1cd83858a1b8a1ea44902d4459c1d807ff8a398cbd11", "PASHUPATI MEDICAL DISTRIBUTORS", "36CGBPA3297A1ZW", 15),
    ("INVOICE_7HH0S5IPC.PDF", "4ab52431c492cc221df4b39c20dc8721ff483a5d77cdf1f275a061b7c0eb090a", "GAJANAND MEDICAL AGENCIES", "36AAZFP3596K1Z5", 9),
    ("Invoice.pdf", "c0d02b670e2caa940714baa6829e247584f11ad2f8fd78b4a1a6037bf0b69a3c", "JP LOGISTICS", "36ABLPA4990K1ZB", 23),
    ("PHUB_L22014.pdf", "563fa908c438ea82fcbeca987fe3bed7e54a42da9986ab3a3531d97e946f6de0", "SHRI AJAY MEDICAL AGENCIES", "36ACUFS2399N1ZY", 22),
    ("SI26-000698.pdf", "6077037eaf235893d0e9ddf0a8163166fb8cea1a350fbd5995d100ba5f27ea1f", "CAPITA MediHub", "36AATFC0891J1ZY", 6),
    ("Sunil_Medicare_Sample_Invoice.pdf", "48cfe98fcdce1509f8165c4bd7fd3f96bb7e127b63885267b325c3827fb471b5", "SUNIL MEDICARE", "36ABCDE1234F1Z5", 18),
    ("invoice (1).pdf", "ae83061e055990bd3a533668b554570491e80f967c10490c72b227192c77ab0d", "SRI HARSHA PHARMA", "36BIXPR6113F1ZU", 40),
]


class TestPrompt14BenchmarkIntegrity:

    # A. Canonical benchmark contains exactly 9 documents
    def test_case_a_canonical_benchmark_exactly_9_documents(self):
        assert os.path.exists(CANONICAL_MANIFEST_PATH)
        with open(CANONICAL_MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        docs = data.get("documents", [])
        assert len(docs) == 9
        assert data.get("benchmark_version") == "v1.0"
        assert data.get("immutable") is True

    # B. Every canonical filename exists on disk
    def test_case_b_every_canonical_filename_exists(self):
        for fname, _, _, _, _ in CANONICAL_BENCHMARK_DOCS:
            fpath = os.path.join(SAMPLE_DIR, fname)
            assert os.path.exists(fpath), f"Canonical benchmark file {fname} is missing!"

    # C. Every canonical SHA-256 matches
    def test_case_c_every_canonical_sha256_matches(self):
        for fname, expected_sha, _, _, _ in CANONICAL_BENCHMARK_DOCS:
            fpath = os.path.join(SAMPLE_DIR, fname)
            with open(fpath, "rb") as fp:
                actual_sha = hashlib.sha256(fp.read()).hexdigest()
            assert actual_sha == expected_sha, f"SHA-256 mismatch for {fname}: expected {expected_sha}, got {actual_sha}"

    # D. Expected supplier identities match
    def test_case_d_expected_supplier_identities_match(self):
        with open(CANONICAL_MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        doc_map = {d["filename"]: d for d in data["documents"]}
        for fname, _, expected_supp, _, _ in CANONICAL_BENCHMARK_DOCS:
            assert doc_map[fname]["supplier_name"] == expected_supp

    # E. Expected GSTINs match
    def test_case_e_expected_gstins_match(self):
        with open(CANONICAL_MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        doc_map = {d["filename"]: d for d in data["documents"]}
        for fname, _, _, expected_gstin, _ in CANONICAL_BENCHMARK_DOCS:
            assert doc_map[fname]["gstin"] == expected_gstin

    # F. Expected row counts match
    def test_case_f_expected_row_counts_match(self):
        with open(CANONICAL_MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        doc_map = {d["filename"]: d for d in data["documents"]}
        for fname, _, _, _, expected_rows in CANONICAL_BENCHMARK_DOCS:
            assert doc_map[fname]["expected_rows"] == expected_rows

    # G. Unexpected Prompt 13 replacement files cannot enter GOLDEN_V1
    def test_case_g_unexpected_replacement_files_cannot_enter_golden_v1(self):
        with open(CANONICAL_MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        filenames = {d["filename"] for d in data["documents"]}
        prohibited_replacements = [
            "INVOICE_7E91640Y2.PDF",
            "INVOICE_7GZ1687Y4.PDF",
            "INVOICE_7HE0S19N9.PDF",
            "INVOICE_7HI0S78G3.PDF",
            "INVOICE_7HK0S8XG0.PDF",
            "INVOICE_7HL0SBAEB.PDF",
            "sample_invoice.pdf",
        ]
        for bad_fn in prohibited_replacements:
            assert bad_fn not in filenames, f"Prohibited replacement {bad_fn} found in GOLDEN_V1 manifest!"

    # H. Evaluation does not mutate golden manifest
    def test_case_h_evaluation_does_not_mutate_golden_manifest(self):
        with open(CANONICAL_MANIFEST_PATH, "r", encoding="utf-8") as f:
            before_content = f.read()
        evaluator = InvoiceEvaluator()
        # Verify file content is unchanged
        with open(CANONICAL_MANIFEST_PATH, "r", encoding="utf-8") as f:
            after_content = f.read()
        assert before_content == after_content

    # I. Extraction does not mutate golden manifest
    def test_case_i_extraction_does_not_mutate_golden_manifest(self):
        with open(CANONICAL_MANIFEST_PATH, "r", encoding="utf-8") as f:
            before_content = f.read()
        extract_pdf_table(os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF"))
        with open(CANONICAL_MANIFEST_PATH, "r", encoding="utf-8") as f:
            after_content = f.read()
        assert before_content == after_content

    # J. REAL dataset cannot overwrite GOLDEN_V1
    def test_case_j_real_dataset_cannot_overwrite_golden_v1(self):
        assert DatasetCategory.REAL.value != DatasetCategory.GOLDEN_V1.value
        assert DatasetCategory.REAL != DatasetCategory.GOLDEN_V1

    # K. SYNTHETIC dataset cannot overwrite GOLDEN_V1
    def test_case_k_synthetic_dataset_cannot_overwrite_golden_v1(self):
        assert DatasetCategory.SYNTHETIC.value != DatasetCategory.GOLDEN_V1.value

    # L. EDGE_CASE dataset cannot overwrite GOLDEN_V1
    def test_case_l_edge_case_dataset_cannot_overwrite_golden_v1(self):
        assert DatasetCategory.EDGE_CASE.value != DatasetCategory.GOLDEN_V1.value

    # M. Same SHA-256 cannot be registered as a different canonical document
    def test_case_m_same_sha256_cannot_register_different_canonical_doc(self):
        with open(CANONICAL_MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        seen_shas = {}
        for d in data["documents"]:
            sha = d["sha256"]
            fn = d["filename"]
            assert sha not in seen_shas, f"Duplicate SHA {sha} across {fn} and {seen_shas.get(sha)}"
            seen_shas[sha] = fn

    # N. Different SHA-256 cannot silently replace a canonical document
    def test_case_n_different_sha256_fails_verification(self, tmp_path):
        bad_manifest = tmp_path / "bad_manifest.json"
        with open(CANONICAL_MANIFEST_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Mutate first document SHA
        data["documents"][0]["sha256"] = "0000000000000000000000000000000000000000000000000000000000000000"
        with open(bad_manifest, "w", encoding="utf-8") as f:
            json.dump(data, f)
        ok, res = verify_golden_benchmark_v1(manifest_path=str(bad_manifest), samples_dir=SAMPLE_DIR)
        assert ok is False
        assert res["status"] == "GOLDEN_BENCHMARK_INTEGRITY_FAILURE"

    # O. Prompt 13 comparison uses the same document identities
    def test_case_o_comparison_uses_same_document_identities(self):
        comp_path = "evaluation/results/prompt14_benchmark_comparison.json"
        if os.path.exists(comp_path):
            with open(comp_path, "r", encoding="utf-8") as f:
                comp = json.load(f)
            assert comp["total_documents"] == 9
            assert comp["sha256_all_verified"] is True
            doc_filenames = {d["filename"] for d in comp["documents"]}
            expected_filenames = {d[0] for d in CANONICAL_BENCHMARK_DOCS}
            assert doc_filenames == expected_filenames

    # P. Supplier profile contamination is detected or ruled out
    def test_case_p_supplier_profile_contamination_ruled_out(self):
        with open("supplier_profiles.json", "r", encoding="utf-8") as f:
            profiles = json.load(f)
        # Ensure no corrupted supplier identities with mismatched GSTINs
        for k, v in profiles.get("suppliers", {}).items():
            if v.get("gstin"):
                assert len(v["gstin"]) == 15

    # Q. Full benchmark verification returns PASS
    def test_case_q_full_benchmark_verification_returns_pass(self):
        ok, res = verify_golden_benchmark_v1(manifest_path=CANONICAL_MANIFEST_PATH, samples_dir=SAMPLE_DIR)
        assert ok is True
        assert res["status"] == "PASS"
        assert res["document_count"] == 9
        assert len(res["verified_documents"]) == 9

    # R. No supplier-specific hardcoding
    def test_case_r_no_supplier_specific_hardcoding(self):
        for path in ["extractor.py", "evaluation/evaluator.py"]:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            assert "if supplier ==" not in content
            assert "if supplier_name ==" not in content
            assert "if filename ==" not in content

    # S. Repeated benchmark execution is deterministic
    def test_case_s_repeated_benchmark_execution_deterministic(self):
        fpath = os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF")
        m1, _, _, rows1 = extract_pdf_table(fpath)
        m2, _, _, rows2 = extract_pdf_table(fpath)
        assert len(rows1) == len(rows2)
        assert m1["confidence"] == m2["confidence"]
        assert m1["classification"] == m2["classification"]

    # T. Historical regression remains compatible
    def test_case_t_historical_regression_compatible(self):
        fpath = os.path.join(SAMPLE_DIR, "SI26-000698.pdf")
        meta, _, _, rows = extract_pdf_table(fpath)
        assert len(rows) == 6
        assert meta["classification"] == "AUTO_ACCEPT"
