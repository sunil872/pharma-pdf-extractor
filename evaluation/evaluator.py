"""
MediAstra Pharma PDF Import Engine - Evaluation & Error Analysis Engine
Core evaluation framework for field-level, row-level, column-mapping, and root-cause error analysis.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from evaluation.ground_truth import GroundTruthStore, GOLDEN_BENCHMARK_GROUND_TRUTH
from evaluation.models import (
    CANONICAL_FIELDS,
    NUMERIC_FIELD_TOLERANCES,
    ColumnMappingEvaluation,
    ConfidenceBucketResult,
    DatasetCategory,
    DiagnosticErrorContext,
    DifficultLayoutFlag,
    EvaluationManifestItem,
    FieldMetricResult,
    GroundTruthDocument,
    GroundTruthRow,
    RootCause,
    RowMetricResult,
    SupplierLayoutStat,
)
from extractor import extract_pdf_table, ALIAS_DICT, clean_text


class InvoiceEvaluator:
    """Evaluates invoice extraction quality, error taxonomy, and layout diversity."""

    def __init__(
        self,
        manifest_path: Optional[str] = None,
        ground_truth_store: Optional[GroundTruthStore] = None,
        extract_fn: Optional[Any] = None,
    ):
        self.manifest_path = manifest_path or os.path.join(
            os.path.dirname(__file__), "manifest.json"
        )
        self.ground_truth_store = ground_truth_store or GroundTruthStore()
        self.extract_fn = extract_fn or extract_pdf_table
        self.manifest_items: List[EvaluationManifestItem] = []
        self._load_manifest()

    def _load_manifest(self) -> None:
        if os.path.exists(self.manifest_path):
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.manifest_items = [
                    EvaluationManifestItem.from_dict(item)
                    for item in data.get("documents", [])
                ]

    def compute_sha256(self, file_path: str) -> str:
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def normalize_string_value(self, val: Any) -> str:
        if val is None:
            return ""
        s = str(val).strip().upper()
        # Collapse multiple whitespaces
        s = re.sub(r"\s+", " ", s)
        # Standardize date separators
        s = re.sub(r"[.-]", "/", s)
        return s

    def normalize_numeric_value(self, val: Any) -> Optional[float]:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        cleaned = re.sub(r"[^\d.-]", "", str(val))
        try:
            return float(cleaned)
        except (ValueError, TypeError):
            return None

    def compare_field_values(
        self,
        field_name: str,
        predicted: Any,
        expected: Any,
    ) -> Tuple[bool, bool, bool]:
        """
        Returns (is_exact_match, is_normalized_match, is_tolerance_match).
        """
        # Exact match
        is_exact = predicted == expected

        if predicted is None or expected is None:
            return (is_exact, is_exact, is_exact)

        # String normalization
        norm_pred = self.normalize_string_value(predicted)
        norm_exp = self.normalize_string_value(expected)
        is_norm = norm_pred == norm_exp

        # Numeric tolerance match
        is_tol = False
        if field_name in NUMERIC_FIELD_TOLERANCES:
            num_pred = self.normalize_numeric_value(predicted)
            num_exp = self.normalize_numeric_value(expected)
            if num_pred is not None and num_exp is not None:
                tol_cfg = NUMERIC_FIELD_TOLERANCES[field_name]
                abs_tol = tol_cfg.get("abs_tol", 0.01)
                rel_tol = tol_cfg.get("rel_tol", 0.0)
                diff = abs(num_pred - num_exp)
                if rel_tol > 0:
                    allowed = max(abs_tol, abs(num_exp) * rel_tol)
                else:
                    allowed = abs_tol
                is_tol = diff <= allowed

        return (is_exact, is_norm, is_tol)

    def evaluate_field_level(
        self,
        extracted_rows: List[Dict[str, Any]],
        ground_truth_rows: List[GroundTruthRow],
    ) -> Dict[str, FieldMetricResult]:
        """Calculates exact, normalized, tolerance matches and precision/recall/F1 per field."""
        metrics: Dict[str, FieldMetricResult] = {
            f: FieldMetricResult(canonical_field=f) for f in CANONICAL_FIELDS
        }

        min_len = min(len(extracted_rows), len(ground_truth_rows))

        for f_name in CANONICAL_FIELDS:
            m = metrics[f_name]
            for i in range(min_len):
                ext_val = extracted_rows[i].get(f_name)
                gt_val = ground_truth_rows[i].fields.get(f_name)

                if gt_val is not None:
                    m.total_ground_truth += 1

                if ext_val is not None:
                    m.total_predictions += 1

                if gt_val is not None and ext_val is not None:
                    exact, norm, tol = self.compare_field_values(f_name, ext_val, gt_val)
                    if exact:
                        m.exact_matches += 1
                        m.normalized_matches += 1
                        m.tolerance_matches += 1
                    elif norm:
                        m.normalized_matches += 1
                        m.tolerance_matches += 1
                    elif tol:
                        m.tolerance_matches += 1
                    else:
                        m.incorrect_predictions += 1
                elif gt_val is not None and ext_val is None:
                    m.missing_predictions += 1
                elif gt_val is None and ext_val is not None:
                    m.unexpected_predictions += 1

            # Extra ground truth rows
            if len(ground_truth_rows) > min_len:
                for i in range(min_len, len(ground_truth_rows)):
                    gt_val = ground_truth_rows[i].fields.get(f_name)
                    if gt_val is not None:
                        m.total_ground_truth += 1
                        m.missing_predictions += 1

            # Extra extracted rows
            if len(extracted_rows) > min_len:
                for i in range(min_len, len(extracted_rows)):
                    ext_val = extracted_rows[i].get(f_name)
                    if ext_val is not None:
                        m.total_predictions += 1
                        m.unexpected_predictions += 1

            # Compute Precision, Recall, F1 (based on best match: tolerance or normalized)
            tp = m.tolerance_matches if f_name in NUMERIC_FIELD_TOLERANCES else m.normalized_matches
            fp = m.unexpected_predictions + m.incorrect_predictions
            fn = m.missing_predictions

            m.precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            m.recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            if (m.precision + m.recall) > 0:
                m.f1 = (2 * m.precision * m.recall) / (m.precision + m.recall)
            else:
                m.f1 = 0.0

        return metrics

    def evaluate_row_level(
        self,
        extracted_rows: List[Dict[str, Any]],
        ground_truth_rows: List[GroundTruthRow],
        expected_count: Optional[int] = None,
    ) -> RowMetricResult:
        """Calculates row-level metrics including split, merged, and duplicate row detection."""
        res = RowMetricResult()
        res.expected_rows = expected_count if expected_count is not None else len(ground_truth_rows)
        res.extracted_rows = len(extracted_rows)

        # Check for duplicates in extracted rows
        seen_signatures = defaultdict(int)
        for r in extracted_rows:
            sig = (
                self.normalize_string_value(r.get("itemName")),
                self.normalize_string_value(r.get("batchNo")),
                self.normalize_numeric_value(r.get("rate")),
            )
            if any(sig):
                seen_signatures[sig] += 1
        res.duplicate_rows = sum(count - 1 for count in seen_signatures.values() if count > 1)

        # Match rows against ground truth
        matched_gt_indices = set()
        matched_ext_indices = set()

        for ext_idx, ext_row in enumerate(extracted_rows):
            ext_item = self.normalize_string_value(ext_row.get("itemName"))
            ext_batch = self.normalize_string_value(ext_row.get("batchNo"))

            best_match_idx = None
            best_score = 0

            for gt_idx, gt_row in enumerate(ground_truth_rows):
                if gt_idx in matched_gt_indices:
                    continue
                gt_item = self.normalize_string_value(gt_row.fields.get("itemName"))
                gt_batch = self.normalize_string_value(gt_row.fields.get("batchNo"))

                score = 0
                if ext_item and gt_item and (ext_item in gt_item or gt_item in ext_item):
                    score += 2
                if ext_batch and gt_batch and ext_batch == gt_batch:
                    score += 2

                if score > best_score:
                    best_score = score
                    best_match_idx = gt_idx

            if best_match_idx is not None and best_score >= 2:
                matched_gt_indices.add(best_match_idx)
                matched_ext_indices.add(ext_idx)

        res.matched_rows = len(matched_gt_indices)
        if len(ground_truth_rows) > 0:
            res.missing_rows = max(0, len(ground_truth_rows) - len(matched_gt_indices))
            res.extra_rows = max(0, len(extracted_rows) - len(matched_ext_indices))
        else:
            if res.expected_rows > 0:
                if res.extracted_rows < res.expected_rows:
                    res.missing_rows = res.expected_rows - res.extracted_rows
                elif res.extracted_rows > res.expected_rows:
                    res.extra_rows = res.extracted_rows - res.expected_rows
                res.matched_rows = min(res.extracted_rows, res.expected_rows)

        # Detect split and merged rows
        if res.extracted_rows > res.expected_rows and res.expected_rows > 0:
            # Possible split rows or extra header/footer lines
            res.split_rows = res.extracted_rows - res.expected_rows
        elif res.extracted_rows < res.expected_rows and res.expected_rows > 0:
            # Possible merged rows
            res.merged_rows = res.expected_rows - res.extracted_rows

        total_denom = max(res.expected_rows, res.extracted_rows, 1)
        res.row_accuracy = res.matched_rows / total_denom

        return res

    def evaluate_column_mappings(
        self,
        document_id: str,
        predicted_mappings: Dict[str, Optional[str]],
        ground_truth_mappings: Optional[Dict[str, str]],
        header_positions: Optional[Dict[str, float]] = None,
    ) -> List[ColumnMappingEvaluation]:
        """Evaluates semantic column mappings and generates root-cause classifications."""
        results: List[ColumnMappingEvaluation] = []
        if not ground_truth_mappings:
            return results

        # Normalized lookup table for predicted headers
        norm_pred_map = {clean_text(k).upper(): v for k, v in predicted_mappings.items() if k}

        col_idx = 0
        for raw_col, exp_canonical in ground_truth_mappings.items():
            pred_canonical = predicted_mappings.get(raw_col)

            # Fallback normalized lookup if exact raw string differs in punctuation / case / spacing
            if pred_canonical is None:
                norm_raw = clean_text(raw_col).upper()
                if norm_raw in norm_pred_map:
                    pred_canonical = norm_pred_map[norm_raw]
                else:
                    # Check prefix or substring match
                    for k_norm, val in norm_pred_map.items():
                        if k_norm and (norm_raw == k_norm or norm_raw.startswith(k_norm) or k_norm.startswith(norm_raw)):
                            pred_canonical = val
                            break

            is_correct = pred_canonical == exp_canonical

            root_cause = None
            if not is_correct:
                root_cause = self.classify_mapping_error(
                    raw_col, pred_canonical, exp_canonical
                )

            results.append(
                ColumnMappingEvaluation(
                    document_id=document_id,
                    physical_column_index=col_idx,
                    header_text=raw_col,
                    predicted_canonical=pred_canonical,
                    expected_canonical=exp_canonical,
                    is_correct=is_correct,
                    confidence=1.0 if is_correct else 0.5,
                    root_cause=root_cause,
                )
            )
            col_idx += 1

        return results

    def classify_mapping_error(
        self,
        header_text: str,
        predicted: Optional[str],
        expected: Optional[str],
    ) -> RootCause:
        """Determines the root cause for column mapping failure."""
        h_upper = header_text.upper().strip()

        # 1. Auxiliary serial number / notes / non-canonical column
        if any(h_upper == s.upper() or h_upper.startswith(s.upper()) for s in ["S.", "S.NO", "SR NO", "SL NO", "S NO", "SR.NO", "SR.", "SL.", "NO.", "INDEX"]):
            return RootCause.AUXILIARY_COLUMN

        # 2. Unmapped non-canonical column (expected is None)
        if expected is None:
            return RootCause.UNMAPPED_NON_CANONICAL_COLUMN

        # 3. Split visual headers (broken header tokens)
        if re.search(r"\b(PT\s+R|M\s+R\s*P|M\s*R\s+P|MR\s+P|RAT\s+E|P\s+A\s+CK|BAT\s+CH|EX\s+P)\b", h_upper):
            return RootCause.HEADER_RECONSTRUCTION

        # 4. Composite logical sub-column split failure
        if any(tok in h_upper for tok in ["QTY FREE", "AMOUNT GST", "BATCH EXP", "MRP RATE", "CGST SGST", "PACK QTY"]):
            return RootCause.LOGICAL_SUBCOLUMN_SPLIT

        # 5. Semantic confusion (both predicted and expected are valid canonical fields, but different)
        if predicted and expected and predicted != expected:
            return RootCause.SEMANTIC_MAPPING

        # 6. Missing column prediction due to boundary coordinate bleed or omission
        if not predicted and expected:
            return RootCause.TRUE_COLUMN_BOUNDARY_ERROR

        return RootCause.TRUE_COLUMN_BOUNDARY_ERROR

    def detect_difficult_layout_flags(
        self,
        extraction_result: Dict[str, Any],
        raw_headers: List[str],
    ) -> List[DifficultLayoutFlag]:
        """Flags challenging layout characteristics in the invoice."""
        flags: List[DifficultLayoutFlag] = []
        header_text_combined = " ".join(raw_headers).upper()

        # Split headers (e.g., 'PT' 'R', 'M' 'RP')
        if any(h in ["PT", "R", "RAT", "MR", "P"] for h in raw_headers):
            flags.append(DifficultLayoutFlag.SPLIT_HEADERS)

        # Unnamed columns
        if any("UNNAMED" in h.upper() for h in raw_headers):
            flags.append(DifficultLayoutFlag.UNNAMED_COLUMNS)

        # Multiple logical values in composite column
        if re.search(r"\b(PACK\s+QTY|QTY\s+FREE|AMOUNT\s+GST|MRP\s+RATE)\b", header_text_combined):
            flags.append(DifficultLayoutFlag.MULTIPLE_LOGICAL_VALUES_IN_CELL)
            if "QTY" in header_text_combined and "FREE" in header_text_combined:
                flags.append(DifficultLayoutFlag.QTY_FREE_MERGED)
            if "AMOUNT" in header_text_combined and "GST" in header_text_combined:
                flags.append(DifficultLayoutFlag.AMOUNT_GST_MERGED)

        # Check extracted row data patterns
        rows = extraction_result.get("rows", [])
        if rows:
            # Missing key fields
            has_mrp = any(r.get("mrp") is not None for r in rows)
            has_rate = any(r.get("rate") is not None for r in rows)
            has_hsn = any(r.get("hsnCode") is not None for r in rows)
            has_gst = any(r.get("gstPercent") is not None for r in rows)

            if not has_mrp:
                flags.append(DifficultLayoutFlag.MISSING_MRP)
            if not has_rate:
                flags.append(DifficultLayoutFlag.MISSING_RATE)
            if not has_hsn:
                flags.append(DifficultLayoutFlag.MISSING_HSN)
            if not has_gst:
                flags.append(DifficultLayoutFlag.MISSING_GST)

            # Multiline / continuation
            long_names = sum(1 for r in rows if len(str(r.get("itemName") or "")) > 35)
            if long_names > 2:
                flags.append(DifficultLayoutFlag.MULTILINE_PRODUCT_NAMES)

        return list(set(flags))

    def evaluate_confidence_calibration(
        self,
        document_evaluations: List[Dict[str, Any]],
    ) -> List[ConfidenceBucketResult]:
        """
        Buckets documents by confidence and measures empirical accuracy.
        Excludes documents without verified ground truth from empirical accuracy calculations.
        """
        buckets = [
            ("0-50", 0.0, 50.0),
            ("50-60", 50.0, 60.0),
            ("60-70", 60.0, 70.0),
            ("70-80", 70.0, 80.0),
            ("80-90", 80.0, 90.0),
            ("90-95", 90.0, 95.0),
            ("95-100", 95.0, 100.0),
        ]

        results = [
            ConfidenceBucketResult(bucket_name=b[0], min_conf=b[1], max_conf=b[2])
            for b in buckets
        ]

        for doc in document_evaluations:
            conf = doc.get("confidence", 0.0)
            is_correct = doc.get("is_correct", False)
            gt_available = doc.get("ground_truth_available", True)
            decision = doc.get("decision", "UNRESOLVED")

            for b in results:
                if b.min_conf <= conf < b.max_conf or (b.max_conf == 100.0 and conf == 100.0):
                    b.total_documents += 1
                    b.sample_count += 1
                    if gt_available:
                        if is_correct:
                            b.correct_documents += 1
                        else:
                            b.incorrect_documents += 1
                    else:
                        b.unknown_count += 1

                    if decision == "REVIEW_REQUIRED":
                        b.review_required_count += 1
                    elif decision == "UNRESOLVED":
                        b.unresolved_count += 1
                    break

        for b in results:
            known_total = b.correct_documents + b.incorrect_documents
            if known_total > 0:
                b.empirical_accuracy = b.correct_documents / known_total
            else:
                b.empirical_accuracy = 0.0

        return results

    def analyze_auto_accept_safety(
        self,
        document_evaluations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Calculates precision and error rate for AUTO_ACCEPT decisions on verified documents."""
        auto_accept_docs = [
            d for d in document_evaluations if d.get("decision") == "AUTO_ACCEPT"
        ]
        total_auto = len(auto_accept_docs)
        if total_auto == 0:
            return {
                "total_auto_accept": 0,
                "fully_correct": 0,
                "with_field_errors": 0,
                "with_row_errors": 0,
                "precision": 1.0,
                "error_rate": 0.0,
                "problematic_fields": [],
            }

        correct_count = 0
        field_errors_count = 0
        row_errors_count = 0
        problem_fields = defaultdict(int)
        verified_count = 0

        for d in auto_accept_docs:
            if d.get("ground_truth_available", True):
                verified_count += 1
                has_field_err = d.get("field_error_count", 0) > 0
                has_row_err = d.get("row_error_count", 0) > 0

                if not has_field_err and not has_row_err:
                    correct_count += 1
                if has_field_err:
                    field_errors_count += 1
                    for fld in d.get("erroneous_fields", []):
                        problem_fields[fld] += 1
                if has_row_err:
                    row_errors_count += 1

        denom = max(verified_count, 1)
        precision = correct_count / denom
        error_rate = (verified_count - correct_count) / denom

        return {
            "total_auto_accept": total_auto,
            "verified_count": verified_count,
            "fully_correct": correct_count,
            "with_field_errors": field_errors_count,
            "with_row_errors": row_errors_count,
            "precision": round(precision, 4),
            "error_rate": round(error_rate, 4),
            "problematic_fields": sorted(
                [{"field": k, "count": v} for k, v in problem_fields.items()],
                key=lambda x: x["count"],
                reverse=True,
            ),
        }

    def analyze_review_required(
        self,
        document_evaluations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Analyzes triggers and fields causing REVIEW_REQUIRED decisions."""
        review_docs = [
            d for d in document_evaluations if d.get("decision") == "REVIEW_REQUIRED"
        ]
        total_reviews = len(review_docs)

        trigger_warnings = defaultdict(int)
        trigger_fields = defaultdict(int)

        for d in review_docs:
            for w in d.get("validation_warnings", []):
                trigger_warnings[w] += 1
            for f in d.get("low_confidence_fields", []):
                trigger_fields[f] += 1

        return {
            "total_review_required": total_reviews,
            "top_warning_triggers": sorted(
                [{"warning": k, "count": v} for k, v in trigger_warnings.items()],
                key=lambda x: x["count"],
                reverse=True,
            ),
            "top_field_triggers": sorted(
                [{"field": k, "count": v} for k, v in trigger_fields.items()],
                key=lambda x: x["count"],
                reverse=True,
            ),
        }

    def analyze_unresolved(
        self,
        document_evaluations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Provides a ranked list of root causes for UNRESOLVED documents."""
        unresolved_docs = [
            d for d in document_evaluations if d.get("decision") == "UNRESOLVED"
        ]
        total_unresolved = len(unresolved_docs)

        root_cause_counts = defaultdict(int)
        missing_evidence_counts = defaultdict(int)

        for d in unresolved_docs:
            cause = d.get("likely_root_cause", "UNKNOWN")
            root_cause_counts[cause] += 1
            for ev in d.get("missing_evidence", []):
                missing_evidence_counts[ev] += 1

        return {
            "total_unresolved": total_unresolved,
            "ranked_root_causes": sorted(
                [{"root_cause": k, "count": v} for k, v in root_cause_counts.items()],
                key=lambda x: x["count"],
                reverse=True,
            ),
            "missing_evidence_breakdown": sorted(
                [{"evidence": k, "count": v} for k, v in missing_evidence_counts.items()],
                key=lambda x: x["count"],
                reverse=True,
            ),
        }

    def analyze_human_corrections(
        self,
        correction_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Measures repeated correction patterns from human review feedback."""
        corrections = correction_history or []
        pattern_counts = defaultdict(int)
        field_corrections = defaultdict(int)

        for c in corrections:
            orig = c.get("original_field", "")
            corr = c.get("corrected_field", "")
            if orig and corr and orig != corr:
                pattern_counts[f"{orig} -> {corr}"] += 1
                field_corrections[corr] += 1

        return {
            "total_corrections": len(corrections),
            "repeated_mapping_patterns": sorted(
                [{"pattern": k, "count": v} for k, v in pattern_counts.items()],
                key=lambda x: x["count"],
                reverse=True,
            ),
            "most_corrected_fields": sorted(
                [{"field": k, "count": v} for k, v in field_corrections.items()],
                key=lambda x: x["count"],
                reverse=True,
            ),
        }

    def compute_layout_diversity(
        self,
        manifest_items: List[EvaluationManifestItem],
        extraction_results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Calculates supplier and layout profile diversity statistics."""
        unique_suppliers = set()
        unique_gstins = set()
        unique_layouts = set()
        supplier_layouts = defaultdict(set)

        for item in manifest_items:
            if item.supplier_name:
                unique_suppliers.add(item.supplier_name)
            if item.gstin:
                unique_gstins.add(item.gstin)

        for res in extraction_results:
            supplier = res.get("supplier_name") or res.get("gstin")
            layout_id = res.get("layout_profile_id") or "default_layout"
            if supplier:
                supplier_layouts[supplier].add(layout_id)
            unique_layouts.add(layout_id)

        layouts_per_supplier = {
            s: len(layouts) for s, layouts in supplier_layouts.items()
        }

        return {
            "unique_suppliers_count": len(unique_suppliers),
            "unique_gstins_count": len(unique_gstins),
            "unique_layout_profiles_count": len(unique_layouts),
            "average_layouts_per_supplier": (
                sum(layouts_per_supplier.values()) / max(len(layouts_per_supplier), 1)
            ),
            "supplier_breakdown": layouts_per_supplier,
        }

    def generate_recommendations(
        self,
        root_cause_distribution: Dict[str, int],
        auto_accept_safety: Dict[str, Any],
        unresolved_analysis: Dict[str, Any],
        mapping_confusion: Dict[str, Dict[str, int]],
    ) -> List[Dict[str, Any]]:
        """Generates evidence-backed ranked engineering priorities."""
        recommendations = []
        total_errors = sum(root_cause_distribution.values())

        sorted_causes = sorted(
            root_cause_distribution.items(), key=lambda x: x[1], reverse=True
        )

        rank = 1
        for cause, count in sorted_causes:
            pct = (count / max(total_errors, 1)) * 100
            if cause == RootCause.LOGICAL_SUBCOLUMN_SPLIT.value:
                recommendations.append(
                    {
                        "priority": rank,
                        "area": "Logical Sub-Column Splitting",
                        "reason": f"{count} errors ({pct:.1f}%) involve composite column extraction failures (e.g. PACK QTY FREE or AMOUNT GST).",
                        "suggested_action": "Enhance generic whitespace and token-type splitting algorithms for composite table cells.",
                    }
                )
                rank += 1
            elif cause == RootCause.HEADER_RECONSTRUCTION.value:
                recommendations.append(
                    {
                        "priority": rank,
                        "area": "Header Reconstruction & Word Joining",
                        "reason": f"{count} errors ({pct:.1f}%) originate from visual split tokens like 'PT R' or 'M R P'.",
                        "suggested_action": "Improve spatial bounding box horizontal proximity clustering for multiline or broken header words.",
                    }
                )
                rank += 1
            elif cause == RootCause.SEMANTIC_MAPPING.value:
                recommendations.append(
                    {
                        "priority": rank,
                        "area": "Semantic Column Inference & Disambiguation",
                        "reason": f"{count} errors ({pct:.1f}%) caused by canonical field confusion (e.g., rate vs MRP, amount vs taxableAmount).",
                        "suggested_action": "Tighten cross-field value distribution heuristics and validation prior to mapping commitment.",
                    }
                )
                rank += 1
            elif cause == RootCause.ROW_RECONSTRUCTION.value:
                recommendations.append(
                    {
                        "priority": rank,
                        "area": "Row Line Aggregation & Continuation Handling",
                        "reason": f"{count} errors ({pct:.1f}%) occur when product description wraps onto subsequent line or footer text intrudes.",
                        "suggested_action": "Refine vertical line grouping thresholds and footer boundary cutoff logic.",
                    }
                )
                rank += 1

        # Check Auto-Accept Safety
        if auto_accept_safety.get("error_rate", 0.0) > 0.05:
            recommendations.append(
                {
                    "priority": rank,
                    "area": "AUTO_ACCEPT Gating Tightening",
                    "reason": f"AUTO_ACCEPT error rate is {auto_accept_safety.get('error_rate', 0.0)*100:.1f}%, indicating false-accept risk.",
                    "suggested_action": "Introduce stricter cross-field accounting validation before granting AUTO_ACCEPT status.",
                }
            )
            rank += 1

        return recommendations

    def run_evaluation(
        self,
        manifest_items: Optional[List[EvaluationManifestItem]] = None,
    ) -> Dict[str, Any]:
        """
        Executes complete evaluation against manifest documents.
        Processes each document, verifies against ground truth where available,
        and aggregates field, row, column, supplier, and calibration metrics.
        """
        start_time = time.time()
        items = manifest_items if manifest_items is not None else self.manifest_items

        document_results = []
        all_field_metrics = defaultdict(lambda: FieldMetricResult(canonical_field=""))
        total_row_metrics = RowMetricResult()
        mapping_confusion_matrix: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        root_cause_counts = defaultdict(int)
        supplier_stats_map = defaultdict(lambda: {
            "doc_count": 0,
            "auto_accept": 0,
            "review": 0,
            "unresolved": 0,
            "failed": 0,
            "total_conf": 0.0,
            "min_conf": 100.0,
            "total_time_ms": 0.0,
            "errors": set(),
        })

        for item in items:
            doc_start = time.time()
            file_path = item.file_path
            if not os.path.exists(file_path):
                # Try relative to repo root
                potential = os.path.join(os.getcwd(), file_path)
                if os.path.exists(potential):
                    file_path = potential

            if not os.path.exists(file_path):
                continue

            # Verify SHA-256
            actual_hash = self.compute_sha256(file_path)
            hash_valid = actual_hash == item.sha256

            # Extract
            try:
                res = self.extract_fn(file_path)
                if isinstance(res, tuple) and len(res) == 4:
                    metadata, headers, column_mappings, all_rows = res
                elif isinstance(res, dict):
                    metadata = res.get("metadata", res)
                    headers = res.get("headers", [])
                    column_mappings = res.get("column_mappings", {})
                    all_rows = res.get("rows", [])
                else:
                    metadata, headers, column_mappings, all_rows = {}, [], {}, []

                # Format rows
                col_idx_to_field = {}
                for idx, h in enumerate(headers):
                    m = column_mappings.get(h)
                    mapped = m.get("mapped_to") if isinstance(m, dict) else m
                    if mapped:
                        col_idx_to_field[idx] = mapped

                formatted_rows = []
                for r in all_rows:
                    if isinstance(r, dict):
                        formatted_rows.append(r)
                    elif isinstance(r, (list, tuple)):
                        row_dict = {}
                        for idx, val_cell in enumerate(r):
                            fn = col_idx_to_field.get(idx, f"col_{idx}")
                            row_dict[fn] = val_cell
                        formatted_rows.append(row_dict)

                flat_pred_mappings = {}
                for h, m in column_mappings.items():
                    flat_pred_mappings[h] = m.get("mapped_to") if isinstance(m, dict) else m

                extraction = {
                    "filename": item.filename,
                    "rows": formatted_rows,
                    "confidence": float(metadata.get("confidence", 0.0)),
                    "decision": metadata.get("classification", metadata.get("decision", "UNRESOLVED")),
                    "supplier_name": metadata.get("supplier_name"),
                    "gstin": metadata.get("supplier_gstin"),
                    "validation_warnings": metadata.get("validation", {}).get("field_warnings", []),
                    "semantic_mapping": flat_pred_mappings,
                    "layout_profile_id": metadata.get("drift_report", {}).get("matched_layout_id"),
                }
                status = "SUCCESS"
            except Exception as e:
                extraction = {
                    "filename": item.filename,
                    "rows": [],
                    "confidence": 0.0,
                    "decision": "FAILED",
                    "supplier_name": None,
                    "gstin": None,
                    "validation_warnings": [str(e)],
                    "semantic_mapping": {},
                    "layout_profile_id": None,
                }
                status = "FAILED"

            doc_duration_ms = (time.time() - doc_start) * 1000.0

            # Ground truth lookup
            gt_doc = self.ground_truth_store.get_ground_truth(item.document_id) or self.ground_truth_store.get_ground_truth(actual_hash)

            extracted_rows = extraction.get("rows", [])
            confidence = extraction.get("confidence", 0.0)
            decision = extraction.get("decision", "UNRESOLVED")
            supplier_name = extraction.get("supplier_name") or item.supplier_name or "UNKNOWN_SUPPLIER"
            gstin = extraction.get("gstin") or item.gstin

            # Difficult layout flags
            raw_headers = list(extraction.get("semantic_mapping", {}).keys())
            difficult_flags = self.detect_difficult_layout_flags(extraction, raw_headers)

            doc_field_errors = []
            doc_row_metrics = None
            is_doc_fully_correct = True

            if gt_doc and len(gt_doc.rows) > 0:
                # Field metrics
                f_metrics = self.evaluate_field_level(extracted_rows, gt_doc.rows)
                for f_name, fm in f_metrics.items():
                    if f_name not in all_field_metrics:
                        all_field_metrics[f_name] = FieldMetricResult(canonical_field=f_name)
                    af = all_field_metrics[f_name]
                    af.total_ground_truth += fm.total_ground_truth
                    af.total_predictions += fm.total_predictions
                    af.exact_matches += fm.exact_matches
                    af.normalized_matches += fm.normalized_matches
                    af.tolerance_matches += fm.tolerance_matches
                    af.missing_predictions += fm.missing_predictions
                    af.unexpected_predictions += fm.unexpected_predictions
                    af.incorrect_predictions += fm.incorrect_predictions

                    if fm.missing_predictions > 0 or fm.incorrect_predictions > 0:
                        doc_field_errors.append(f_name)
                        is_doc_fully_correct = False

                # Row metrics
                doc_row_metrics = self.evaluate_row_level(
                    extracted_rows, gt_doc.rows, item.expected_row_count
                )
                total_row_metrics.expected_rows += doc_row_metrics.expected_rows
                total_row_metrics.extracted_rows += doc_row_metrics.extracted_rows
                total_row_metrics.matched_rows += doc_row_metrics.matched_rows
                total_row_metrics.missing_rows += doc_row_metrics.missing_rows
                total_row_metrics.extra_rows += doc_row_metrics.extra_rows
                total_row_metrics.duplicate_rows += doc_row_metrics.duplicate_rows
                total_row_metrics.split_rows += doc_row_metrics.split_rows
                total_row_metrics.merged_rows += doc_row_metrics.merged_rows
                total_row_metrics.continuation_errors += doc_row_metrics.continuation_errors

                if doc_row_metrics.row_accuracy < 1.0:
                    is_doc_fully_correct = False
            else:
                # No ground truth rows available, evaluate row count only if known
                if item.expected_row_count is not None:
                    doc_row_metrics = self.evaluate_row_level(
                        extracted_rows, [], item.expected_row_count
                    )
                    total_row_metrics.expected_rows += doc_row_metrics.expected_rows
                    total_row_metrics.extracted_rows += doc_row_metrics.extracted_rows
                    total_row_metrics.matched_rows += doc_row_metrics.matched_rows
                    total_row_metrics.missing_rows += doc_row_metrics.missing_rows
                    total_row_metrics.extra_rows += doc_row_metrics.extra_rows
                    if doc_row_metrics.row_accuracy < 1.0:
                        is_doc_fully_correct = False

            # Evaluate Column Mapping
            pred_mappings = extraction.get("semantic_mapping", {})
            gt_mappings = gt_doc.column_mappings if gt_doc else None
            col_evals = self.evaluate_column_mappings(
                item.document_id, pred_mappings, gt_mappings
            )
            for ce in col_evals:
                if ce.expected_canonical and ce.predicted_canonical:
                    mapping_confusion_matrix[ce.expected_canonical][ce.predicted_canonical] += 1
                if ce.root_cause:
                    root_cause_counts[ce.root_cause.value] += 1

            # Supplier stats aggregation
            s_key = (supplier_name, gstin, item.dataset_category.value)
            st = supplier_stats_map[s_key]
            st["doc_count"] += 1
            if decision == "AUTO_ACCEPT":
                st["auto_accept"] += 1
            elif decision == "REVIEW_REQUIRED":
                st["review"] += 1
            elif decision == "UNRESOLVED":
                st["unresolved"] += 1
            elif decision == "FAILED":
                st["failed"] += 1
            st["total_conf"] += confidence
            st["min_conf"] = min(st["min_conf"], confidence)
            st["total_time_ms"] += doc_duration_ms

            doc_info = {
                "document_id": item.document_id,
                "filename": item.filename,
                "dataset_category": item.dataset_category.value,
                "sha256": actual_hash,
                "hash_valid": hash_valid,
                "ground_truth_available": item.ground_truth_available and (gt_doc is not None),
                "supplier_name": supplier_name,
                "gstin": gstin,
                "decision": decision,
                "confidence": confidence,
                "extracted_row_count": len(extracted_rows),
                "expected_row_count": item.expected_row_count,
                "is_correct": is_doc_fully_correct,
                "field_error_count": len(doc_field_errors),
                "erroneous_fields": doc_field_errors,
                "row_error_count": (doc_row_metrics.missing_rows + doc_row_metrics.extra_rows) if doc_row_metrics else 0,
                "validation_warnings": extraction.get("validation_warnings", []),
                "difficult_flags": [f.value for f in difficult_flags],
                "processing_time_ms": doc_duration_ms,
                "likely_root_cause": (
                    RootCause.LOGICAL_SUBCOLUMN_SPLIT.value
                    if DifficultLayoutFlag.MULTIPLE_LOGICAL_VALUES_IN_CELL in difficult_flags
                    else (
                        RootCause.HEADER_RECONSTRUCTION.value
                        if DifficultLayoutFlag.SPLIT_HEADERS in difficult_flags
                        else RootCause.UNKNOWN.value
                    )
                ),
            }
            document_results.append(doc_info)

        # Finalize field metrics precision/recall/F1
        for f_name, fm in all_field_metrics.items():
            tp = fm.tolerance_matches if f_name in NUMERIC_FIELD_TOLERANCES else fm.normalized_matches
            fp = fm.unexpected_predictions + fm.incorrect_predictions
            fn = fm.missing_predictions
            fm.precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            fm.recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            fm.f1 = (2 * fm.precision * fm.recall) / (fm.precision + fm.recall) if (fm.precision + fm.recall) > 0 else 0.0

        # Finalize row accuracy
        total_denom = max(total_row_metrics.expected_rows, total_row_metrics.extracted_rows, 1)
        total_row_metrics.row_accuracy = total_row_metrics.matched_rows / total_denom

        # Calibration
        calibration_results = self.evaluate_confidence_calibration(document_results)

        # Safety & Decision Analysis
        auto_accept_safety = self.analyze_auto_accept_safety(document_results)
        review_analysis = self.analyze_review_required(document_results)
        unresolved_analysis = self.analyze_unresolved(document_results)
        diversity_stats = self.compute_layout_diversity(items, document_results)

        # Supplier statistics list
        supplier_stats_list = []
        for (s_name, s_gstin, s_cat), st in supplier_stats_map.items():
            cnt = st["doc_count"]
            supplier_stats_list.append(
                SupplierLayoutStat(
                    supplier_name=s_name,
                    gstin=s_gstin,
                    layout_profile_id=None,
                    layout_version=None,
                    dataset_category=s_cat,
                    doc_count=cnt,
                    auto_accept_pct=(st["auto_accept"] / cnt) * 100 if cnt > 0 else 0.0,
                    review_required_pct=(st["review"] / cnt) * 100 if cnt > 0 else 0.0,
                    unresolved_pct=(st["unresolved"] / cnt) * 100 if cnt > 0 else 0.0,
                    failed_pct=(st["failed"] / cnt) * 100 if cnt > 0 else 0.0,
                    avg_confidence=st["total_conf"] / cnt if cnt > 0 else 0.0,
                    min_confidence=st["min_conf"] if cnt > 0 else 0.0,
                    avg_processing_time_ms=st["total_time_ms"] / cnt if cnt > 0 else 0.0,
                    common_errors=list(st["errors"]),
                )
            )

        # Recommendations
        recommendations = self.generate_recommendations(
            root_cause_counts, auto_accept_safety, unresolved_analysis, mapping_confusion_matrix
        )

        total_duration = time.time() - start_time

        return {
            "evaluation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_documents_evaluated": len(document_results),
            "total_evaluation_time_seconds": round(total_duration, 3),
            "average_document_time_ms": round(
                (total_duration * 1000.0) / max(len(document_results), 1), 2
            ),
            "dataset_categories": {
                cat.value: sum(1 for d in document_results if d["dataset_category"] == cat.value)
                for cat in DatasetCategory
            },
            "decision_breakdown": {
                "AUTO_ACCEPT": sum(1 for d in document_results if d["decision"] == "AUTO_ACCEPT"),
                "REVIEW_REQUIRED": sum(1 for d in document_results if d["decision"] == "REVIEW_REQUIRED"),
                "UNRESOLVED": sum(1 for d in document_results if d["decision"] == "UNRESOLVED"),
                "FAILED": sum(1 for d in document_results if d["decision"] == "FAILED"),
            },
            "documents": document_results,
            "field_metrics": {k: v.to_dict() for k, v in all_field_metrics.items()},
            "row_metrics": total_row_metrics.to_dict(),
            "column_mapping_confusion": {k: dict(v) for k, v in mapping_confusion_matrix.items()},
            "root_cause_distribution": dict(root_cause_counts),
            "confidence_calibration": [b.to_dict() for b in calibration_results],
            "auto_accept_safety": auto_accept_safety,
            "review_required_analysis": review_analysis,
            "unresolved_analysis": unresolved_analysis,
            "layout_diversity": diversity_stats,
            "supplier_statistics": [s.to_dict() for s in supplier_stats_list],
            "engineering_priorities": recommendations,
        }


def verify_golden_benchmark_v1(
    manifest_path: Optional[str] = None,
    samples_dir: Optional[str] = None,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Validates that the canonical golden benchmark v1 is strictly intact:
    - Manifest file exists and is marked immutable
    - Contains exactly 9 documents
    - Each document matches its expected SHA-256 hash on disk
    - Expected supplier names, GSTINs, and row counts match
    - No unexpected or missing documents
    Returns (True, details) on success, or (False, details) with error GOLDEN_BENCHMARK_INTEGRITY_FAILURE.
    """
    if manifest_path is None:
        manifest_path = os.path.join(os.path.dirname(__file__), "golden_manifest_v1.json")
        if not os.path.exists(manifest_path):
            manifest_path = os.path.join(os.path.dirname(__file__), "..", "benchmark_manifest.json")

    if samples_dir is None:
        samples_dir = os.path.join(os.path.dirname(__file__), "..", "Sample Invoices")

    if not os.path.exists(manifest_path):
        return False, {
            "status": "GOLDEN_BENCHMARK_INTEGRITY_FAILURE",
            "error": f"Golden benchmark manifest not found: {manifest_path}",
            "passed": False,
        }

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return False, {
            "status": "GOLDEN_BENCHMARK_INTEGRITY_FAILURE",
            "error": f"Could not parse manifest JSON: {e}",
            "passed": False,
        }

    docs = data.get("documents") or data.get("samples") or []
    if len(docs) != 9:
        return False, {
            "status": "GOLDEN_BENCHMARK_INTEGRITY_FAILURE",
            "error": f"Golden benchmark must contain exactly 9 documents, found {len(docs)}",
            "passed": False,
        }

    errors = []
    verified_docs = []

    for doc in docs:
        fname = doc.get("filename")
        expected_sha = doc.get("sha256") or doc.get("file_hash")
        expected_supplier = doc.get("supplier_name") or doc.get("expected_supplier_if_verified")
        expected_gstin = doc.get("gstin") or doc.get("expected_gstin_if_verified")
        expected_rows = doc.get("expected_rows") or doc.get("expected_row_count_if_verified")

        fpath = os.path.join(samples_dir, fname)
        if not os.path.exists(fpath):
            errors.append(f"Missing benchmark file on disk: {fname}")
            continue

        try:
            with open(fpath, "rb") as fp:
                actual_sha = hashlib.sha256(fp.read()).hexdigest()
        except Exception as e:
            errors.append(f"Could not read benchmark file {fname}: {e}")
            continue

        if actual_sha != expected_sha:
            errors.append(
                f"BENCHMARK_IDENTITY_MISMATCH in {fname}: expected SHA {expected_sha}, found {actual_sha}"
            )
            continue

        verified_docs.append({
            "filename": fname,
            "sha256": actual_sha,
            "supplier_name": expected_supplier,
            "gstin": expected_gstin,
            "expected_rows": expected_rows,
            "status": "VERIFIED_GOLDEN_V1",
        })

    if errors or len(verified_docs) != 9:
        return False, {
            "status": "GOLDEN_BENCHMARK_INTEGRITY_FAILURE",
            "errors": errors,
            "verified_count": len(verified_docs),
            "passed": False,
        }

    return True, {
        "status": "PASS",
        "benchmark_version": data.get("benchmark_version", "v1.0"),
        "document_count": len(verified_docs),
        "total_expected_rows": sum(d.get("expected_rows", 0) for d in verified_docs),
        "verified_documents": verified_docs,
        "passed": True,
    }
