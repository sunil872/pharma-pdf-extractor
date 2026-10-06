import sys, os
sys.path.insert(0, os.path.abspath("."))
import pdfplumber

with pdfplumber.open("Sample Invoices/invoice (1).pdf") as pdf:
    for page_idx, page in enumerate(pdf.pages):
        print(f"\n=== PAGE {page_idx+1} ===")
        words = page.extract_words()
        # Sort words by top, x0
        words_sorted = sorted(words, key=lambda w: (w["top"], w["x0"]))
        for w in words_sorted:
            if w["top"] > 400: # bottom half of page
                print(f"y={w['top']:.1f}-{w['bottom']:.1f}, x={w['x0']:.1f}-{w['x1']:.1f}: {w['text']}")
