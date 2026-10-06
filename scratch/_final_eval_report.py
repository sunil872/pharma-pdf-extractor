"""Final GOLDEN evaluation report. Read-only besides printing metrics."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.field_accuracy import evaluate_canonical_field_accuracy, MatchType
from evaluation.field_ground_truth import CRITICAL_FIELDS

OK = {MatchType.EXACT, MatchType.NORMALIZED, MatchType.TOLERANCE, MatchType.IGNORED}


def main():
    golden = json.loads((ROOT / "evaluation/golden_manifest_v1.json").read_text(encoding="utf-8"))
    samples = ROOT / "Sample Invoices"
    print("=== SHA ===")
    for d in golden["documents"]:
        h = hashlib.sha256((samples / d["filename"]).read_bytes()).hexdigest()
        print(f"  {d['filename']}: {'OK' if h==d['sha256'] else 'FAIL'}")

    s = evaluate_canonical_field_accuracy()
    print("\n=== GLOBAL ===")
    print(f"overall={s.overall_field_accuracy}")
    print(f"critical={s.overall_critical_field_accuracy}")
    print(f"financial={s.overall_financial_field_accuracy}")
    print(f"fully={s.fully_correct_rows}")
    print(f"partial={s.partially_correct_rows}")
    print(f"critical_error_rows={s.critical_error_rows}")
    print(f"missing_rows={s.missing_rows}")
    print(f"extra_rows={s.extra_rows}")

    # Classification counts from live extract via document reports if available
    aa = rr = un = 0
    aa_correct = 0
    aa_total = 0
    for d in s.document_reports:
        print(f"\nDOC {d.filename}")
        print(f"  rows_gt={d.expected_rows} extracted={d.extracted_rows}")
        print(f"  field_acc={getattr(d,'field_accuracy',None)} crit={getattr(d,'critical_field_accuracy',None)} fin={getattr(d,'financial_field_accuracy',None)}")
        print(f"  fully={d.fully_correct_rows} partial={d.partially_correct_rows} crit_err={d.critical_error_rows}")
        print(f"  decision={getattr(d,'classification',None)} conf={getattr(d,'confidence',None)}")
        cls = getattr(d, "classification", None) or getattr(d, "document_decision", None)
        # attrs vary
        for attr in ("classification", "decision", "document_classification"):
            if hasattr(d, attr):
                cls = getattr(d, attr)
                break
        conf = getattr(d, "confidence", None) or getattr(d, "document_confidence", None)
        print(f"  attrs classification-like={cls} conf={conf}")

        crit_details = []
        for reval in d.row_evaluations:
            if reval.critical_errors:
                wrong = {f: mt.value for f, mt in reval.field_results.items() if mt not in OK}
                crit_details.append((reval.row_index, reval.critical_errors, wrong, reval.root_cause))
        if crit_details:
            print("  CRITICAL ROWS:")
            for ri, errs, wrong, rc in crit_details:
                print(f"    row {ri} root={rc}")
                for e in errs:
                    print(f"      {e}")
                print(f"      wrong={wrong}")

    # Live classification tallies
    from extractor import extract_pdf_table
    print("\n=== LIVE CLASSIFICATIONS ===")
    for d in golden["documents"]:
        meta, _, _, rows = extract_pdf_table(str(samples / d["filename"]))
        cls = meta.get("classification")
        conf = meta.get("confidence")
        print(f"  {d['filename']}: {cls} conf={conf} rows={len(rows)}")
        if cls == "AUTO_ACCEPT":
            aa += 1
        elif cls == "REVIEW_REQUIRED":
            rr += 1
        else:
            un += 1
    print(f"AUTO_ACCEPT={aa} REVIEW_REQUIRED={rr} UNRESOLVED={un}")


if __name__ == "__main__":
    main()
