"""
MediAstra Pharma PDF Purchase Import Engine - Prompt 11 Batch Processing Test Suite
Covers Cases A through Z for discovery, error isolation, duplicate detection, SQLite integration, and batch export.
"""
import os
import sys
import json
import shutil
import pytest
import pandas as pd
import io

# Ensure project root is on sys.path
PROJECT_ROOT = r"c:\Users\sunil\pharma-pdf-extractor"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from batch_processor import (
    discover_pdf_files,
    process_single_document,
    process_batch,
    export_batch_results,
    DocumentProcessingResult,
    BatchProcessingResult,
)
from storage import StorageService, init_db

SAMPLE_DIR = os.path.join(PROJECT_ROOT, "Sample Invoices")


@pytest.fixture
def temp_db(tmp_path):
    db_file = str(tmp_path / "test_batch_storage.db")
    init_db(db_file)
    return db_file


@pytest.fixture
def temp_batch_dir(tmp_path):
    bdir = tmp_path / "batch_test_folder"
    bdir.mkdir()
    return str(bdir)


class TestPrompt11BatchProcessingSuite:

    def test_case_a_single_pdf_processing(self, temp_db):
        """Case A: Single PDF processing returns valid DocumentProcessingResult."""
        service = StorageService(temp_db)
        pdf_path = os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF")
        res = process_single_document(pdf_path, storage_service=service)
        assert res.status == "SUCCESS"
        assert res.filename == "INVOICE_7GX167AKM.PDF"
        assert res.supplier_name == "MOHIT PHARMA"
        assert res.row_count == 4
        assert res.decision == "AUTO_ACCEPT"
        assert res.document_id is not None

    def test_case_b_empty_directory(self, temp_batch_dir):
        """Case B: Discovering from empty directory returns empty list."""
        discovered = discover_pdf_files(temp_batch_dir)
        assert discovered == []
        batch_res = process_batch(temp_batch_dir)
        assert batch_res.total_documents == 0

    def test_case_c_directory_with_one_pdf(self, temp_batch_dir):
        """Case C: Directory with 1 PDF discovers and processes exactly 1 file."""
        src = os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF")
        dst = os.path.join(temp_batch_dir, "single.pdf")
        shutil.copyfile(src, dst)

        discovered = discover_pdf_files(temp_batch_dir)
        assert len(discovered) == 1
        batch_res = process_batch(temp_batch_dir)
        assert batch_res.total_documents == 1
        assert batch_res.document_results[0].row_count == 4

    def test_case_d_directory_with_multiple_pdfs(self, temp_batch_dir):
        """Case D: Directory with multiple PDFs discovers all files."""
        for f in ["INVOICE_7GX167AKM.PDF", "INVOICE_7HH0S5IPC.PDF", "SI26-000698.pdf"]:
            shutil.copyfile(os.path.join(SAMPLE_DIR, f), os.path.join(temp_batch_dir, f))

        discovered = discover_pdf_files(temp_batch_dir)
        assert len(discovered) == 3

    def test_case_e_uppercase_pdf_extension(self, temp_batch_dir):
        """Case E: Uppercase .PDF extension is correctly recognized."""
        src = os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF")
        dst = os.path.join(temp_batch_dir, "UPPERCASE_TEST.PDF")
        shutil.copyfile(src, dst)

        discovered = discover_pdf_files(temp_batch_dir)
        assert len(discovered) == 1
        assert discovered[0].endswith("UPPERCASE_TEST.PDF")

    def test_case_f_filenames_with_spaces_and_parentheses(self, temp_batch_dir):
        """Case F: Filenames containing spaces and parentheses are handled properly."""
        src = os.path.join(SAMPLE_DIR, "invoice (1).pdf")
        dst = os.path.join(temp_batch_dir, "my test invoice (1) final.pdf")
        shutil.copyfile(src, dst)

        discovered = discover_pdf_files(temp_batch_dir)
        assert len(discovered) == 1
        batch_res = process_batch(temp_batch_dir)
        assert batch_res.total_documents == 1
        assert batch_res.document_results[0].supplier_name == "SRI HARSHA PHARMA"

    def test_case_g_deterministic_ordering(self, temp_batch_dir):
        """Case G: File discovery returns deterministically sorted list."""
        fnames = ["Z_invoice.pdf", "A_invoice.pdf", "M_invoice.pdf"]
        src = os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF")
        for fn in fnames:
            shutil.copyfile(src, os.path.join(temp_batch_dir, fn))

        disc1 = discover_pdf_files(temp_batch_dir)
        disc2 = discover_pdf_files(temp_batch_dir)
        assert disc1 == disc2
        assert [os.path.basename(p) for p in disc1] == ["A_invoice.pdf", "M_invoice.pdf", "Z_invoice.pdf"]

    def test_case_h_sha256_duplicate_detection(self, temp_db, temp_batch_dir):
        """Case H: SHA-256 duplicate detection flags duplicate documents."""
        service = StorageService(temp_db)
        src = os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF")
        
        res1 = process_single_document(src, storage_service=service)
        assert res1.is_duplicate is False

        # Second processing of same file
        res2 = process_single_document(src, storage_service=service)
        assert res2.is_duplicate is True

    def test_case_i_duplicate_document_handling(self, temp_db):
        """Case I: Re-processing duplicate file increments run number without duplicating doc record."""
        service = StorageService(temp_db)
        src = os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF")
        
        doc1 = process_single_document(src, storage_service=service)
        doc2 = process_single_document(src, storage_service=service)
        assert doc1.document_id == doc2.document_id
        assert doc1.run_id != doc2.run_id

    def test_case_j_invalid_pdf_isolation(self, temp_batch_dir):
        """Case J: Zero-byte or corrupted file is captured as FAILED without unhandled crash."""
        bad_file = os.path.join(temp_batch_dir, "corrupt.pdf")
        with open(bad_file, "wb") as f:
            f.write(b"not a valid pdf content at all")

        res = process_single_document(bad_file)
        assert res.status == "FAILED"
        assert res.decision == "FAILED"
        assert res.error_message is not None

    def test_case_k_failed_document_does_not_stop_batch(self, temp_batch_dir):
        """Case K: One failed document does not terminate the batch."""
        # 1 valid file
        shutil.copyfile(os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF"), os.path.join(temp_batch_dir, "01_valid.pdf"))
        # 1 corrupted file
        with open(os.path.join(temp_batch_dir, "02_corrupt.pdf"), "wb") as f:
            f.write(b"corrupt")
        # 1 valid file
        shutil.copyfile(os.path.join(SAMPLE_DIR, "SI26-000698.pdf"), os.path.join(temp_batch_dir, "03_valid.pdf"))

        batch_res = process_batch(temp_batch_dir)
        assert batch_res.total_documents == 3
        assert batch_res.failed_count == 1
        assert batch_res.auto_accept_count == 2
        assert len(batch_res.document_results) == 3

    def test_case_l_auto_accept_counting(self, temp_batch_dir):
        """Case L: AUTO_ACCEPT documents are accurately counted."""
        shutil.copyfile(os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF"), os.path.join(temp_batch_dir, "doc1.pdf"))
        shutil.copyfile(os.path.join(SAMPLE_DIR, "SI26-000698.pdf"), os.path.join(temp_batch_dir, "doc2.pdf"))

        batch_res = process_batch(temp_batch_dir)
        assert batch_res.auto_accept_count == 2
        assert batch_res.review_required_count == 0

    def test_case_m_review_required_counting(self, temp_batch_dir):
        """Case M: REVIEW_REQUIRED documents are accurately counted."""
        shutil.copyfile(os.path.join(SAMPLE_DIR, "INVOICE_7GU0X28XM.PDF"), os.path.join(temp_batch_dir, "doc1.pdf"))
        batch_res = process_batch(temp_batch_dir)
        assert batch_res.review_required_count == 1

    def test_case_n_unresolved_counting(self, temp_batch_dir, monkeypatch):
        """Case N: UNRESOLVED documents are accurately counted."""
        import batch_processor
        shutil.copyfile(os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF"), os.path.join(temp_batch_dir, "doc1.pdf"))
        orig_process = batch_processor.process_single_document
        def mock_process(pdf_path, **kwargs):
            res = orig_process(pdf_path, **kwargs)
            res.status = "UNRESOLVED"
            res.decision = "UNRESOLVED"
            return res
        monkeypatch.setattr(batch_processor, "process_single_document", mock_process)
        batch_res = batch_processor.process_batch(temp_batch_dir)
        assert batch_res.unresolved_count == 1

    def test_case_o_failed_counting(self, temp_batch_dir):
        """Case O: FAILED documents are accurately counted."""
        with open(os.path.join(temp_batch_dir, "empty.pdf"), "wb") as f:
            pass  # 0 bytes
        batch_res = process_batch(temp_batch_dir)
        assert batch_res.failed_count == 1

    def test_case_p_total_row_aggregation(self, temp_batch_dir):
        """Case P: Total extracted rows aggregated across documents."""
        shutil.copyfile(os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF"), os.path.join(temp_batch_dir, "doc1.pdf")) # 4 rows
        shutil.copyfile(os.path.join(SAMPLE_DIR, "SI26-000698.pdf"), os.path.join(temp_batch_dir, "doc2.pdf"))       # 6 rows
        batch_res = process_batch(temp_batch_dir)
        assert batch_res.total_rows == 10

    def test_case_q_supplier_identity_isolation(self, temp_batch_dir):
        """Case Q: Distinct suppliers in a batch remain separate."""
        shutil.copyfile(os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF"), os.path.join(temp_batch_dir, "doc1.pdf"))
        shutil.copyfile(os.path.join(SAMPLE_DIR, "SI26-000698.pdf"), os.path.join(temp_batch_dir, "doc2.pdf"))
        batch_res = process_batch(temp_batch_dir)
        suppliers = {d.supplier_name for d in batch_res.document_results}
        assert "MOHIT PHARMA" in suppliers
        assert "CAPITA MediHub" in suppliers

    def test_case_r_layout_profile_isolation(self, temp_batch_dir):
        """Case R: Layout profiles remain isolated per document."""
        shutil.copyfile(os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF"), os.path.join(temp_batch_dir, "doc1.pdf"))
        shutil.copyfile(os.path.join(SAMPLE_DIR, "SI26-000698.pdf"), os.path.join(temp_batch_dir, "doc2.pdf"))
        batch_res = process_batch(temp_batch_dir)
        assert batch_res.document_results[0].headers != batch_res.document_results[1].headers

    def test_case_s_extraction_run_persistence(self, temp_db, temp_batch_dir):
        """Case S: All batch extraction runs are persisted to SQLite."""
        service = StorageService(temp_db)
        shutil.copyfile(os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF"), os.path.join(temp_batch_dir, "doc1.pdf"))
        batch_res = process_batch(temp_batch_dir, storage_service=service)

        with service.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM extraction_runs;")
            assert cursor.fetchone()["cnt"] == 1

    def test_case_t_error_persistence(self, temp_db, temp_batch_dir):
        """Case T: Failed document error message is captured in DocumentProcessingResult."""
        service = StorageService(temp_db)
        with open(os.path.join(temp_batch_dir, "bad.pdf"), "wb") as f:
            f.write(b"bad")
        batch_res = process_batch(temp_batch_dir, storage_service=service)
        assert batch_res.document_results[0].status == "FAILED"
        assert batch_res.document_results[0].error_message is not None

    def test_case_u_batch_summary_correctness(self, temp_batch_dir):
        """Case U: summary_dict fields match batch metrics."""
        shutil.copyfile(os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF"), os.path.join(temp_batch_dir, "doc1.pdf"))
        batch_res = process_batch(temp_batch_dir)
        summary = batch_res.summary_dict()
        assert summary["total_documents"] == 1
        assert summary["auto_accept"] == 1
        assert summary["total_rows"] == 4

    def test_case_v_json_batch_export(self, temp_batch_dir):
        """Case V: Batch export produces valid JSON containing document metadata."""
        shutil.copyfile(os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF"), os.path.join(temp_batch_dir, "doc1.pdf"))
        batch_res = process_batch(temp_batch_dir)
        json_out = export_batch_results(batch_res, export_format="json")
        data = json.loads(json_out)
        assert isinstance(data, list)
        assert len(data) == 4
        assert "filename" in data[0]
        assert "itemName" in data[0]

    def test_case_w_csv_batch_export(self, temp_batch_dir):
        """Case W: Batch export produces valid CSV with metadata and canonical fields."""
        shutil.copyfile(os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF"), os.path.join(temp_batch_dir, "doc1.pdf"))
        batch_res = process_batch(temp_batch_dir)
        csv_out = export_batch_results(batch_res, export_format="csv")
        df = pd.read_csv(io.StringIO(csv_out))
        assert len(df) == 4
        assert "filename" in df.columns
        assert "supplier_name" in df.columns
        assert "itemName" in df.columns

    def test_case_x_repeated_batch_determinism(self, temp_batch_dir):
        """Case X: Running the same batch twice produces deterministic row counts and decisions."""
        shutil.copyfile(os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF"), os.path.join(temp_batch_dir, "doc1.pdf"))
        shutil.copyfile(os.path.join(SAMPLE_DIR, "SI26-000698.pdf"), os.path.join(temp_batch_dir, "doc2.pdf"))

        batch1 = process_batch(temp_batch_dir)
        batch2 = process_batch(temp_batch_dir)
        assert batch1.total_rows == batch2.total_rows
        assert batch1.auto_accept_count == batch2.auto_accept_count
        assert batch1.total_documents == batch2.total_documents

    def test_case_y_benchmark_9_pdfs_batch(self):
        """Case Y: Processing all 9 benchmark PDFs in one batch succeeds with 0 failures."""
        batch_res = process_batch(SAMPLE_DIR)
        assert batch_res.total_documents == 9
        assert batch_res.failed_count == 0
        assert batch_res.total_rows in (147, 148, 149, 150, 151)
        assert batch_res.auto_accept_count == 4
        assert batch_res.review_required_count in (3, 4)
        assert batch_res.unresolved_count in (1, 2)

    def test_case_z_synthetic_larger_batch_stress_test(self, temp_batch_dir):
        """Case Z: Synthetic stress test with 27 copies completes with error isolation."""
        sample_files = [
            "INVOICE_7GX167AKM.PDF",
            "INVOICE_7HH0S5IPC.PDF",
            "SI26-000698.pdf",
        ]
        # Create 27 copies (9 copies of each of the 3 files)
        for i in range(9):
            for s_name in sample_files:
                src = os.path.join(SAMPLE_DIR, s_name)
                dst = os.path.join(temp_batch_dir, f"copy_{i}_{s_name}")
                shutil.copyfile(src, dst)

        batch_res = process_batch(temp_batch_dir)
        assert batch_res.total_documents == 27
        assert batch_res.failed_count == 0
        assert batch_res.auto_accept_count == 27
        assert batch_res.total_rows == 9 * (4 + 9 + 6)  # 171 rows
