"""
Prompt 21B: PHUB clean-header column/value assignment tests.

Tests:
A. PHUB RATE
B. PHUB PTR
C. PHUB AMOUNT
D. PHUB GST
E. MRP/RATE separation
F. QTY/FREE separation
G. BATCH/EXP separation
H. HSN/EXP separation
I. multiple product rows
J. missing numeric value (empty FREE)
K. regression on other sample invoices
"""
import json
import os
import sys
from pathlib import Path

import pdfplumber
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extractor import (  # noqa: E402
    extract_coordinate_table,
    extract_pdf_table,
    resolve_column_mappings,
    _mapping_field,
    _header_field_priority_score,
)

PHUB = ROOT / "Sample Invoices" / "PHUB_L22014.pdf"
GT_PATH = ROOT / "evaluation" / "field_ground_truth_manifest.json"


def _phub_gt_rows():
    data = json.loads(GT_PATH.read_text(encoding="utf-8"))
    docs = data.get("documents") or []
    for d in docs:
        if d.get("filename") == "PHUB_L22014.pdf":
            return d.get("rows") or []
    raise AssertionError("PHUB ground truth not found")


def _coord_phub():
    with pdfplumber.open(PHUB) as pdf:
        return extract_coordinate_table(pdf.pages[0], debug=True)


def _cell(row_dict, *keys):
    for k in keys:
        if k in row_dict and str(row_dict[k]).strip():
            return str(row_dict[k]).strip()
    return ""


def test_a_phub_rate():
    headers, rows, conf, dbg = _coord_phub()
    assert "RATE" in headers
    r0 = dict(zip(headers, rows[0]))
    assert _cell(r0, "RATE") == "74.27"
    # Mapping winner for rate must be RATE, not P.T.R
    assert _header_field_priority_score("rate", "RATE") > _header_field_priority_score(
        "rate", "P.T.R"
    )
    maps = resolve_column_mappings(headers)
    assert _mapping_field(maps, "RATE") == "rate"
    assert _mapping_field(maps, "P.T.R") in (None, "rate")  # loser may be None after dedup
    if _mapping_field(maps, "P.T.R") == "rate":
        # if both still map, RATE must win in resolve winners
        winners = [h for h, f in maps.items() if f == "rate"]
        assert winners == ["RATE"] or "RATE" in winners


def test_b_phub_ptr():
    headers, rows, conf, dbg = _coord_phub()
    assert "P.T.R" in headers
    r0 = dict(zip(headers, rows[0]))
    assert _cell(r0, "P.T.R") == "82.52"
    # PTR must not overwrite RATE cell
    assert _cell(r0, "RATE") != _cell(r0, "P.T.R")


def test_c_phub_amount():
    headers, rows, conf, dbg = _coord_phub()
    r0 = dict(zip(headers, rows[0]))
    amt = _cell(r0, "AMOUNT")
    assert amt == "371.35"
    assert "-1.50" not in amt
    assert " " not in amt.strip()


def test_d_phub_gst():
    headers, rows, conf, dbg = _coord_phub()
    r0 = dict(zip(headers, rows[0]))
    assert _cell(r0, "GST") == "5"
    assert _cell(r0, "Disc") == "-1.50"


def test_e_mrp_rate_separation():
    headers, rows, conf, dbg = _coord_phub()
    r0 = dict(zip(headers, rows[0]))
    assert _cell(r0, "M.R.P") == "108.31"
    assert _cell(r0, "RATE") == "74.27"
    assert _cell(r0, "M.R.P") != _cell(r0, "RATE")


def test_f_qty_free_separation():
    headers, rows, conf, dbg = _coord_phub()
    r0 = dict(zip(headers, rows[0]))
    assert _cell(r0, "QTY") == "5"
    assert _cell(r0, "FREE") == "1"


def test_g_batch_exp_separation():
    headers, rows, conf, dbg = _coord_phub()
    r0 = dict(zip(headers, rows[0]))
    assert _cell(r0, "BATCH") == "TEB25004"
    assert _cell(r0, "E.X.P") == "05/27"
    assert _cell(r0, "BATCH") != _cell(r0, "E.X.P")


def test_h_hsn_exp_separation():
    headers, rows, conf, dbg = _coord_phub()
    r0 = dict(zip(headers, rows[0]))
    assert _cell(r0, "HSNCode") == "30049099"
    assert _cell(r0, "E.X.P") == "05/27"
    assert not _cell(r0, "HSNCode").startswith("05")


def test_i_multiple_product_rows():
    headers, rows, conf, dbg = _coord_phub()
    assert len(rows) >= 10
    # Spot-check three rows against GT criticals
    gt = _phub_gt_rows()
    for i in (0, 1, 2):
        r = dict(zip(headers, rows[i]))
        cells = gt[i]["cells"]
        assert float(_cell(r, "RATE")) == pytest.approx(float(cells["rate"]["value"]), rel=1e-3)
        assert float(_cell(r, "AMOUNT")) == pytest.approx(float(cells["amount"]["value"]), rel=1e-3)
        assert float(_cell(r, "GST")) == pytest.approx(float(cells["gstPercent"]["value"]), rel=1e-3)
        assert float(_cell(r, "M.R.P")) == pytest.approx(float(cells["mrp"]["value"]), rel=1e-3)
        assert "-1.50" not in _cell(r, "AMOUNT")


def test_j_missing_numeric_value_free_empty():
    headers, rows, conf, dbg = _coord_phub()
    # Row 1 (LINATIN) has empty FREE in GT / source
    r1 = dict(zip(headers, rows[1]))
    assert _cell(r1, "PRODUCTNAME") == "LINATIN 5 TAB" or "LINATIN" in _cell(r1, "PRODUCTNAME")
    assert _cell(r1, "FREE") == ""
    assert _cell(r1, "QTY") == "3"
    # Empty FREE must not steal QTY or PACK
    assert _cell(r1, "PACK") == "10"


def test_k_regression_other_invoices():
    samples = [
        ROOT / "Sample Invoices" / "Invoice.pdf",
        ROOT / "Sample Invoices" / "invoice (1).pdf",
        ROOT / "Sample Invoices" / "SI26-000698.pdf",
    ]
    for path in samples:
        if not path.exists():
            continue
        meta, headers, maps, rows = extract_pdf_table(str(path))
        assert headers, f"no headers for {path.name}"
        assert len(rows) >= 1, f"no rows for {path.name}"
        # Must map an itemName column
        assert any(_mapping_field(maps, h) == "itemName" for h in headers), path.name


def test_amount_disc_gst_column_cuts():
    """Physical cuts must separate AMOUNT | Disc | GST using body valleys."""
    headers, rows, conf, dbg = _coord_phub()
    cols = {c["header_text"]: c for c in dbg["logical_columns"]}
    assert cols["AMOUNT"]["x1"] == pytest.approx(cols["Disc"]["x0"], abs=0.5)
    assert cols["Disc"]["x1"] == pytest.approx(cols["GST"]["x0"], abs=0.5)
    # Body valley evidence: cut AMOUNT|Disc around ~749.6, Disc|GST around ~787
    assert 745.0 <= cols["AMOUNT"]["x1"] <= 760.0
    assert 780.0 <= cols["Disc"]["x1"] <= 800.0
