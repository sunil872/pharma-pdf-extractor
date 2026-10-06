"""
MediAstra Pharma PDF Import Engine - Canonical Field-Level Extraction Accuracy & Error Attribution
Calculates normalization-aware field metrics, high-risk error detection, row classification,
accounting validation, and AUTO_ACCEPT safety analysis.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from evaluation.field_ground_truth import (
    CANONICAL_FIELDS,
    CRITICAL_FIELDS,
    FINANCIAL_FIELDS,
    AccountingStatus,
    AutoAcceptSafety,
    FieldGroundTruthCell,
    FieldGroundTruthDocument,
    FieldGroundTruthRow,
    FieldGroundTruthStore,
    FieldPresenceState,
    RowClassification,
)
from evaluation.models import (
    NUMERIC_FIELD_TOLERANCES,
    ConfidenceBucketResult,
    FieldMetricResult,
    RootCause,
)


# Comparison match types
class MatchType(str, Enum):
    EXACT = "EXACT"
    NORMALIZED = "NORMALIZED"
    TOLERANCE = "TOLERANCE"
    MISMATCH = "MISMATCH"
    MISSING = "MISSING"
    UNEXPECTED = "UNEXPECTED"
    IGNORED = "IGNORED"  # for UNKNOWN, NOT_PRESENT, NOT_APPLICABLE, AMBIGUOUS


def normalize_text(text: Optional[str]) -> str:
    """Normalizes string for comparison (removes redundant spacing, case-insensitive, strips trailing hyphens)."""
    if text is None:
        return ""
    t = str(text).strip().upper()
    t = re.sub(r"\s+", " ", t)
    # Remove trailing non-alphanumeric noise like '--9%', '--12%' etc. if extracted as part of product name
    t = re.sub(r"--\d+%$", "", t).strip()
    return t


def normalize_date(date_str: Optional[str]) -> Optional[str]:
    """Normalizes expiry date formats like '12/27', '12-27', '08-2027', '8/27' to 'MM/YY'."""
    if date_str is None:
        return None
    s = str(date_str).strip()
    # Remove spacing inside date strings like '0 8 - 2 6'
    s = re.sub(r"\s+", "", s)
    # Match patterns like M/YY, MM/YY, MM-YY, MM/YYYY
    m = re.match(r"^(\d{1,2})[/\-\.](\d{2,4})$", s)
    if m:
        month = int(m.group(1))
        year = int(m.group(2))
        if year > 2000:
            year = year % 100
        return f"{month:02d}/{year:02d}"
    return s.upper()


def parse_numeric(val: Any) -> Optional[float]:
    """Extracts a clean float from string or number."""
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "")
    # Clean leading/trailing currency symbols or percent
    s = re.sub(r"^[^\d\.\-+]+", "", s)
    s = re.sub(r"[^\d\.]+$", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def compare_text_field(gt_val: Any, pred_val: Any) -> MatchType:
    """Compares text fields with exact and normalized matching."""
    if gt_val is None and (pred_val is None or pred_val == ""):
        return MatchType.EXACT
    if gt_val is None:
        return MatchType.UNEXPECTED
    if pred_val is None or pred_val == "":
        return MatchType.MISSING

    gt_str = str(gt_val).strip()
    pred_str = str(pred_val).strip()

    if gt_str == pred_str:
        return MatchType.EXACT

    gt_norm = normalize_text(gt_str)
    pred_norm = normalize_text(pred_str)

    if gt_norm == pred_norm:
        return MatchType.NORMALIZED

    # Substring / fuzzy containment for long medicine descriptions
    if len(gt_norm) > 5 and len(pred_norm) > 5:
        if gt_norm in pred_norm or pred_norm in gt_norm:
            return MatchType.NORMALIZED

    return MatchType.MISMATCH


def compare_numeric_field(gt_val: Any, pred_val: Any, field_name: str = "amount") -> MatchType:
    """Compares numeric fields with centralized tolerances."""
    if gt_val is None and (pred_val is None or pred_val == ""):
        return MatchType.EXACT
    if gt_val is None:
        return MatchType.UNEXPECTED
    if pred_val is None or pred_val == "":
        return MatchType.MISSING

    gt_num = parse_numeric(gt_val)
    pred_num = parse_numeric(pred_val)

    if gt_num is None or pred_num is None:
        return MatchType.MISMATCH

    if gt_num == pred_num:
        return MatchType.EXACT

    tol_cfg = NUMERIC_FIELD_TOLERANCES.get(field_name, {"abs_tol": 0.05, "rel_tol": 0.005})
    abs_tol = tol_cfg.get("abs_tol", 0.05)
    rel_tol = tol_cfg.get("rel_tol", 0.005)

    diff = abs(gt_num - pred_num)
    if diff <= abs_tol:
        return MatchType.TOLERANCE

    if gt_num != 0 and (diff / abs(gt_num)) <= rel_tol:
        return MatchType.TOLERANCE

    return MatchType.MISMATCH


def compare_date_field(gt_val: Any, pred_val: Any) -> MatchType:
    """Compares date fields (e.g. expiryDate) with format normalization."""
    if gt_val is None and (pred_val is None or pred_val == ""):
        return MatchType.EXACT
    if gt_val is None:
        return MatchType.UNEXPECTED
    if pred_val is None or pred_val == "":
        return MatchType.MISSING

    gt_str = str(gt_val).strip()
    pred_str = str(pred_val).strip()

    if gt_str == pred_str:
        return MatchType.EXACT

    gt_d = normalize_date(gt_str)
    pred_d = normalize_date(pred_str)

    if gt_d and pred_d and gt_d == pred_d:
        return MatchType.NORMALIZED

    return MatchType.MISMATCH


def compare_percentage_field(gt_val: Any, pred_val: Any, field_name: str = "gstPercent") -> MatchType:
    """Compares percentage fields (GST, discount) with tolerance."""
    return compare_numeric_field(gt_val, pred_val, field_name=field_name)


def compare_integer_field(gt_val: Any, pred_val: Any) -> MatchType:
    """Compares integer-like fields (quantity, freeQuantity)."""
    return compare_numeric_field(gt_val, pred_val, field_name="quantity")


def compare_field_value(field_name: str, gt_cell: Optional[FieldGroundTruthCell], pred_val: Any) -> Tuple[MatchType, Optional[str]]:
    """
    Compares extracted prediction against ground truth cell, respecting presence state.
    Returns (MatchType, reason_if_mismatch).
    """
    if gt_cell is None or gt_cell.state in (FieldPresenceState.UNKNOWN, FieldPresenceState.NOT_PRESENT, FieldPresenceState.NOT_APPLICABLE):
        # Ground truth is not present or unknown; do not penalize as extraction error
        return MatchType.IGNORED, None

    if gt_cell.state == FieldPresenceState.AMBIGUOUS:
        return MatchType.IGNORED, "AMBIGUOUS_GROUND_TRUTH"

    gt_val = gt_cell.value

    if field_name == "itemName":
        m_type = compare_text_field(gt_val, pred_val)
    elif field_name == "expiryDate":
        m_type = compare_date_field(gt_val, pred_val)
    elif field_name in ("quantity", "freeQuantity"):
        m_type = compare_integer_field(gt_val, pred_val)
    elif field_name in ("gstPercent", "cgstPercent", "sgstPercent", "discountPercent"):
        m_type = compare_percentage_field(gt_val, pred_val, field_name)
    elif field_name in ("rate", "mrp", "amount", "taxableAmount", "netAmount"):
        m_type = compare_numeric_field(gt_val, pred_val, field_name)
    elif field_name in ("pack", "batchNo", "hsnCode", "company"):
        m_type = compare_text_field(gt_val, pred_val)
    else:
        m_type = compare_text_field(gt_val, pred_val)

    reason = None
    if m_type == MatchType.MISMATCH:
        reason = f"Expected {repr(gt_val)}, got {repr(pred_val)}"
    elif m_type == MatchType.MISSING:
        reason = f"Expected {repr(gt_val)}, but field was missing"
    elif m_type == MatchType.UNEXPECTED:
        reason = f"Field extracted as {repr(pred_val)} but ground truth cell has no value"

    return m_type, reason


# =========================================================================
# High-Risk Error Detectors
# =========================================================================

def detect_quantity_free_swap(pred_dict: Dict[str, Any], gt_row: FieldGroundTruthRow) -> Optional[str]:
    """Detects if quantity and freeQuantity were swapped."""
    gt_q = gt_row.get_cell("quantity")
    gt_f = gt_row.get_cell("freeQuantity")
    if not gt_q or not gt_f or gt_q.value is None or gt_f.value is None:
        return None
    pq = parse_numeric(pred_dict.get("quantity"))
    pf = parse_numeric(pred_dict.get("freeQuantity"))
    if pq is not None and pf is not None:
        if math.isclose(pq, float(gt_f.value), abs_tol=0.01) and math.isclose(pf, float(gt_q.value), abs_tol=0.01) and gt_q.value != gt_f.value:
            return f"Quantity ({pq}) and FreeQuantity ({pf}) swapped with expected ({gt_q.value}, {gt_f.value})"
    return None


def detect_rate_mrp_swap(pred_dict: Dict[str, Any], gt_row: FieldGroundTruthRow) -> Optional[str]:
    """Detects if rate and MRP were swapped."""
    gt_r = gt_row.get_cell("rate")
    gt_m = gt_row.get_cell("mrp")
    if not gt_r or not gt_m or gt_r.value is None or gt_m.value is None:
        return None
    pr = parse_numeric(pred_dict.get("rate"))
    pm = parse_numeric(pred_dict.get("mrp"))
    if pr is not None and pm is not None:
        if math.isclose(pr, float(gt_m.value), abs_tol=0.05) and math.isclose(pm, float(gt_r.value), abs_tol=0.05) and gt_r.value != gt_m.value:
            return f"Rate ({pr}) and MRP ({pm}) swapped with expected ({gt_r.value}, {gt_m.value})"
    return None


def detect_batch_expiry_swap(pred_dict: Dict[str, Any], gt_row: FieldGroundTruthRow) -> Optional[str]:
    """Detects if batch number and expiry date were swapped."""
    gt_b = gt_row.get_cell("batchNo")
    gt_e = gt_row.get_cell("expiryDate")
    if not gt_b or not gt_e or not gt_b.value or not gt_e.value:
        return None
    pb = str(pred_dict.get("batchNo", "")).strip()
    pe = str(pred_dict.get("expiryDate", "")).strip()
    if normalize_date(pb) == normalize_date(str(gt_e.value)) and normalize_text(pe) == normalize_text(str(gt_b.value)):
        return f"Batch ({pb}) and Expiry ({pe}) swapped"
    return None


def detect_expiry_hsn_swap(pred_dict: Dict[str, Any], gt_row: FieldGroundTruthRow) -> Optional[str]:
    """Detects if expiry date and HSN code were swapped."""
    gt_e = gt_row.get_cell("expiryDate")
    gt_h = gt_row.get_cell("hsnCode")
    if not gt_e or not gt_h or not gt_e.value or not gt_h.value:
        return None
    pe = str(pred_dict.get("expiryDate", "")).strip()
    ph = str(pred_dict.get("hsnCode", "")).strip()
    if normalize_date(ph) == normalize_date(str(gt_e.value)):
        return f"Expiry ({pe}) and HSN ({ph}) swapped"
    return None


def detect_amount_gst_swap(pred_dict: Dict[str, Any], gt_row: FieldGroundTruthRow) -> Optional[str]:
    """Detects if row amount and GST percentage/amount were confused."""
    gt_a = gt_row.get_cell("amount")
    gt_g = gt_row.get_cell("gstPercent")
    if not gt_a or not gt_a.value:
        return None
    pa = parse_numeric(pred_dict.get("amount"))
    pg = parse_numeric(pred_dict.get("gstPercent"))
    if pa is not None and gt_g and gt_g.value is not None:
        if math.isclose(pa, float(gt_g.value), abs_tol=0.05) and not math.isclose(pa, float(gt_a.value), abs_tol=0.05):
            return f"Amount predicted as {pa} which matches GST rate {gt_g.value}"
    return None


def detect_compound_quantity_collapsed(pred_dict: Dict[str, Any], raw_text: Optional[str]) -> Optional[str]:
    """Detects if compound quantity (e.g. 23+2) was collapsed or free quantity lost."""
    if not raw_text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*\+\s*(\d+(?:\.\d+)?)", raw_text)
    if m:
        main_q = float(m.group(1))
        free_q = float(m.group(2))
        extracted_q = parse_numeric(pred_dict.get("quantity"))
        extracted_f = parse_numeric(pred_dict.get("freeQuantity"))
        if extracted_q == main_q and (extracted_f is None or extracted_f == 0):
            return f"Compound quantity '{m.group(0)}' collapsed: free quantity {free_q} was lost"
    return None


# =========================================================================
# Accounting Validation
# =========================================================================

def validate_row_accounting(row_dict: Dict[str, Any]) -> Tuple[AccountingStatus, Optional[str]]:
    """
    Independently validates arithmetic relationships for a row:
    quantity * rate ≈ amount, amount - discount + GST ≈ netAmount.
    Supports gross, discounted, and net accounting models.
    """
    qty = parse_numeric(row_dict.get("quantity"))
    rate = parse_numeric(row_dict.get("rate"))
    amt = parse_numeric(row_dict.get("amount"))
    disc = parse_numeric(row_dict.get("discountPercent")) or 0.0
    gst = parse_numeric(row_dict.get("gstPercent")) or 0.0
    net = parse_numeric(row_dict.get("netAmount"))

    if qty is None or rate is None:
        return AccountingStatus.INSUFFICIENT_DATA, "Missing quantity or rate"

    expected_gross = qty * rate

    # Check 1: Simple Amount = Qty * Rate
    if amt is not None:
        if math.isclose(amt, expected_gross, abs_tol=0.20, rel_tol=0.01):
            return AccountingStatus.ACCOUNTING_CONSISTENT, "Amount matches Qty * Rate exactly"

        # Check 2: Amount is discounted Amount = (Qty * Rate) * (1 - Disc/100)
        expected_disc_amt = expected_gross * (1.0 - disc / 100.0)
        if math.isclose(amt, expected_disc_amt, abs_tol=0.20, rel_tol=0.01):
            return AccountingStatus.ACCOUNTING_CONSISTENT, "Amount matches discounted Qty * Rate"

        # Check 3: Amount is Net Amount with GST
        expected_taxable = expected_disc_amt
        expected_net = expected_taxable * (1.0 + gst / 100.0)
        if math.isclose(amt, expected_net, abs_tol=0.20, rel_tol=0.01):
            return AccountingStatus.ACCOUNTING_CONSISTENT, "Amount matches tax-inclusive net"

        return AccountingStatus.ACCOUNTING_INCONSISTENT, f"Amount {amt} != Qty*Rate {expected_gross:.2f}"

    if net is not None:
        expected_disc_amt = expected_gross * (1.0 - disc / 100.0)
        expected_net = expected_disc_amt * (1.0 + gst / 100.0)
        if math.isclose(net, expected_net, abs_tol=0.25, rel_tol=0.01):
            return AccountingStatus.ACCOUNTING_CONSISTENT, "Net amount matches computed formula"
        return AccountingStatus.ACCOUNTING_INCONSISTENT, f"Net {net} != computed {expected_net:.2f}"

    return AccountingStatus.INSUFFICIENT_DATA, "Insufficient financial fields to verify"


# =========================================================================
# Row Evaluation & Classification
# =========================================================================

@dataclass
class RowEvaluationResult:
    row_index: int
    classification: RowClassification
    field_results: Dict[str, MatchType]
    known_field_count: int
    correct_field_count: int
    critical_errors: List[str]
    detected_high_risk_errors: List[str]
    accounting_status: AccountingStatus
    accounting_note: Optional[str] = None
    root_cause: Optional[RootCause] = None


def evaluate_extracted_row(
    pred_dict: Dict[str, Any],
    gt_row: Optional[FieldGroundTruthRow],
    raw_row_text: Optional[str] = None,
) -> RowEvaluationResult:
    """Evaluates a single extracted row against ground truth."""
    if gt_row is None:
        return RowEvaluationResult(
            row_index=-1,
            classification=RowClassification.EXTRA_ROW,
            field_results={},
            known_field_count=0,
            correct_field_count=0,
            critical_errors=[],
            detected_high_risk_errors=["Extra row extracted that is not present in ground truth"],
            accounting_status=AccountingStatus.INSUFFICIENT_DATA,
            root_cause=RootCause.ROW_RECONSTRUCTION,
        )

    field_results: Dict[str, MatchType] = {}
    known_count = 0
    correct_count = 0
    critical_errors = []
    detected_errors = []

    # High risk error detection
    swap_qf = detect_quantity_free_swap(pred_dict, gt_row)
    if swap_qf: detected_errors.append(swap_qf)

    swap_rm = detect_rate_mrp_swap(pred_dict, gt_row)
    if swap_rm: detected_errors.append(swap_rm)

    swap_be = detect_batch_expiry_swap(pred_dict, gt_row)
    if swap_be: detected_errors.append(swap_be)

    swap_eh = detect_expiry_hsn_swap(pred_dict, gt_row)
    if swap_eh: detected_errors.append(swap_eh)

    swap_ag = detect_amount_gst_swap(pred_dict, gt_row)
    if swap_ag: detected_errors.append(swap_ag)

    compound_q = detect_compound_quantity_collapsed(pred_dict, raw_row_text or gt_row.raw_row_text)
    if compound_q: detected_errors.append(compound_q)

    # Field-by-field evaluation
    for field_name in CANONICAL_FIELDS:
        gt_cell = gt_row.get_cell(field_name)
        pred_val = pred_dict.get(field_name)

        if gt_cell is not None and gt_cell.state == FieldPresenceState.KNOWN:
            known_count += 1
            m_type, reason = compare_field_value(field_name, gt_cell, pred_val)
            field_results[field_name] = m_type

            if m_type in (MatchType.EXACT, MatchType.NORMALIZED, MatchType.TOLERANCE):
                correct_count += 1
            else:
                if field_name in CRITICAL_FIELDS:
                    critical_errors.append(f"{field_name}: {reason}")
        else:
            field_results[field_name] = MatchType.IGNORED

    # Accounting check
    acc_status, acc_note = validate_row_accounting(pred_dict)

    # Classification
    if critical_errors:
        classification = RowClassification.CRITICAL_FIELD_ERROR
        root_cause = RootCause.SEMANTIC_MAPPING if any("swap" in e.lower() for e in detected_errors) else RootCause.LOGICAL_SUBCOLUMN_SPLIT
    elif correct_count == known_count and known_count > 0:
        classification = RowClassification.FULLY_CORRECT
        root_cause = None
    elif correct_count > 0:
        classification = RowClassification.PARTIALLY_CORRECT
        root_cause = RootCause.VALUE_NORMALIZATION
    else:
        classification = RowClassification.CRITICAL_FIELD_ERROR
        root_cause = RootCause.COLUMN_BOUNDARY

    return RowEvaluationResult(
        row_index=gt_row.row_index,
        classification=classification,
        field_results=field_results,
        known_field_count=known_count,
        correct_field_count=correct_count,
        critical_errors=critical_errors,
        detected_high_risk_errors=detected_errors,
        accounting_status=acc_status,
        accounting_note=acc_note,
        root_cause=root_cause,
    )


# =========================================================================
# Full Document & Benchmark Field Accuracy Evaluator
# =========================================================================

@dataclass
class DocumentFieldAccuracyReport:
    document_id: str
    filename: str
    supplier_name: str
    gstin: str
    expected_rows: int
    extracted_rows: int
    known_field_cells: int = 0
    correct_field_cells: int = 0
    incorrect_field_cells: int = 0
    missing_field_cells: int = 0
    overall_field_accuracy: float = 0.0
    critical_field_accuracy: float = 0.0
    financial_field_accuracy: float = 0.0
    accounting_status: AccountingStatus = AccountingStatus.INSUFFICIENT_DATA
    auto_accept_safety: AutoAcceptSafety = AutoAcceptSafety.INSUFFICIENT_GROUND_TRUTH
    decision: str = "REVIEW_REQUIRED"
    confidence: float = 0.0
    row_evaluations: List[RowEvaluationResult] = field(default_factory=list)
    field_metrics: Dict[str, FieldMetricResult] = field(default_factory=dict)
    detected_errors: List[str] = field(default_factory=list)


@dataclass
class BenchmarkFieldAccuracySummary:
    total_documents: int = 9
    total_expected_rows: int = 148
    total_clean_rows: int = 147
    total_extracted_rows: int = 0
    total_known_cells: int = 0
    total_correct_cells: int = 0
    overall_field_accuracy: float = 0.0
    overall_critical_field_accuracy: float = 0.0
    overall_financial_field_accuracy: float = 0.0
    fully_correct_rows: int = 0
    partially_correct_rows: int = 0
    critical_error_rows: int = 0
    missing_rows: int = 0
    extra_rows: int = 0
    document_reports: List[DocumentFieldAccuracyReport] = field(default_factory=list)
    per_field_metrics: Dict[str, FieldMetricResult] = field(default_factory=dict)
    confidence_buckets: List[ConfidenceBucketResult] = field(default_factory=list)
    root_cause_distribution: Dict[str, int] = field(default_factory=dict)
    high_risk_errors: List[Dict[str, Any]] = field(default_factory=list)


def evaluate_canonical_field_accuracy(
    sample_dir: str = "Sample Invoices",
    manifest_path: Optional[str] = None,
) -> BenchmarkFieldAccuracySummary:
    """
    Runs the full field-level accuracy evaluation over the canonical 9-PDF golden benchmark.
    Verifies golden benchmark integrity before executing.
    """
    import os
    import json
    from evaluation.evaluator import verify_golden_benchmark_v1
    from extractor import extract_pdf_table, _mapping_field, compute_row_accounting

    # Step 1: Verify Golden Benchmark Integrity
    is_valid, integrity = verify_golden_benchmark_v1(manifest_path=manifest_path, samples_dir=sample_dir)
    if not is_valid:
        raise ValueError(f"GOLDEN_BENCHMARK_INTEGRITY_FAILURE: {integrity.get('error') or integrity.get('errors')}")

    gt_store = FieldGroundTruthStore()
    golden_manifest_path = manifest_path or "evaluation/golden_manifest_v1.json"
    with open(golden_manifest_path, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    doc_reports: List[DocumentFieldAccuracyReport] = []
    field_counts: Dict[str, Dict[str, int]] = {
        f: {"gt": 0, "pred": 0, "exact": 0, "norm": 0, "tol": 0, "missing": 0, "unexpected": 0, "mismatch": 0}
        for f in CANONICAL_FIELDS
    }
    root_cause_counts: Dict[str, int] = {rc.value: 0 for rc in RootCause}
    all_high_risk_errors: List[Dict[str, Any]] = []

    total_known = 0
    total_correct = 0
    total_critical_known = 0
    total_critical_correct = 0
    total_financial_known = 0
    total_financial_correct = 0

    total_extracted_rows = 0
    fully_correct_rows = 0
    partially_correct_rows = 0
    critical_error_rows = 0
    missing_rows = 0
    extra_rows = 0

    # Process each canonical document
    for doc_meta in manifest_data["documents"]:
        fname = doc_meta["filename"]
        fpath = os.path.join(sample_dir, fname)

        gt_doc = gt_store.get_document(fname)
        if not gt_doc:
            continue

        # Run extraction
        meta, hdrs, maps, rows = extract_pdf_table(fpath)
        extracted_row_count = len(rows)
        total_extracted_rows += extracted_row_count
        doc_conf = meta.get("confidence", 0.0)
        doc_dec = meta.get("classification", "REVIEW_REQUIRED")
        doc_supp = meta.get("supplier_name", doc_meta["supplier_name"])
        doc_gstin = meta.get("supplier_gstin", doc_meta["gstin"])

        doc_known = 0
        doc_correct = 0
        doc_incorrect = 0
        doc_missing = 0
        doc_crit_known = 0
        doc_crit_correct = 0
        doc_fin_known = 0
        doc_fin_correct = 0

        row_evals: List[RowEvaluationResult] = []
        doc_detected_errors: List[str] = []

        # Evaluate rows
        for r_idx in range(max(len(gt_doc.rows), extracted_row_count)):
            gt_row = gt_doc.get_row(r_idx) if r_idx < len(gt_doc.rows) else None

            if r_idx < extracted_row_count:
                # Build row dictionary from extraction
                r_cells = rows[r_idx]
                r_dict = {}
                for h_idx, h in enumerate(hdrs):
                    fld = _mapping_field(maps, h)
                    if fld and h_idx < len(r_cells):
                        r_dict[fld] = r_cells[h_idx]
                acc_row = compute_row_accounting(r_dict)
                raw_text = " ".join(str(c) for c in r_cells if c)

                eval_res = evaluate_extracted_row(acc_row, gt_row, raw_row_text=raw_text)
                row_evals.append(eval_res)

                if eval_res.classification == RowClassification.FULLY_CORRECT:
                    fully_correct_rows += 1
                elif eval_res.classification == RowClassification.PARTIALLY_CORRECT:
                    partially_correct_rows += 1
                elif eval_res.classification == RowClassification.CRITICAL_FIELD_ERROR:
                    critical_error_rows += 1
                elif eval_res.classification == RowClassification.EXTRA_ROW:
                    extra_rows += 1

                if eval_res.root_cause:
                    root_cause_counts[eval_res.root_cause.value] += 1

                for err in eval_res.detected_high_risk_errors:
                    doc_detected_errors.append(err)
                    all_high_risk_errors.append({
                        "document": fname,
                        "row": r_idx + 1,
                        "error": err,
                        "root_cause": eval_res.root_cause.value if eval_res.root_cause else "UNKNOWN",
                    })

                # Field metrics accumulation
                if gt_row:
                    for fld in CANONICAL_FIELDS:
                        gt_c = gt_row.get_cell(fld)
                        if gt_c and gt_c.state == FieldPresenceState.KNOWN:
                            doc_known += 1
                            total_known += 1
                            field_counts[fld]["gt"] += 1
                            m_type = eval_res.field_results.get(fld, MatchType.MISMATCH)

                            if fld in CRITICAL_FIELDS:
                                doc_crit_known += 1
                                total_critical_known += 1
                            if fld in FINANCIAL_FIELDS:
                                doc_fin_known += 1
                                total_financial_known += 1

                            if m_type == MatchType.EXACT:
                                doc_correct += 1
                                total_correct += 1
                                field_counts[fld]["exact"] += 1
                                field_counts[fld]["pred"] += 1
                                if fld in CRITICAL_FIELDS:
                                    doc_crit_correct += 1
                                    total_critical_correct += 1
                                if fld in FINANCIAL_FIELDS:
                                    doc_fin_correct += 1
                                    total_financial_correct += 1
                            elif m_type == MatchType.NORMALIZED:
                                doc_correct += 1
                                total_correct += 1
                                field_counts[fld]["norm"] += 1
                                field_counts[fld]["pred"] += 1
                                if fld in CRITICAL_FIELDS:
                                    doc_crit_correct += 1
                                    total_critical_correct += 1
                                if fld in FINANCIAL_FIELDS:
                                    doc_fin_correct += 1
                                    total_financial_correct += 1
                            elif m_type == MatchType.TOLERANCE:
                                doc_correct += 1
                                total_correct += 1
                                field_counts[fld]["tol"] += 1
                                field_counts[fld]["pred"] += 1
                                if fld in CRITICAL_FIELDS:
                                    doc_crit_correct += 1
                                    total_critical_correct += 1
                                if fld in FINANCIAL_FIELDS:
                                    doc_fin_correct += 1
                                    total_financial_correct += 1
                            elif m_type == MatchType.MISSING:
                                doc_missing += 1
                                field_counts[fld]["missing"] += 1
                            else:
                                doc_incorrect += 1
                                field_counts[fld]["mismatch"] += 1
                                field_counts[fld]["pred"] += 1
            else:
                # Row missing from prediction
                missing_rows += 1
                if gt_row:
                    for fld in CANONICAL_FIELDS:
                        gt_c = gt_row.get_cell(fld)
                        if gt_c and gt_c.state == FieldPresenceState.KNOWN:
                            doc_known += 1
                            total_known += 1
                            doc_missing += 1
                            field_counts[fld]["gt"] += 1
                            field_counts[fld]["missing"] += 1
                            if fld in CRITICAL_FIELDS:
                                doc_crit_known += 1
                                total_critical_known += 1
                            if fld in FINANCIAL_FIELDS:
                                doc_fin_known += 1
                                total_financial_known += 1

        overall_acc = (doc_correct / doc_known * 100.0) if doc_known > 0 else 0.0
        crit_acc = (doc_crit_correct / doc_crit_known * 100.0) if doc_crit_known > 0 else 0.0
        fin_acc = (doc_fin_correct / doc_fin_known * 100.0) if doc_fin_known > 0 else 0.0

        # Document Accounting Status
        consistent_rows = sum(1 for r in row_evals if r.accounting_status == AccountingStatus.ACCOUNTING_CONSISTENT)
        if len(row_evals) > 0 and (consistent_rows / len(row_evals)) >= 0.70:
            doc_acc_status = AccountingStatus.ACCOUNTING_CONSISTENT
        elif len(row_evals) > 0 and consistent_rows == 0:
            doc_acc_status = AccountingStatus.ACCOUNTING_INCONSISTENT
        else:
            doc_acc_status = AccountingStatus.AMBIGUOUS_ACCOUNTING

        # AUTO_ACCEPT Safety Assessment
        if doc_dec == "AUTO_ACCEPT":
            if doc_conf >= 90.0 and crit_acc >= 95.0 and fin_acc >= 85.0:
                safety = AutoAcceptSafety.AUTO_ACCEPT_SAFE
            else:
                safety = AutoAcceptSafety.AUTO_ACCEPT_UNSAFE
        else:
            safety = AutoAcceptSafety.INSUFFICIENT_GROUND_TRUTH

        doc_report = DocumentFieldAccuracyReport(
            document_id=gt_doc.document_id,
            filename=fname,
            supplier_name=doc_supp,
            gstin=doc_gstin,
            expected_rows=gt_doc.expected_rows,
            extracted_rows=extracted_row_count,
            known_field_cells=doc_known,
            correct_field_cells=doc_correct,
            incorrect_field_cells=doc_incorrect,
            missing_field_cells=doc_missing,
            overall_field_accuracy=round(overall_acc, 2),
            critical_field_accuracy=round(crit_acc, 2),
            financial_field_accuracy=round(fin_acc, 2),
            accounting_status=doc_acc_status,
            auto_accept_safety=safety,
            decision=doc_dec,
            confidence=round(doc_conf, 2),
            row_evaluations=row_evals,
            detected_errors=doc_detected_errors,
        )
        doc_reports.append(doc_report)

    # Compute Per-Field Metrics (Precision, Recall, F1)
    per_field_metrics: Dict[str, FieldMetricResult] = {}
    for fld in CANONICAL_FIELDS:
        fc = field_counts[fld]
        n_corr = fc["exact"] + fc["norm"] + fc["tol"]
        n_gt = fc["gt"]
        n_pred = fc["pred"]
        precision = (n_corr / n_pred) if n_pred > 0 else 0.0
        recall = (n_corr / n_gt) if n_gt > 0 else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        per_field_metrics[fld] = FieldMetricResult(
            canonical_field=fld,
            total_ground_truth=n_gt,
            total_predictions=n_pred,
            exact_matches=fc["exact"],
            normalized_matches=fc["norm"],
            tolerance_matches=fc["tol"],
            missing_predictions=fc["missing"],
            unexpected_predictions=fc["unexpected"],
            incorrect_predictions=fc["mismatch"],
            precision=precision,
            recall=recall,
            f1=f1,
        )

    # Compute Confidence Buckets
    bucket_ranges = [
        ("0–50", 0.0, 50.0),
        ("50–60", 50.0, 60.0),
        ("60–70", 60.0, 70.0),
        ("70–80", 70.0, 80.0),
        ("80–90", 80.0, 90.0),
        ("90–95", 90.0, 95.0),
        ("95–100", 95.0, 100.0),
    ]
    buckets: List[ConfidenceBucketResult] = []
    for b_name, b_min, b_max in bucket_ranges:
        matching_docs = [
            d for d in doc_reports
            if (b_min <= d.confidence <= b_max if b_max == 100.0 else b_min <= d.confidence < b_max)
        ]
        b_doc_count = len(matching_docs)
        b_auto = sum(1 for d in matching_docs if d.decision == "AUTO_ACCEPT")
        b_rev = sum(1 for d in matching_docs if d.decision == "REVIEW_REQUIRED")
        b_unres = sum(1 for d in matching_docs if d.decision == "UNRESOLVED")

        b_known = sum(d.known_field_cells for d in matching_docs)
        b_correct = sum(d.correct_field_cells for d in matching_docs)
        b_acc = (b_correct / b_known) if b_known > 0 else 0.0

        buckets.append(ConfidenceBucketResult(
            bucket_name=b_name,
            min_conf=b_min,
            max_conf=b_max,
            total_documents=b_doc_count,
            sample_count=b_known,
            correct_documents=b_correct,
            incorrect_documents=b_known - b_correct,
            unknown_count=0,
            review_required_count=b_rev,
            unresolved_count=b_unres,
            empirical_accuracy=b_acc,
        ))

    overall_field_acc = (total_correct / total_known * 100.0) if total_known > 0 else 0.0
    overall_crit_acc = (total_critical_correct / total_critical_known * 100.0) if total_critical_known > 0 else 0.0
    overall_fin_acc = (total_financial_correct / total_financial_known * 100.0) if total_financial_known > 0 else 0.0

    return BenchmarkFieldAccuracySummary(
        total_documents=len(manifest_data["documents"]),
        total_expected_rows=manifest_data.get("total_expected_rows", 148),
        total_clean_rows=147,
        total_extracted_rows=total_extracted_rows,
        total_known_cells=total_known,
        total_correct_cells=total_correct,
        overall_field_accuracy=round(overall_field_acc, 2),
        overall_critical_field_accuracy=round(overall_crit_acc, 2),
        overall_financial_field_accuracy=round(overall_fin_acc, 2),
        fully_correct_rows=fully_correct_rows,
        partially_correct_rows=partially_correct_rows,
        critical_error_rows=critical_error_rows,
        missing_rows=missing_rows,
        extra_rows=extra_rows,
        document_reports=doc_reports,
        per_field_metrics=per_field_metrics,
        confidence_buckets=buckets,
        root_cause_distribution={k: v for k, v in root_cause_counts.items() if v > 0},
        high_risk_errors=all_high_risk_errors,
    )

