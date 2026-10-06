import sys, os
sys.path.insert(0, os.path.abspath("."))
import pdfplumber
import re
from extractor import (
    extract_page_words,
    detect_coordinate_header_row,
    determine_column_boundaries,
    detect_logical_subcolumns,
    COORD_ROW_Y_TOLERANCE,
    COORD_COL_BOUNDARY_MARGIN,
    match_column_name,
)

def adaptive_determine_column_boundaries(header_tokens, page_width: float, table_bbox=None, body_words=None, page_lines=None, page_rects=None):
    if not header_tokens:
        return []

    sorted_headers = sorted(header_tokens, key=lambda h: h["center_x"])
    left_bound = table_bbox[0] if table_bbox else 10.0
    right_bound = table_bbox[2] if table_bbox else page_width - 10.0

    n = len(sorted_headers)
    cut_points = [0.0] * (n + 1)

    # Vertical ruling lines from page
    ruling_x = []
    if page_lines:
        for l in page_lines:
            if abs(l.get("x0", 0) - l.get("x1", 0)) < 1.0:  # vertical line
                length = abs(l.get("bottom", 0) - l.get("top", 0))
                if length > 20.0:
                    ruling_x.append((l["x0"] + l["x1"]) / 2.0)
    if page_rects:
        for r in page_rects:
            if r.get("height", 0) > 20.0:
                if r.get("width", 0) > 10.0:
                    ruling_x.append(r["x0"])
                    ruling_x.append(r["x1"])

    # Leftmost cut (cut_0)
    left_words = [w for w in body_words if w["center_x"] <= sorted_headers[0]["center_x"] + 10.0] if body_words else []
    cand_left = min([sorted_headers[0]["x0"]] + [w["x0"] for w in left_words]) - COORD_COL_BOUNDARY_MARGIN if left_words else sorted_headers[0]["x0"] - COORD_COL_BOUNDARY_MARGIN
    cut_points[0] = max(0.0, min(left_bound, cand_left))

    # Rightmost cut (cut_n)
    right_words = [w for w in body_words if w["center_x"] >= sorted_headers[-1]["center_x"] - 10.0] if body_words else []
    cand_right = max([sorted_headers[-1]["x1"]] + [w["x1"] for w in right_words]) + COORD_COL_BOUNDARY_MARGIN if right_words else sorted_headers[-1]["x1"] + COORD_COL_BOUNDARY_MARGIN
    cut_points[n] = min(page_width, max(right_bound, cand_right))

    # Intermediate cuts: find the best candidate boundary between adjacent headers
    for i in range(n - 1):
        h_left = sorted_headers[i]
        h_right = sorted_headers[i + 1]

        # Valid range for cut point: strictly between header centers
        min_allowed_cut = h_left["center_x"] + 2.0
        max_allowed_cut = h_right["center_x"] - 2.0
        if min_allowed_cut >= max_allowed_cut:
            min_allowed_cut = h_left["center_x"]
            max_allowed_cut = h_right["center_x"]

        # Default naive cut
        if h_left["x1"] < h_right["x0"]:
            default_cut = (h_left["x1"] + h_right["x0"]) / 2.0
        else:
            default_cut = (h_left["center_x"] + h_right["center_x"]) / 2.0
        default_cut = max(min_allowed_cut, min(max_allowed_cut, default_cut))

        candidates = [(default_cut, 10.0)]  # (cut_x, score)

        # Signal 1: Vertical ruling lines
        for rx in ruling_x:
            if min_allowed_cut <= rx <= max_allowed_cut:
                candidates.append((rx, 50.0))

        # Signal 2: Whitespace valleys between body words
        if body_words:
            region_words = [w for w in body_words if w["x1"] >= min_allowed_cut - 5.0 and w["x0"] <= max_allowed_cut + 5.0]
            if len(region_words) >= 2:
                intervals = sorted([(w["x0"], w["x1"]) for w in region_words], key=lambda x: x[0])
                merged = []
                for iv in intervals:
                    if not merged or iv[0] > merged[-1][1]:
                        merged.append(list(iv))
                    else:
                        merged[-1][1] = max(merged[-1][1], iv[1])

                for j in range(len(merged) - 1):
                    gap_start = merged[j][1]
                    gap_end = merged[j+1][0]
                    gap_width = gap_end - gap_start
                    if gap_width >= 1.5:
                        mid = (gap_start + gap_end) / 2.0
                        if min_allowed_cut <= mid <= max_allowed_cut:
                            dist = abs(mid - default_cut)
                            score = 25.0 + min(20.0, gap_width * 2.0) - dist * 0.2
                            candidates.append((mid, score))

        # Select highest scoring candidate
        candidates.sort(key=lambda c: c[1], reverse=True)
        chosen_cut = candidates[0][0]
        # Ensure strict monotonicity with previous cut point
        if chosen_cut <= cut_points[i] + 4.0:
            chosen_cut = cut_points[i] + max(5.0, (default_cut - cut_points[i]) * 0.5)
        cut_points[i + 1] = chosen_cut

    # Ensure rightmost cut is greater than penultimate cut
    if cut_points[n] <= cut_points[n - 1] + 4.0:
        cut_points[n] = cut_points[n - 1] + 15.0

    columns = []
    for i, h in enumerate(sorted_headers):
        columns.append({
            "index": i,
            "header_raw": h["raw"],
            "header_text": h["text"],
            "field": h["field"],
            "x0": cut_points[i],
            "x1": cut_points[i + 1],
            "center_x": h["center_x"],
        })

    # Intermediate / rightmost unnamed column discovery
    # 1. Check far right
    if body_words and n > 0:
        last_h = sorted_headers[-1]
        far_right_words = [w for w in body_words if w["x0"] > last_h["x1"] + 5.0]
        if len(far_right_words) >= 3:
            min_r_x0 = min(w["x0"] for w in far_right_words)
            max_r_x1 = max(w["x1"] for w in far_right_words)
            split_x = (last_h["x1"] + min_r_x0) / 2.0
            if split_x > columns[-1]["x0"] + 10.0:
                columns[-1]["x1"] = split_x
                unnamed_idx = len(columns)
                columns.append({
                    "index": unnamed_idx,
                    "header_raw": f"Unnamed_Col_{unnamed_idx}",
                    "header_text": f"Unnamed_Col_{unnamed_idx}",
                    "field": None,
                    "x0": split_x,
                    "x1": min(page_width, max(right_bound, max_r_x1 + COORD_COL_BOUNDARY_MARGIN)),
                    "center_x": (min_r_x0 + max_r_x1) / 2.0,
                })

    return columns


