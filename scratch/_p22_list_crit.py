"""Prompt 22 diagnostic: list all critical-error rows from GOLDEN_V1. Read-only."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.field_accuracy import evaluate_canonical_field_accuracy, MatchType
from evaluation.field_ground_truth import CRITICAL_FIELDS

OK = {MatchType.EXACT, MatchType.NORMALIZED, MatchType.TOLERANCE, MatchType.IGNORED}

s = evaluate_canonical_field_accuracy()
print("SUMMARY", s.overall_field_accuracy, s.overall_critical_field_accuracy, s.overall_financial_field_accuracy)
print("FULLY", s.fully_correct_rows, "CRIT_ERR", s.critical_error_rows)

crit_rows = []
for d in s.document_reports:
    for reval in d.row_evaluations:
        if not reval.critical_errors:
            continue
        wrong = {f: mt.value for f, mt in reval.field_results.items() if mt not in OK}
        crit_rows.append({
            "filename": d.filename,
            "row_index": reval.row_index,
            "classification": reval.classification.value if hasattr(reval.classification, "value") else str(reval.classification),
            "critical_errors": reval.critical_errors,
            "wrong_fields": wrong,
            "high_risk": reval.detected_high_risk_errors,
            "root_cause": reval.root_cause.value if reval.root_cause and hasattr(reval.root_cause, "value") else str(reval.root_cause),
            "accounting": reval.accounting_status.value if hasattr(reval.accounting_status, "value") else str(reval.accounting_status),
        })

print("CRIT_ROW_COUNT", len(crit_rows))
out = ROOT / "scratch" / "_p22_crit_rows.json"
out.write_text(json.dumps(crit_rows, indent=2), encoding="utf-8")
print("WROTE", out)
for r in crit_rows:
    print(f"\n{r['filename']} row={r['row_index']} root={r['root_cause']}")
    for e in r["critical_errors"]:
        print(" ", e)
    print(" wrong", r["wrong_fields"])
