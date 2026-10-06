import sys, os
sys.path.insert(0, os.path.abspath("."))
import pdfplumber

path = "Sample Invoices/invoice (1).pdf"
with pdfplumber.open(path) as pdf:
    page = pdf.pages[0]
    for l in page.lines:
        if abs(l["x0"] - l["x1"]) < 1.0:
            print(f"Vertical line: x0={l['x0']:.1f}, x1={l['x1']:.1f}, top={l['top']:.1f}, bot={l['bottom']:.1f}, len={l['bottom']-l['top']:.1f}")
