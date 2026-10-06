import os, sys, glob, re
sys.path.insert(0, os.getcwd())
import pdfplumber
import pandas as pd
from rapidfuzz import process, fuzz
from extractor import (
    extract_page_words, detect_coordinate_header_row, determine_column_boundaries,
    match_column_name, clean_text, _to_float, parse_compound_qty, standardize_date,
    profile_column, score_column_candidates, infer_unresolved_column_semantics,
    _is_genuine_product_row, _is_footer_row, _is_letterhead_row, _merge_continuation_rows,
    ALIAS_DICT, SYSTEM_COLUMNS, PACK_PATTERN, PHARMA_ITEM_WORDS, GST_STANDARD_RATES
)

def cluster_1d_coords(vals, tol=6.0):
    """Cluster 1D values by proximity."""
    if not vals:
        return []
    sorted_v = sorted(vals)
    clusters = [[sorted_v[0]]]
    for v in sorted_v[1:]:
        if v - clusters[-1][-1] <= tol:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return clusters

def detect_body_x_clusters_in_column(words_in_col, total_rows_count):
    """
    Given all words from product rows inside a physical column region,
    detects if there are multiple stable horizontal X clusters.
    Returns: list of cluster dicts: [{"x_mean": ..., "x_min": ..., "x_max": ..., "count": ..., "coverage": ...}]
    """
    if not words_in_col or total_rows_count < 2:
        return []

    # Get centers of all words
    centers = [w["center_x"] for w in words_in_col]
    raw_clusters = cluster_1d_coords(centers, tol=7.0)

    clusters = []
    for c in raw_clusters:
        # Number of unique rows represented in this cluster
        row_ys = {round(w["top"], 1) for w in words_in_col if w["center_x"] in c}
        coverage = len(row_ys) / max(1, total_rows_count)
        
        # Only consider clusters that appear in at least 40% of rows
        if coverage >= 0.40 and len(c) >= 2:
            x_min = min(w["x0"] for w in words_in_col if w["center_x"] in c)
            x_max = max(w["x1"] for w in words_in_col if w["center_x"] in c)
            c_words = [w for w in words_in_col if w["center_x"] in c]
            clusters.append({
                "x_mean": sum(c) / len(c),
                "x_min": x_min,
                "x_max": x_max,
                "count": len(c),
                "coverage": coverage,
                "sample_texts": [w["text"] for w in c_words[:5]],
            })

    clusters.sort(key=lambda x: x["x_mean"])
    return clusters

def test_on_invoice_gajanand():
    p = pdfplumber.open("Sample Invoices/INVOICE_7HH0S5IPC.PDF").pages[0]
    words = extract_page_words(p)
    ht, top, bot, conf = detect_coordinate_header_row(words, p.height)
    body_words = [w for w in words if w["top"] > bot]
    cols = determine_column_boundaries(ht, p.width, body_words=body_words)
    
    print("==================================================================")
    print("TESTING SUB-COLUMN CLUSTERING ON INVOICE_7HH0S5IPC.PDF")
    print("==================================================================")
    
    # Estimate product row count by unique Y positions
    y_positions = {round(w["top"], 1) for w in body_words if w["top"] < bot + 300}
    total_rows = len(y_positions)
    print(f"Detected ~{total_rows} product rows")

    for col in cols:
        w_in_c = [w for w in body_words if col["x0"] <= w["center_x"] < col["x1"]]
        clusters = detect_body_x_clusters_in_column(w_in_c, total_rows)
        print(f"\nPhysical Col {col['index']}: '{col['header_text']}' [x0={col['x0']:.1f}, x1={col['x1']:.1f}]")
        print(f"  Total words: {len(w_in_c)}, Stable X-clusters: {len(clusters)}")
        for idx, cl in enumerate(clusters):
            print(f"    Cluster {idx}: x_mean={cl['x_mean']:.1f} [{cl['x_min']:.1f}..{cl['x_max']:.1f}], coverage={cl['coverage']:.0%}, samples={cl['sample_texts']}")

if __name__ == "__main__":
    test_on_invoice_gajanand()
