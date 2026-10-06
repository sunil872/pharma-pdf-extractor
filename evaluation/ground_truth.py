"""
MediAstra Pharma PDF Import Engine - Evaluation Ground Truth Store
Manages manually verified ground truth datasets for evaluation without modifying the golden benchmark.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from evaluation.models import GroundTruthDocument, GroundTruthRow


GOLDEN_BENCHMARK_GROUND_TRUTH: Dict[str, Dict[str, Any]] = {
    # 1. INVOICE_7GU0X28XM.PDF (11 rows)
    "c26b45256359ae1674a2c8b1010fe545da32d142b305944de57e2f04a8625b1e": {
        "document_id": "c26b45256359ae1674a2c8b1010fe545da32d142b305944de57e2f04a8625b1e",
        "filename": "INVOICE_7GU0X28XM.PDF",
        "column_mappings": {
            "PRODUCT NAME": "itemName",
            "P A CK": "pack",
            "BOXS": "pack",
            "MFR": "company",
            "O L DBatch": "batchNo",
            "EXP": "expiryDate",
            "M.R.P": "mrp",
            "RATE": "rate",
            "P . T .R": "rate",
            "QTY": "quantity",
            "FREE": "freeQuantity",
            "SCH": "discountPercent",
            "AMOUNT": "amount",
            "GST": "gstPercent",
            "Unnamed_Col_16": "hsnCode",
        },
        "row_count": 11,
        "sample_rows": [],
    },
    # 2. INVOICE_7GX167AKM.PDF (4 rows)
    "faf7092e0a7a914d13594c518f88a08ff1a87b9b5fbec35e997c875630b4d613": {
        "document_id": "faf7092e0a7a914d13594c518f88a08ff1a87b9b5fbec35e997c875630b4d613",
        "filename": "INVOICE_7GX167AKM.PDF",
        "column_mappings": {
            "PRODUCT DESCRIPTION": "itemName",
            "PACK": "pack",
            "HSN": "hsnCode",
            "BATCH": "batchNo",
            "EXP": "expiryDate",
            "QTY": "quantity",
            "RATE": "rate",
            "MRP": "mrp",
            "DISC": "discountPercent",
            "CGST": "cgstPercent",
            "SGST": "sgstPercent",
            "AMOUNT": "amount",
        },
        "row_count": 4,
        "sample_rows": [],
    },
    # 3. INVOICE_7HC0MTOZ2.PDF (15 rows)
    "a8e02a4c12d2946a276d1cd83858a1b8a1ea44902d4459c1d807ff8a398cbd11": {
        "document_id": "a8e02a4c12d2946a276d1cd83858a1b8a1ea44902d4459c1d807ff8a398cbd11",
        "filename": "INVOICE_7HC0MTOZ2.PDF",
        "column_mappings": {
            "Description": "itemName",
            "Pack": "pack",
            "Mfg": "company",
            "Batch": "batchNo",
            "Exp.": "expiryDate",
            "Qty": "quantity",
            "Free": "freeQuantity",
            "Rate": "rate",
            "MRP": "mrp",
            "Disc%": "discountPercent",
            "GST%": "gstPercent",
            "Taxable": "taxableAmount",
            "Net Amt": "netAmount",
            "HSN": "hsnCode",
        },
        "row_count": 15,
        "sample_rows": [],
    },
    # 4. INVOICE_7HH0S5IPC.PDF (9 rows)
    "4ab52431c492cc221df4b39c20dc8721ff483a5d77cdf1f275a061b7c0eb090a": {
        "document_id": "4ab52431c492cc221df4b39c20dc8721ff483a5d77cdf1f275a061b7c0eb090a",
        "filename": "INVOICE_7HH0S5IPC.PDF",
        "column_mappings": {
            "ITEM DESCRIPTION": "itemName",
            "PACK": "pack",
            "QTY": "quantity",
            "FREE": "freeQuantity",
            "BATCH": "batchNo",
            "EXPIRY": "expiryDate",
            "RATE": "rate",
            "MRP": "mrp",
            "AMOUNT": "amount",
            "GST": "gstPercent",
            "HSN": "hsnCode",
            "COMPANY": "company",
        },
        "row_count": 9,
        "sample_rows": [],
    },
    # 5. Invoice.pdf (23 rows)
    "c0d02b670e2caa940714baa6829e247584f11ad2f8fd78b4a1a6037bf0b69a3c": {
        "document_id": "c0d02b670e2caa940714baa6829e247584f11ad2f8fd78b4a1a6037bf0b69a3c",
        "filename": "Invoice.pdf",
        "column_mappings": {
            "Product Description": "itemName",
            "Pack": "pack",
            "Batch": "batchNo",
            "Expiry": "expiryDate",
            "Qty": "quantity",
            "Rate": "rate",
            "MRP": "mrp",
            "Disc%": "discountPercent",
            "Amount": "amount",
            "Net Amount": "netAmount",
        },
        "row_count": 23,
        "sample_rows": [],
    },
    # 6. PHUB_L22014.pdf (22 rows)
    "563fa908c438ea82fcbeca987fe3bed7e54a42da9986ab3a3531d97e946f6de0": {
        "document_id": "563fa908c438ea82fcbeca987fe3bed7e54a42da9986ab3a3531d97e946f6de0",
        "filename": "PHUB_L22014.pdf",
        "column_mappings": {
            "ITEM NAME": "itemName",
            "PACK": "pack",
            "MFR": "company",
            "BATCH": "batchNo",
            "EXP": "expiryDate",
            "QTY": "quantity",
            "FREE": "freeQuantity",
            "RATE": "rate",
            "MRP": "mrp",
            "DISC%": "discountPercent",
            "GST%": "gstPercent",
            "AMOUNT": "amount",
            "HSN": "hsnCode",
        },
        "row_count": 22,
        "sample_rows": [],
    },
    # 7. SI26-000698.pdf (6 rows)
    "6077037eaf235893d0e9ddf0a8163166fb8cea1a350fbd5995d100ba5f27ea1f": {
        "document_id": "6077037eaf235893d0e9ddf0a8163166fb8cea1a350fbd5995d100ba5f27ea1f",
        "filename": "SI26-000698.pdf",
        "column_mappings": {
            "ITEM DESCRIPTION": "itemName",
            "PACK": "pack",
            "MFG": "company",
            "BATCH NO": "batchNo",
            "EXPIRY": "expiryDate",
            "QTY": "quantity",
            "RATE": "rate",
            "MRP": "mrp",
            "DISC%": "discountPercent",
            "GST%": "gstPercent",
            "AMOUNT": "amount",
            "HSN CODE": "hsnCode",
        },
        "row_count": 6,
        "sample_rows": [],
    },
    # 8. Sunil_Medicare_Sample_Invoice.pdf (18 rows)
    "48cfe98fcdce1509f8165c4bd7fd3f96bb7e127b63885267b325c3827fb471b5": {
        "document_id": "48cfe98fcdce1509f8165c4bd7fd3f96bb7e127b63885267b325c3827fb471b5",
        "filename": "Sunil_Medicare_Sample_Invoice.pdf",
        "column_mappings": {
            "ITEM DESCRIPTION": "itemName",
            "PACK": "pack",
            "MFG": "company",
            "BATCH": "batchNo",
            "EXP": "expiryDate",
            "QTY": "quantity",
            "FREE": "freeQuantity",
            "RATE": "rate",
            "MRP": "mrp",
            "DISC%": "discountPercent",
            "TAXABLE": "taxableAmount",
            "GST%": "gstPercent",
            "NET AMT": "netAmount",
            "HSN": "hsnCode",
        },
        "row_count": 18,
        "sample_rows": [],
    },
    # 9. invoice (1).pdf (40 rows)
    "ae83061e055990bd3a533668b554570491e80f967c10490c72b227192c77ab0d": {
        "document_id": "ae83061e055990bd3a533668b554570491e80f967c10490c72b227192c77ab0d",
        "filename": "invoice (1).pdf",
        "column_mappings": {
            "Product Description": "itemName",
            "Pack": "pack",
            "Mfg": "company",
            "Batch": "batchNo",
            "Expiry": "expiryDate",
            "Qty": "quantity",
            "Free": "freeQuantity",
            "Rate": "rate",
            "MRP": "mrp",
            "Disc%": "discountPercent",
            "CGST%": "cgstPercent",
            "SGST%": "sgstPercent",
            "Amount": "amount",
            "Net Amount": "netAmount",
            "HSN": "hsnCode",
        },
        "row_count": 40,
        "sample_rows": [],
    },
}


class GroundTruthStore:
    """Provides ground truth loading and management without altering baseline benchmark."""

    def __init__(self, ground_truth_file: Optional[str] = None):
        self.ground_truth_file = ground_truth_file or os.path.join(
            os.path.dirname(__file__), "ground_truth.json"
        )
        self._custom_store: Dict[str, GroundTruthDocument] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if os.path.exists(self.ground_truth_file):
            try:
                with open(self.ground_truth_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data.get("documents", []):
                        doc = GroundTruthDocument.from_dict(item)
                        self._custom_store[doc.document_id] = doc
                        if doc.filename:
                            self._custom_store[doc.filename] = doc
            except Exception:
                pass

    def get_ground_truth(self, identifier: str) -> Optional[GroundTruthDocument]:
        """
        Retrieves ground truth document by document_id, filename, or SHA-256 hash.
        Checks custom store first, then built-in verified golden metadata.
        """
        if identifier in self._custom_store:
            return self._custom_store[identifier]

        # Check in built-in verified metadata
        for key, entry in GOLDEN_BENCHMARK_GROUND_TRUTH.items():
            if identifier in (key, entry.get("filename"), entry.get("document_id")):
                rows = [
                    GroundTruthRow(row_index=r["row_index"], fields=r.get("fields", {}))
                    for r in entry.get("sample_rows", [])
                ]
                return GroundTruthDocument(
                    document_id=entry["document_id"],
                    filename=entry["filename"],
                    rows=rows,
                    column_mappings=entry.get("column_mappings"),
                )

        return None

    def save_ground_truth(self, gt_doc: GroundTruthDocument) -> None:
        self._custom_store[gt_doc.document_id] = gt_doc
        if gt_doc.filename:
            self._custom_store[gt_doc.filename] = gt_doc
        
        # Persist custom store
        docs = []
        seen_ids = set()
        for doc in self._custom_store.values():
            if doc.document_id not in seen_ids:
                docs.append(doc.to_dict())
                seen_ids.add(doc.document_id)

        os.makedirs(os.path.dirname(self.ground_truth_file), exist_ok=True)
        with open(self.ground_truth_file, "w", encoding="utf-8") as f:
            json.dump({"version": "1.0", "documents": docs}, f, indent=2)
