import sys, os
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
import pdfplumber
from extractor import extract_pdf_table, extract_page_words, detect_coordinate_header_row, reconstruct_header_tokens

with pdfplumber.open("Sample Invoices/INVOICE_7HH0S5IPC.PDF") as pdf:
    words = extract_page_words(pdf.pages[0])
    h_words = [w for w in words if 105 <= w["top"] <= 120]
    h_words.sort(key=lambda w: w["x0"])
    for idx, w in enumerate(h_words):
        gap = (w["x0"] - h_words[idx-1]["x1"]) if idx > 0 else 0
        print(f"  word: {w['text']:15} x0={w['x0']:6.2f} x1={w['x1']:6.2f} gap={gap:6.2f}")
