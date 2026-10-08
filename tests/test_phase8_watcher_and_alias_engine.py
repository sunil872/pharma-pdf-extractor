"""
Tests for Phase 8: Autonomous Hot-Folder Watcher, Pharmacy Product Alias Mapping & HSN GST Tax Audit Sentinel
"""
import os
import tempfile
import time
import pytest
import pandas as pd

from storage import StorageService
from storage.models import PharmacyMasterItem, ProductAlias
from product_alias_engine import (
    normalize_drug_name_tokens,
    resolve_product_alias,
    resolve_invoice_row_aliases,
    learn_product_alias,
)
from hsn_tax_sentinel import (
    validate_hsn_code,
    validate_gst_tax_slab,
    audit_line_item_tax,
    audit_invoice_tax_compliance,
)
from watcher import (
    is_file_ready_for_processing,
    InvoiceFolderWatcher,
)
from batch_processor import DocumentProcessingResult


# ------------------------------------------------------------------------------
# 1. Product Alias & Drug Name Normalization Tests
# ------------------------------------------------------------------------------

def test_drug_name_token_normalization():
    assert normalize_drug_name_tokens("TELMA 40MG TAB 15S") == "TELMA 40MG"
    assert normalize_drug_name_tokens("AUGMENTIN 625 DUO TABLETS 10S") == "AUGMENTIN 625"
    assert normalize_drug_name_tokens("PAN-D CAPSULE (1X15)") == "PAN D"
    assert normalize_drug_name_tokens("AZITHRAL 500 MG TABLET 5'S") == "AZITHRAL 500MG"
    assert normalize_drug_name_tokens("DOLO 650 TABLETS") == "DOLO 650"
    assert normalize_drug_name_tokens("BETADINE 10% OINTMENT 20GM") == "BETADINE 10%"


def test_master_catalogue_seeding_and_lookup():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = os.path.join(tmpdir, "test_alias.db")
        service = StorageService(test_db)

        # Seed master items
        count = service.seed_default_master_pharmacy_catalogue()
        assert count >= 15

        # Lookup by code
        telma = service.get_master_item_by_code("MED-1003")
        assert telma is not None
        assert telma.item_name == "TELMA 40MG TABLET"
        assert telma.default_hsn == "30049099"
        assert telma.default_gst_percent == 12.0

        # Search master items
        results = service.list_master_items(search="PAN")
        assert len(results) >= 2


def test_product_alias_learning_and_exact_resolution():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = os.path.join(tmpdir, "test_alias_learn.db")
        service = StorageService(test_db)
        service.seed_default_master_pharmacy_catalogue()

        # Create realistic supplier
        sup = service.get_or_create_supplier("DIVYA PHARMA DISTRIBUTORS", gstin="27DIVYA1234F1Z5")

        # Learn supplier-specific alias
        learn_product_alias(
            raw_alias="TL40 TAB 15S",
            master_item_code="MED-1003",
            master_item_name="TELMA 40MG TABLET",
            supplier_id=sup.id,
            storage_service=service,
        )

        # 1. Matching with exact supplier ID
        res1 = resolve_product_alias("TL40 TAB 15S", supplier_id=sup.id, storage_service=service)
        assert res1["is_resolved"] is True
        assert res1["master_item_code"] == "MED-1003"
        assert res1["match_type"] == "SUPPLIER_ALIAS"

        # 2. Matching with different supplier ID falls back to GLOBAL_ALIAS
        res2 = resolve_product_alias("TL40 TAB 15S", supplier_id=999, storage_service=service)
        assert res2["is_resolved"] is True
        assert res2["master_item_code"] == "MED-1003"
        assert res2["match_type"] == "GLOBAL_ALIAS"


def test_product_alias_fuzzy_matching():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = os.path.join(tmpdir, "test_alias_fuzzy.db")
        service = StorageService(test_db)
        service.seed_default_master_pharmacy_catalogue()

        # Unseen variations should fuzzy match against seeded master
        res_telma = resolve_product_alias("TELMA 40 TABLETS (1X15)", storage_service=service)
        assert res_telma["is_resolved"] is True
        assert res_telma["master_item_code"] == "MED-1003"
        assert res_telma["match_score"] >= 80.0

        res_amaryl = resolve_product_alias("AMARYL 1MG STRIP", storage_service=service)
        assert res_amaryl["is_resolved"] is True
        assert res_amaryl["master_item_code"] == "MED-1001"


def test_resolve_invoice_row_aliases():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = os.path.join(tmpdir, "test_alias_rows.db")
        service = StorageService(test_db)
        service.seed_default_master_pharmacy_catalogue()

        sample_rows = [
            {"itemName": "TELMA 40MG TAB", "batchNo": "TL01", "quantity": 10},
            {"itemName": "DOLO 650 TABLET", "batchNo": "DL99", "quantity": 20},
        ]

        enriched = resolve_invoice_row_aliases(sample_rows, storage_service=service)
        assert len(enriched) == 2
        assert enriched[0]["master_item_code"] == "MED-1003"
        assert enriched[1]["master_item_code"] == "MED-1009"


# ------------------------------------------------------------------------------
# 2. HSN & GST Statutory Tax Compliance Sentinel Tests
# ------------------------------------------------------------------------------

