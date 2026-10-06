"""P22 readonly suite + hardcoding audit. No modifications."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.field_accuracy import evaluate_canonical_field_accuracy


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    golden = json.loads((ROOT / "evaluation/golden_manifest_v1.json").read_text(encoding="utf-8"))
    print("GOLDEN docs", len(golden["documents"]))
    samples = ROOT / "Sample Invoices"
    for d in golden["documents"]:
        p = samples / d["filename"]
        ok = sha_file(p) == d["sha256"]
        print(f"  HASH {d['filename']}: {'OK' if ok else 'CHANGED'}")

    # Before/after behavior: re-run accuracy (should match stated baseline)
    s = evaluate_canonical_field_accuracy()
    print(
        f"ACCURACY overall={s.overall_field_accuracy} crit={s.overall_critical_field_accuracy} "
        f"fin={s.overall_financial_field_accuracy} fully={s.fully_correct_rows} crit_rows={s.critical_error_rows}"
    )

    # Hardcoding audit in extractor.py
    text = (ROOT / "extractor.py").read_text(encoding="utf-8", errors="replace")
    needles = [
        r"7GU0",
        r"SI26",
        r"PHUB",
        r"filename\s*==",
        r"endswith\(\s*['\"]\.pdf",
        r"Sample Invoices",
        r"INVOICE_7",
        r"absolute",
        r"x0\s*==\s*\d",
        r"x1\s*==\s*\d",
    ]
    print("\n=== Hardcoding scan extractor.py ===")
    for pat in needles:
        hits = list(re.finditer(pat, text, flags=re.I))
        if hits:
            print(f"  PATTERN {pat!r}: {len(hits)} hits")
            for m in hits[:5]:
                line = text.count("\n", 0, m.start()) + 1
                snippet = text[m.start() : m.start() + 60].replace("\n", " ")
                print(f"    L{line}: {snippet}")
        else:
            print(f"  PATTERN {pat!r}: none")

    # supplier-specific if/filename rules
    for pat in [r"if\s+.*supplier", r"supplier_key\s*==", r"gstin\s*=="]:
        hits = list(re.finditer(pat, text, flags=re.I))
        print(f"  PATTERN {pat!r}: {len(hits)} hits (context-only; profiles OK)")

    # Confirm Digene absent from 7GU0 PDF but present in GT only
    import pdfplumber

    p7 = samples / "INVOICE_7GU0X28XM.PDF"
    with pdfplumber.open(p7) as pdf:
        t = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
    print("\n7GU0 Digene?", "DIGENE" in t.upper(), "Gluconorm?", "GLUCONORM" in t.upper())
    print("invoice(1) Digene?", end=" ")
    with pdfplumber.open(samples / "invoice (1).pdf") as pdf:
        t1 = "\n".join((pg.extract_text() or "") for pg in pdf.pages).upper()
    print("DIGENE" in t1, "THYRONORM" in t1, "SENQUEL" in t1)

    # Compare GT Digene raw rows to any PDF - none have Digene
    any_digene = False
    for p in samples.glob("*"):
        if p.suffix.lower() != ".pdf":
            continue
        with pdfplumber.open(p) as pdf:
            tt = "\n".join((pg.extract_text() or "") for pg in pdf.pages).upper()
        if "DIGENE" in tt:
            print("DIGENE found in", p.name)
            any_digene = True
    if not any_digene:
        print("DIGENE not present in ANY Sample Invoices PDF — GT for 7GU0 Digene row is orphaned")


if __name__ == "__main__":
    main()
