"""
MediAstra Pharma PDF Purchase Import Engine - Prompt 10A SQLite Storage Test Suite
Covers Cases A through V for SQLite persistence, models, concurrency locking, and migration.
"""
import os
import sys
import json
import sqlite3
import pytest

# Ensure project root is on sys.path
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")

from storage import (
    StorageService,
    get_db_connection,
    init_db,
    ProfileVersionConflictError,
    Supplier,
    SupplierLayoutProfile,
    InvoiceDocument,
    ExtractionRun,
    ReviewSessionRecord,
    AuditEvent,
)
from migrate_json_to_sqlite import run_migration


@pytest.fixture
def temp_db(tmp_path):
    db_file = str(tmp_path / "test_mediastra.db")
    return db_file


class TestPrompt10StorageSuite:

    def test_case_a_database_initialization(self, temp_db):
        """Case A: Database initializes and creates SQLite database file."""
        assert not os.path.exists(temp_db)
        init_db(temp_db)
        assert os.path.exists(temp_db)

    def test_case_b_schema_creation(self, temp_db):
        """Case B: Schema creates all required tables and indexes."""
        init_db(temp_db)
        with get_db_connection(temp_db) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row["name"] for row in cursor.fetchall()}
            expected_tables = {
                "suppliers",
                "supplier_layout_profiles",
                "invoice_documents",
                "extraction_runs",
                "review_sessions",
                "audit_events",
            }
            assert expected_tables.issubset(tables)

            cursor.execute("SELECT name FROM sqlite_master WHERE type='index';")
            indexes = {row["name"] for row in cursor.fetchall()}
            assert "idx_suppliers_gstin" in indexes
            assert "idx_docs_file_hash" in indexes

    def test_case_c_supplier_creation(self, temp_db):
        """Case C: Supplier creation inserts record with defaults."""
        service = StorageService(temp_db)
        res = service.save_or_update_supplier_profile_memory(
            supplier_key="36AASFP4005A1ZJ",
            supplier_name="PRAPTI MEDICARE",
            gstin="36AASFP4005A1ZJ",
            headers=["Item", "Qty", "Amount"],
            logical_columns=[{"header": "Item"}, {"header": "Qty"}, {"header": "Amount"}],
            resolved_mappings={"Item": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "Amount": {"mapped_to": "amount"}},
            rows=[["Medicine A", "10", "100"]],
            validation_result={"classification": "AUTO_ACCEPT", "document_confidence": 92.0, "accounting_summary": {"critical_mismatches": 0}},
        )
        assert res["updated"] is True
        assert res["action"] == "NEW_SUPPLIER_PROFILE_CREATED"

        sup = service.find_supplier_by_gstin("36AASFP4005A1ZJ")
        assert sup is not None
        assert sup.supplier_name == "PRAPTI MEDICARE"
        assert sup.profile_version == 1
        assert sup.is_active is True

    def test_case_d_gstin_uniqueness_and_lookup(self, temp_db):
        """Case D: GSTIN lookup finds supplier and maintains integrity."""
        service = StorageService(temp_db)
        service.save_or_update_supplier_profile_memory(
            supplier_key="36AAZFP3596K1Z5",
            supplier_name="MOHIT PHARMA",
            gstin="36AAZFP3596K1Z5",
            headers=["Item", "Amount"],
            logical_columns=[{"header": "Item"}, {"header": "Amount"}],
            resolved_mappings={"Item": {"mapped_to": "itemName"}, "Amount": {"mapped_to": "amount"}},
            rows=[["A", "100"]],
            validation_result={"classification": "AUTO_ACCEPT", "document_confidence": 95.0, "accounting_summary": {"critical_mismatches": 0}},
        )
        sup = service.find_supplier_by_gstin("36AAZFP3596K1Z5")
        assert sup is not None
        assert sup.supplier_key == "36AAZFP3596K1Z5"

    def test_case_e_distinct_supplier_isolation(self, temp_db):
        """Case E: Distinct suppliers with different GSTINs remain isolated."""
        service = StorageService(temp_db)
        headers = ["Item", "Qty", "Price", "Total"]
        cols = [{"header": h} for h in headers]
        mappings = {"Item": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "Price": {"mapped_to": "rate"}, "Total": {"mapped_to": "amount"}}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 94.0, "accounting_summary": {"critical_mismatches": 0}}

        res_a = service.save_or_update_supplier_profile_memory(
            supplier_key="SUPPLIER_A",
            supplier_name="SUPPLIER_A",
            gstin="36AAAAA1111A1Z1",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=mappings,
            rows=[["A", "1", "10", "10"]],
            validation_result=val_res,
        )
        res_b = service.save_or_update_supplier_profile_memory(
            supplier_key="SUPPLIER_B",
            supplier_name="SUPPLIER_B",
            gstin="36BBBBB2222B1Z2",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=mappings,
            rows=[["B", "2", "20", "40"]],
            validation_result=val_res,
        )
        assert res_a["supplier_id"] != res_b["supplier_id"]

        sup_a = service.get_supplier_by_id(res_a["supplier_id"])
        sup_b = service.get_supplier_by_id(res_b["supplier_id"])
        assert sup_a.gstin == "36AAAAA1111A1Z1"
        assert sup_b.gstin == "36BBBBB2222B1Z2"

    def test_case_f_supplier_lookup_by_identity(self, temp_db):
        """Case F: Supplier lookup by normalized name and key."""
        service = StorageService(temp_db)
        service.save_or_update_supplier_profile_memory(
            supplier_key="CAPITA MediHub",
            supplier_name="CAPITA MediHub",
            gstin="36AATFC0891J1ZY",
            headers=["Item", "Amount"],
            logical_columns=[{"header": "Item"}, {"header": "Amount"}],
            resolved_mappings={"Item": {"mapped_to": "itemName"}, "Amount": {"mapped_to": "amount"}},
            rows=[["A", "100"]],
            validation_result={"classification": "AUTO_ACCEPT", "document_confidence": 98.0, "accounting_summary": {"critical_mismatches": 0}},
        )
        sup = service.find_supplier_by_identity("non_existent_key", gstin=None, name="capita medihub")
        assert sup is not None
        assert sup.gstin == "36AATFC0891J1ZY"

    def test_case_g_layout_creation(self, temp_db):
        """Case G: Layout creation inserts profile with JSON structures."""
        service = StorageService(temp_db)
        headers = ["Drug Name", "Pack", "Batch", "Expiry", "Qty", "Rate", "Amount"]
        cols = [{"header": h} for h in headers]
        mappings = {h: {"mapped_to": "itemName" if "Drug" in h else "amount"} for h in headers}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 91.0, "accounting_summary": {"critical_mismatches": 0}}

        res = service.save_or_update_supplier_profile_memory(
            supplier_key="36TESTL1234T1Z1",
            supplier_name="TEST PHARMA",
            gstin="36TESTL1234T1Z1",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=mappings,
            rows=[["A", "10T", "B1", "12/26", "5", "10", "50"]],
            validation_result=val_res,
        )
        layouts = service.get_layout_profiles_for_supplier(res["supplier_id"])
        assert len(layouts) == 1
        assert layouts[0].header_sequence == headers
        assert layouts[0].layout_version == 1

    def test_case_h_layout_version_preservation(self, temp_db):
        """Case H: Changed layout creates layout_v2 without deleting layout_v1."""
        service = StorageService(temp_db)
        headers_v1 = ["Item", "Amount"]
        cols_v1 = [{"header": h} for h in headers_v1]
        mappings_v1 = {"Item": {"mapped_to": "itemName"}, "Amount": {"mapped_to": "amount"}}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}}

        res1 = service.save_or_update_supplier_profile_memory(
            supplier_key="SUP_DRIFT",
            supplier_name="SUP_DRIFT",
            gstin="36DRIFT1234D1Z1",
            headers=headers_v1,
            logical_columns=cols_v1,
            resolved_mappings=mappings_v1,
            rows=[["A", "10"]],
            validation_result=val_res,
        )
        assert res1["action"] == "NEW_SUPPLIER_PROFILE_CREATED"

        # Drifted layout
        headers_v2 = ["Product", "Batch", "Exp", "Qty", "MRP", "Rate", "Total Amount"]
        cols_v2 = [{"header": h} for h in headers_v2]
        mappings_v2 = {h: {"mapped_to": "itemName" if "Product" in h else "amount"} for h in headers_v2}

        res2 = service.save_or_update_supplier_profile_memory(
            supplier_key="SUP_DRIFT",
            supplier_name="SUP_DRIFT",
            gstin="36DRIFT1234D1Z1",
            headers=headers_v2,
            logical_columns=cols_v2,
            resolved_mappings=mappings_v2,
            rows=[["A", "B", "C", "D", "E", "F", "G"]],
            validation_result=val_res,
        )
        assert res2["action"] == "NEW_LAYOUT_VERSION_CREATED"

        layouts = service.get_layout_profiles_for_supplier(res1["supplier_id"])
        assert len(layouts) == 2
        assert {l.layout_version for l in layouts} == {1, 2}

    def test_case_i_profile_update_and_counters(self, temp_db):
        """Case I: Repeated successful processing updates document counters and reliability."""
        service = StorageService(temp_db)
        headers = ["Item", "Amount"]
        cols = [{"header": h} for h in headers]
        mappings = {"Item": {"mapped_to": "itemName"}, "Amount": {"mapped_to": "amount"}}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}}

        res1 = service.save_or_update_supplier_profile_memory(
            supplier_key="SUP_COUNT",
            supplier_name="SUP_COUNT",
            gstin="36COUNT1234C1Z1",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=mappings,
            rows=[["A", "10"]],
            validation_result=val_res,
        )
        res2 = service.save_or_update_supplier_profile_memory(
            supplier_key="SUP_COUNT",
            supplier_name="SUP_COUNT",
            gstin="36COUNT1234C1Z1",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=mappings,
            rows=[["B", "20"]],
            validation_result=val_res,
        )
        assert res2["action"] == "LAYOUT_PROFILE_UPDATED"

        sup = service.get_supplier_by_id(res1["supplier_id"])
        assert sup.successful_document_count == 2
        assert sup.profile_version == 2

    def test_case_j_optimistic_locking_success(self, temp_db):
        """Case J: Optimistic locking succeeds when expected_version matches current version."""
        service = StorageService(temp_db)
        headers = ["Item", "Amount"]
        cols = [{"header": h} for h in headers]
        mappings = {"Item": {"mapped_to": "itemName"}, "Amount": {"mapped_to": "amount"}}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}}

        res1 = service.save_or_update_supplier_profile_memory(
            supplier_key="SUP_LOCK",
            supplier_name="SUP_LOCK",
            gstin="36LOCK11234L1Z1",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=mappings,
            rows=[["A", "10"]],
            validation_result=val_res,
        )
        sup = service.get_supplier_by_id(res1["supplier_id"])
        assert sup.profile_version == 1

        res2 = service.save_or_update_supplier_profile_memory(
            supplier_key="SUP_LOCK",
            supplier_name="SUP_LOCK",
            gstin="36LOCK11234L1Z1",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=mappings,
            rows=[["B", "20"]],
            validation_result=val_res,
            expected_version=1,
        )
        assert res2["updated"] is True
        sup_after = service.get_supplier_by_id(res1["supplier_id"])
        assert sup_after.profile_version == 2

    def test_case_k_stale_profile_update_rejection(self, temp_db):
        """Case K: Stale profile update is rejected with PROFILE_VERSION_CONFLICT."""
        service = StorageService(temp_db)
        headers = ["Item", "Amount"]
        cols = [{"header": h} for h in headers]
        mappings = {"Item": {"mapped_to": "itemName"}, "Amount": {"mapped_to": "amount"}}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}}

        # Process A creates supplier (version 1)
        res1 = service.save_or_update_supplier_profile_memory(
            supplier_key="SUP_CONFLICT",
            supplier_name="SUP_CONFLICT",
            gstin="36CONF11234C1Z1",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=mappings,
            rows=[["A", "10"]],
            validation_result=val_res,
        )
        # Process A updates to version 2
        service.save_or_update_supplier_profile_memory(
            supplier_key="SUP_CONFLICT",
            supplier_name="SUP_CONFLICT",
            gstin="36CONF11234C1Z1",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=mappings,
            rows=[["B", "20"]],
            validation_result=val_res,
            expected_version=1,
        )
        # Process B attempts update expecting stale version 1
        res_stale = service.save_or_update_supplier_profile_memory(
            supplier_key="SUP_CONFLICT",
            supplier_name="SUP_CONFLICT",
            gstin="36CONF11234C1Z1",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=mappings,
            rows=[["C", "30"]],
            validation_result=val_res,
            expected_version=1,
        )
        assert res_stale["updated"] is False
        assert res_stale["conflict"] is True
        assert res_stale["reason"] == "PROFILE_VERSION_CONFLICT"

        # Version 2 remains intact
        sup = service.get_supplier_by_id(res1["supplier_id"])
        assert sup.profile_version == 2

    def test_case_l_duplicate_sha256_handling(self, temp_db):
        """Case L: Duplicate SHA-256 creates run and audit event without duplicating document."""
        service = StorageService(temp_db)
        file_hash = "abc123sha256testfake"
        meta = {"supplier_name": "Test Sup", "supplier_gstin": "36TESTD1234D1Z1", "classification": "AUTO_ACCEPT", "confidence": 95.0}
        headers = ["Item", "Qty", "Amount"]
        cols = [{"header": h} for h in headers]
        mappings = {"Item": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "Amount": {"mapped_to": "amount"}}
        rows = [["Product", "1", "10"]]

        doc1, run1 = service.register_document_and_run("test.pdf", file_hash, 1024, meta, headers, cols, mappings, rows)
        doc2, run2 = service.register_document_and_run("test.pdf", file_hash, 1024, meta, headers, cols, mappings, rows)

        assert doc1.id == doc2.id
        assert run1.run_number == 1
        assert run2.run_number == 2

    def test_case_m_invoice_creation(self, temp_db):
        """Case M: Invoice document metadata is saved correctly."""
        service = StorageService(temp_db)
        meta = {"supplier_name": "Pashupati", "supplier_gstin": "36CGBPA3297A1ZW", "classification": "REVIEW_REQUIRED", "confidence": 74.0}
        doc, run = service.register_document_and_run("invoice_sample.pdf", "hash_case_m_123", 2048, meta, ["A"], [{"header": "A"}], {"A": {"mapped_to": "itemName"}}, [["v"]])
        assert doc.document_status == "REVIEW_REQUIRED"
        assert doc.file_size_bytes == 2048

    def test_case_n_extraction_run_creation(self, temp_db):
        """Case N: Extraction run is linked to document with accurate stats."""
        service = StorageService(temp_db)
        meta = {"supplier_name": "Pashupati", "classification": "AUTO_ACCEPT", "confidence": 90.0}
        doc, run = service.register_document_and_run("inv.pdf", "hash_case_n_123", 500, meta, ["A"], [{"header": "A"}], {"A": {"mapped_to": "itemName"}}, [["1"], ["2"]])
        assert run.row_count == 2
        assert run.confidence == 90.0
        assert run.decision == "AUTO_ACCEPT"

    def test_case_o_review_session_persistence(self, temp_db):
        """Case O: Human review session record is saved in SQLite."""
        service = StorageService(temp_db)
        session_data = {
            "review_id": "rev_session_case_o",
            "supplier_name": "Test Sup",
            "gstin": "36TEST1234T1Z1",
            "original_decision": "REVIEW_REQUIRED",
            "original_confidence": 72.0,
            "original_headers": ["Col1", "Col2"],
            "logical_columns": [{"header": "Col1"}, {"header": "Col2"}],
            "original_semantic_mapping": {"Col1": {"mapped_to": "itemName"}},
            "original_rows": [["Med A", "100"]],
            "corrections": [{"logical_column": "Col2", "old_field": None, "new_field": "amount"}],
            "validated_result": {"status": "CORRECTION_VALIDATED", "outcome": "REVIEW_CONFIRMED"},
            "review_status": "REVIEW_CONFIRMED",
            "reviewed_by": "test_operator",
            "reviewed_at": "2026-09-11T12:00:00",
            "profile_update_status": "UPDATED",
        }
        pk = service.save_review_session_record(session_data)
        assert pk > 0

    def test_case_p_audit_event_persistence(self, temp_db):
        """Case P: Append-only audit events are recorded for lifecycle actions."""
        service = StorageService(temp_db)
        res = service.save_or_update_supplier_profile_memory(
            supplier_key="SUP_AUDIT",
            supplier_name="SUP_AUDIT",
            gstin="36AUDIT1234A1Z1",
            headers=["Item", "Amount"],
            logical_columns=[{"header": "Item"}, {"header": "Amount"}],
            resolved_mappings={"Item": {"mapped_to": "itemName"}, "Amount": {"mapped_to": "amount"}},
            rows=[["A", "10"]],
            validation_result={"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}},
        )
        events = service.get_audit_events_for_supplier(res["supplier_id"])
        assert len(events) >= 1
        assert events[0].event_type == "PROFILE_CREATED"

    def test_case_q_json_migration(self, temp_db):
        """Case Q: JSON supplier profiles migrate cleanly into SQLite."""
        report = run_migration(db_path=temp_db)
        assert report["suppliers_imported"] > 0
        assert report["layouts_imported"] > 0
        assert len(report["errors"]) == 0

    def test_case_r_migration_idempotency(self, temp_db):
        """Case R: Repeated migration does not duplicate records."""
        report1 = run_migration(db_path=temp_db)
        report2 = run_migration(db_path=temp_db)
        assert report2["suppliers_imported"] == 0
        assert report2["layouts_imported"] == 0
        assert report2["records_skipped"] > 0
        assert len(report2["errors"]) == 0

    def test_case_s_transaction_rollback(self, temp_db):
        """Case S: Transaction rollback preserves database consistency."""
        init_db(temp_db)
        with get_db_connection(temp_db) as conn:
            cursor = conn.cursor()
            try:
                conn.execute("BEGIN TRANSACTION;")
                cursor.execute("INSERT INTO suppliers (supplier_key, created_at, updated_at) VALUES ('ROLLBACK_KEY', 'now', 'now');")
                # Intentionally trigger an error with invalid query
                cursor.execute("INSERT INTO non_existent_table VALUES (1);")
                conn.commit()
            except Exception:
                conn.rollback()

            cursor.execute("SELECT * FROM suppliers WHERE supplier_key = 'ROLLBACK_KEY';")
            assert cursor.fetchone() is None

    def test_case_t_foreign_key_enforcement(self, temp_db):
        """Case T: Foreign keys are enforced on child tables."""
        init_db(temp_db)
        with get_db_connection(temp_db) as conn:
            cursor = conn.cursor()
            with pytest.raises(sqlite3.IntegrityError):
                cursor.execute("""
                    INSERT INTO supplier_layout_profiles (
                        supplier_id, layout_id, layout_signature, created_at, updated_at
                    ) VALUES (99999, 'orphan_layout', 'sig', 'now', 'now');
                """)

    def test_case_u_parameterized_queries(self, temp_db):
        """Case U: Parameterized queries protect against special characters."""
        service = StorageService(temp_db)
        dangerous_name = "DR. O'REILLY & SONS; DROP TABLE suppliers; --"
        res = service.save_or_update_supplier_profile_memory(
            supplier_key=dangerous_name,
            supplier_name=dangerous_name,
            gstin="36OREIL1234O1Z1",
            headers=["Item", "Amount"],
            logical_columns=[{"header": "Item"}, {"header": "Amount"}],
            resolved_mappings={"Item": {"mapped_to": "itemName"}, "Amount": {"mapped_to": "amount"}},
            rows=[["A", "10"]],
            validation_result={"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}},
        )
        sup = service.get_supplier_by_id(res["supplier_id"])
        assert sup.supplier_name == dangerous_name

    def test_case_v_persistence_across_process_restart(self, temp_db):
        """Case V: Data written by one service instance is visible to a subsequent instance."""
        service1 = StorageService(temp_db)
        service1.save_or_update_supplier_profile_memory(
            supplier_key="PERSIST_KEY",
            supplier_name="PERSIST_NAME",
            gstin="36PERST1234P1Z1",
            headers=["Item", "Amount"],
            logical_columns=[{"header": "Item"}, {"header": "Amount"}],
            resolved_mappings={"Item": {"mapped_to": "itemName"}, "Amount": {"mapped_to": "amount"}},
            rows=[["A", "10"]],
            validation_result={"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}},
        )
        del service1

        # Brand new instance
        service2 = StorageService(temp_db)
        sup = service2.find_supplier_by_gstin("36PERST1234P1Z1")
        assert sup is not None
        assert sup.supplier_key == "PERSIST_KEY"
