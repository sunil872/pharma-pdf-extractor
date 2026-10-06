"""Final metrics + remaining non-critical errors."""
from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.field_accuracy import evaluate_canonical_field_accuracy, MatchType
from extractor import extract_pdf_table

OK = {MatchType.EXACT, MatchType.NORMALIZED, MatchType.TOLERANCE, MatchType.IGNORED}


def main():
    s = evaluate_canonical_field_accuracy()
    print("GLOBAL")
    print(" overall", s.overall_field_accuracy)
    print(" critical", s.overall_critical_field_accuracy)
    print(" financial", s.overall_financial_field_accuracy)
    print(" fully", s.fully_correct_rows)
    print(" partial", s.partially_correct_rows)
    print(" crit_err", s.critical_error_rows)
    print(" extra", s.extra_rows)
    print(" missing", s.missing_rows)

    field_wrong = Counter()
    remaining = []
    for d in s.document_reports:
        fully = partial = crit = extra = 0
        doc_wrong = Counter()
        for r in d.row_evaluations:
            cls = str(r.classification)
            if "FULLY" in cls:
                fully += 1
            elif "PARTIAL" in cls:
                partial += 1
            elif "CRITICAL" in cls:
                crit += 1
            elif "EXTRA" in cls:
                extra += 1
            for f, mt in r.field_results.items():
                if mt not in OK:
                    field_wrong[f] += 1
                    doc_wrong[f] += 1
                    remaining.append(
                        {
                            "doc": d.filename,
                            "row": r.row_index,
                            "field": f,
                            "match": mt.value,
                            "root": r.root_cause.value if r.root_cause else None,
                        }
                    )
        print(
            f"DOC {d.filename}: crit_acc={d.critical_field_accuracy} fin={d.financial_field_accuracy} "
            f"fully={fully} partial={partial} crit={crit} extra={extra} wrong={dict(doc_wrong)}"
        )

    print("\nFIELD_WRONG", dict(field_wrong))
    print("REMAINING_NONCRITICAL", len(remaining))
    # sample remaining by field
    by_field = Counter(x["field"] for x in remaining)
    print("BY_FIELD", dict(by_field))
    roots = Counter(x["root"] for x in remaining)
    print("ROOTS", dict(roots))
    # show up to 25 remaining
    for x in remaining[:25]:
        print(" ", x)

    golden = json.loads((ROOT / "evaluation/golden_manifest_v1.json").read_text(encoding="utf-8"))
    samples = ROOT / "Sample Invoices"
    aa = rr = un = 0
    print("\nCLASSIFICATIONS")
    for d in golden["documents"]:
        meta, _, _, rows = extract_pdf_table(str(samples / d["filename"]))
        cls = meta.get("classification")
        blockers = (meta.get("validation") or {}).get("auto_accept_blockers")
        print(f" {d['filename']}: {cls} conf={meta.get('confidence')} rows={len(rows)}")
        if blockers:
            print(f"   blockers={blockers}")
        if cls == "AUTO_ACCEPT":
            aa += 1
        elif cls == "REVIEW_REQUIRED":
            rr += 1
        else:
            un += 1
    print(f"COUNTS AUTO_ACCEPT={aa} REVIEW_REQUIRED={rr} UNRESOLVED={un}")

    # GT integrity: only 7GU0 note
    gt = json.loads((ROOT / "evaluation/field_ground_truth_manifest.json").read_text(encoding="utf-8"))
    for d in gt["documents"]:
        h = hashlib.sha256((samples / d["filename"]).read_bytes()).hexdigest()
        assert h == d["sha256"], d["filename"]
    print("All GT sha match PDFs")

    Path(ROOT / "scratch/_final_remaining.json").write_text(
        json.dumps(remaining, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