def score_token_column_assignment(word: dict, col: dict) -> float:
    """
    Computes an adaptive assignment score for placing a word token into a candidate column.
    Considers interval overlap, center containment, proximity, and semantic type affinity.
    """
    w_x0 = word["x0"]
    w_x1 = word["x1"]
    w_width = max(0.5, word.get("width", w_x1 - w_x0))
    w_cx = word.get("center_x", (w_x0 + w_x1) / 2.0)
    w_text = word.get("text", "").strip()

    c_x0 = col["x0"]
    c_x1 = col["x1"]
    c_cx = col.get("center_x", (c_x0 + c_x1) / 2.0)
    c_field = col.get("field")

    # 1. Interval Overlap
    overlap = max(0.0, min(w_x1, c_x1) - max(w_x0, c_x0))
    overlap_ratio = overlap / w_width

    # 2. Center Containment & Proximity
    center_contained = (c_x0 <= w_cx <= c_x1)
    center_dist = abs(w_cx - c_cx)

    score = overlap_ratio * 60.0
    if center_contained:
        score += 30.0
    score -= center_dist * 0.15

    # 3. Type Affinity / Protection
    is_numeric = bool(re.match(r"^[-+]?\d+(\.\d+)?%?$", w_text))
    is_date = bool(re.match(r"^\d{1,2}[/\-\.]\d{2,4}$", w_text))
    is_pure_alpha = bool(re.match(r"^[A-Za-z\s\(\)\/\-\+]+$", w_text) and not is_numeric)

    # Protection: Wide alphabetic text strongly prefers itemName / description over narrow numeric cols
    if is_pure_alpha and w_width > 25.0:
        if c_field in ("rate", "mrp", "amount", "taxableAmount", "netAmount", "quantity", "freeQuantity", "discountPercent", "gstPercent"):
            score -= 40.0
        elif c_field == "itemName":
            score += 20.0

    # Numeric affinity
    if is_numeric:
        if c_field in ("rate", "mrp", "amount", "taxableAmount", "netAmount", "quantity", "freeQuantity", "discountPercent", "gstPercent", "hsnCode"):
            score += 15.0
        elif c_field == "itemName" and not center_contained:
            score -= 15.0

    # Date affinity
    if is_date:
        if c_field == "expiryDate":
            score += 25.0

    return score


