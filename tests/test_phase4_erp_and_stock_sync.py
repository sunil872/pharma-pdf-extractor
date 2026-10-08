"""
Unit and Integration Tests for MediAstra Phase 4:
- Cloud Stock Inventory Database Sync (storage/repositories.py)
- Marg ERP 9+ Export Adapter (export_engine.py)
- TallyPrime XML Purchase Voucher Generator (export_engine.py)
- Vyapar & Busy Accounting Excel Export (export_engine.py)
- Canonical Stock Payload Cloud Synchronization
"""

import os
import json
import pytest
import tempfile
import pandas as pd
import xml.etree.ElementTree as ET

from export_engine import (
    export_to_marg_csv,
    export_to_tally_xml,
    export_to_busy_vyapar_excel,
    export_to_canonical_json,
    export_to_formatted_excel,
)
from storage import StorageService
from batch_processor import BatchProcessingResult, DocumentProcessingResult, sync_batch_to_stock_inventory


@pytest.fixture
def sample_invoice_df():
    return pd.DataFrame([
        {
            "itemName": "AMARYL 1MG TABLET",
            "pack": "30'S",
            "batchNo": "AM1029",
            "expiryDate": "12/27",
            "hsnCode": "30049099",
            "quantity": 10.0,
            "freeQuantity": 2.0,
            "rate": 88.80,
            "mrp": 115.00,
            "discountPercent": 5.0,
            "gstPercent": 12.0,
            "cgstPercent": 6.0,
            "sgstPercent": 6.0,
            "amount": 888.00,
            "taxableAmount": 843.60,
            "gstAmount": 101.23,
            "netAmount": 944.83,
        },
        {
            "itemName": "TELMA 40MG TABLET",
            "pack": "15'S",
            "batchNo": "TL9921",
            "expiryDate": "08/28",
            "hsnCode": "30049099",
            "quantity": 20.0,
            "freeQuantity": 0.0,
            "rate": 140.00,
            "mrp": 185.00,
            "discountPercent": 0.0,
            "gstPercent": 12.0,
            "cgstPercent": 6.0,
            "sgstPercent": 6.0,
            "amount": 2800.00,
            "taxableAmount": 2800.00,
            "gstAmount": 336.00,
            "netAmount": 3136.00,
        },
    ])


@pytest.fixture
def sample_metadata():
    return {
        "supplier_name": "MOHIT PHARMA DISTRIBUTORS",
        "gstin": "27AABCM1234F1Z5",
        "invoice_number": "INV-2026-9081",
        "invoice_date": "2026-04-15",
    }


def test_export_to_marg_csv(sample_invoice_df, sample_metadata):
    """Test Marg ERP 9+ CSV generation and columns."""
    csv_out = export_to_marg_csv(sample_invoice_df, metadata=sample_metadata)

    assert "ITEM_NAME" in csv_out
    assert "BATCH_NO" in csv_out
    assert "EXPIRY" in csv_out
    assert "QTY" in csv_out
    assert "FREE_QTY" in csv_out
    assert "PURCHASE_RATE" in csv_out
    assert "AMARYL 1MG TABLET" in csv_out
    assert "AM1029" in csv_out
    assert "TELMA 40MG TABLET" in csv_out

    # Verify CSV is parseable
    df_read = pd.read_csv(pd.io.common.StringIO(csv_out))
    assert len(df_read) == 2
    assert df_read.iloc[0]["QTY"] == 10
    assert df_read.iloc[0]["FREE_QTY"] == 2
    assert df_read.iloc[0]["PURCHASE_RATE"] == 88.80


def test_export_to_tally_xml(sample_invoice_df, sample_metadata):
    """Test TallyPrime Purchase Voucher XML structure and ledger allocations."""
    xml_out = export_to_tally_xml(sample_invoice_df, metadata=sample_metadata)

    assert "<ENVELOPE>" in xml_out
    assert "<VOUCHER VCHTYPE=\"Purchase\"" in xml_out
    assert "<STOCKITEMNAME>AMARYL 1MG TABLET</STOCKITEMNAME>" in xml_out
    assert "<BATCHNAME>AM1029</BATCHNAME>" in xml_out
    assert "<ACTUALQTY> 12 Nos</ACTUALQTY>" in xml_out  # 10 billed + 2 free
    assert "<BILLEDQTY> 10 Nos</BILLEDQTY>" in xml_out
    assert "<LEDGERNAME>Input CGST</LEDGERNAME>" in xml_out
    assert "<LEDGERNAME>Input SGST</LEDGERNAME>" in xml_out
    assert "<LEDGERNAME>MOHIT PHARMA DISTRIBUTORS</LEDGERNAME>" in xml_out

    # Verify XML is well-formed
    root = ET.fromstring(xml_out)
    assert root.tag == "ENVELOPE"


def test_export_to_busy_vyapar_excel(sample_invoice_df, sample_metadata):
    """Test Busy & Vyapar Excel format generation."""
    excel_bytes = export_to_busy_vyapar_excel(sample_invoice_df, metadata=sample_metadata)
    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 1000  # Non-trivial valid xlsx bytes


