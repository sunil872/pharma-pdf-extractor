import sys, os
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
import pdfplumber
from extractor import extract_pdf_table, extract_coordinate_table, extract_page_words, detect_coordinate_header_row

with pdfplumber.open("Sample Invoices/INVOICE_7GX167AKM.PDF") as pdf:
    page = pdf.pages[0]
    words = extract_page_words(page)
    h_tokens, h_top, h_bot, conf = detect_coordinate_header_row(words, page.height)
    print("Coordinate header conf:", conf)
    if h_tokens:
        for h in h_tokens:
            print(f"  {h['text']:15} [{h['x0']:6.2f}..{h['x1']:6.2f}] field={h['field']}")
    c_hdrs, c_rows, c_conf, c_dbg = extract_coordinate_table(page, debug=True)
    print("\nCoordinate extraction conf:", c_conf, "rows:", len(c_rows), "headers:", c_hdrs)
