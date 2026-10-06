import pdfplumber, glob, os, sys, re
sys.path.insert(0, os.getcwd())
import pandas as pd
from rapidfuzz import process, fuzz
from extractor import (
    ALIAS_DICT, match_column_name, clean_text,
    _is_valid_header_row, _is_footer_row, _is_letterhead_row,
    _is_genuine_product_row, _looks_like_item_row, _looks_like_primary_item_row,
    ensure_named_headers, resolve_column_mappings, extract_pdf_table
)

# Configurable coordinate extraction constants
COORD_HEADER_Y_TOLERANCE = 3.5
COORD_HEADER_X_GAP_TOLERANCE = 8.0
COORD_ROW_Y_TOLERANCE = 4.5
COORD_ITEM_CONTINUATION_Y_GAP = 12.0
COORD_COL_BOUNDARY_MARGIN = 3.0

def extract_page_words(page):
    raw_words = page.extract_words(
        x_tolerance=2, y_tolerance=2,
        keep_blank_chars=False, use_text_flow=False
    ) or []
    words = []
    for w in raw_words:
        x0 = float(w["x0"])
        x1 = float(w["x1"])
        top = float(w["top"])
        bottom = float(w["bottom"])
        words.append({
            "text": str(w["text"]).strip(),
            "x0": x0,
            "x1": x1,
            "top": top,
            "bottom": bottom,
            "center_x": (x0 + x1) / 2.0,
            "center_y": (top + bottom) / 2.0,
            "width": float(w.get("width", x1 - x0)),
            "height": float(w.get("height", bottom - top)),
            "doctop": float(w.get("doctop", top)),
        })
    return words

def reconstruct_header_tokens(words, y_tolerance=COORD_HEADER_Y_TOLERANCE, x_gap_tolerance=COORD_HEADER_X_GAP_TOLERANCE):
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (round(w["top"] / y_tolerance) * y_tolerance, w["x0"]))
    lines = []
    curr_line = []
    curr_y = None
    for w in sorted_words:
        if curr_y is None or abs(w["top"] - curr_y) <= y_tolerance:
            curr_line.append(w)
            curr_y = w["top"] if curr_y is None else (curr_y * len(curr_line) + w["top"]) / (len(curr_line) + 1)
        else:
            lines.append(sorted(curr_line, key=lambda x: x["x0"]))
            curr_line = [w]
            curr_y = w["top"]
    if curr_line:
        lines.append(sorted(curr_line, key=lambda x: x["x0"]))
    
    reconstructed_lines = []
    for line in lines:
        merged = []
        i = 0
        while i < len(line):
            curr = dict(line[i])
            while i + 1 < len(line):
                nxt = line[i + 1]
                gap = nxt["x0"] - curr["x1"]
                combined_no_space = curr["text"] + nxt["text"]
                combined_space = curr["text"] + " " + nxt["text"]
                
                is_known_split = match_column_name(combined_no_space) is not None and match_column_name(curr["text"]) is None
                is_phrase_header = match_column_name(combined_space) is not None
                is_small_gap = 0 <= gap <= x_gap_tolerance
                
                if (is_small_gap and (is_known_split or is_phrase_header or len(curr["text"]) <= 3 or len(nxt["text"]) <= 3)) or (0 <= gap <= 2.5):
                    if is_known_split:
                        curr["text"] = combined_no_space
                    else:
                        curr["text"] = combined_space
                    curr["x1"] = max(curr["x1"], nxt["x1"])
                    curr["bottom"] = max(curr["bottom"], nxt["bottom"])
                    curr["center_x"] = (curr["x0"] + curr["x1"]) / 2.0
                    curr["center_y"] = (curr["top"] + curr["bottom"]) / 2.0
                    i += 1
                else:
                    break
            merged.append(curr)
            i += 1
        reconstructed_lines.append(merged)
    return reconstructed_lines

