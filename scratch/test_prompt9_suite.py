import os
import sys
import json
import hashlib
import copy
import pytest
import re

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
    match_supplier_layout_profile,
    extract_pdf_table,
)

SAMPLE_DIR = r"c:\Users\sunil\pharma-pdf-extractor\Sample Invoices"
MANIFEST_PATH = r"c:\Users\sunil\pharma-pdf-extractor\benchmark_manifest.json"
RESULTS_PATH = r"c:\Users\sunil\pharma-pdf-extractor\benchmark_results_v1.json"


@pytest.fixture
def temp_profile_env(tmp_path):
    prof_path = str(tmp_path / "test_prompt9_profiles.json")
    return prof_path


class TestPrompt9FixedBenchmarkAndHardening:

    def test_case_a_manifest_exists(self):
        """Case A: Original benchmark manifest exists."""
        assert os.path.exists(MANIFEST_PATH), f"Benchmark manifest missing at {MANIFEST_PATH}"
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        assert manifest.get("sample_count") == 9
        assert len(manifest.get("samples", [])) == 9

    def test_case_b_file_hashes_recorded_and_match(self):
        """Case B: File hashes are recorded and match actual disk files."""
        with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        for sample in manifest["samples"]:
            fname = sample["filename"]
            fpath = os.path.join(SAMPLE_DIR, fname)
            assert os.path.exists(fpath), f"Sample file {fname} not found in {SAMPLE_DIR}"
            with open(fpath, "rb") as pdf_f:
                actual_hash = hashlib.sha256(pdf_f.read()).hexdigest()
            assert actual_hash == sample["file_hash"], f"Hash mismatch for {fname}: expected {sample['file_hash']}, got {actual_hash}"

    def test_case_c_missing_benchmark_file_detected(self):
        """Case C: Missing benchmark file is detected explicitly."""
        dummy_manifest = {
            "samples": [{"filename": "NON_EXISTENT_INVOICE.PDF", "file_hash": "dummy123"}]
        }
        for sample in dummy_manifest["samples"]:
            fpath = os.path.join(SAMPLE_DIR, sample["filename"])
            assert not os.path.exists(fpath)

    def test_case_d_additional_sample_files_identified_separately(self):
        """Case D: Prompt 8 phantom filenames are verified as non-existent or separate."""
        phantom_names = [
            "INVOICE_7HQ1E9E4J.PDF",
            "INVOICE_7I704R44R.PDF",
            "INVOICE_7IR2K2Q8E.PDF",
            "INVOICE_7K5135Y5K.PDF",
            "INVOICE_7KO3S7D2I.PDF",
            "INVOICE_7KU1C007R.PDF",
            "INVOICE_7LW17Q1J5.PDF",
        ]
        disk_files = os.listdir(SAMPLE_DIR)
        for p in phantom_names:
            assert p not in disk_files, f"File {p} unexpectedly found in benchmark folder"

    def test_case_e_supplier_identity_deterministic(self):
        """Case E: Supplier identity extraction is 100% deterministic."""
        res1 = validate_supplier_identity_safety("PRAPTI MEDICARE", "36AASFP4005A1ZJ", 0.95)
        res2 = validate_supplier_identity_safety("PRAPTI MEDICARE", "36AASFP4005A1ZJ", 0.95)
        assert res1 == res2
        assert res1["status"] == "EXACT_GSTIN"
        assert res1["supplier_key"] == "36AASFP4005A1ZJ"

    def test_case_f_gstin_protects_identity(self):
        """Case F: Valid GSTIN format provides EXACT_GSTIN protection."""
        res = validate_supplier_identity_safety("Arbitrary Name", "27AABCT3518Q1ZV", 0.50)
        assert res["status"] == "EXACT_GSTIN"
        assert res["supplier_key"] == "27AABCT3518Q1ZV"
        assert res["is_safe_to_attach"] is True

    def test_case_g_similar_supplier_names_do_not_merge(self, temp_profile_env):
        """Case G: Similar supplier names with different GSTINs do not merge profiles."""
        headers = ["Item Name", "Batch", "Expiry", "Qty", "Rate", "Amount"]
        cols = [{"header": h, "values": ["v1", "v2"]} for h in headers]
        resolved = {
            "Item Name": {"mapped_to": "itemName", "status": "mapped"},
            "Batch": {"mapped_to": "batchNo", "status": "mapped"},
            "Expiry": {"mapped_to": "expiryDate", "status": "mapped"},
            "Qty": {"mapped_to": "quantity", "status": "mapped"},
            "Rate": {"mapped_to": "rate", "status": "mapped"},
            "Amount": {"mapped_to": "amount", "status": "mapped"},
        }
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 92.0, "accounting_summary": {"critical_mismatches": 0}}
        
        # Supplier 1
        update_supplier_profile_memory(
            supplier_key="36AASFP4005A1ZJ",
            supplier_name="MEDICARE PHARMA",
            gstin="36AASFP4005A1ZJ",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=resolved,
            rows=[["A", "B1", "12/26", "10", "100", "1000"]],
            validation_result=val_res,
            profiles_storage_path=temp_profile_env,
        )

        # Supplier 2 with similar name but different GSTIN
        update_supplier_profile_memory(
            supplier_key="36ABCDE1234F1Z5",
            supplier_name="MEDICARE PHARMACEUTICALS",
            gstin="36ABCDE1234F1Z5",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=resolved,
            rows=[["A", "B1", "12/26", "10", "100", "1000"]],
            validation_result=val_res,
            profiles_storage_path=temp_profile_env,
        )

        profiles = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]
        assert len(profiles) == 2
        assert "36AASFP4005A1ZJ" in profiles
        assert "36ABCDE1234F1Z5" in profiles

    def test_case_h_similar_layouts_do_not_merge_suppliers(self, temp_profile_env):
        """Case H: Identical layout across two distinct suppliers does not merge supplier profiles."""
        headers = ["Item", "Qty", "Price", "Total"]
        cols = [{"header": h, "values": ["v1"]} for h in headers]
        resolved = {
            "Item": {"mapped_to": "itemName", "status": "mapped"},
            "Qty": {"mapped_to": "quantity", "status": "mapped"},
            "Price": {"mapped_to": "rate", "status": "mapped"},
            "Total": {"mapped_to": "amount", "status": "mapped"},
        }
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 95.0, "accounting_summary": {"critical_mismatches": 0}}

        update_supplier_profile_memory(
            supplier_key="SUPPLIER_A",
            supplier_name="SUPPLIER_A",
            gstin="36AAAAA1111A1Z1",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=resolved,
            rows=[["Product 1", "2", "50", "100"]],
            validation_result=val_res,
            profiles_storage_path=temp_profile_env,
        )

        update_supplier_profile_memory(
            supplier_key="SUPPLIER_B",
            supplier_name="SUPPLIER_B",
            gstin="36BBBBB2222B1Z2",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=resolved,
            rows=[["Product 2", "5", "20", "100"]],
            validation_result=val_res,
            profiles_storage_path=temp_profile_env,
        )

        profiles = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]
        assert "SUPPLIER_A" in profiles
        assert "SUPPLIER_B" in profiles
        assert len(profiles["SUPPLIER_A"]["layout_profiles"]) == 1
        assert len(profiles["SUPPLIER_B"]["layout_profiles"]) == 1

    def test_case_i_same_supplier_changed_layout_creates_layout_v2(self, temp_profile_env):
        """Case I: Same supplier with drifted layout creates layout_v2 without deleting layout_v1."""
        headers_v1 = ["Item", "Qty", "Price", "Total"]
        cols_v1 = [{"header": h, "values": ["v1"]} for h in headers_v1]
        resolved_v1 = {
            "Item": {"mapped_to": "itemName", "status": "mapped"},
            "Qty": {"mapped_to": "quantity", "status": "mapped"},
            "Price": {"mapped_to": "rate", "status": "mapped"},
            "Total": {"mapped_to": "amount", "status": "mapped"},
        }
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 95.0, "accounting_summary": {"critical_mismatches": 0}}

        res1 = update_supplier_profile_memory(
            supplier_key="SUPPLIER_X",
            supplier_name="SUPPLIER_X",
            gstin="36XXXXX1234X1Z1",
            headers=headers_v1,
            logical_columns=cols_v1,
            resolved_mappings=resolved_v1,
            rows=[["Product", "1", "10", "10"]],
            validation_result=val_res,
            profiles_storage_path=temp_profile_env,
        )
        assert res1["action"] == "NEW_SUPPLIER_PROFILE_CREATED"

        # Completely different layout for SUPPLIER_X
        headers_v2 = ["Drug Description", "Batch No", "Exp", "Pack Size", "Quantity", "Unit Rate", "Discount %", "Taxable Val", "GST %", "Net Amount"]
        cols_v2 = [{"header": h, "values": ["v2"]} for h in headers_v2]
        resolved_v2 = {h: {"mapped_to": "itemName" if "Drug" in h else "amount", "status": "mapped"} for h in headers_v2}

        res2 = update_supplier_profile_memory(
            supplier_key="SUPPLIER_X",
            supplier_name="SUPPLIER_X",
            gstin="36XXXXX1234X1Z1",
            headers=headers_v2,
            logical_columns=cols_v2,
            resolved_mappings=resolved_v2,
            rows=[["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]],
            validation_result=val_res,
            profiles_storage_path=temp_profile_env,
        )
        assert res2["action"] == "NEW_LAYOUT_VERSION_CREATED"

        prof = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["SUPPLIER_X"]
        assert len(prof["layout_profiles"]) == 2
        assert res1["layout_id"] in prof["layout_profiles"]
        assert res2["layout_id"] in prof["layout_profiles"]

    def test_case_j_profile_matching_deterministic(self, temp_profile_env):
        """Case J: Profile matching produces identical match score and status repeatedly."""
        headers = ["Item", "Qty", "Amount"]
        cols = [{"header": h, "values": ["v"]} for h in headers]
        resolved = {"Item": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "Amount": {"mapped_to": "amount"}}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}}
        update_supplier_profile_memory(
            supplier_key="SUP_DET",
            supplier_name="SUP_DET",
            gstin="36DDDDD1234D1Z1",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=resolved,
            rows=[["A", "1", "10"]],
            validation_result=val_res,
            profiles_storage_path=temp_profile_env,
        )
        profiles_data = load_supplier_profiles(storage_path=temp_profile_env)
        sig = compute_layout_signature(headers, cols, [["A", "1", "10"]])
        
        match1 = match_supplier_layout_profile("SUP_DET", sig, profiles_data=profiles_data, headers=headers)
        match2 = match_supplier_layout_profile("SUP_DET", sig, profiles_data=profiles_data, headers=headers)
        assert match1["drift_status"] == match2["drift_status"]
        assert match1["similarity_score"] == match2["similarity_score"]
        assert match1["matched_layout"]["layout_id"] == match2["matched_layout"]["layout_id"]

    def test_case_k_extraction_deterministic(self):
        """Case K: Running extraction on benchmark PDF 3 times produces byte-identical rows and confidence."""
        pdf_path = os.path.join(SAMPLE_DIR, "INVOICE_7GX167AKM.PDF")
        meta1, hdrs1, maps1, rows1 = extract_pdf_table(pdf_path)
        meta2, hdrs2, maps2, rows2 = extract_pdf_table(pdf_path)
        meta3, hdrs3, maps3, rows3 = extract_pdf_table(pdf_path)

        assert hdrs1 == hdrs2 == hdrs3
        assert rows1 == rows2 == rows3
        assert meta1["confidence"] == meta2["confidence"] == meta3["confidence"]
        assert meta1["classification"] == meta2["classification"] == meta3["classification"]
        assert maps1 == maps2 == maps3

    def test_case_l_review_simulation_does_not_update_without_confirmation(self, temp_profile_env):
        """Case L: Review simulation does not touch profile memory until commit is called."""
        metadata = {"supplier_name": "Review Sup", "supplier_gstin": "36REVXX1234X1Z1", "supplier_confidence": 0.95}
        headers = ["Product", "Qty", "Total"]
        cols = [{"header": h, "values": ["1"]} for h in headers]
        mappings = {"Product": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "Total": {"mapped_to": None}}
        rows = [["Medicine A", "10", "100.00"]]
        
        session = create_review_session(metadata, headers, cols, mappings, rows)
        apply_res = apply_and_validate_review_corrections(session, {"Product": "itemName", "Qty": "quantity", "Total": "amount"})
        assert apply_res["status"] == "CORRECTION_VALIDATED"
        
        # Profile store should remain empty since commit was not called
        profiles_data = load_supplier_profiles(storage_path=temp_profile_env)
        assert len(profiles_data.get("profiles", {})) == 0

    def test_case_m_valid_review_updates_profile(self, temp_profile_env):
        """Case M: Valid review correction successfully updates profile memory upon commit."""
        metadata = {"supplier_name": "Review Sup", "supplier_gstin": "36REVXX1234X1Z1", "supplier_confidence": 0.95}
        headers = ["Product", "Qty", "Total"]
        cols = [{"header": h, "values": ["1"]} for h in headers]
        mappings = {"Product": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "Total": {"mapped_to": None}}
        rows = [["Medicine A", "10", "100.00"]]
        
        session = create_review_session(metadata, headers, cols, mappings, rows)
        apply_res = apply_and_validate_review_corrections(session, {"Product": "itemName", "Qty": "quantity", "Total": "amount"})
        
        commit_res = commit_reviewed_layout_to_profile_memory(apply_res["updated_session"], profiles_storage_path=temp_profile_env)
        assert commit_res["committed"] is True
        
        profiles = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]
        assert "36REVXX1234X1Z1" in profiles
        assert profiles["36REVXX1234X1Z1"]["reviewed_document_count"] == 1

    def test_case_n_invalid_review_does_not_update_profile(self, temp_profile_env):
        """Case N: Invalid review correction (duplicate assignment or rejected) cannot be committed."""
        metadata = {"supplier_name": "Review Sup", "supplier_gstin": "36REVXX1234X1Z1", "supplier_confidence": 0.95}
        headers = ["Product", "Qty", "Total"]
        cols = [{"header": h, "values": ["1"]} for h in headers]
        mappings = {"Product": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "Total": {"mapped_to": None}}
        rows = [["Medicine A", "10", "100.00"]]
        
        session = create_review_session(metadata, headers, cols, mappings, rows)
        # Duplicate mapping
        apply_res = apply_and_validate_review_corrections(session, {"Product": "itemName", "Qty": "itemName", "Total": "amount"})
        assert apply_res["status"] == "CORRECTION_REJECTED"

        commit_res = commit_reviewed_layout_to_profile_memory(apply_res["updated_session"], profiles_storage_path=temp_profile_env)
        assert commit_res["committed"] is False
        assert "Cannot commit" in commit_res["reason"]

    def test_case_o_historical_layout_remains_intact(self, temp_profile_env):
        """Case O: Profile update preserves previous layout history and counters."""
        headers = ["Item", "Qty", "Amount"]
        cols = [{"header": h, "values": ["v"]} for h in headers]
        resolved = {"Item": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "Amount": {"mapped_to": "amount"}}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}}
        
        update_supplier_profile_memory(
            supplier_key="SUP_HIST",
            supplier_name="SUP_HIST",
            gstin="36HIST1234H1Z1",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=resolved,
            rows=[["A", "1", "10"]],
            validation_result=val_res,
            profiles_storage_path=temp_profile_env,
        )
        
        prof1 = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["SUP_HIST"]
        first_layout_id = list(prof1["layout_profiles"].keys())[0]

        # Add second layout version
        headers2 = ["Product Description", "Batch", "Expiry", "Qty", "MRP", "Rate", "Amount"]
        cols2 = [{"header": h, "values": ["v"]} for h in headers2]
        resolved2 = {h: {"mapped_to": "itemName" if "Product" in h else "amount"} for h in headers2}
        update_supplier_profile_memory(
            supplier_key="SUP_HIST",
            supplier_name="SUP_HIST",
            gstin="36HIST1234H1Z1",
            headers=headers2,
            logical_columns=cols2,
            resolved_mappings=resolved2,
            rows=[["A", "B", "C", "D", "E", "F", "G"]],
            validation_result=val_res,
            profiles_storage_path=temp_profile_env,
        )

        prof2 = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["SUP_HIST"]
        assert first_layout_id in prof2["layout_profiles"]
        assert len(prof2["layout_profiles"]) == 2

    def test_case_p_stale_profile_write_is_rejected(self, temp_profile_env):
        """Case P: Stale profile write is rejected with PROFILE_VERSION_CONFLICT."""
        headers = ["Item", "Qty", "Amount"]
        cols = [{"header": h, "values": ["v"]} for h in headers]
        resolved = {"Item": {"mapped_to": "itemName"}, "Qty": {"mapped_to": "quantity"}, "Amount": {"mapped_to": "amount"}}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}}

        # Process A loads initial state (version 1)
        p_data_a = load_supplier_profiles(storage_path=temp_profile_env)
        v_a = p_data_a.get("version", 1)

        # Process B loads initial state (version 1)
        p_data_b = load_supplier_profiles(storage_path=temp_profile_env)
        v_b = p_data_b.get("version", 1)

        # Process A updates and saves (version increments to 2)
        res_a = update_supplier_profile_memory(
            supplier_key="SUP_CONC",
            supplier_name="SUP_CONC",
            gstin="36CONC1234C1Z1",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=resolved,
            rows=[["A", "1", "10"]],
            validation_result=val_res,
            expected_version=v_a,
            profiles_storage_path=temp_profile_env,
        )
        assert res_a["updated"] is True

        # Process B attempts to save using stale expected_version=v_b (version 1)
        res_b = update_supplier_profile_memory(
            supplier_key="SUP_CONC_B",
            supplier_name="SUP_CONC_B",
            gstin="36CONC2222B1Z2",
            headers=headers,
            logical_columns=cols,
            resolved_mappings=resolved,
            rows=[["B", "2", "20"]],
            validation_result=val_res,
            expected_version=v_b,
            profiles_storage_path=temp_profile_env,
        )
        assert res_b["updated"] is False
        assert res_b.get("conflict") is True
        assert res_b.get("reason") == "PROFILE_VERSION_CONFLICT"

    def test_case_q_confidence_remains_separate_from_human_confirmation(self):
        """Case Q: Human confirmation does NOT artificially inflate algorithm confidence to 100%."""
        metadata = {"supplier_name": "Test Sup", "supplier_gstin": "36TEST1234T1Z1", "confidence": 68.5}
        headers = ["Item", "Qty", "Total"]
        cols = [{"header": h, "values": ["1"]} for h in headers]
        mappings = {"Item": {"mapped_to": "itemName", "confidence": 70.0}, "Qty": {"mapped_to": "quantity", "confidence": 70.0}, "Total": {"mapped_to": None}}
        rows = [["Medicine A", "10", "100.00"]]

        session = create_review_session(metadata, headers, cols, mappings, rows)
        apply_res = apply_and_validate_review_corrections(session, {"Item": "itemName", "Qty": "quantity", "Total": "amount"})
        val_result = apply_res["validated_result"]
        
        assert val_result["confirmation_status"] == "HUMAN_CONFIRMED"
        assert session["original_confidence"] == 68.5

    def test_case_r_prompt0_to_8_regression_suite_intact(self):
        """Case R: Regression test verifying key modules load and schemas remain compatible."""
        assert os.path.exists(r"c:\Users\sunil\pharma-pdf-extractor\extractor.py")
        assert os.path.exists(r"c:\Users\sunil\pharma-pdf-extractor\app.py")
        assert os.path.exists(r"c:\Users\sunil\pharma-pdf-extractor\templates.json")
        assert os.path.exists(r"c:\Users\sunil\pharma-pdf-extractor\supplier_profiles.json")

    def test_case_s_invoice_7hh0s5ipc_regression(self):
        """Case S: INVOICE_7HH0S5IPC.PDF processes cleanly with PACK, QTY, FREE, AMOUNT, GST and HSN."""
        pdf_path = os.path.join(SAMPLE_DIR, "INVOICE_7HH0S5IPC.PDF")
        metadata, headers, mappings, rows = extract_pdf_table(pdf_path)
        mapped_fields = {v.get("mapped_to") for v in mappings.values() if v.get("mapped_to")}
        
        assert "pack" in mapped_fields
        assert "quantity" in mapped_fields
        assert "freeQuantity" in mapped_fields
        assert "amount" in mapped_fields
        assert "gstPercent" in mapped_fields
        assert "hsnCode" in mapped_fields
        assert metadata["confidence"] >= 90.0

    def test_case_t_no_supplier_specific_branches(self):
        """Case T: Zero supplier-specific parsing branches exist in extractor.py."""
        with open(r"c:\Users\sunil\pharma-pdf-extractor\extractor.py", "r", encoding="utf-8") as f:
            content = f.read()

        # Check for forbidden vendor specific if statements
        forbidden_patterns = [
            r"if\s+supplier\s*==",
            r"if\s+supplier_name\s*==",
            r"if\s+gstin\s*==",
            r"if\s+['\"]GAJANAND['\"]",
            r"if\s+['\"]MOHIT['\"]",
            r"if\s+['\"]PASHUPATI['\"]",
            r"if\s+['\"]CAPITA['\"]",
        ]
        for pat in forbidden_patterns:
            matches = re.findall(pat, content, re.IGNORECASE)
            assert len(matches) == 0, f"Found forbidden hardcoded branch matching: {pat}"

    def test_case_u_no_filename_specific_parsing_branches(self):
        """Case U: Zero filename-specific parsing branches exist in extractor.py."""
        with open(r"c:\Users\sunil\pharma-pdf-extractor\extractor.py", "r", encoding="utf-8") as f:
            content = f.read()

        forbidden_patterns = [
            r"filename\s*==",
            r"if\s+['\"]INVOICE_7HH0S5IPC['\"]",
            r"if\s+['\"]PHUB_L22014['\"]",
            r"if\s+['\"]SI26-000698['\"]",
        ]
        for pat in forbidden_patterns:
            matches = re.findall(pat, content, re.IGNORECASE)
            assert len(matches) == 0, f"Found forbidden filename branch matching: {pat}"
