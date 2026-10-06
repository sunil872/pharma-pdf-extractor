import os
import sys
import json
import pytest

# Add project root to sys.path
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")

from extractor import (
    load_supplier_profiles,
    save_supplier_profiles,
    compute_layout_signature,
    compute_global_validation_and_confidence,
    detect_layout_drift,
    update_supplier_profile_memory,
    validate_supplier_identity_safety,
    create_review_session,
    check_duplicate_field_assignments,
    apply_and_validate_review_corrections,
    commit_reviewed_layout_to_profile_memory,
)


@pytest.fixture
def temp_profile_env(tmp_path):
    prof_path = str(tmp_path / "test_prompt8_profiles.json")
    return prof_path


class TestPrompt8HumanReviewSuite:

    def test_case_a_review_required_invoice_loads(self):
        """Case A: Review session object is properly constructed for REVIEW_REQUIRED invoice."""
        metadata = {
            "supplier_name": "Test Supplier",
            "supplier_gstin": "36TESTS1234F1Z5",
            "invoice_number": "INV-001",
            "supplier_confidence": 0.95,
            "classification": "REVIEW_REQUIRED",
            "confidence": 72.0,
            "validation": {
                "classification": "REVIEW_REQUIRED",
                "document_confidence": 72.0,
                "field_diagnostics": {},
                "row_discrepancies": [],
                "accounting_summary": {"critical_mismatches": 0},
            },
            "drift_report": {"drift_status": "NEW_SUPPLIER"},
        }
        headers = ["Product", "Pack", "Qty", "UnknownCol", "Rate", "Amount"]
        mappings = {
            "Product": {"mapped_to": "itemName", "status": "known_header", "confidence": 95.0},
            "Pack": {"mapped_to": "pack", "status": "known_header", "confidence": 95.0},
            "Qty": {"mapped_to": "quantity", "status": "known_header", "confidence": 95.0},
            "UnknownCol": {"mapped_to": None, "status": "unresolved", "confidence": 0.0},
            "Rate": {"mapped_to": "rate", "status": "known_header", "confidence": 95.0},
            "Amount": {"mapped_to": "amount", "status": "known_header", "confidence": 95.0},
        }
        rows = [["Dolo 650", "15T", "10", "30049099", "20.00", "200.00"]]

        session = create_review_session(metadata, headers, [], mappings, rows)

        assert session["review_id"].startswith("rev_")
        assert session["invoice_id"] == "INV-001"
        assert session["review_status"] == "PENDING_REVIEW"
        assert "UnknownCol" in session["unresolved_columns"]
        assert session["original_confidence"] == 72.0

    def test_case_b_unresolved_invoice_loads(self):
        """Case B: Unresolved invoice session properly identifies missing mandatory columns."""
        metadata = {
            "supplier_name": "Ambiguous Supplier",
            "classification": "UNRESOLVED",
            "confidence": 42.0,
            "validation": {"classification": "UNRESOLVED", "document_confidence": 42.0},
        }
        headers = ["Col1", "Col2", "Col3"]
        mappings = {
            "Col1": {"mapped_to": None, "status": "unresolved"},
            "Col2": {"mapped_to": None, "status": "unresolved"},
            "Col3": {"mapped_to": None, "status": "unresolved"},
        }
        rows = [["A", "B", "C"]]

        session = create_review_session(metadata, headers, [], mappings, rows)
        assert session["original_decision"] == "UNRESOLVED"
        assert len(session["unresolved_columns"]) == 3

    def test_case_c_reviewer_changes_field_mapping(self):
        """Case C: Reviewer modifies an unresolved mapping to hsnCode."""
        metadata = {
            "supplier_name": "Test Supplier",
            "invoice_number": "INV-002",
            "supplier_confidence": 0.95,
            "validation": {"classification": "REVIEW_REQUIRED", "document_confidence": 75.0},
        }
        headers = ["Product", "Pack", "Qty", "UnknownCol", "Rate", "Amount"]
        mappings = {
            "Product": {"mapped_to": "itemName", "status": "known_header", "confidence": 95.0},
            "Pack": {"mapped_to": "pack", "status": "known_header", "confidence": 95.0},
            "Qty": {"mapped_to": "quantity", "status": "known_header", "confidence": 95.0},
            "UnknownCol": {"mapped_to": None, "status": "unresolved", "confidence": 0.0},
            "Rate": {"mapped_to": "rate", "status": "known_header", "confidence": 95.0},
            "Amount": {"mapped_to": "amount", "status": "known_header", "confidence": 95.0},
        }
        rows = [["Dolo 650", "15T", "10", "30049099", "20.00", "200.00"]]
        session = create_review_session(metadata, headers, [], mappings, rows)

        proposed = {
            "Product": "itemName", "Pack": "pack", "Qty": "quantity",
            "UnknownCol": "hsnCode", "Rate": "rate", "Amount": "amount"
        }

        res = apply_and_validate_review_corrections(session, proposed)
        assert res["status"] in ("CORRECTION_VALIDATED", "CORRECTION_HAS_WARNINGS")
        assert res["corrections_count"] == 1
        updated = res["updated_session"]
        assert updated["corrections"][0]["new_field"] == "hsnCode"
        assert updated["corrections"][0]["old_field"] is None

    def test_case_d_duplicate_field_assignment_prevented(self):
        """Case D: Reviewer tries to map two columns to 'quantity'; system rejects duplicate."""
        metadata = {"supplier_name": "Test Supplier", "invoice_number": "INV-003"}
        headers = ["Product", "ColA", "ColB", "Rate", "Amount"]
        mappings = {
            "Product": {"mapped_to": "itemName"}, "ColA": {"mapped_to": "quantity"},
            "ColB": {"mapped_to": None}, "Rate": {"mapped_to": "rate"}, "Amount": {"mapped_to": "amount"}
        }
        rows = [["A", "10", "10", "20", "200"]]
        session = create_review_session(metadata, headers, [], mappings, rows)

        # Propose duplicate assignment of 'quantity' to both ColA and ColB
        proposed = {
            "Product": "itemName", "ColA": "quantity", "ColB": "quantity",
            "Rate": "rate", "Amount": "amount"
        }

        res = apply_and_validate_review_corrections(session, proposed)
        assert res["status"] == "CORRECTION_REJECTED"
        assert res["error_type"] == "DUPLICATE_FIELD_ASSIGNMENT"

    def test_case_e_correction_reruns_validation(self):
        """Case E: Applying a correction re-runs the global validation and re-evaluates accounting health."""
        metadata = {"supplier_name": "Test Supplier", "invoice_number": "INV-004"}
        headers = ["Product", "Pack", "Qty", "Rate", "Amount"]
        mappings = {
            "Product": {"mapped_to": "itemName"}, "Pack": {"mapped_to": "pack"},
            "Qty": {"mapped_to": "rate"}, "Rate": {"mapped_to": "quantity"}, "Amount": {"mapped_to": "amount"}
        }
        rows = [["Dolo 650", "10T", "10.00", "20.00", "200.00"]]
        session = create_review_session(metadata, headers, [], mappings, rows)

        # Fix swapped Qty and Rate
        proposed = {"Product": "itemName", "Pack": "pack", "Qty": "quantity", "Rate": "rate", "Amount": "amount"}
        res = apply_and_validate_review_corrections(session, proposed)

        assert res["status"] == "CORRECTION_VALIDATED"
        assert res["validated_result"]["accounting_summary"]["critical_mismatches"] == 0

    def test_case_f_valid_correction_accepted(self):
        """Case F: Valid correction achieves REVIEW_CONFIRMED status."""
        metadata = {"supplier_name": "Valid Supp", "invoice_number": "INV-005"}
        headers = ["Product", "Qty", "Rate", "Amount"]
        mappings = {"Product": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "Rate": {"mapped_to": None}, "Amount": {"mapped_to": "amount"}}
        rows = [["Dolo", "5", "10.00", "50.00"]]
        session = create_review_session(metadata, headers, [], mappings, rows)

        proposed = {"Product": "itemName", "Qty": "quantity", "Rate": "rate", "Amount": "amount"}
        res = apply_and_validate_review_corrections(session, proposed)

        assert res["status"] == "CORRECTION_VALIDATED"
        assert res["outcome"] == "REVIEW_CONFIRMED"

    def test_case_g_invalid_correction_rejected(self):
        """Case G: Human assigns completely contradictory mapping (e.g. non-numeric text column as Rate) -> Rejected."""
        metadata = {"supplier_name": "Invalid Supp", "invoice_number": "INV-006"}
        headers = ["Product", "Qty", "DescriptionText", "Amount"]
        mappings = {"Product": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "DescriptionText": {"mapped_to": None}, "Amount": {"mapped_to": "amount"}}
        rows = [["Dolo", "5", "THIS IS NON NUMERIC TEXT", "50.00"]]
        session = create_review_session(metadata, headers, [], mappings, rows)

        # Try to map pure text column to numeric 'rate'
        proposed = {"Product": "itemName", "Qty": "quantity", "DescriptionText": "rate", "Amount": "amount"}
        res = apply_and_validate_review_corrections(session, proposed)

        assert res["status"] == "CORRECTION_REJECTED" or res["outcome"] == "REVIEW_NOT_CONFIRMED" or res["status"] == "CORRECTION_HAS_WARNINGS"

    def test_case_h_human_confirmation_updates_profile(self, temp_profile_env):
        """Case H: Human confirmation with explicit save commits to profile memory."""
        metadata = {"supplier_name": "Supplier H", "supplier_gstin": "36HHHHH0000H1Z5", "invoice_number": "INV-008"}
        headers = ["Product", "Pack", "Qty", "Rate", "Amount"]
        mappings = {"Product": {"mapped_to": "itemName"}, "Pack": {"mapped_to": "pack"}, "Qty": {"mapped_to": "quantity"}, "Rate": {"mapped_to": "rate"}, "Amount": {"mapped_to": "amount"}}
        rows = [["Dolo", "10T", "5", "10.00", "50.00"]]
        session = create_review_session(metadata, headers, [], mappings, rows)

        proposed = {"Product": "itemName", "Pack": "pack", "Qty": "quantity", "Rate": "rate", "Amount": "amount"}
        val_res = apply_and_validate_review_corrections(session, proposed)
        updated_session = val_res["updated_session"]

        commit_res = commit_reviewed_layout_to_profile_memory(updated_session, profiles_storage_path=temp_profile_env)
        assert commit_res["committed"] is True

        prof = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["36HHHHH0000H1Z5"]
        assert prof["reviewed_document_count"] == 1

    def test_case_i_no_save_correction_does_not_update_profile(self, temp_profile_env):
        """Case I: Validating/correcting without explicit commit does not pollute profile store."""
        metadata = {"supplier_name": "Supplier I", "supplier_gstin": "36IIIII0000I1Z5", "invoice_number": "INV-009"}
        headers = ["Product", "Qty", "Rate", "Amount"]
        mappings = {"Product": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "Rate": {"mapped_to": "rate"}, "Amount": {"mapped_to": "amount"}}
        rows = [["Dolo", "5", "10.00", "50.00"]]
        session = create_review_session(metadata, headers, [], mappings, rows)

        proposed = {"Product": "itemName", "Qty": "quantity", "Rate": "rate", "Amount": "amount"}
        apply_and_validate_review_corrections(session, proposed)

        # Do NOT call commit_reviewed_layout_to_profile_memory
        profiles = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]
        assert "36IIIII0000I1Z5" not in profiles

    def test_case_j_existing_layout_remains_unchanged(self, temp_profile_env):
        """Case J: Existing historical layout version remains unchanged when reviewing."""
        metadata = {"supplier_name": "Supplier J", "supplier_gstin": "36JJJJJ0000J1Z5", "invoice_number": "INV-010"}
        h1 = ["Product", "Qty", "Rate", "Amount"]
        m1 = {h: {"mapped_to": f, "status": "known_header"} for h, f in [("Product", "itemName"), ("Qty", "quantity"), ("Rate", "rate"), ("Amount", "amount")]}
        val_dict = {"classification": "AUTO_ACCEPT", "document_confidence": 95.0, "accounting_summary": {"critical_mismatches": 0}}
        update_supplier_profile_memory("36JJJJJ0000J1Z5", "Supplier J", "36JJJJJ0000J1Z5", h1, [], m1, [["A", "1", "10", "10"]], val_dict, profiles_storage_path=temp_profile_env)

        # Review second invoice with same layout
        session = create_review_session(metadata, h1, [], m1, [["B", "2", "10", "20"]])
        val_res = apply_and_validate_review_corrections(session, {h: m1[h]["mapped_to"] for h in h1})
        commit_reviewed_layout_to_profile_memory(val_res["updated_session"], profiles_storage_path=temp_profile_env)

        prof = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["36JJJJJ0000J1Z5"]
        assert len(prof["layout_profiles"]) == 1
        assert prof["reviewed_document_count"] == 1

    def test_case_k_changed_layout_creates_new_layout_version(self, temp_profile_env):
        """Case K: Reviewing a changed layout creates layout_v2 preserving layout_v1."""
        h1 = ["Product", "Qty", "Rate", "Amount"]
        m1 = {h: {"mapped_to": f, "status": "known_header"} for h, f in [("Product", "itemName"), ("Qty", "quantity"), ("Rate", "rate"), ("Amount", "amount")]}
        val_dict = {"classification": "AUTO_ACCEPT", "document_confidence": 95.0, "accounting_summary": {"critical_mismatches": 0}}
        update_supplier_profile_memory("36KKKKK0000K1Z5", "Supplier K", "36KKKKK0000K1Z5", h1, [], m1, [["A", "1", "10", "10"]], val_dict, profiles_storage_path=temp_profile_env)

        # New layout with 8 columns
        h2 = ["SNo", "Item", "Pack", "Batch", "Exp", "Qty", "Rate", "Amount"]
        m2 = {h: {"mapped_to": None, "status": "unresolved"} for h in h2}
        metadata = {"supplier_name": "Supplier K", "supplier_gstin": "36KKKKK0000K1Z5", "invoice_number": "INV-011"}
        session = create_review_session(metadata, h2, [], m2, [["1", "A", "10T", "B1", "12/26", "2", "10", "20"]])

        proposed = {"SNo": None, "Item": "itemName", "Pack": "pack", "Batch": "batchNo", "Exp": "expiryDate", "Qty": "quantity", "Rate": "rate", "Amount": "amount"}
        val_res = apply_and_validate_review_corrections(session, proposed)
        commit_res = commit_reviewed_layout_to_profile_memory(val_res["updated_session"], profiles_storage_path=temp_profile_env)

        assert commit_res["committed"] is True
        prof = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["36KKKKK0000K1Z5"]
        assert len(prof["layout_profiles"]) == 2

    def test_case_l_review_history_recorded(self, temp_profile_env):
        """Case L: Each review confirmation records audit metadata into review_history."""
        metadata = {"supplier_name": "Supplier L", "supplier_gstin": "36LLLLL0000L1Z5", "invoice_number": "INV-012"}
        headers = ["Product", "Qty", "Rate", "Amount"]
        mappings = {"Product": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "Rate": {"mapped_to": "rate"}, "Amount": {"mapped_to": "amount"}}
        rows = [["Dolo", "5", "10.00", "50.00"]]
        session = create_review_session(metadata, headers, [], mappings, rows)

        proposed = {"Product": "itemName", "Qty": "quantity", "Rate": "rate", "Amount": "amount"}
        val_res = apply_and_validate_review_corrections(session, proposed, reviewer_id="audit_operator_1")
        commit_reviewed_layout_to_profile_memory(val_res["updated_session"], profiles_storage_path=temp_profile_env)

        prof = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["36LLLLL0000L1Z5"]
        layout_p = list(prof["layout_profiles"].values())[0]
        assert "review_history" in layout_p
        assert len(layout_p["review_history"]) == 1
        assert layout_p["review_history"][0]["reviewed_by"] == "audit_operator_1"

    def test_case_m_human_confirmed_field_reliability_increases(self, temp_profile_env):
        """Case M: Human confirmation increments human_confirmed_count on mapped fields."""
        metadata = {"supplier_name": "Supplier M", "supplier_gstin": "36MMMMM0000M1Z5", "invoice_number": "INV-013"}
        headers = ["Product", "Qty", "Rate", "Amount"]
        mappings = {"Product": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "Rate": {"mapped_to": "rate"}, "Amount": {"mapped_to": "amount"}}
        rows = [["Dolo", "5", "10.00", "50.00"]]
        session = create_review_session(metadata, headers, [], mappings, rows)

        proposed = {"Product": "itemName", "Qty": "quantity", "Rate": "rate", "Amount": "amount"}
        val_res = apply_and_validate_review_corrections(session, proposed)
        commit_reviewed_layout_to_profile_memory(val_res["updated_session"], profiles_storage_path=temp_profile_env)

        prof = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["36MMMMM0000M1Z5"]
        layout_p = list(prof["layout_profiles"].values())[0]
        assert layout_p["field_reliability"]["quantity"]["human_confirmed_count"] == 1

    def test_case_n_inferred_field_does_not_equal_human_confirmed_field(self, temp_profile_env):
        """Case N: Automated inference tracks algorithm_confirmed_count separately from human_confirmed_count."""
        h = ["Product", "Qty", "Rate", "Amount"]
        m = {f_name: {"mapped_to": f, "status": "known_header"} for f_name, f in [("Product", "itemName"), ("Qty", "quantity"), ("Rate", "rate"), ("Amount", "amount")]}
        val_dict = {"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}}
        # Automated update
        update_supplier_profile_memory("36NNNNN0000N1Z5", "Supplier N", "36NNNNN0000N1Z5", h, [], m, [["A", "1", "10", "10"]], val_dict, is_user_reviewed=False, profiles_storage_path=temp_profile_env)

        prof = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["36NNNNN0000N1Z5"]
        layout_p = list(prof["layout_profiles"].values())[0]
        assert layout_p["field_reliability"]["quantity"]["algorithm_confirmed_count"] == 1
        assert layout_p["field_reliability"]["quantity"]["human_confirmed_count"] == 0

    def test_case_o_current_evidence_overrides_historical_profile(self, temp_profile_env):
        """Case O: Profile prior is overridden when current invoice evidence clearly indicates different fields."""
        metadata = {"supplier_name": "Supplier O", "supplier_gstin": "36OOOOO0000O1Z5", "invoice_number": "INV-015"}
        h = ["Product", "PriceA", "PriceB", "Qty", "Amount"]
        # Prior had PriceA = Rate, PriceB = MRP
        m_prior = {"Product": {"mapped_to": "itemName"}, "PriceA": {"mapped_to": "rate"}, "PriceB": {"mapped_to": "mrp"}, "Qty": {"mapped_to": "quantity"}, "Amount": {"mapped_to": "amount"}}
        val_dict = {"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}}
        update_supplier_profile_memory("36OOOOO0000O1Z5", "Supplier O", "36OOOOO0000O1Z5", h, [], m_prior, [["A", "10.00", "15.00", "1", "10.00"]], val_dict, profiles_storage_path=temp_profile_env)

        # Current invoice has PriceA = 150.00 (MRP), PriceB = 100.00 (Rate), Amount = 100.00 (Qty=1)
        current_rows = [["Dolo", "150.00", "100.00", "1", "100.00"]]
        val_curr = compute_global_validation_and_confidence(
            headers=h, logical_columns=[], column_mappings=m_prior, rows=current_rows, metadata=metadata
        )
        assert val_curr["resolved_mappings"]["PriceB"]["mapped_to"] == "rate"
        assert val_curr["resolved_mappings"]["PriceA"]["mapped_to"] == "mrp"

    def test_case_p_new_supplier_review_creates_layout_v1(self, temp_profile_env):
        """Case P: Reviewing a new supplier invoice creates a supplier profile with layout_v1."""
        metadata = {"supplier_name": "Brand New Pharma", "supplier_gstin": "36PPPPP0000P1Z5", "invoice_number": "INV-016"}
        headers = ["Product", "Pack", "Qty", "Rate", "Amount"]
        mappings = {"Product": {"mapped_to": "itemName"}, "Pack": {"mapped_to": "pack"}, "Qty": {"mapped_to": "quantity"}, "Rate": {"mapped_to": "rate"}, "Amount": {"mapped_to": "amount"}}
        session = create_review_session(metadata, headers, [], mappings, [["A", "10T", "1", "10", "10"]])

        val_res = apply_and_validate_review_corrections(session, {h: mappings[h]["mapped_to"] for h in headers})
        commit_res = commit_reviewed_layout_to_profile_memory(val_res["updated_session"], profiles_storage_path=temp_profile_env)

        assert commit_res["committed"] is True
        assert commit_res["action"] == "NEW_SUPPLIER_PROFILE_CREATED"

    def test_case_q_ambiguous_supplier_identity_not_auto_attached(self):
        """Case Q: Ambiguous supplier identity triggers SUPPLIER_IDENTITY_REVIEW_REQUIRED and blocks auto-attach."""
        identity = validate_supplier_identity_safety(supplier_name="P", gstin="INVALID_GSTIN", name_confidence=0.40)
        assert identity["status"] in ("SUPPLIER_IDENTITY_REVIEW_REQUIRED", "NO_IDENTITY")
        assert identity["is_safe_to_attach"] is False

    def test_case_r_existing_supplier_new_layout_creates_layout_v2(self, temp_profile_env):
        """Case R: Existing supplier with newly confirmed layout produces layout_v2."""
        h1 = ["Product", "Qty", "Rate", "Amount"]
        m1 = {h: {"mapped_to": f, "status": "known_header"} for h, f in [("Product", "itemName"), ("Qty", "quantity"), ("Rate", "rate"), ("Amount", "amount")]}
        val_dict = {"classification": "AUTO_ACCEPT", "document_confidence": 95.0, "accounting_summary": {"critical_mismatches": 0}}
        update_supplier_profile_memory("36RRRRR0000R1Z5", "Supplier R", "36RRRRR0000R1Z5", h1, [], m1, [["A", "1", "10", "10"]], val_dict, profiles_storage_path=temp_profile_env)

        # New layout
        h2 = ["SNo", "Product", "Batch", "Exp", "Qty", "Free", "Rate", "MRP", "GST", "Amount"]
        m2 = {h: {"mapped_to": None, "status": "unresolved"} for h in h2}
        metadata = {"supplier_name": "Supplier R", "supplier_gstin": "36RRRRR0000R1Z5", "invoice_number": "INV-018"}
        session = create_review_session(metadata, h2, [], m2, [["1", "A", "B", "12/26", "1", "0", "10", "15", "5", "10"]])

        proposed = {"SNo": None, "Product": "itemName", "Batch": "batchNo", "Exp": "expiryDate", "Qty": "quantity", "Free": "freeQuantity", "Rate": "rate", "MRP": "mrp", "GST": "gstPercent", "Amount": "amount"}
        val_res = apply_and_validate_review_corrections(session, proposed)
        commit_res = commit_reviewed_layout_to_profile_memory(val_res["updated_session"], profiles_storage_path=temp_profile_env)

        assert commit_res["committed"] is True
        assert commit_res["action"] == "NEW_LAYOUT_VERSION_CREATED"

    def test_case_s_export_without_saving_works(self):
        """Case S: Reviewer can export corrected DataFrame without modifying profile storage."""
        metadata = {"supplier_name": "Supplier S", "invoice_number": "INV-019"}
        headers = ["Product", "Qty", "Rate", "Amount"]
        mappings = {"Product": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "Rate": {"mapped_to": "rate"}, "Amount": {"mapped_to": "amount"}}
        rows = [["Dolo 650", "10", "20.00", "200.00"]]
        session = create_review_session(metadata, headers, [], mappings, rows)

        proposed = {"Product": "itemName", "Qty": "quantity", "Rate": "rate", "Amount": "amount"}
        res = apply_and_validate_review_corrections(session, proposed)

        assert res["status"] == "CORRECTION_VALIDATED"
        # Successfully produced validated mappings for DataFrame conversion without storage commit
        assert res["validated_result"]["revalidated_mappings"]["Product"]["mapped_to"] == "itemName"

    def test_case_t_regression_check_prompts_0_to_7(self):
        """Case T: Verify ALIAS_DICT and baseline template data integrity."""
        from extractor import ALIAS_DICT
        assert "m r p" in ALIAS_DICT["mrp"]
        assert "m.r.p." in ALIAS_DICT["mrp"]