def detect_coordinate_header_row(words, page_height, saved_template=None):
    lines = reconstruct_header_tokens(words)
    best_line = None
    best_score = -1
    best_idx = None
    
    scan_limit_y = page_height * 0.65
    for idx, line in enumerate(lines):
        if not line or line[0]["top"] > scan_limit_y:
            continue
        mapped = [match_column_name(w["text"], saved_template) for w in line]
        valid_mapped = [m for m in mapped if m]
        unique_fields = set(valid_mapped)
        
        # Check two-line header case (e.g. QTY \n BILLED FREE)
        if idx + 1 < len(lines) and abs(lines[idx + 1][0]["top"] - line[0]["bottom"]) <= 10.0:
            sub_line = lines[idx + 1]
            sub_mapped = [match_column_name(w["text"], saved_template) for w in sub_line]
            sub_valid = [m for m in sub_mapped if m]
            combined_fields = set(valid_mapped + sub_valid)
            score = len(combined_fields) * 15 + len(valid_mapped) * 5
        else:
            score = len(unique_fields) * 15 + len(valid_mapped) * 5
            
        if "itemName" in unique_fields:
            score += 25
            
        if len(unique_fields) >= 2 and score > best_score:
            best_score = score
            best_line = line
            best_idx = idx

    if best_line is None:
        return None, None, None, 0.0

    # Build header tokens
    header_tokens = []
    for w in best_line:
        field = match_column_name(w["text"], saved_template)
        header_tokens.append({
            "raw": w["text"],
            "text": w["text"],
            "field": field,
            "x0": w["x0"],
            "x1": w["x1"],
            "center_x": w["center_x"],
            "top": w["top"],
            "bottom": w["bottom"],
        })
    
    header_top = min(w["top"] for w in best_line)
    header_bottom = max(w["bottom"] for w in best_line)
    
    # Check if subheader row should be absorbed into column boundaries
    if best_idx is not None and best_idx + 1 < len(lines):
        sub_line = lines[best_idx + 1]
        if sub_line and abs(sub_line[0]["top"] - header_bottom) <= 10.0:
            # Check if sub_line contains non-numeric header tokens (not a data row)
            has_digits = any(re.search(r"\d{3,}", w["text"]) for w in sub_line)
            if not has_digits:
                header_bottom = max(header_bottom, max(w["bottom"] for w in sub_line))

    conf = min(1.0, best_score / 120.0)
    return header_tokens, header_top, header_bottom, conf

def determine_column_boundaries(header_tokens, page_width, table_bbox=None):
    if not header_tokens:
        return []
    
    sorted_headers = sorted(header_tokens, key=lambda h: h["center_x"])
    left_bound = table_bbox[0] if table_bbox else 10.0
    right_bound = table_bbox[2] if table_bbox else page_width - 10.0
    
    columns = []
    n = len(sorted_headers)
    for i, h in enumerate(sorted_headers):
        # Left boundary
        if i == 0:
            col_x0 = max(0.0, min(left_bound, h["x0"] - COORD_COL_BOUNDARY_MARGIN))
        else:
            prev = sorted_headers[i - 1]
            col_x0 = (prev["x1"] + h["x0"]) / 2.0 if prev["x1"] < h["x0"] else (prev["center_x"] + h["center_x"]) / 2.0
            
        # Right boundary
        if i == n - 1:
            col_x1 = min(page_width, max(right_bound, h["x1"] + COORD_COL_BOUNDARY_MARGIN))
        else:
            nxt = sorted_headers[i + 1]
            col_x1 = (h["x1"] + nxt["x0"]) / 2.0 if h["x1"] < nxt["x0"] else (h["center_x"] + nxt["center_x"]) / 2.0
            
        columns.append({
            "index": i,
            "header_raw": h["raw"],
            "header_text": h["text"],
            "field": h["field"],
            "x0": col_x0,
            "x1": col_x1,
            "center_x": h["center_x"],
        })
    return columns

