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

def inspect_7hh0s5ipc():
    path = "Sample Invoices/INVOICE_7HH0S5IPC.PDF"
    with pdfplumber.open(path) as pdf:
        page = pdf.pages[0]
        words = extract_page_words(page)
        htokens, htop, hbot, hconf = detect_coordinate_header_row(words, float(page.height))
        print("Header Tokens:")
        for h in htokens:
            print(f"  {h['raw']} [{h['x0']:.1f}, {h['x1']:.1f}], cx={h['center_x']:.1f}")
        body_words = [w for w in words if w['top'] > hbot]
        cols = determine_column_boundaries(htokens, float(page.width), body_words=body_words, page_lines=page.lines, page_rects=page.rects)
        print("Physical Columns:")
        for c in cols:
            print(f"  Col {c['index']}: '{c['header_text']}' [{c['x0']:.1f}, {c['x1']:.1f}], cx={c['center_x']:.1f}")
        headers, rows, conf, debug_info = extract_coordinate_table(page, debug=True)
        print("Headers:", headers)
        print(f"Rows ({len(rows)}):")
        for r in rows:
            print("  ", r)

if __name__ == "__main__":
    inspect_7hh0s5ipc()
