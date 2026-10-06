"""P22: compare PDF text products vs GT vs extraction for 7GU0 and SI26."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pdfplumber
from extractor import extract_pdf_table, extract_coordinate_table, extract_page_words, _mapping_field
from evaluation.field_ground_truth import FieldGroundTruthStore

GT = FieldGroundTruthStore()


def analyze(fname: str):
    path = ROOT / "Sample Invoices" / fname
    gt = GT.get_document(fname)
    print("=" * 80, fname)

    gt_items = []
    for row in gt.rows:
        cell = row.get_cell("itemName")
        gt_items.append((row.row_index, cell.value if cell else None, getattr(row, "raw_row_text", None) or row.__dict__.get("raw_row_text")))
        # also print raw from manifest style
        print(f"GT[{row.row_index}] item={cell.value if cell else None} qty={row.get_cell('quantity').value if row.get_cell('quantity') else None} rate={row.get_cell('rate').value if row.get_cell('rate') else None}")

    meta, headers, maps, rows = extract_pdf_table(str(path))
    item_i = next(i for i, h in enumerate(headers) if _mapping_field(maps, h) == "itemName")
    print("\nEXTRACTED:")
    for i, r in enumerate(rows):
        print(f" EX[{i}] {r[item_i]}")

    with pdfplumber.open(path) as pdf:
        print("\npages", len(pdf.pages), "size", pdf.pages[0].width, pdf.pages[0].height)
        full = []
        for pi, page in enumerate(pdf.pages):
            t = page.extract_text() or ""
            full.append(t)
            print(f"\nPAGE {pi} TEXT (product-ish lines):")
            for ln in t.splitlines():
                up = ln.upper()
                if any(k in up for k in ["DIGENE", "THYRONORM", "SENQUEL", "GLUCONORM", "TONACT", "BILAHIST", "CONCOR", "AMLONG", "OMNIMOIST", "ANOBLISS", "URSOCOL", "PREGEB", "SUNKROMA", "MGD3", "VSL", "BECOSULES", "LULIFIN", "TAB", "CAP", "PRODUCT"]):
                    print(" ", ln[:140])

        joined = "\n".join(full).upper()
        for name in ["DIGENE", "THYRONORM", "SENQUEL", "GLUCONORM", "TONACT", "MGD3", "VSL#3", "VSL"]:
            print(f" PDF contains {name}? {name in joined}")

        # coordinate detail page 0
        h, rws, conf, dbg = extract_coordinate_table(pdf.pages[0], debug=True)
        print(f"\nCOORD conf={conf} n_rows={len(rws)} headers={h}")
        if rws:
            for i, row in enumerate(rws[:3]):
                d = dict(zip(h, row))
                print(f" coord[{i}] PRODUCT={d.get('PRODUCTNAME') or d.get('ProductName') or d} ")

        # SI26-style product token boxes for truncated names
        if "SI26" in fname:
            words = extract_page_words(pdf.pages[0])
            print("\nSI26 words containing MGD / VSL / TAB / CAP:")
            for w in words:
                if any(x in w["text"].upper() for x in ["MGD", "VSL", "TAB", "CAP", "#"]):
                    print(f"  {w['text']!r} x={w['x0']:.1f}-{w['x1']:.1f} y={w['top']:.1f}-{w['bottom']:.1f}")
            if dbg.get("logical_columns"):
                print("\nlogical cols:")
                for c in dbg["logical_columns"]:
                    print(f"  {c['header_text']!r} field={c.get('field')} x={c['x0']:.1f}-{c['x1']:.1f}")


analyze("INVOICE_7GU0X28XM.PDF")
print("\n")
analyze("SI26-000698.pdf")