def extract_coordinate_table(page, saved_template=None, expected_cols=None, debug=False):
    words = extract_page_words(page)
    if not words:
        return [], [], 0.0, {}
    
    page_width = float(page.width or 612.0)
    page_height = float(page.height or 792.0)
    
    tables = page.find_tables()
    table_bbox = tables[0].bbox if tables else None
    
    header_tokens, header_top, header_bottom, header_conf = detect_coordinate_header_row(
        words, page_height, saved_template=saved_template
    )
    if not header_tokens or header_conf < 0.40:
        return [], [], 0.0, {}
    
    columns = determine_column_boundaries(header_tokens, page_width, table_bbox=table_bbox)
    headers = [c["header_text"] for c in columns]
    item_idx = None
    for i, c in enumerate(columns):
        if c["field"] == "itemName":
            item_idx = i
            break
            
    # Filter body words
    body_words = [w for w in words if w["top"] >= header_bottom + 1.0]
    
    # Check footer cutoff
    footer_top = page_height
    for w in body_words:
        lowered = w["text"].lower()
        if any(fw in lowered for fw in ["bank name", "terms", "condition", "authorised signatory", "authorized signatory", "grand total"]):
            if w["top"] < footer_top and w["top"] > header_bottom + 30.0:
                footer_top = min(footer_top, w["top"])
                
    body_words = [w for w in body_words if w["bottom"] <= footer_top + 2.0]
    
    # Group body words by vertical lines
    body_words_sorted = sorted(body_words, key=lambda w: (round(w["top"] / COORD_ROW_Y_TOLERANCE) * COORD_ROW_Y_TOLERANCE, w["x0"]))
    row_groups = []
    curr_group = []
    curr_y = None
    for w in body_words_sorted:
        if curr_y is None or abs(w["top"] - curr_y) <= COORD_ROW_Y_TOLERANCE:
            curr_group.append(w)
            curr_y = w["top"] if curr_y is None else (curr_y * len(curr_group) + w["top"]) / (len(curr_group) + 1)
        else:
            row_groups.append(curr_group)
            curr_group = [w]
            curr_y = w["top"]
    if curr_group:
        row_groups.append(curr_group)
        
    # Reconstruct rows by assigning words to columns
    raw_rows = []
    row_records = []
    for g_idx, group in enumerate(row_groups):
        row_cells = [""] * len(columns)
        cell_words = {i: [] for i in range(len(columns))}
        
        for w in group:
            # Find best column for word
            best_col = None
            best_dist = 1e9
            for col in columns:
                if col["x0"] <= w["center_x"] < col["x1"]:
                    best_col = col["index"]
                    break
                # Distance to column boundaries if outside
                dist = min(abs(w["center_x"] - col["x0"]), abs(w["center_x"] - col["x1"]))
                if dist < best_dist:
                    best_dist = dist
                    best_col = col["index"]
                    
            if best_col is not None:
                cell_words[best_col].append(w)
                
        for col_i, words_in_col in cell_words.items():
            if words_in_col:
                words_in_col.sort(key=lambda x: x["x0"])
                row_cells[col_i] = " ".join(w["text"] for w in words_in_col).strip()
                
        # Check if genuine product row or continuation row
        if _is_footer_row(row_cells) or _is_letterhead_row(row_cells):
            continue
            
        raw_rows.append(row_cells)
        row_records.append({
            "row_index": g_idx,
            "cells": {columns[i]["header_text"]: {"text": row_cells[i], "words": cell_words[i]} for i in range(len(columns))},
            "top": min(w["top"] for w in group) if group else 0.0,
            "bottom": max(w["bottom"] for w in group) if group else 0.0,
        })
        
    # Merge continuation rows
    from extractor import _merge_continuation_rows
    merged_rows = _merge_continuation_rows(raw_rows, item_idx=item_idx)
    genuine_rows = [r for r in merged_rows if _is_genuine_product_row(r, item_idx=item_idx)]
    
    conf = header_conf * (min(len(genuine_rows), 20) / 10.0)
    conf = min(1.0, max(0.0, conf))
    
    debug_info = {
        "header_top": header_top,
        "header_bottom": header_bottom,
        "columns": columns,
        "raw_rows_count": len(raw_rows),
        "genuine_rows_count": len(genuine_rows),
    } if debug else {}
    
    return headers, genuine_rows, conf, debug_info

def run_comparison():
    samples = sorted(glob.glob("Sample Invoices/*.[pP][dD][fF]"))
    print("=================================================================")
    print("COMPARISON: COORDINATE EXTRACTION VS V1 TABLE EXTRACTION")
    print("=================================================================")
    for s in samples:
        bname = os.path.basename(s)
        with pdfplumber.open(s) as pdf:
            p0 = pdf.pages[0]
            c_hdrs, c_rows, c_conf, _ = extract_coordinate_table(p0, debug=True)
            v1_meta, v1_hdrs, v1_maps, v1_rows = extract_pdf_table(s)
            print(f"\n[FILE]: {bname} (Pages: {len(pdf.pages)})")
            print(f"  Coordinate extraction: {len(c_rows)} rows | {len(c_hdrs)} cols | Conf: {c_conf:.0%}")
            print(f"  V1 extraction        : {len(v1_rows)} rows | {len(v1_hdrs)} cols")
            if c_rows:
                print(f"  Sample Coord Row 1   : {c_rows[0][:5]}")
            if v1_rows:
                print(f"  Sample V1 Row 1      : {v1_rows[0][:5]}")

if __name__ == "__main__":
    run_comparison()
