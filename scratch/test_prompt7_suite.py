import os
import sys
import json
import pytest
import tempfile
import shutil

# Add project root to sys.path
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")

from extractor import (
    load_supplier_profiles,
    save_supplier_profiles,
    calculate_header_sequence_similarity,
    match_supplier_layout_profile,
    update_supplier_profile_memory,
    compute_layout_signature,
    compute_global_validation_and_confidence,
    detect_layout_drift,
)


@pytest.fixture
def temp_profile_env(tmp_path):
    prof_path = str(tmp_path / "test_supplier_profiles.json")
    return prof_path


class TestPrompt7ProfileMemorySuite:

    def test_case_a_new_supplier_creates_profile(self, temp_profile_env):
        """Case A: First invoice from a new supplier creates supplier profile and layout_v1."""
        headers = ["Item Name", "Pack", "Batch", "Expiry", "Qty", "Rate", "Amount"]
        mappings = {h: {"mapped_to": f, "status": "known_header"} for h, f in [
            ("Item Name", "itemName"), ("Pack", "pack"), ("Batch", "batchNo"),
            ("Expiry", "expiryDate"), ("Qty", "quantity"), ("Rate", "rate"), ("Amount", "amount")
        ]}
        rows = [["Dolo 650", "15T", "B101", "12/26", "10", "20.00", "200.00"]]
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 95.0, "accounting_summary": {"critical_mismatches": 0}}

        res = update_supplier_profile_memory(
            supplier_key="SUPPLIER_A",
            supplier_name="Supplier Alpha",
            gstin="36AAAAA0000A1Z5",
            headers=headers,
            logical_columns=[],
            resolved_mappings=mappings,
            rows=rows,
            validation_result=val_res,
            profiles_storage_path=temp_profile_env,
        )

        assert res["updated"] is True
        assert res["action"] == "NEW_SUPPLIER_PROFILE_CREATED"

        # Verify persisted structure
        profiles_data = load_supplier_profiles(storage_path=temp_profile_env)
        assert "SUPPLIER_A" in profiles_data["profiles"]
        prof = profiles_data["profiles"]["SUPPLIER_A"]
        assert prof["supplier_name"] == "Supplier Alpha"
        assert len(prof["layout_profiles"]) == 1
        assert prof["successful_document_count"] == 1

    def test_case_b_same_supplier_same_layout_matches_profile(self, temp_profile_env):
        """Case B: Subsequent invoice with same layout matches profile with EXACT_MATCH."""
        headers = ["Item Name", "Pack", "Batch", "Expiry", "Qty", "Rate", "Amount"]
        mappings = {h: {"mapped_to": f, "status": "known_header"} for h, f in [
            ("Item Name", "itemName"), ("Pack", "pack"), ("Batch", "batchNo"),
            ("Expiry", "expiryDate"), ("Qty", "quantity"), ("Rate", "rate"), ("Amount", "amount")
        ]}
        rows = [["Dolo 650", "15T", "B101", "12/26", "10", "20.00", "200.00"]]
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 95.0, "accounting_summary": {"critical_mismatches": 0}}

        # First ingestion
        update_supplier_profile_memory(
            supplier_key="SUPPLIER_A", supplier_name="Supplier Alpha", gstin="36AAAAA0000A1Z5",
            headers=headers, logical_columns=[], resolved_mappings=mappings, rows=rows,
            validation_result=val_res, profiles_storage_path=temp_profile_env
        )

        # Match second invoice
        sig = compute_layout_signature(headers)
        profiles_data = load_supplier_profiles(storage_path=temp_profile_env)
        match = match_supplier_layout_profile("SUPPLIER_A", sig, profiles_data=profiles_data, headers=headers)

        assert match["drift_status"] == "EXACT_MATCH"
        assert match["similarity_score"] >= 0.95
        assert match["matched_layout"] is not None

        # Second update increments counter
        res2 = update_supplier_profile_memory(
            supplier_key="SUPPLIER_A", supplier_name="Supplier Alpha", gstin="36AAAAA0000A1Z5",
            headers=headers, logical_columns=[], resolved_mappings=mappings, rows=rows,
            validation_result=val_res, profiles_storage_path=temp_profile_env
        )
        assert res2["updated"] is True
        assert res2["action"] == "LAYOUT_PROFILE_UPDATED"

        prof2 = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["SUPPLIER_A"]
        assert prof2["successful_document_count"] == 2

    def test_case_c_same_supplier_changed_layout_creates_new_layout_version(self, temp_profile_env):
        """Case C: Supplier alters layout (e.g. added HSN, Free, GST columns) -> creates Layout V2."""
        # Initial V1 layout
        headers_v1 = ["Item Name", "Qty", "Rate", "Amount"]
        mappings_v1 = {h: {"mapped_to": f, "status": "known_header"} for h, f in [
            ("Item Name", "itemName"), ("Qty", "quantity"), ("Rate", "rate"), ("Amount", "amount")
        ]}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 95.0, "accounting_summary": {"critical_mismatches": 0}}
        update_supplier_profile_memory(
            supplier_key="SUPPLIER_A", supplier_name="Supplier Alpha", gstin="36AAAAA0000A1Z5",
            headers=headers_v1, logical_columns=[], resolved_mappings=mappings_v1, rows=[["A", "1", "10", "10"]],
            validation_result=val_res, profiles_storage_path=temp_profile_env
        )

        # Fundamentally new V2 layout with 10 columns
        headers_v2 = ["S.No", "HSN", "Product Description", "Pack", "Batch", "Exp", "Qty", "Free", "Rate", "MRP", "GST", "Amount"]
        mappings_v2 = {h: {"mapped_to": f, "status": "known_header"} for h, f in [
            ("HSN", "hsnCode"), ("Product Description", "itemName"), ("Pack", "pack"), ("Batch", "batchNo"),
            ("Exp", "expiryDate"), ("Qty", "quantity"), ("Free", "freeQuantity"), ("Rate", "rate"), ("MRP", "mrp"),
            ("GST", "gstPercent"), ("Amount", "amount")
        ]}
        res_v2 = update_supplier_profile_memory(
            supplier_key="SUPPLIER_A", supplier_name="Supplier Alpha", gstin="36AAAAA0000A1Z5",
            headers=headers_v2, logical_columns=[], resolved_mappings=mappings_v2, rows=[["1", "3004", "A", "10T", "B1", "12/26", "5", "0", "10", "15", "12", "50"]],
            validation_result=val_res, profiles_storage_path=temp_profile_env
        )

        assert res_v2["updated"] is True
        assert res_v2["action"] == "NEW_LAYOUT_VERSION_CREATED"

        prof = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["SUPPLIER_A"]
        assert len(prof["layout_profiles"]) == 2  # Both V1 and V2 preserved!

    def test_case_d_different_suppliers_similar_layout_remain_separate(self, temp_profile_env):
        """Case D: Two suppliers sharing standard Marg template stay separate in identity."""
        headers = ["Product Name", "Pack", "Batch", "Expiry", "Qty", "Rate", "Amount"]
        mappings = {h: {"mapped_to": f, "status": "known_header"} for h, f in [
            ("Product Name", "itemName"), ("Pack", "pack"), ("Batch", "batchNo"),
            ("Expiry", "expiryDate"), ("Qty", "quantity"), ("Rate", "rate"), ("Amount", "amount")
        ]}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 95.0, "accounting_summary": {"critical_mismatches": 0}}

        update_supplier_profile_memory(
            supplier_key="SUPPLIER_A", supplier_name="Supplier Alpha", gstin="36AAAAA0000A1Z5",
            headers=headers, logical_columns=[], resolved_mappings=mappings, rows=[["A", "10T", "B1", "12/26", "1", "10", "10"]],
            validation_result=val_res, profiles_storage_path=temp_profile_env
        )
        update_supplier_profile_memory(
            supplier_key="SUPPLIER_B", supplier_name="Supplier Beta", gstin="36BBBBB0000B1Z6",
            headers=headers, logical_columns=[], resolved_mappings=mappings, rows=[["B", "10T", "B2", "12/26", "2", "20", "40"]],
            validation_result=val_res, profiles_storage_path=temp_profile_env
        )

        profiles_data = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]
        assert "SUPPLIER_A" in profiles_data
        assert "SUPPLIER_B" in profiles_data
        assert profiles_data["SUPPLIER_A"]["supplier_name"] == "Supplier Alpha"
        assert profiles_data["SUPPLIER_B"]["supplier_name"] == "Supplier Beta"

    def test_case_e_historical_profile_does_not_override_current_evidence(self, temp_profile_env):
        """Case E: Historical profile has Rate <-> MRP in certain order, but current rows show inverted values."""
        headers = ["Product", "ColA", "ColB", "Qty", "Amount"]
        # In historical profile ColA was rate, ColB was mrp
        mappings_hist = {
            "Product": {"mapped_to": "itemName", "status": "known_header"},
            "ColA": {"mapped_to": "rate", "status": "known_header"},
            "ColB": {"mapped_to": "mrp", "status": "known_header"},
            "Qty": {"mapped_to": "quantity", "status": "known_header"},
            "Amount": {"mapped_to": "amount", "status": "known_header"},
        }
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 95.0, "accounting_summary": {"critical_mismatches": 0}}
        update_supplier_profile_memory(
            supplier_key="SUPPLIER_E", supplier_name="Supplier E", gstin="36EEEEE0000E1Z5",
            headers=headers, logical_columns=[], resolved_mappings=mappings_hist, rows=[["A", "10.00", "15.00", "1", "10.00"]],
            validation_result=val_res, profiles_storage_path=temp_profile_env
        )

        # New invoice from same supplier has ColA = 150.00 (MRP), ColB = 100.00 (Rate), Amount = 100.00 (Qty=1)
        current_rows = [
            ["Dolo", "150.00", "100.00", "1", "100.00"],
            ["Azithral", "250.00", "180.00", "2", "360.00"],
        ]
        # Current evidence validates ColB is Rate (Qty*ColB == Amount) and ColA is MRP
        val_curr = compute_global_validation_and_confidence(
            headers=headers, logical_columns=[], column_mappings=mappings_hist, rows=current_rows,
            metadata={"supplier_name": "Supplier E", "supplier_gstin": "36EEEEE0000E1Z5"}
        )
        # Current evidence must win: ColB mapped to rate, ColA mapped to mrp
        res_mappings = val_curr["resolved_mappings"]
        assert res_mappings["ColB"]["mapped_to"] == "rate"
        assert res_mappings["ColA"]["mapped_to"] == "mrp"

    def test_case_f_low_confidence_invoice_does_not_update_profile(self, temp_profile_env):
        """Case F: Bad / unvalidated extraction is rejected from updating profile memory."""
        headers = ["Unknown1", "Unknown2", "Unknown3"]
        mappings = {"Unknown1": {"mapped_to": None, "status": "unresolved"}}
        rows = [["???", "###", "!!!"]]
        val_res = {"classification": "UNRESOLVED", "document_confidence": 35.0, "accounting_summary": {"critical_mismatches": 2}}

        res = update_supplier_profile_memory(
            supplier_key="SUPPLIER_F", supplier_name="Supplier F", gstin="36FFFFF0000F1Z5",
            headers=headers, logical_columns=[], resolved_mappings=mappings, rows=rows,
            validation_result=val_res, is_user_reviewed=False, profiles_storage_path=temp_profile_env
        )
        assert res["updated"] is False
        assert "Validation gate not passed" in res["reason"]

        profiles_data = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]
        assert "SUPPLIER_F" not in profiles_data

    def test_case_g_reviewed_invoice_updates_profile(self, temp_profile_env):
        """Case G: User manually reviews and confirms mapping -> safely updates profile memory."""
        headers = ["X1", "X2", "X3", "X4"]
        mappings = {
            "X1": {"mapped_to": "itemName", "status": "user_confirmed"},
            "X2": {"mapped_to": "quantity", "status": "user_confirmed"},
            "X3": {"mapped_to": "rate", "status": "user_confirmed"},
            "X4": {"mapped_to": "amount", "status": "user_confirmed"},
        }
        val_res = {"classification": "REVIEW_REQUIRED", "document_confidence": 65.0, "accounting_summary": {"critical_mismatches": 0}}

        res = update_supplier_profile_memory(
            supplier_key="SUPPLIER_G", supplier_name="Supplier G", gstin="36GGGGG0000G1Z5",
            headers=headers, logical_columns=[], resolved_mappings=mappings, rows=[["A", "1", "10", "10"]],
            validation_result=val_res, is_user_reviewed=True, profiles_storage_path=temp_profile_env
        )
        assert res["updated"] is True
        prof = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["SUPPLIER_G"]
        assert prof["reviewed_document_count"] == 1

    def test_case_h_multiple_layouts_for_same_supplier(self, temp_profile_env):
        """Case H: Multiple layouts stored under single supplier profile."""
        h1 = ["Item", "Qty", "Rate", "Amt"]
        m1 = {h: {"mapped_to": f, "status": "known_header"} for h, f in [("Item", "itemName"), ("Qty", "quantity"), ("Rate", "rate"), ("Amt", "amount")]}
        h2 = ["SNo", "Product", "Batch", "Exp", "Qty", "PTR", "Total"]
        m2 = {h: {"mapped_to": f, "status": "known_header"} for h, f in [("Product", "itemName"), ("Batch", "batchNo"), ("Exp", "expiryDate"), ("Qty", "quantity"), ("PTR", "rate"), ("Total", "amount")]}

        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}}

        update_supplier_profile_memory("SUPP_H", "Supp H", "36HHHHH0000H1Z5", h1, [], m1, [["A", "1", "10", "10"]], val_res, profiles_storage_path=temp_profile_env)
        update_supplier_profile_memory("SUPP_H", "Supp H", "36HHHHH0000H1Z5", h2, [], m2, [["1", "A", "B", "12/26", "1", "10", "10"]], val_res, profiles_storage_path=temp_profile_env)

        prof = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["SUPP_H"]
        assert len(prof["layout_profiles"]) == 2

    def test_case_i_layout_profile_ranking(self, temp_profile_env):
        """Case I: Layout profile ranking correctly selects the closest matching layout."""
        h1 = ["Item", "Qty", "Rate", "Amt"]
        m1 = {h: {"mapped_to": f, "status": "known_header"} for h, f in [("Item", "itemName"), ("Qty", "quantity"), ("Rate", "rate"), ("Amt", "amount")]}
        h2 = ["SNo", "Product", "Batch", "Exp", "Qty", "PTR", "Total"]
        m2 = {h: {"mapped_to": f, "status": "known_header"} for h, f in [("Product", "itemName"), ("Batch", "batchNo"), ("Exp", "expiryDate"), ("Qty", "quantity"), ("PTR", "rate"), ("Total", "amount")]}

        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}}
        update_supplier_profile_memory("SUPP_I", "Supp I", "36IIIII0000I1Z5", h1, [], m1, [["A", "1", "10", "10"]], val_res, profiles_storage_path=temp_profile_env)
        update_supplier_profile_memory("SUPP_I", "Supp I", "36IIIII0000I1Z5", h2, [], m2, [["1", "A", "B", "12/26", "1", "10", "10"]], val_res, profiles_storage_path=temp_profile_env)

        # Incoming invoice has structure almost identical to h2
        incoming_h = ["SNo", "Product", "Batch", "Exp", "Qty", "PTR", "Disc", "Total"]
        sig = compute_layout_signature(incoming_h)
        profiles_data = load_supplier_profiles(storage_path=temp_profile_env)
        match = match_supplier_layout_profile("SUPP_I", sig, profiles_data=profiles_data, headers=incoming_h)

        assert match["matched_layout"]["header_sequence"] == h2

    def test_case_j_layout_drift_classification(self, temp_profile_env):
        """Case J: Distinguishes MINOR_DRIFT vs MAJOR_DRIFT."""
        base_h = ["Product", "Pack", "Batch", "Exp", "Qty", "Rate", "Amount"]
        m = {h: {"mapped_to": f, "status": "known_header"} for h, f in [("Product", "itemName"), ("Pack", "pack"), ("Batch", "batchNo"), ("Exp", "expiryDate"), ("Qty", "quantity"), ("Rate", "rate"), ("Amount", "amount")]}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}}
        update_supplier_profile_memory("SUPP_J", "Supp J", "36JJJJJ0000J1Z5", base_h, [], m, [["A", "10T", "B1", "12/26", "1", "10", "10"]], val_res, profiles_storage_path=temp_profile_env)

        profiles_data = load_supplier_profiles(storage_path=temp_profile_env)

        # Minor drift: 1 column added
        minor_h = ["Product", "Pack", "Batch", "Exp", "Qty", "Disc%", "Rate", "Amount"]
        match_minor = match_supplier_layout_profile("SUPP_J", compute_layout_signature(minor_h), profiles_data=profiles_data, headers=minor_h)
        assert match_minor["drift_status"] in ("MINOR_DRIFT", "EXACT_MATCH")

        # Major drift: completely different columns
        major_h = ["Code", "Description", "UOM", "Net Value"]
        match_major = match_supplier_layout_profile("SUPP_J", compute_layout_signature(major_h), profiles_data=profiles_data, headers=major_h)
        assert match_major["drift_status"] in ("MAJOR_DRIFT", "NEW_LAYOUT")

    def test_case_k_new_supplier_with_no_template(self, temp_profile_env):
        """Case K: New supplier processes through generic layout inference without failing."""
        drift = detect_layout_drift(compute_layout_signature(["Item", "Qty", "Rate"]), "BRAND_NEW_SUPPLIER", saved_templates={})
        assert drift["drift_status"] == "NEW_SUPPLIER"

    def test_case_l_supplier_identity_mismatch(self, temp_profile_env):
        """Case L: Querying with unmatched supplier key does not cross-pollinate other profiles."""
        base_h = ["Product", "Qty", "Rate", "Amount"]
        m = {h: {"mapped_to": f, "status": "known_header"} for h, f in [("Product", "itemName"), ("Qty", "quantity"), ("Rate", "rate"), ("Amount", "amount")]}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 90.0, "accounting_summary": {"critical_mismatches": 0}}
        update_supplier_profile_memory("SUPP_L1", "Supp L1", "36LLLLL0000L1Z5", base_h, [], m, [["A", "1", "10", "10"]], val_res, profiles_storage_path=temp_profile_env)

        profiles_data = load_supplier_profiles(storage_path=temp_profile_env)
        match = match_supplier_layout_profile("SUPP_L2_DIFFERENT", compute_layout_signature(base_h), profiles_data=profiles_data, headers=base_h)
        assert match["drift_status"] == "NEW_SUPPLIER"
        assert match["supplier_profile"] is None

    def test_case_m_profile_history_accumulation(self, temp_profile_env):
        """Case M: Document counts and field observations accumulate accurately over time."""
        h = ["Product", "Qty", "Rate", "Amount"]
        m = {h_name: {"mapped_to": f, "status": "known_header"} for h_name, f in [("Product", "itemName"), ("Qty", "quantity"), ("Rate", "rate"), ("Amount", "amount")]}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 92.0, "accounting_summary": {"critical_mismatches": 0}}

        for _ in range(5):
            update_supplier_profile_memory("SUPP_M", "Supp M", "36MMMMM0000M1Z5", h, [], m, [["A", "1", "10", "10"]], val_res, profiles_storage_path=temp_profile_env)

        prof = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["SUPP_M"]
        assert prof["successful_document_count"] == 5
        layout_p = list(prof["layout_profiles"].values())[0]
        assert layout_p["successful_document_count"] == 5
        assert layout_p["field_reliability"]["quantity"]["observed_count"] == 5

    def test_case_n_non_destructive_profile_updates(self, temp_profile_env):
        """Case N: Creating Layout V2 leaves Layout V1 metadata and history intact."""
        h1 = ["Product", "Qty", "Rate", "Amount"]
        m1 = {h_name: {"mapped_to": f, "status": "known_header"} for h_name, f in [("Product", "itemName"), ("Qty", "quantity"), ("Rate", "rate"), ("Amount", "amount")]}
        val_res = {"classification": "AUTO_ACCEPT", "document_confidence": 92.0, "accounting_summary": {"critical_mismatches": 0}}

        # Add 3 invoices under V1
        for _ in range(3):
            update_supplier_profile_memory("SUPP_N", "Supp N", "36NNNNN0000N1Z5", h1, [], m1, [["A", "1", "10", "10"]], val_res, profiles_storage_path=temp_profile_env)

        # Introduce V2
        h2 = ["SNo", "Item", "Pack", "Batch", "Exp", "Qty", "Rate", "MRP", "GST", "Amount"]
        m2 = {h_name: {"mapped_to": f, "status": "known_header"} for h_name, f in [("Item", "itemName"), ("Pack", "pack"), ("Batch", "batchNo"), ("Exp", "expiryDate"), ("Qty", "quantity"), ("Rate", "rate"), ("MRP", "mrp"), ("GST", "gstPercent"), ("Amount", "amount")]}
        update_supplier_profile_memory("SUPP_N", "Supp N", "36NNNNN0000N1Z5", h2, [], m2, [["1", "A", "10T", "B1", "12/26", "1", "10", "15", "5", "10"]], val_res, profiles_storage_path=temp_profile_env)

        prof = load_supplier_profiles(storage_path=temp_profile_env)["profiles"]["SUPP_N"]
        assert len(prof["layout_profiles"]) == 2
        # Check that V1 still has successful_document_count == 3
        v1_layout = [l for l in prof["layout_profiles"].values() if l["logical_column_count"] == 4][0]
        assert v1_layout["successful_document_count"] == 3
