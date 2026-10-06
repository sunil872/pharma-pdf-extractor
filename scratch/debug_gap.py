import sys, os
sys.path.insert(0, os.path.abspath("."))
import pdfplumber
from extractor import extract_page_words, detect_coordinate_header_row, match_column_name

path = "Sample Invoices/invoice (1).pdf"
with pdfplumber.open(path) as pdf:
    page = pdf.pages[0]
    words = extract_page_words(page)
    htokens, htop, hbot, hconf = detect_coordinate_header_row(words, float(page.height))
    sorted_headers = sorted(htokens, key=lambda h: h["center_x"])
    body_words = [w for w in words if w['top'] > hbot]
    
    h_left = sorted_headers[5] # ProductName
    h_right = sorted_headers[6] # Batch
    print("h_left:", h_left)
    print("h_right:", h_right)
    
    min_allowed_cut = max(h_left["x1"] - 2.0, h_left["center_x"] + 2.0)
    max_allowed_cut = min(h_right["x0"] + 2.0, h_right["center_x"] - 2.0)
    default_cut = max(min_allowed_cut, h_right["x0"] - 4.0)
    print("min_allowed_cut:", min_allowed_cut, "max_allowed_cut:", max_allowed_cut, "default_cut:", default_cut)
    
    region_words = [w for w in body_words if w["x1"] >= min_allowed_cut - 3.0 and w["x0"] <= max_allowed_cut + 3.0]
    intervals = sorted([(w["x0"], w["x1"]) for w in region_words], key=lambda x: x[0])
    merged = []
    for iv in intervals:
        if not merged or iv[0] > merged[-1][1]:
            merged.append(list(iv))
        else:
            merged[-1][1] = max(merged[-1][1], iv[1])
    print("Merged intervals:", merged)
    for j in range(len(merged) - 1):
        gap_start = merged[j][1]
        gap_end = merged[j + 1][0]
        gap_width = gap_end - gap_start
        mid = (gap_start + gap_end) / 2.0
        dist = abs(mid - default_cut)
        score = 25.0 + min(20.0, gap_width * 2.0) - dist * 0.2
        print(f"Gap {j}: [{gap_start:.1f}, {gap_end:.1f}], width={gap_width:.1f}, mid={mid:.1f}, dist={dist:.1f}, score={score:.1f}")
