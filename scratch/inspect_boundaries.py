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

def inspect_doc(path):
    print("=" * 60)
    print("INSPECTING:", path)
    with pdfplumber.open(path) as pdf:
        for p_idx, page in enumerate(pdf.pages):
            words = extract_page_words(page)
            htokens, htop, hbot, hconf = detect_coordinate_header_row(words, float(page.height))
            print(f"--- Page {p_idx+1} ---")
            print(f"Header conf: {hconf:.2f}, htop: {htop:.1f}, hbot: {hbot:.1f}")
            for h in htokens:
                print(f"  Header token: '{h['raw']}' -> field '{h['field']}' [x0={h['x0']:.1f}, x1={h['x1']:.1f}, cx={h['center_x']:.1f}]")
            body_words = [w for w in words if w['top'] > hbot]
            cols = determine_column_boundaries(htokens, float(page.width), body_words=body_words)
            print("Physical columns:")
            for c in cols:
                print(f"  Col {c['index']}: '{c['header_text']}' ({c['field']}) -> [{c['x0']:.1f}, {c['x1']:.1f}], cx={c['center_x']:.1f}")

            headers, rows, conf, debug_info = extract_coordinate_table(page, debug=True)
            print(f"Extracted headers ({len(headers)}):", headers)
            print(f"Extracted rows ({len(rows)}):")
            for r in rows[:4]:
                print("  Row:", r)

if __name__ == "__main__":
    inspect_doc("Sample Invoices/INVOICE_7GU0X28XM.PDF")
    inspect_doc("Sample Invoices/Invoice.pdf")
    inspect_doc("Sample Invoices/Sunil_Medicare_Sample_Invoice.pdf")
