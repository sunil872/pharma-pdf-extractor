import os
import sys
sys.path.insert(0, os.path.abspath("."))
import json
import hashlib

sample_dir = "Sample Invoices"
print("=== Sample Invoices Directory ===")
files = [f for f in sorted(os.listdir(sample_dir)) if f.lower().endswith(".pdf")]
print(f"Total PDFs in {sample_dir}: {len(files)}")
pdf_info = {}
for f in files:
    p = os.path.join(sample_dir, f)
    with open(p, "rb") as fp:
        h = hashlib.sha256(fp.read()).hexdigest()
    sz = os.path.getsize(p)
    pdf_info[f] = {"size": sz, "sha256": h}
    print(f"  {f:35s} | size={sz:6d} | sha256={h}")

print("\n=== benchmark_manifest.json ===")
if os.path.exists("benchmark_manifest.json"):
    with open("benchmark_manifest.json", "r", encoding="utf-8") as fp:
        bm = json.load(fp)
    print(f"Version: {bm.get('benchmark_version')}, Samples: {bm.get('sample_count')}")
    for s in bm.get("samples", []):
        fn = s.get("filename")
        fh = s.get("file_hash")
        supp = s.get("expected_supplier_if_verified")
        gstin = s.get("expected_gstin_if_verified")
        rows = s.get("expected_row_count_if_verified")
        matches = (fn in pdf_info and pdf_info[fn]["sha256"] == fh)
        print(f"  {fn:35s} | rows={str(rows):2s} | supp={supp} | gstin={gstin} | SHA MATCH: {matches}")
else:
    print("  benchmark_manifest.json NOT FOUND!")

print("\n=== benchmark_results_v1.json ===")
if os.path.exists("benchmark_results_v1.json"):
    with open("benchmark_results_v1.json", "r", encoding="utf-8") as fp:
        br = json.load(fp)
    print(f"Version: {br.get('benchmark_version')}, Invoices: {br.get('total_invoices')}")
    for r in br.get("results", []):
        fn = r.get("filename")
        supp = r.get("supplier_name")
        rows = r.get("row_count")
        dec = r.get("decision")
        conf = r.get("confidence")
        print(f"  {fn:35s} | rows={str(rows):2s} | dec={str(dec):15s} | conf={str(conf):5s} | supp={supp}")
else:
    print("  benchmark_results_v1.json NOT FOUND!")

print("\n=== evaluation/manifest.json ===")
if os.path.exists("evaluation/manifest.json"):
    with open("evaluation/manifest.json", "r", encoding="utf-8") as fp:
        em = json.load(fp)
    print(f"Version: {em.get('manifest_version')}, Total Documents: {len(em.get('documents', []))}")
    for d in em.get("documents", []):
        fn = d.get("filename")
        cat = str(d.get("dataset_category"))
        sha = str(d.get("sha256"))
        supp = str(d.get("supplier_name"))
        rows = str(d.get("expected_rows"))
        print(f"  {fn:35s} | cat={cat:10s} | rows={rows:2s} | supp={supp} | sha={sha[:12]}...")
else:
    print("  evaluation/manifest.json NOT FOUND!")

print("\n=== evaluation/ground_truth.py ===")
try:
    from evaluation.ground_truth import GROUND_TRUTH_DATASET
    print(f"GROUND_TRUTH_DATASET contains {len(GROUND_TRUTH_DATASET)} documents:")
    for doc_id, doc in GROUND_TRUTH_DATASET.items():
        fn = doc.filename
        rows = len(doc.expected_rows)
        supp = doc.expected_supplier_name
        cat = str(doc.dataset_category)
        print(f"  ID={doc_id:25s} | fn={fn:30s} | cat={cat:10s} | rows={rows:2d} | supp={supp}")
except Exception as e:
    print(f"  Error loading ground truth dataset: {e}")
