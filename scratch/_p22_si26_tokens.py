"""P22 SI26 token assignment detail + 7GU0 GT/PDF mismatch confirmation."""
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import json
import pdfplumber
from extractor import (
    extract_page_words,
    extract_coordinate_table,
    score_token_column_assignment,
    extract_pdf_table,
    _mapping_field,
)

# SHA check vs golden
manifest = json.loads((ROOT / "evaluation" / "golden_manifest_v1.json").read_text(encoding="utf-8"))
for d in manifest["documents"]:
    path = ROOT / "Sample Invoices" / d["filename"]
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    match = h == d.get("sha256")
    print(f"SHA {d['filename']}: match={match}")

print("\n=== SI26 product tokens vs columns ===")
path = ROOT / "Sample Invoices" / "SI26-000698.pdf"
with pdfplumber.open(path) as pdf:
    words = extract_page_words(pdf.pages[0])
    h, rows, conf, dbg = extract_coordinate_table(pdf.pages[0], debug=True)

cols = dbg["logical_columns"]
pn = next(c for c in cols if c["header_text"] == "ProductName")
sn = next(c for c in cols if c["header_text"] == "SN")
print(f"SN x={sn['x0']:.1f}-{sn['x1']:.1f} cx={sn.get('center_x')}")
print(f"ProductName x={pn['x0']:.1f}-{pn['x1']:.1f} cx={pn.get('center_x')}")

# row bands for products
for label in ["BECOSULES", "GLYCOMET", "LULIFIN", "MGD3", "TOPAMAC", "VSL"]:
    matches = [w for w in words if label in w["text"].upper() or (label == "VSL" and "VSL" in w["text"].upper())]
    print(f"\n{label}:")
    for w in matches:
        scores = sorted(
            [(c["header_text"], round(score_token_column_assignment(w, c), 1)) for c in cols],
            key=lambda x: -x[1],
        )[:3]
        print(
            f"  tok={w['text']!r:16s} x={w['x0']:.1f}-{w['x1']:.1f} cx={(w['x0']+w['x1'])/2:.1f} "
            f"y={w['top']:.1f} top3={scores}"
        )

print("\nExtracted rows full:")
meta, headers, maps, rows = extract_pdf_table(str(path))
for i, r in enumerate(rows):
    d = {headers[j]: r[j] for j in range(len(headers))}
    print(i, {k: d[k] for k in headers if d[k]})

# Compound qty check
print("\nQty+Free raw cells:")
qi = headers.index("Qty+Free")
for i, r in enumerate(rows):
    print(i, repr(r[qi]), "-> mapped", _mapping_field(maps, "Qty+Free"))

print("\n=== 7GU0: confirm GT products absent, extracted match PDF ===")
path2 = ROOT / "Sample Invoices" / "INVOICE_7GU0X28XM.PDF"
with pdfplumber.open(path2) as pdf:
    text = pdf.pages[0].extract_text() or ""
print("DIGENE in PDF?", "DIGENE" in text.upper())
print("THYRONORM in PDF?", "THYRONORM" in text.upper())
print("GLUCONORM in PDF?", "GLUCONORM" in text.upper())
# GT raw looks like Sri Harsha / ABBO style - check invoice (1)
path3 = ROOT / "Sample Invoices" / "invoice (1).pdf"
with pdfplumber.open(path3) as pdf:
    t3 = (pdf.pages[0].extract_text() or "").upper()
print("DIGENE in invoice (1)?", "DIGENE" in t3)
print("THYRONORM in invoice (1)?", "THYRONORM" in t3)
print("SENQUEL in invoice (1)?", "SENQUEL" in t3)
