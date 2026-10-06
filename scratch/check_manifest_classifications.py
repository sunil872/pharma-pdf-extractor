import sys, os, json
sys.path.insert(0, os.path.abspath("."))
from extractor import extract_pdf_table

with open("benchmark_manifest.json", "r", encoding="utf-8") as f:
    manifest = json.load(f)

for item in manifest["samples"]:
    fn = item["filename"]
    p = os.path.join("Sample Invoices", fn)
    meta, headers, mappings, rows = extract_pdf_table(p)
    cls = meta.get("classification")
    conf = meta.get("confidence")
    print(f"{fn}: {cls} (conf={conf:.1f}) - {len(rows)} rows")