def test_hsn_code_validation():
    # Standard 8-digit pharma
    res1 = validate_hsn_code("30049099")
    assert res1["is_valid"] is True
    assert res1["hsn_status"] == "STANDARD_PHARMA_HSN"

    # Standard 4-digit pharma
    res2 = validate_hsn_code("3004")
    assert res2["is_valid"] is True

    # Valid non-pharma 8-digit
    res3 = validate_hsn_code("84131900")
    assert res3["is_valid"] is True
    assert res3["hsn_status"] == "NON_STANDARD_CHAPTER"

    # Invalid format (3 digits)
    res4 = validate_hsn_code("300")
    assert res4["is_valid"] is False
    assert res4["hsn_status"] == "INVALID_FORMAT"

    # Missing HSN
    res5 = validate_hsn_code("")
    assert res5["is_valid"] is False
    assert res5["hsn_status"] == "MISSING_HSN"


def test_gst_statutory_slab_validation():
    # Valid Indian GST slabs
    for slab in (0.0, 5.0, 12.0, 18.0, 28.0):
        res = validate_gst_tax_slab(slab)
        assert res["is_statutory"] is True
        assert res["status"] == "STATUTORY_SLAB"

    # Non-statutory GST rates
    res_bad = validate_gst_tax_slab(7.5)
    assert res_bad["is_statutory"] is False
    assert res_bad["status"] == "NON_STATUTORY_RATE"


def test_line_item_and_invoice_tax_compliance_audit():
    sample_invoice_rows = [
        {
            "itemName": "AMARYL 1MG TABLET",
            "hsnCode": "30049099",
            "taxableAmount": 1000.0,
            "gstPercent": 12.0,
            "gstAmount": 120.0,
            "netAmount": 1120.0,
            "rate": 100.0,
            "mrp": 125.0,
        },
        {
            "itemName": "BETADINE OINTMENT",
            "hsnCode": "30049099",
            "taxableAmount": 500.0,
            "gstPercent": 12.0,
            "gstAmount": 60.0,
            "netAmount": 560.0,
            "rate": 50.0,
            "mrp": 65.0,
        },
    ]

    meta = {"supplier_gstin": "27AAACB1234F1Z5", "buyer_gstin": "27XYZAB5678F1Z9"}  # Intra-state (both 27 Maharashtra)
    audit_res = audit_invoice_tax_compliance(sample_invoice_rows, invoice_meta=meta)

    assert audit_res["is_overall_compliant"] is True
    assert audit_res["is_interstate"] is False
    assert audit_res["total_taxable_amount"] == 1500.0
    assert audit_res["total_cgst_amount"] == 90.0  # (120+60)/2 = 90
    assert audit_res["total_sgst_amount"] == 90.0
    assert audit_res["total_igst_amount"] == 0.0
    assert audit_res["total_gst_amount"] == 180.0
    assert audit_res["total_itc_claimable"] == 180.0
    assert "12.0%" in audit_res["tax_slab_breakdown"]


def test_tax_compliance_flags_calculation_mismatch():
    corrupted_row = [{
        "itemName": "TELMA 40MG TABLET",
        "hsnCode": "30049099",
        "taxableAmount": 1000.0,
        "gstPercent": 12.0,
        "gstAmount": 180.0,  # Stated 180 instead of 120
        "netAmount": 1180.0,
        "rate": 100.0,
        "mrp": 125.0,
    }]
    audit_res = audit_invoice_tax_compliance(corrupted_row)
    assert audit_res["is_overall_compliant"] is False
    assert audit_res["compliance_alerts_count"] >= 1
    assert any("GST Amount Mismatch" in a for a in audit_res["compliance_alerts"])


# ------------------------------------------------------------------------------
# 3. Hot-Folder Ingestion Watcher Tests
# ------------------------------------------------------------------------------

def test_watcher_file_readiness_probe():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Non-existent file
        assert is_file_ready_for_processing(os.path.join(tmpdir, "missing.pdf"), wait_probe_sec=0.05) is False

        # Zero-byte empty file
        empty_file = os.path.join(tmpdir, "empty.pdf")
        with open(empty_file, "wb") as f:
            pass
        assert is_file_ready_for_processing(empty_file, wait_probe_sec=0.05) is False

        # Ready non-empty file
        valid_file = os.path.join(tmpdir, "ready.pdf")
        with open(valid_file, "wb") as f:
            f.write(b"%PDF-1.4 sample content bytes")
        assert is_file_ready_for_processing(valid_file, wait_probe_sec=0.05) is True


def test_watcher_scan_and_route_mock_document():
    with tempfile.TemporaryDirectory() as tmpdir:
        inbox = os.path.join(tmpdir, "inbox")
        processed = os.path.join(tmpdir, "processed")
        review = os.path.join(tmpdir, "review")
        errors = os.path.join(tmpdir, "errors")
        db_path = os.path.join(tmpdir, "watcher_test.db")

        service = StorageService(db_path)
        service.seed_default_master_pharmacy_catalogue()

        watcher = InvoiceFolderWatcher(
            inbox_dir=inbox,
            processed_dir=processed,
            review_dir=review,
            error_dir=errors,
            storage_service=service,
            poll_interval_sec=0.2,
            auto_sync_stock=True,
        )

        metrics = watcher.get_watcher_metrics()
        assert metrics["is_running"] is False
        assert metrics["total_scanned"] == 0

        # Start and Stop daemon cycle test
        watcher.start()
        assert watcher.is_running() is True
        time.sleep(0.3)
        watcher.stop()
        assert watcher.is_running() is False
