import sys, os
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
import pdfplumber
from extractor import (
    extract_page_words,
    detect_coordinate_header_row,
    determine_column_boundaries,
    detect_logical_subcolumns,
)

with pdfplumber.open("Sample Invoices/INVOICE_7HH0S5IPC.PDF") as pdf:
    words = extract_page_words(pdf.pages[0])
    h_tokens, h_top, h_bot, conf = detect_coordinate_header_row(words, pdf.pages[0].height)
    print("Detected headers from detect_coordinate_header_row:")
    for h in h_tokens:
        print(f"  {h['text']:15} [{h['x0']:6.2f}..{h['x1']:6.2f}]")
        
    cols = determine_column_boundaries(h_tokens, pdf.pages[0].width)
    print("\nPhysical columns from determine_column_boundaries:")
    for c in cols:
        print(f"  Col {c['index']:2d}: {c['header_text']:15} [{c['x0']:6.2f}..{c['x1']:6.2f}]")

    body_words = [w for w in words if w["top"] >= h_bot + 1.0 and w["bottom"] <= 400.0]
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

    log_cols, diag = detect_logical_subcolumns(cols, row_groups, debug=True)
    print("\nLogical columns after detect_logical_subcolumns:")
    for lc in log_cols:
        print(f"  LogCol {lc['logical_index']:2d}: {lc['header_text']:15} [{lc['x0']:6.2f}..{lc['x1']:6.2f}] status={lc['status']} prov={lc['provenance']}")
    print("\nDiagnostics:")
    for k, v in diag.items():
        print(f"  {k}: {v}")