def test_export_to_canonical_json(sample_invoice_df, sample_metadata):
    """Test Canonical Cloud Sync JSON schema."""
    items = sample_invoice_df.to_dict(orient="records")
    returns = [{"product_name": "EXPIRED COUGH SYRUP", "batch_no": "EXP01", "return_qty": 3.0}]

    payload = export_to_canonical_json(items, metadata=sample_metadata, returns=returns)

    assert "supplier" in payload
    assert payload["supplier"]["name"] == "MOHIT PHARMA DISTRIBUTORS"
    assert payload["supplier"]["gstin"] == "27AABCM1234F1Z5"
    assert payload["invoice"]["invoice_no"] == "INV-2026-9081"
    assert len(payload["stock_update_items"]) == 2

    amaryl_stock = payload["stock_update_items"][0]
    assert amaryl_stock["product_name"] == "AMARYL 1MG TABLET"
    assert amaryl_stock["billed_quantity"] == 10.0
    assert amaryl_stock["free_quantity"] == 2.0
    assert amaryl_stock["total_received_stock"] == 12.0

    assert len(payload["returns_adjusted"]) == 1


def test_storage_stock_inventory_ingestion_and_reconciliation(sample_invoice_df, sample_metadata):
    """Test updating retail stock list in SQLite database via StorageService."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = os.path.join(tmpdir, "test_stock.db")
        service = StorageService(test_db_path)

        items = sample_invoice_df.to_dict(orient="records")
        canonical_payload = export_to_canonical_json(items, metadata=sample_metadata)

        # 1. First Ingestion
        res1 = service.ingest_stock_payload(canonical_payload)
        assert res1["status"] == "SUCCESS"
        assert res1["items_updated"] == 2
        assert res1["total_stock_added"] == 32.0  # (10+2) + (20+0)

        # Verify stock inventory record
        stock = service.get_stock_inventory()
        assert len(stock) == 2

        amaryl = [s for s in stock if "AMARYL" in s.product_name][0]
        assert amaryl.current_stock_qty == 12.0
        assert amaryl.batch_no == "AM1029"
        assert amaryl.ptr_rate == 88.80
        assert amaryl.mrp == 115.00

        # 2. Re-ingesting a 2nd shipment of same batch increments stock
        res2 = service.ingest_stock_payload(canonical_payload)
        assert res2["status"] == "SUCCESS"
        amaryl_after = [s for s in service.get_stock_inventory() if "AMARYL" in s.product_name][0]
        assert amaryl_after.current_stock_qty == 24.0  # 12 + 12

        # 3. Verify stock movements logged
        movements = service.get_stock_movements(amaryl.id)
        assert len(movements) == 2
        assert movements[0].movement_type == "PURCHASE_RECEIPT"


def test_storage_stock_returns_deduction():
    """Test credit note returns adjust stock inventory down."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = os.path.join(tmpdir, "test_returns.db")
        service = StorageService(test_db_path)

        # Initial stock of 10 units
        initial_payload = {
            "supplier": {"name": "DIVYA PHARMA", "gstin": "27DIVYA1234"},
            "invoice": {"invoice_no": "INV-001", "invoice_date": "2026-04-01"},
            "stock_update_items": [{
                "product_name": "PAN 40MG TABLET",
                "pack": "10'S",
                "batch_no": "PN501",
                "expiry_date": "05/28",
                "hsn_code": "30049099",
                "billed_quantity": 10.0,
                "free_quantity": 0.0,
                "total_received_stock": 10.0,
                "mrp": 150.0,
                "ptr_rate": 110.0,
                "discount_percent": 0.0,
                "gst_percent": 12.0,
                "line_net_amount": 1232.0,
            }],
            "returns_adjusted": [],
        }
        service.ingest_stock_payload(initial_payload)

        # Return 3 units in subsequent invoice
        return_payload = {
            "supplier": {"name": "DIVYA PHARMA", "gstin": "27DIVYA1234"},
            "invoice": {"invoice_no": "INV-002", "invoice_date": "2026-04-05"},
            "stock_update_items": [],
            "returns_adjusted": [{
                "product_name": "PAN 40MG TABLET",
                "batch_no": "PN501",
                "return_qty": 3.0,
            }],
        }
        res = service.ingest_stock_payload(return_payload)
        assert res["returns_adjusted"] == 1

        pan_item = service.get_stock_inventory(search="PAN 40MG")[0]
        assert pan_item.current_stock_qty == 7.0  # 10 - 3


def test_batch_sync_to_stock_inventory(sample_invoice_df):
    """Test syncing batch processor results directly into inventory database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = os.path.join(tmpdir, "test_batch_sync.db")
        service = StorageService(test_db_path)

        batch_result = BatchProcessingResult(
            batch_id="batch_test_123",
            input_path="Sample Invoices",
            total_documents=1,
            auto_accept_count=1,
            document_results=[
                DocumentProcessingResult(
                    filename="sample_inv.pdf",
                    status="SUCCESS",
                    decision="AUTO_ACCEPT",
                    supplier_name="SUNIL MEDICARE",
                    gstin="27SUNIL9999",
                    extracted_rows=sample_invoice_df.to_dict(orient="records"),
                )
            ]
        )

        sync_summary = sync_batch_to_stock_inventory(batch_result, storage_service=service)
        assert sync_summary["status"] == "SUCCESS"
        assert sync_summary["invoices_synced"] == 1
        assert sync_summary["items_updated"] == 2
        assert sync_summary["total_stock_added"] == 32.0

        inventory = service.get_stock_inventory()
        assert len(inventory) == 2
