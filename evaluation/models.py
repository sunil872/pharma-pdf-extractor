"""
MediAstra Pharma PDF Import Engine - Evaluation & Error Analysis Models
Defines dataclasses, enums, and schemas for Prompt 12 evaluation framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class DatasetCategory(str, Enum):
    GOLDEN = "GOLDEN"
    GOLDEN_V1 = "GOLDEN_V1"
    REAL = "REAL"
    SYNTHETIC = "SYNTHETIC"
    EDGE_CASE = "EDGE_CASE"
    OTHER = "OTHER"


class RootCause(str, Enum):
    HEADER_RECONSTRUCTION = "HEADER_RECONSTRUCTION"
    COLUMN_BOUNDARY = "COLUMN_BOUNDARY"
    TRUE_COLUMN_BOUNDARY_ERROR = "TRUE_COLUMN_BOUNDARY_ERROR"
    AUXILIARY_COLUMN = "AUXILIARY_COLUMN"
    UNMAPPED_NON_CANONICAL_COLUMN = "UNMAPPED_NON_CANONICAL_COLUMN"
    LOGICAL_SUBCOLUMN_SPLIT = "LOGICAL_SUBCOLUMN_SPLIT"
    LOGICAL_SUBCOLUMN_ERROR = "LOGICAL_SUBCOLUMN_ERROR"
    SEMANTIC_MAPPING = "SEMANTIC_MAPPING"
    VALUE_NORMALIZATION = "VALUE_NORMALIZATION"
    ROW_RECONSTRUCTION = "ROW_RECONSTRUCTION"
    SUPPLIER_IDENTITY = "SUPPLIER_IDENTITY"
    LAYOUT_MATCHING = "LAYOUT_MATCHING"
    ACCOUNTING_VALIDATION = "ACCOUNTING_VALIDATION"
    CONFIDENCE_DECISION = "CONFIDENCE_DECISION"
    PDF_EXTRACTION = "PDF_EXTRACTION"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class DifficultLayoutFlag(str, Enum):
    MERGED_HEADERS = "merged_headers"
    SPLIT_HEADERS = "split_headers"
    UNNAMED_COLUMNS = "unnamed_columns"
    MULTIPLE_LOGICAL_VALUES_IN_CELL = "multiple_logical_values_in_cell"
    MISSING_HEADERS = "missing_headers"
    UNUSUAL_COLUMN_ORDER = "unusual_column_order"
    MULTILINE_PRODUCT_NAMES = "multiline_product_names"
    CONTINUATION_ROWS = "continuation_rows"
    BATCH_EXPIRY_MERGED = "batch_expiry_merged"
    HSN_EXPIRY_MERGED = "hsn_expiry_merged"
    MRP_RATE_MERGED = "mrp_rate_merged"
    QTY_FREE_MERGED = "quantity_free_merged"
    AMOUNT_GST_MERGED = "amount_gst_merged"
    CGST_SGST_COMBINED = "cgst_sgst_combined"
    MISSING_MRP = "missing_mrp"
    MISSING_RATE = "missing_rate"
    MISSING_HSN = "missing_hsn"
    MISSING_GST = "missing_gst"
    UNUSUAL_FOOTER_INTERFERENCE = "unusual_footer_interference"


CANONICAL_FIELDS = [
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

# Field-specific numeric tolerance configuration
NUMERIC_FIELD_TOLERANCES: Dict[str, Dict[str, float]] = {
    "quantity": {"abs_tol": 0.01, "rel_tol": 0.0},
    "freeQuantity": {"abs_tol": 0.01, "rel_tol": 0.0},
    "discountPercent": {"abs_tol": 0.05, "rel_tol": 0.01},
    "rate": {"abs_tol": 0.05, "rel_tol": 0.005},
    "mrp": {"abs_tol": 0.05, "rel_tol": 0.005},
    "amount": {"abs_tol": 0.10, "rel_tol": 0.005},
    "taxableAmount": {"abs_tol": 0.10, "rel_tol": 0.005},
    "netAmount": {"abs_tol": 0.10, "rel_tol": 0.005},
    "cgstPercent": {"abs_tol": 0.10, "rel_tol": 0.0},
    "sgstPercent": {"abs_tol": 0.10, "rel_tol": 0.0},
    "gstPercent": {"abs_tol": 0.10, "rel_tol": 0.0},
}


@dataclass
class EvaluationManifestItem:
    document_id: str
    filename: str
    file_path: str
    sha256: str
    dataset_category: DatasetCategory
    supplier_name: Optional[str] = None
    gstin: Optional[str] = None
    expected_row_count: Optional[int] = None
    ground_truth_available: bool = False
    ground_truth_source: Optional[str] = None
    notes: Optional[str] = None
    added_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "file_path": self.file_path,
            "sha256": self.sha256,
            "dataset_category": self.dataset_category.value if isinstance(self.dataset_category, DatasetCategory) else str(self.dataset_category),
            "supplier_name": self.supplier_name,
            "gstin": self.gstin,
            "expected_row_count": self.expected_row_count,
            "ground_truth_available": self.ground_truth_available,
            "ground_truth_source": self.ground_truth_source,
            "notes": self.notes,
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvaluationManifestItem:
        cat_val = data.get("dataset_category", "REAL")
        cat = DatasetCategory(cat_val) if cat_val in [e.value for e in DatasetCategory] else DatasetCategory.REAL
        return cls(
            document_id=data["document_id"],
            filename=data["filename"],
            file_path=data.get("file_path", ""),
            sha256=data["sha256"],
            dataset_category=cat,
            supplier_name=data.get("supplier_name"),
            gstin=data.get("gstin"),
            expected_row_count=data.get("expected_row_count"),
            ground_truth_available=data.get("ground_truth_available", False),
            ground_truth_source=data.get("ground_truth_source"),
            notes=data.get("notes"),
            added_at=data.get("added_at"),
        )


@dataclass
class GroundTruthRow:
    row_index: int
    fields: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GroundTruthDocument:
    document_id: str
    filename: str
    rows: List[GroundTruthRow] = field(default_factory=list)
    column_mappings: Optional[Dict[str, str]] = None  # physical/header -> canonical_field

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "rows": [{"row_index": r.row_index, "fields": r.fields} for r in self.rows],
            "column_mappings": self.column_mappings,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GroundTruthDocument:
        rows = [GroundTruthRow(row_index=r["row_index"], fields=r.get("fields", {})) for r in data.get("rows", [])]
        return cls(
            document_id=data["document_id"],
            filename=data["filename"],
            rows=rows,
            column_mappings=data.get("column_mappings"),
        )


@dataclass
class FieldMetricResult:
    canonical_field: str
    total_ground_truth: int = 0
    total_predictions: int = 0
    exact_matches: int = 0
    normalized_matches: int = 0
    tolerance_matches: int = 0
    missing_predictions: int = 0
    unexpected_predictions: int = 0
    incorrect_predictions: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "canonical_field": self.canonical_field,
            "total_ground_truth": self.total_ground_truth,
            "total_predictions": self.total_predictions,
            "exact_matches": self.exact_matches,
            "normalized_matches": self.normalized_matches,
            "tolerance_matches": self.tolerance_matches,
            "missing_predictions": self.missing_predictions,
            "unexpected_predictions": self.unexpected_predictions,
            "incorrect_predictions": self.incorrect_predictions,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


@dataclass
class RowMetricResult:
    expected_rows: int = 0
    extracted_rows: int = 0
    matched_rows: int = 0
    missing_rows: int = 0
    extra_rows: int = 0
    duplicate_rows: int = 0
    split_rows: int = 0
    merged_rows: int = 0
    continuation_errors: int = 0
    row_accuracy: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "expected_rows": self.expected_rows,
            "extracted_rows": self.extracted_rows,
            "matched_rows": self.matched_rows,
            "missing_rows": self.missing_rows,
            "extra_rows": self.extra_rows,
            "duplicate_rows": self.duplicate_rows,
            "split_rows": self.split_rows,
            "merged_rows": self.merged_rows,
            "continuation_errors": self.continuation_errors,
            "row_accuracy": round(self.row_accuracy, 4),
        }


@dataclass
class ColumnMappingEvaluation:
    document_id: str
    physical_column_index: int
    header_text: str
    predicted_canonical: Optional[str]
    expected_canonical: Optional[str]
    is_correct: bool
    confidence: float
    root_cause: Optional[RootCause] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "physical_column_index": self.physical_column_index,
            "header_text": self.header_text,
            "predicted_canonical": self.predicted_canonical,
            "expected_canonical": self.expected_canonical,
            "is_correct": self.is_correct,
            "confidence": round(self.confidence, 4),
            "root_cause": self.root_cause.value if self.root_cause else None,
        }


@dataclass
class DiagnosticErrorContext:
    document_id: str
    filename: str
    page: int
    physical_column: Optional[int]
    header_text: Optional[str]
    x_coords: Optional[List[float]]
    predicted_field: Optional[str]
    expected_field: Optional[str]
    raw_extracted_value: Optional[str]
    normalized_value: Optional[Any]
    ground_truth_value: Optional[Any]
    confidence: float
    validation_warnings: List[str]
    root_cause: RootCause

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "page": self.page,
            "physical_column": self.physical_column,
            "header_text": self.header_text,
            "x_coords": self.x_coords,
            "predicted_field": self.predicted_field,
            "expected_field": self.expected_field,
            "raw_extracted_value": self.raw_extracted_value,
            "normalized_value": str(self.normalized_value) if self.normalized_value is not None else None,
            "ground_truth_value": str(self.ground_truth_value) if self.ground_truth_value is not None else None,
            "confidence": round(self.confidence, 4),
            "validation_warnings": self.validation_warnings,
            "root_cause": self.root_cause.value,
        }


@dataclass
class ConfidenceBucketResult:
    bucket_name: str
    min_conf: float
    max_conf: float
    total_documents: int = 0
    sample_count: int = 0
    correct_documents: int = 0
    incorrect_documents: int = 0
    unknown_count: int = 0
    review_required_count: int = 0
    unresolved_count: int = 0
    empirical_accuracy: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bucket_name": self.bucket_name,
            "min_conf": self.min_conf,
            "max_conf": self.max_conf,
            "total_documents": self.total_documents,
            "sample_count": self.sample_count or self.total_documents,
            "correct_documents": self.correct_documents,
            "incorrect_documents": self.incorrect_documents,
            "unknown_count": self.unknown_count,
            "review_required_count": self.review_required_count,
            "unresolved_count": self.unresolved_count,
            "empirical_accuracy": round(self.empirical_accuracy, 4),
        }


@dataclass
class SupplierLayoutStat:
    supplier_name: str
    gstin: Optional[str]
    layout_profile_id: Optional[str]
    layout_version: Optional[int]
    dataset_category: str
    doc_count: int = 0
    auto_accept_pct: float = 0.0
    review_required_pct: float = 0.0
    unresolved_pct: float = 0.0
    failed_pct: float = 0.0
    avg_confidence: float = 0.0
    min_confidence: float = 0.0
    avg_processing_time_ms: float = 0.0
    common_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "supplier_name": self.supplier_name,
            "gstin": self.gstin,
            "layout_profile_id": self.layout_profile_id,
            "layout_version": self.layout_version,
            "dataset_category": self.dataset_category,
            "doc_count": self.doc_count,
            "auto_accept_pct": round(self.auto_accept_pct, 2),
            "review_required_pct": round(self.review_required_pct, 2),
            "unresolved_pct": round(self.unresolved_pct, 2),
            "failed_pct": round(self.failed_pct, 2),
            "avg_confidence": round(self.avg_confidence, 4),
            "min_confidence": round(self.min_confidence, 4),
            "avg_processing_time_ms": round(self.avg_processing_time_ms, 2),
            "common_errors": self.common_errors,
        }
