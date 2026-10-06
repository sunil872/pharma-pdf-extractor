import sys, os
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
import pdfplumber
from extractor import (
    extract_page_words,
    reconstruct_header_tokens,
    detect_coordinate_header_row,
    determine_column_boundaries,
    match_column_name,
)

with pdfplumber.open("Sample Invoices/INVOICE_7HH0S5IPC.PDF") as pdf:
    page = pdf.pages[0]
    words = extract_page_words(page)
    
    # Custom token reconstruction rule preventing merge of distinct fields
    lines = []
    # group by Y
    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    curr_line = []
    curr_y = None
    for w in sorted_words:
        if curr_y is None or abs(w["top"] - curr_y) <= 3.0:
            curr_line.append(w)
            curr_y = w["top"] if curr_y is None else (curr_y * len(curr_line) + w["top"]) / (len(curr_line) + 1)
        else:
            lines.append(sorted(curr_line, key=lambda x: x["x0"]))
            curr_line = [w]
            curr_y = w["top"]
    if curr_line:
        lines.append(sorted(curr_line, key=lambda x: x["x0"]))
        
    # Reconstruct tokens with canonical field check
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

                f_curr = match_column_name(curr["text"])
                f_nxt = match_column_name(nxt["text"])
                f_comb_space = match_column_name(combined_space)
                f_comb_nospace = match_column_name(combined_no_space)

                # Never merge if both are distinct canonical fields
                if f_curr is not None and f_nxt is not None and f_curr != f_nxt:
                    break

                # Merge split word fragments (e.g. PT+R -> PTR, MR+P -> MRP)
                is_known_split = f_comb_nospace is not None and f_curr is None
                # Merge multi-word header phrases (e.g. PRODUCT NAME, BATCH NO)
                is_phrase_header = f_comb_space is not None and (f_curr is None or f_nxt is None or f_curr == f_comb_space)
                
                is_small_gap = 0 <= gap <= 8.0
                is_kerning_gap = 0 <= gap <= 1.5

                if is_known_split or (is_phrase_header and is_small_gap) or (is_kerning_gap and f_curr is None and f_nxt is None):
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

    # Detect header row
    for line in reconstructed_lines:
        if 105 <= line[0]["top"] <= 120:
            print(f"Detected {len(line)} header tokens:")
            for t in line:
                f = match_column_name(t["text"])
                print(f"  {t['text']:15} [{t['x0']:6.2f}..{t['x1']:6.2f}] field={f}")
                
            cols = determine_column_boundaries([
                {"raw": t["text"], "text": t["text"], "field": match_column_name(t["text"]),
                 "x0": t["x0"], "x1": t["x1"], "center_x": t["center_x"], "top": t["top"], "bottom": t["bottom"]}
                for t in line
            ], page.width)
            
            print(f"\nCreated {len(cols)} column boundaries:")
            for c in cols:
                print(f"  Col {c['index']:2d}: {c['header_text']:15} [{c['x0']:6.2f}..{c['x1']:6.2f}] -> {c['field']}")
