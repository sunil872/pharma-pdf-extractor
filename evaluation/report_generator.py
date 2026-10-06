"""
MediAstra Pharma PDF Import Engine - Evaluation Report Generator
Produces machine-readable JSON and human-readable Markdown evaluation reports.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List


class EvaluationReportGenerator:
    """Generates evaluation_results.json and evaluation_report.md."""

    def __init__(self, base_eval_dir: Optional[str] = None):
        self.base_eval_dir = base_eval_dir or os.path.join(
            os.path.dirname(__file__)
        )
        self.results_dir = os.path.join(self.base_eval_dir, "results")
        self.reports_dir = os.path.join(self.base_eval_dir, "reports")
        os.makedirs(self.results_dir, exist_ok=True)
        os.makedirs(self.reports_dir, exist_ok=True)

    def save_json_results(
        self, evaluation_data: Dict[str, Any], filename: str = "evaluation_results.json"
    ) -> str:
        out_path = os.path.join(self.results_dir, filename)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(evaluation_data, f, indent=2)
        return out_path

    def generate_markdown_report(
        self, evaluation_data: Dict[str, Any], filename: str = "evaluation_report.md"
    ) -> str:
        out_path = os.path.join(self.reports_dir, filename)

        md: List[str] = []
        md.append("# MediAstra Pharma PDF Extractor — Real-World Evaluation & Error Analysis Report\n")
        md.append(f"**Generated at**: `{evaluation_data.get('evaluation_timestamp', 'N/A')}`  ")
        md.append(f"**Total Documents Evaluated**: `{evaluation_data.get('total_documents_evaluated', 0)}`  ")
        md.append(f"**Total Duration**: `{evaluation_data.get('total_evaluation_time_seconds', 0.0):.2f} s` (avg `{evaluation_data.get('average_document_time_ms', 0.0):.1f} ms/doc`)\n")

        # 1. Dataset Summary
        md.append("## 1. Dataset Summary\n")
        cats = evaluation_data.get("dataset_categories", {})
        decisions = evaluation_data.get("decision_breakdown", {})
        md.append("| Category | Document Count | AUTO_ACCEPT | REVIEW_REQUIRED | UNRESOLVED | FAILED |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for cat, cnt in cats.items():
            aa = sum(1 for d in evaluation_data.get("documents", []) if d.get("dataset_category") == cat and d.get("decision") == "AUTO_ACCEPT")
            rr = sum(1 for d in evaluation_data.get("documents", []) if d.get("dataset_category") == cat and d.get("decision") == "REVIEW_REQUIRED")
            un = sum(1 for d in evaluation_data.get("documents", []) if d.get("dataset_category") == cat and d.get("decision") == "UNRESOLVED")
            fa = sum(1 for d in evaluation_data.get("documents", []) if d.get("dataset_category") == cat and d.get("decision") == "FAILED")
            md.append(f"| **{cat}** | {cnt} | {aa} | {rr} | {un} | {fa} |")
        md.append("\n")

        # 2. Supplier & Layout Diversity
        md.append("## 2. Supplier & Layout Diversity\n")
        div = evaluation_data.get("layout_diversity", {})
        md.append(f"- **Unique Verified Suppliers**: `{div.get('unique_suppliers_count', 0)}`")
        md.append(f"- **Unique Verified GSTINs**: `{div.get('unique_gstins_count', 0)}`")
        md.append(f"- **Unique Layout Profiles**: `{div.get('unique_layout_profiles_count', 0)}`")
        md.append(f"- **Avg Layouts per Supplier**: `{div.get('average_layouts_per_supplier', 1.0):.2f}`\n")

        # 3. Field-Level Performance
        md.append("## 3. Field-Level Performance\n")
        md.append("| Canonical Field | Ground Truth | Extracted | Exact Match | Norm/Tol Match | Precision | Recall | F1 Score |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        f_metrics = evaluation_data.get("field_metrics", {})
        for f_name, fm in sorted(f_metrics.items()):
            if fm.get("total_ground_truth", 0) > 0 or fm.get("total_predictions", 0) > 0:
                md.append(
                    f"| `{f_name}` | {fm.get('total_ground_truth', 0)} | {fm.get('total_predictions', 0)} | "
                    f"{fm.get('exact_matches', 0)} | {fm.get('tolerance_matches', 0) or fm.get('normalized_matches', 0)} | "
                    f"{fm.get('precision', 0.0):.2f} | {fm.get('recall', 0.0):.2f} | **{fm.get('f1', 0.0):.2f}** |"
                )
        md.append("\n")

        # 4. Row-Level Performance
        md.append("## 4. Row-Level Performance\n")
        rm = evaluation_data.get("row_metrics", {})
        md.append(f"- **Expected Benchmark Rows**: `{rm.get('expected_rows', 0)}`")
        md.append(f"- **Extracted Rows**: `{rm.get('extracted_rows', 0)}`")
        md.append(f"- **Correctly Reconstructed Rows**: `{rm.get('matched_rows', 0)}`")
        md.append(f"- **Missing Rows**: `{rm.get('missing_rows', 0)}` | **Extra Rows**: `{rm.get('extra_rows', 0)}`")
        md.append(f"- **Duplicate Rows**: `{rm.get('duplicate_rows', 0)}` | **Split Rows**: `{rm.get('split_rows', 0)}` | **Merged Rows**: `{rm.get('merged_rows', 0)}`")
        md.append(f"- **Overall Row Accuracy**: **`{rm.get('row_accuracy', 0.0)*100:.1f}%`**\n")

        # 5. Mapping Confusion Matrix
        md.append("## 5. Semantic Mapping Confusion Matrix\n")
        conf_mat = evaluation_data.get("column_mapping_confusion", {})
        if conf_mat:
            md.append("| Expected Canonical Field | Predicted Field | Frequency | Status |")
            md.append("| :--- | :--- | :--- | :--- |")
            for exp, preds in conf_mat.items():
                for pred, count in preds.items():
                    status = "✅ Match" if exp == pred else "⚠️ Confusion"
                    md.append(f"| `{exp}` | `{pred}` | {count} | {status} |")
            md.append("\n")
        else:
            md.append("_No column mapping confusion detected across evaluated ground truth documents._\n")

        # 6. Confidence Calibration
        md.append("## 6. Confidence Calibration Analysis\n")
        md.append("| Confidence Range | Documents | Fully Correct | Incorrect | Review Reqd | Unresolved | Empirical Accuracy |")
        md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        calibs = evaluation_data.get("confidence_calibration", [])
        for cb in calibs:
            md.append(
                f"| `{cb.get('bucket_name')}` | {cb.get('total_documents')} | {cb.get('correct_documents')} | "
                f"{cb.get('incorrect_documents')} | {cb.get('review_required_count')} | {cb.get('unresolved_count')} | "
                f"**{cb.get('empirical_accuracy', 0.0)*100:.1f}%** |"
            )
        md.append("\n")

        # 7. AUTO_ACCEPT Safety Analysis
        md.append("## 7. AUTO_ACCEPT Safety Analysis\n")
        aa_safety = evaluation_data.get("auto_accept_safety", {})
        md.append(f"- **Total AUTO_ACCEPT Invoices**: `{aa_safety.get('total_auto_accept', 0)}`")
        md.append(f"- **Fully Verified Correct**: `{aa_safety.get('fully_correct', 0)}`")
        md.append(f"- **With Field Errors**: `{aa_safety.get('with_field_errors', 0)}`")
        md.append(f"- **With Row Errors**: `{aa_safety.get('with_row_errors', 0)}`")
        md.append(f"- **AUTO_ACCEPT Precision**: **`{aa_safety.get('precision', 1.0)*100:.1f}%`**")
        md.append(f"- **AUTO_ACCEPT Error Rate**: **`{aa_safety.get('error_rate', 0.0)*100:.1f}%`**\n")

        # 8. REVIEW_REQUIRED & UNRESOLVED Analysis
        md.append("## 8. REVIEW_REQUIRED & UNRESOLVED Analysis\n")
        rev = evaluation_data.get("review_required_analysis", {})
        unres = evaluation_data.get("unresolved_analysis", {})
        md.append(f"### REVIEW_REQUIRED (`{rev.get('total_review_required', 0)}` documents)\n")
        if rev.get("top_warning_triggers"):
            for w in rev["top_warning_triggers"][:5]:
                md.append(f"- Warning: `{w['warning']}` ({w['count']} occurrences)")
        else:
            md.append("- No explicit validation warnings logged.")
        md.append("\n")

        md.append(f"### UNRESOLVED (`{unres.get('total_unresolved', 0)}` documents)\n")
        if unres.get("ranked_root_causes"):
            for c in unres["ranked_root_causes"]:
                md.append(f"- Root Cause: `{c['root_cause']}` ({c['count']} documents)")
        else:
            md.append("- No unresolved documents in this evaluation run.")
        md.append("\n")

        # 9. Root Cause Error Distribution
        md.append("## 9. Root-Cause Pipeline Distribution\n")
        rc_dist = evaluation_data.get("root_cause_distribution", {})
        if rc_dist:
            md.append("| Pipeline Stage Root Cause | Detected Error Occurrences | Percentage |")
            md.append("| :--- | :--- | :--- |")
            total_rc = sum(rc_dist.values())
            for rc, count in sorted(rc_dist.items(), key=lambda x: x[1], reverse=True):
                pct = (count / max(total_rc, 1)) * 100
                md.append(f"| `{rc}` | {count} | {pct:.1f}% |")
            md.append("\n")
        else:
            md.append("_No pipeline stage root-cause errors recorded._\n")

        # 10. Recommended Engineering Priorities
        md.append("## 10. Recommended Engineering Priorities (Evidence-Backed)\n")
        priorities = evaluation_data.get("engineering_priorities", [])
        if priorities:
            for p in priorities:
                md.append(f"### Priority {p['priority']}: {p['area']}\n")
                md.append(f"- **Measured Evidence**: {p['reason']}")
                md.append(f"- **Suggested Action**: {p['suggested_action']}\n")
        else:
            md.append("1. **Continuous Pipeline Validation**: Maintain current coordinate and sub-column reconstruction routines.\n")

        content = "\n".join(md)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)

        return out_path
