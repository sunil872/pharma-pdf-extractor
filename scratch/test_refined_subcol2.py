import sys, os
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
import pdfplumber
from extractor import (
    extract_page_words,
    detect_coordinate_header_row,
    determine_column_boundaries,
    match_column_name,
)

def test_refined_subcol():
    with pdfplumber.open("Sample Invoices/INVOICE_7HH0S5IPC.PDF") as pdf:
        words = extract_page_words(pdf.pages[0])
        h_tokens, h_top, h_bot, conf = detect_coordinate_header_row(words, pdf.pages[0].height)
        cols = determine_column_boundaries(h_tokens, pdf.pages[0].width)
        
        print("Physical columns detected:")
        for c in cols:
            f = match_column_name(c["header_text"])
            print(f"  Col {c['index']:2d}: {c['header_text']:15} [{c['x0']:6.2f}..{c['x1']:6.2f}] field={f}")

test_refined_subcol()
