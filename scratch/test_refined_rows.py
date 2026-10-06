import sys, os
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
import pdfplumber
from extractor import (
    extract_page_words,
    determine_column_boundaries,
    match_column_name,
    _is_footer_row,
    _is_letterhead_row,
    _merge_continuation_rows,
    _is_genuine_product_row,
)

with pdfplumber.open("Sample Invoices/INVOICE_7HH0S5IPC.PDF") as pdf:
    page = pdf.pages[0]
    words = extract_page_words(page)
    
    # Custom token reconstruction rule preventing merge of distinct fields
    lines = []
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

                if f_curr is not None and f_nxt is not None and f_curr != f_nxt:
                    break

                is_known_split = f_comb_nospace is not None and f_curr is None
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

    # find best header line
    header_line = [l for l in reconstructed_lines if 105 <= l[0]["top"] <= 120][0]
    header_bottom = max(w["bottom"] for w in header_line)

    cols = determine_column_boundaries([
        {"raw": t["text"], "text": t["text"], "field": match_column_name(t["text"]),
         "x0": t["x0"], "x1": t["x1"], "center_x": t["center_x"], "top": t["top"], "bottom": t["bottom"]}
        for t in header_line
    ], page.width)

    body_words = [w for w in words if w["top"] >= header_bottom + 1.0 and w["bottom"] <= 400.0]
    body_words_sorted = sorted(body_words, key=lambda w: (round(w["top"] / 5.0) * 5.0, w["x0"]))
    row_groups = []
    curr_group = []
    curr_y = None
    for w in body_words_sorted:
        if curr_y is None or abs(w["top"] - curr_y) <= 5.0:
            curr_group.append(w)
            curr_y = w["top"] if curr_y is None else (curr_y * len(curr_group) + w["top"]) / (len(curr_group) + 1)
        else:
            row_groups.append(curr_group)
            curr_group = [w]
            curr_y = w["top"]
    if curr_group:
        row_groups.append(curr_group)

    raw_rows = []
    for g in row_groups:
        row_cells = [""] * len(cols)
        cell_words = {i: [] for i in range(len(cols))}
        for w in g:
            best_col = None
            for c in cols:
                if c["x0"] <= w["center_x"] < c["x1"]:
                    best_col = c["index"]
                    break
            if best_col is not None:
                cell_words[best_col].append(w)
        for i, ws in cell_words.items():
            if ws:
                ws.sort(key=lambda x: x["x0"])
                row_cells[i] = " ".join(x["text"] for x in ws).strip()
        if not _is_footer_row(row_cells) and not _is_letterhead_row(row_cells):
            raw_rows.append(row_cells)

    merged_rows = _merge_continuation_rows(raw_rows, item_idx=1)
    genuine_rows = [r for r in merged_rows if _is_genuine_product_row(r, item_idx=1)]

    print(f"Extracted {len(genuine_rows)} genuine rows. First 5 rows:")
    headers = [c["header_text"] for c in cols]
    print(f"{' | '.join(headers)}")
    for r in genuine_rows[:5]:
        print(f"{' | '.join(r)}")
