"""
MediAstra Pharma PDF Import Engine - Canonical Field-Level Ground Truth Framework
Defines data structures, enums, cell states, and store for document -> row -> field ground truth.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class FieldPresenceState(str, Enum):
    """Presence state of a canonical field in an invoice."""
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    NOT_PRESENT = "NOT_PRESENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    AMBIGUOUS = "AMBIGUOUS"


class RowClassification(str, Enum):
    """Classification of an extracted row compared to ground truth."""
    FULLY_CORRECT = "FULLY_CORRECT"
    PARTIALLY_CORRECT = "PARTIALLY_CORRECT"
    CRITICAL_FIELD_ERROR = "CRITICAL_FIELD_ERROR"
    MISSING_ROW = "MISSING_ROW"
    EXTRA_ROW = "EXTRA_ROW"
    AMBIGUOUS = "AMBIGUOUS"


class AccountingStatus(str, Enum):
    """Accounting mathematical consistency status."""
    ACCOUNTING_CONSISTENT = "ACCOUNTING_CONSISTENT"
    ACCOUNTING_INCONSISTENT = "ACCOUNTING_INCONSISTENT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    AMBIGUOUS_ACCOUNTING = "AMBIGUOUS_ACCOUNTING"


class AutoAcceptSafety(str, Enum):
    """Safety classification for documents marked AUTO_ACCEPT."""
    AUTO_ACCEPT_SAFE = "AUTO_ACCEPT_SAFE"
    AUTO_ACCEPT_UNSAFE = "AUTO_ACCEPT_UNSAFE"
    INSUFFICIENT_GROUND_TRUTH = "INSUFFICIENT_GROUND_TRUTH"


# Canonical field definitions for the purchase import engine
CANONICAL_FIELDS: List[str] = [
    "itemName",
    "pack",
    "batchNo",
    "expiryDate",
    "quantity",
    "freeQuantity",
    "discountPercent",
    "rate",
    "mrp",
    "hsnCode",
    "amount",
    "taxableAmount",
    "netAmount",
    "cgstPercent",
    "sgstPercent",
    "gstPercent",
    "company",
]

CRITICAL_FIELDS: List[str] = [
    "itemName",
    "quantity",
    "rate",
    "amount",
]

FINANCIAL_FIELDS: List[str] = [
    "rate",
    "mrp",
    "discountPercent",
    "taxableAmount",
    "cgstPercent",
    "sgstPercent",
    "gstPercent",
    "netAmount",
    "amount",
]


@dataclass
class FieldGroundTruthCell:
    """Represents the ground truth for a single cell (document -> row -> field)."""
    field_name: str
    value: Any = None
    raw_text: Optional[str] = None
    state: FieldPresenceState = FieldPresenceState.KNOWN
    evidence: Optional[str] = None
    verification_status: str = "VERIFIED"  # VERIFIED, ESTIMATED, UNVERIFIED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_name": self.field_name,
            "value": self.value,
            "raw_text": self.raw_text,
            "state": self.state.value if isinstance(self.state, FieldPresenceState) else str(self.state),
            "evidence": self.evidence,
            "verification_status": self.verification_status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FieldGroundTruthCell:
        st_val = data.get("state", "KNOWN")
        st = FieldPresenceState(st_val) if st_val in [e.value for e in FieldPresenceState] else FieldPresenceState.KNOWN
        return cls(
            field_name=data["field_name"],
            value=data.get("value"),
            raw_text=data.get("raw_text"),
            state=st,
            evidence=data.get("evidence"),
            verification_status=data.get("verification_status", "VERIFIED"),
        )


@dataclass
class FieldGroundTruthRow:
    """Represents the ground truth for a single line item row."""
    row_index: int
    cells: Dict[str, FieldGroundTruthCell] = field(default_factory=dict)
    raw_row_text: Optional[str] = None
    page: int = 1

    def get_cell(self, field_name: str) -> Optional[FieldGroundTruthCell]:
        return self.cells.get(field_name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "row_index": self.row_index,
            "page": self.page,
            "raw_row_text": self.raw_row_text,
            "cells": {k: c.to_dict() for k, c in self.cells.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FieldGroundTruthRow:
        cells = {}
        for k, v in data.get("cells", {}).items():
            if isinstance(v, dict):
                cell_dict = dict(v)
                if "field_name" not in cell_dict:
                    cell_dict["field_name"] = k
                cells[k] = FieldGroundTruthCell.from_dict(cell_dict)
            else:
                # Shorthand format: field_name -> value
                cells[k] = FieldGroundTruthCell(
                    field_name=k,
                    value=v,
                    raw_text=str(v) if v is not None else None,
                    state=FieldPresenceState.KNOWN if v is not None else FieldPresenceState.NOT_PRESENT,
                )
        return cls(
            row_index=data["row_index"],
            page=data.get("page", 1),
            raw_row_text=data.get("raw_row_text"),
            cells=cells,
        )


@dataclass
class FieldGroundTruthDocument:
    """Represents complete field-level ground truth for a canonical document."""
    document_id: str
    filename: str
    sha256: str
    expected_rows: int
    clean_medicine_rows: int
    supplier_name: Optional[str] = None
    gstin: Optional[str] = None
    field_presence_matrix: Dict[str, str] = field(default_factory=dict)  # field -> "YES" / "NO" / "HEADERLESS"
    rows: List[FieldGroundTruthRow] = field(default_factory=list)
    accounting_formula: Optional[str] = None
    notes: Optional[str] = None

    def get_row(self, index: int) -> Optional[FieldGroundTruthRow]:
        for r in self.rows:
            if r.row_index == index:
                return r
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "sha256": self.sha256,
            "expected_rows": self.expected_rows,
            "clean_medicine_rows": self.clean_medicine_rows,
            "supplier_name": self.supplier_name,
            "gstin": self.gstin,
            "field_presence_matrix": self.field_presence_matrix,
            "accounting_formula": self.accounting_formula,
            "notes": self.notes,
            "rows": [r.to_dict() for r in self.rows],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FieldGroundTruthDocument:
        rows = [FieldGroundTruthRow.from_dict(r) for r in data.get("rows", [])]
        return cls(
            document_id=data["document_id"],
            filename=data["filename"],
            sha256=data.get("sha256", ""),
            expected_rows=data.get("expected_rows", len(rows)),
            clean_medicine_rows=data.get("clean_medicine_rows", len(rows)),
            supplier_name=data.get("supplier_name"),
            gstin=data.get("gstin"),
            field_presence_matrix=data.get("field_presence_matrix", {}),
            accounting_formula=data.get("accounting_formula"),
            notes=data.get("notes"),
            rows=rows,
        )


class FieldGroundTruthStore:
    """
    Manages loading, validation, and retrieval of canonical field-level ground truth.
    Strictly isolated from predictions and extraction outputs.
    """

    def __init__(self, manifest_path: Optional[str] = None):
        self.manifest_path = manifest_path or os.path.join(
            os.path.dirname(__file__), "field_ground_truth_manifest.json"
        )
        self._documents: Dict[str, FieldGroundTruthDocument] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.manifest_path):
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for doc_data in data.get("documents", []):
                    doc = FieldGroundTruthDocument.from_dict(doc_data)
                    self._documents[doc.filename] = doc
                    self._documents[doc.sha256] = doc
                    if doc.document_id:
                        self._documents[doc.document_id] = doc

    def get_document(self, identifier: str) -> Optional[FieldGroundTruthDocument]:
        return self._documents.get(identifier)

    def get_all_documents(self) -> List[FieldGroundTruthDocument]:
        seen = set()
        res = []
        for doc in self._documents.values():
            if doc.filename not in seen:
                res.append(doc)
                seen.add(doc.filename)
        return res

    def get_presence_matrix(self) -> Dict[str, Dict[str, str]]:
        """Returns the full document x canonical field presence matrix."""
        matrix = {}
        for doc in self.get_all_documents():
            matrix[doc.filename] = doc.field_presence_matrix
        return matrix
