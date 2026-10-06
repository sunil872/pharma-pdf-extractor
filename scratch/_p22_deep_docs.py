"""P22 deep diagnostic for 7GU0 + SI26. Read-only."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pdfplumber
from extractor import (
    extract_pdf_table,
    extract_coordinate_table,
    extract_page_words,
    _mapping_field,
    detect_coordinate_header_row,
)
from evaluation.field_ground_truth import FieldGroundTruthStore

GT = FieldGroundTruthStore()


def dump_doc(fname: str):
    path = ROOT / "Sample Invoices" / fname
    gt = GT.get_document(fname)
    print("=" * 80)
    print(fname)
    print("GT expected_rows", gt.expected_rows if gt else None, "clean", getattr(gt, "clean_medicine_rows", None))
    meta, headers, maps, rows = extract_pdf_table(str(path))
    print("extracted", len(rows), "decision", meta.get("classification"), "conf", meta.get("confidence"))
    print("headers", headers)
    print("maps", {h: _mapping_field(maps, h) for h in headers})

    item_i = next((i for i, h in enumerate(headers) if _mapping_field(maps, h) == "itemName"), None)
    qty_i = next((i for i, h in enumerate(headers) if _mapping_field(maps, h) == "quantity"), None)
    rate_i = next((i for i, h in enumerate(headers) if _mapping_field(maps, h) == "rate"), None)
    amt_i = next((i for i, h in enumerate(headers) if _mapping_field(maps, h) == "amount"), None)

    print("\nEXTRACTED rows:")
    for i, r in enumerate(rows):
        print(
            f"  {i}: item={r[item_i] if item_i is not None else None!r} "
            f"qty={r[qty_i] if qty_i is not None else None} "
            f"rate={r[rate_i] if rate_i is not None else None} "
            f"amt={r[amt_i] if amt_i is not None else None}"
        )

    print("\nGT rows:")
    if gt:
        for row in gt.rows:
            cells = {c.field_name: c.value for c in row.cells} if hasattr(row, "cells") and row.cells and hasattr(row.cells[0], "field_name") else None
            if cells is None and hasattr(row, "get_cell"):
                cells = {
                    f: (row.get_cell(f).value if row.get_cell(f) else None)
                    for f in ("itemName", "quantity", "rate", "amount", "freeQuantity", "pack", "batchNo")
                }
            print(f"  {row.row_index}: {cells}")

    # PDF text product names via words
    with pdfplumber.open(path) as pdf:
        print("\npages", len(pdf.pages))
        for pi, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            lines = [ln for ln in text.splitlines() if ln.strip()]
            print(f"\n--- page {pi} first 40 nonempty lines ---")
            for ln in lines[:40]:
                print(" ", ln[:120])
            # coordinate headers/rows
            h, rws, conf, dbg = extract_coordinate_table(page, debug=True)
            print(f"\ncoord page{pi}: conf={conf:.3f} headers={h} rows={len(rws)}")
            if dbg.get("logical_columns"):
                for c in dbg["logical_columns"]:
                    print(
                        f"  COL {c['header_text']!r:20s} field={c.get('field')} "
                        f"x={c['x0']:.1f}-{c['x1']:.1f} status={c.get('status')}"
                    )
            if rws:
                for i, row in enumerate(rws[:5]):
                    print(f"  coord_row{i}: {dict(zip(h, row))}")


dump_doc("INVOICE_7GU0X28XM.PDF")
print("\n\n")
dump_doc("SI26-000698.pdf")
