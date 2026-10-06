"""P22 finalize diagnostics — read-only. No extractor/GT changes."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pdfplumber
from extractor import extract_pdf_table, _mapping_field, tokenize_compound_quantity
from evaluation.field_accuracy import evaluate_canonical_field_accuracy, MatchType
from evaluation.field_ground_truth import CRITICAL_FIELDS

SAMPLES = ROOT / "Sample Invoices"
OK = {MatchType.EXACT, MatchType.NORMALIZED, MatchType.TOLERANCE, MatchType.IGNORED}


def gv(cells, f):
    c = cells.get(f)
    if isinstance(c, dict):
        return c.get("value")
    return c


def resolve(fname: str) -> Path:
    p = SAMPLES / fname
    if p.exists():
        return p
    hits = list(ROOT.rglob(fname))
    if not hits:
        raise FileNotFoundError(fname)
    return hits[0]


def row_to_dict(headers, maps, row):
    out = {}
    for i, h in enumerate(headers):
        f = _mapping_field(maps, h)
        if not f:
            continue
        val = row[i] if i < len(row) else None
        # prefer first non-empty for duplicates? keep last non-empty
        if val is None or val == "":
            if f not in out:
                out[f] = val
        else:
            out[f] = val
    return out


def main():
    gt = json.loads((ROOT / "evaluation/field_ground_truth_manifest.json").read_text(encoding="utf-8"))
    golden = json.loads((ROOT / "evaluation/golden_manifest_v1.json").read_text(encoding="utf-8"))

    print("=== SHA verify golden vs Sample Invoices ===")
    for d in golden["documents"]:
        p = resolve(d["filename"])
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        print(f"{d['filename']}: match={h == d['sha256']} path={p}")

    print("\n=== PDF product keyword search ===")
    for p in sorted(SAMPLES.glob("*.pdf")) + sorted(SAMPLES.glob("*.PDF")):
        with pdfplumber.open(p) as pdf:
            text = "\n".join((pg.extract_text() or "") for pg in pdf.pages).upper()
        hits = [n for n in ("DIGENE", "THYRONORM", "SENQUEL", "GLUCONORM", "MGD3", "VSL#3", "ABBO") if n in text]
        print(f"  {p.name}: {hits or '-'}")

    res = evaluate_canonical_field_accuracy()
    print(
        f"\n=== Eval overall={res.overall_field_accuracy*100:.2f}% "
        f"crit={res.overall_critical_field_accuracy*100:.2f}% "
        f"fin={res.overall_financial_field_accuracy*100:.2f}% "
        f"fully={res.fully_correct_rows} crit_rows={res.critical_error_rows}"
    )

    for fname in ("INVOICE_7GU0X28XM.PDF", "SI26-000698.pdf"):
        gtd = next(d for d in gt["documents"] if d["filename"] == fname)
        path = resolve(fname)
        meta, headers, maps, rows = extract_pdf_table(str(path))
        drep = next(d for d in res.document_reports if d.filename == fname)
        print(f"\n======== {fname} extracted={len(rows)} conf={meta.get('confidence')} ========")
        print("headers", headers)
        print("maps", {h: _mapping_field(maps, h) for h in headers})

        for reval in drep.row_evaluations:
            gt_row = next(r for r in gtd["rows"] if r["row_index"] == reval.row_index)
            cells = gt_row.get("cells") or {}
            pred = row_to_dict(headers, maps, rows[reval.row_index]) if reval.row_index < len(rows) else {}
            wrong = {f: mt.value for f, mt in reval.field_results.items() if mt not in OK}
            print(
                f"\nROW {reval.row_index} class={reval.classification} root={reval.root_cause}"
            )
            if reval.critical_errors:
                for e in reval.critical_errors:
                    print(f"  CRIT: {e}")
            print(f"  wrong={wrong}")
            for f in [
                "itemName",
                "quantity",
                "freeQuantity",
                "rate",
                "amount",
                "mrp",
                "pack",
                "batchNo",
                "discountPercent",
                "gstPercent",
                "company",
                "hsnCode",
            ]:
                exp = gv(cells, f)
                act = pred.get(f)
                mt = reval.field_results.get(f)
                flag = ""
                if mt and mt not in OK:
                    flag = f" ***{mt.value}"
                elif f in CRITICAL_FIELDS and mt:
                    flag = f" ({mt.value})"
                if exp is not None or act is not None or (mt and mt not in OK):
                    print(f"  {f}: EXP={exp!r} ACT={act!r}{flag}")

            # compound qty diagnostic for SI26
            if fname.startswith("SI26"):
                raw_qf = None
                for i, h in enumerate(headers):
                    if "qty" in h.lower() or "free" in h.lower():
                        raw_qf = rows[reval.row_index][i] if reval.row_index < len(rows) else None
                        print(f"  raw[{h}]={raw_qf!r} tokenize={tokenize_compound_quantity(raw_qf)}")

    # SI26 coordinate evidence for critical rows
    print("\n=== SI26 token assignment evidence (rows 3,5) ===")
    path = resolve("SI26-000698.pdf")
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        words = page.extract_words() or []
    # recreate column bounds from earlier dump
    cols = {
        "SN": (8.3, 47.4),
        "ProductName": (47.4, 202.0),
    }
    for needle in ("4MGD3", "TAB.", "6VSL#3", "CAP.", "3LULIFIN", "CREAM", "5TOPAMAC", "1BECOSULES", "2GLYCOMET"):
        for w in words:
            if w["text"] == needle or needle in w["text"]:
                cx = (w["x0"] + w["x1"]) / 2
                assign = "SN" if cx < 47.4 else ("ProductName" if cx < 202 else "OTHER")
                print(
                    f"  {w['text']!r:20s} x={w['x0']:.1f}-{w['x1']:.1f} cx={cx:.1f} "
                    f"y={w['top']:.1f} -> {assign}"
                )

    # freeQuantity MISSING reason for SI26 free=0
    print("\n=== freeQuantity compare notes ===")
    print("SI26 GT freeQuantity is 0.0 for rows 1-5; row0 free=2.0 from 23+2")
    print("If extractor omits freeQuantity key when 0, evaluator marks MISSING (non-critical)")


if __name__ == "__main__":
    main()