def adaptive_assign_tokens_to_columns(group: list, columns: list) -> tuple:
    """
    Assigns row word tokens to columns using interval overlap, center proximity, and type affinity.
    Returns (cell_words_dict, diagnostics_list)
    """
    cell_words = {i: [] for i in range(len(columns))}
    diagnostics = []

    for w in group:
        col_scores = []
        for col_i, col in enumerate(columns):
            s = score_token_column_assignment(w, col)
            col_scores.append((col_i, s))

        col_scores.sort(key=lambda x: x[1], reverse=True)
        best_col_idx, best_score = col_scores[0]
        second_idx, second_score = col_scores[1] if len(col_scores) > 1 else (None, -1e9)

        is_ambiguous = (best_score - second_score < 8.0) and (best_score > 10.0) and (second_score > 10.0)

        cell_words[best_col_idx].append(w)
        diagnostics.append({
            "token": w["text"],
            "x0": w["x0"],
            "x1": w["x1"],
            "center_x": w["center_x"],
            "assigned_column": columns[best_col_idx]["header_text"],
            "assigned_field": columns[best_col_idx].get("field"),
            "best_score": round(best_score, 2),
            "second_column": columns[second_idx]["header_text"] if second_idx is not None else None,
            "second_score": round(second_score, 2),
            "is_ambiguous": is_ambiguous,
        })

    return cell_words, diagnostics

def test_table_extraction(pdf_path):
    print("=" * 60)
    print("TESTING:", pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        for p_idx, page in enumerate(pdf.pages):
            words = extract_page_words(page)
            htokens, htop, hbot, hconf = detect_coordinate_header_row(words, float(page.height))
            if not htokens or hconf < 0.40:
                print(f"Page {p_idx+1}: No headers found (conf={hconf:.2f})")
                continue
            body_words = [w for w in words if w["top"] > hbot]
            cols = adaptive_determine_column_boundaries(
                htokens, float(page.width), body_words=body_words,
                page_lines=getattr(page, "lines", None), page_rects=getattr(page, "rects", None)
            )

            # Group body words into rows
            body_words_sorted = sorted(body_words, key=lambda w: (round(w["top"] / COORD_ROW_Y_TOLERANCE) * COORD_ROW_Y_TOLERANCE, w["x0"]))
            row_groups = []
            curr_group = []
            curr_y = None
            for w in body_words_sorted:
                if curr_y is None or abs(w["top"] - curr_y) <= COORD_ROW_Y_TOLERANCE:
                    curr_group.append(w)
                    curr_y = w["top"] if curr_y is None else (curr_y * len(curr_group) + w["top"]) / (len(curr_group) + 1)
                else:
                    row_groups.append(curr_group)
                    curr_group = [w]
                    curr_y = w["top"]
            if curr_group:
                row_groups.append(curr_group)

            logical_cols, split_diag = detect_logical_subcolumns(cols, row_groups)
            print(f"Page {p_idx+1} Logical Cols ({len(logical_cols)}):", [c["header_text"] for c in logical_cols])

            raw_rows = []
            for group in row_groups:
                cell_words, diag = adaptive_assign_tokens_to_columns(group, logical_cols)
                row_cells = [""] * len(logical_cols)
                for c_i, ws in cell_words.items():
                    if ws:
                        ws.sort(key=lambda x: x["x0"])
                        row_cells[c_i] = " ".join(w["text"] for w in ws).strip()
                if any(row_cells):
                    raw_rows.append(row_cells)

            print(f"Page {p_idx+1} Raw Rows extracted: {len(raw_rows)}")
            for r in raw_rows[:3]:
                print("  Sample Row:", r)

if __name__ == "__main__":
    test_table_extraction("Sample Invoices/Sunil_Medicare_Sample_Invoice.pdf")
    test_table_extraction("Sample Invoices/Invoice.pdf")

