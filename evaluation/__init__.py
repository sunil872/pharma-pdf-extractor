"""
MediAstra Pharma PDF Import Engine - Evaluation & Error Analysis Package (Prompt 12)
"""

from evaluation.models import (
    DatasetCategory,
    RootCause,
    DifficultLayoutFlag,
    CANONICAL_FIELDS,
    NUMERIC_FIELD_TOLERANCES,
    EvaluationManifestItem,
    GroundTruthRow,
    GroundTruthDocument,
    FieldMetricResult,
    RowMetricResult,
    ColumnMappingEvaluation,
    DiagnosticErrorContext,
    ConfidenceBucketResult,
    SupplierLayoutStat,
)

__all__ = [
    "DatasetCategory",
    "RootCause",
    "DifficultLayoutFlag",
    "CANONICAL_FIELDS",
    "NUMERIC_FIELD_TOLERANCES",
    "EvaluationManifestItem",
    "GroundTruthRow",
    "GroundTruthDocument",
    "FieldMetricResult",
    "RowMetricResult",
    "ColumnMappingEvaluation",
    "DiagnosticErrorContext",
    "ConfidenceBucketResult",
    "verify_golden_benchmark_v1",
    "FieldPresenceState",
    "RowClassification",
    "AccountingStatus",
    "AutoAcceptSafety",
    "FieldGroundTruthCell",
    "FieldGroundTruthRow",
    "FieldGroundTruthDocument",
    "FieldGroundTruthStore",
    "DocumentFieldAccuracyReport",
    "BenchmarkFieldAccuracySummary",
    "evaluate_canonical_field_accuracy",
]

from evaluation.evaluator import verify_golden_benchmark_v1
from evaluation.field_ground_truth import (
    FieldPresenceState,
    RowClassification,
    AccountingStatus,
    AutoAcceptSafety,
    FieldGroundTruthCell,
    FieldGroundTruthRow,
    FieldGroundTruthDocument,
    FieldGroundTruthStore,
)
from evaluation.field_accuracy import (
    DocumentFieldAccuracyReport,
    BenchmarkFieldAccuracySummary,
    evaluate_canonical_field_accuracy,
)

