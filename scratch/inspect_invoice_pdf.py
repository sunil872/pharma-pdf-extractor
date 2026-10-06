import sys, os
sys.path.insert(0, os.path.abspath("."))
import pdfplumber
from extractor import (
    extract_page_words,
    detect_coordinate_header_row,
    determine_column_boundaries,
    detect_logical_subcolumns,
    extract_coordinate_table,
    extract_pdf_table
)

def inspect_invoice_pdf():
    path = "Sample Invoices/Invoice.pdf"
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        words = extract_page_words(page)
        htokens, htop, hbot, hconf = detect_coordinate_header_row(words, float(page.height))
        print(f"Header conf: {hconf:.2f}, htop: {htop:.1f}, hbot: {hbot:.1f}")
        for h in htokens:
            print(f"  Header token: '{h['raw']}' -> field '{h['field']}' [x0={h['x0']:.1f}, x1={h['x1']:.1f}, cx={h['center_x']:.1f}]")
        body_words = [w for w in words if w['top'] > hbot]
        cols = determine_column_boundaries(htokens, float(page.width), body_words=body_words)
        print("\nPhysical columns:")
        for c in cols:
            print(f"  Col {c['index']}: '{c['header_text']}' ({c['field']}) -> [{c['x0']:.1f}, {c['x1']:.1f}], cx={c['center_x']:.1f}")

        # Let's inspect words in the first 3 rows
        row_groups = []
        body_words_sorted = sorted(body_words, key=lambda w: (round(w["top"] / 5.0) * 5.0, w["x0"]))
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

        print(f"\nRow groups found: {len(row_groups)}")
        for r_idx, g in enumerate(row_groups[:3]):
            print(f"\n--- Row {r_idx} (top={g[0]['top']:.1f}) ---")
            for w in g:
                print(f"    Word: '{w['text']}' [x0={w['x0']:.1f}, x1={w['x1']:.1f}, cx={w['center_x']:.1f}]")

if __name__ == "__main__":
    inspect_invoice_pdf()
