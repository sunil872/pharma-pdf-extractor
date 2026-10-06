import pdfplumber, glob, os, sys, re
sys.path.insert(0, os.getcwd())
import pandas as pd
from rapidfuzz import process, fuzz
from extractor import (
    ALIAS_DICT, match_column_name, clean_text,
    _is_valid_header_row, _is_footer_row, _is_letterhead_row,
    _is_genuine_product_row, ensure_named_headers, resolve_column_mappings
)

# Configurable coordinate extraction constants
COORD_HEADER_Y_TOLERANCE = 3.5
COORD_HEADER_X_GAP_TOLERANCE = 6.0
COORD_ROW_Y_TOLERANCE = 4.0
COORD_ITEM_CONTINUATION_Y_GAP = 12.0
COORD_COL_BOUNDARY_MARGIN = 2.0

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
    """
    Horizontally merges adjacent words that belong to the same visual column header.
    Handles split headers like 'PT' + 'R', 'MR' + 'P', 'RAT' + 'E', 'BATCH' + 'NO.'
    """
    if not words:
        return []
    
    # Sort words primarily by top (Y), then by x0 (X)
    sorted_words = sorted(words, key=lambda w: (round(w["top"] / y_tolerance) * y_tolerance, w["x0"]))
    
    # Group into rough Y lines
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
            # Check if next word can be merged with curr
            while i + 1 < len(line):
                nxt = line[i + 1]
                gap = nxt["x0"] - curr["x1"]
                
                # Check known split header pattern (e.g. PT + R, MR + P, RAT + E, S + NO)
                combined_no_space = curr["text"] + nxt["text"]
                combined_space = curr["text"] + " " + nxt["text"]
                
                is_known_split = match_column_name(combined_no_space) is not None and match_column_name(curr["text"]) is None
                is_phrase_header = match_column_name(combined_space) is not None
                is_small_gap = 0 <= gap <= x_gap_tolerance
                
                if (is_small_gap and (is_known_split or is_phrase_header or len(curr["text"]) <= 3 or len(nxt["text"]) <= 3)) or (0 <= gap <= 2.5):
                    # Merge words
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

def test_on_samples():
    samples = sorted(glob.glob("Sample Invoices/*.[pP][dD][fF]"))
    for s in samples:
        with pdfplumber.open(s) as pdf:
            p0 = pdf.pages[0]
            words = extract_page_words(p0)
            lines = reconstruct_header_tokens(words)
            print(f"\n--- {os.path.basename(s)} ---")
            for idx, line in enumerate(lines[:25]):
                matched = [f"{w['text']} -> {match_column_name(w['text'])}" for w in line if match_column_name(w['text'])]
                if len(matched) >= 3:
                    print(f"Header candidate line {idx} (Y={line[0]['top']:.1f}):", [w['text'] for w in line])
                    print("  Matched canonical fields:", matched)

if __name__ == "__main__":
    test_on_samples()
