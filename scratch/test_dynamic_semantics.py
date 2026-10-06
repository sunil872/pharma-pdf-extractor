import os, sys, glob, re
sys.path.insert(0, os.getcwd())
import pandas as pd
from rapidfuzz import process, fuzz
from extractor import (
    ALIAS_DICT, SYSTEM_COLUMNS, match_column_name, clean_text,
    parse_compound_qty, standardize_date, _to_float, is_serial_number_header
)

# Canonical system fields
CANONICAL_FIELDS = list(SYSTEM_COLUMNS.keys())

PACK_PATTERN = re.compile(r"(?i)\b(\d+['`’]s|\d+\s*s|\d+x\d+|\d+\*\d+|\d+\s*(?:ml|gm|mg|tab|cap|vial|amp|btl|strip|box))\b")
PHARMA_ITEM_WORDS = {
    "tab", "caps", "cap", "syp", "inj", "gel", "susp", "oint", "drops", "cream",
    "tablet", "capsule", "syrup", "injection", "ointment", "powder", "lotion",
    "solution", "emulsion", "pharma", "mg", "ml", "gm", "forte", "plus", "duo",
    "ds", "dry", "dt", "sr", "er", "cr", "xl", "xr", "mr"
}

def profile_single_column(col_idx, header_raw, values, x0=None, x1=None, total_cols=None):
    total = len(values)
    non_empty = [str(v).strip() for v in values if v is not None and str(v).strip() != ""]
    n_count = len(non_empty)
    if n_count == 0:
        return {
            "col_idx": col_idx,
            "header_raw": header_raw,
            "non_empty_count": 0,
            "total_count": total,
            "empty": True,
        }

    # Data type counters
    numeric_count = 0
    decimal_count = 0
    integer_count = 0
    text_count = 0
    date_count = 0
    percentage_count = 0
    
    # Specific pattern counters
    hsn_like_count = 0
    expiry_like_count = 0
    quantity_like_count = 0
    free_qty_like_count = 0
    discount_like_count = 0
    gst_like_count = 0
    mrp_rate_like_count = 0
    amount_like_count = 0
    company_like_count = 0
    pack_like_count = 0
    item_name_like_count = 0
    batch_like_count = 0

    lengths = []
    numeric_vals = []
    unique_vals = set(non_empty)

    for val in non_empty:
        lengths.append(len(val))
        cleaned = clean_text(val)
        
        # Date check
        std_date = standardize_date(val)
        is_date = std_date is not None or bool(re.match(r"^\d{1,2}[/-]\d{2,4}$", val))
        if is_date:
            date_count += 1
            expiry_like_count += 1

        # Numeric check
        f_val = _to_float(val)
        if f_val is not None and not is_date:
            numeric_count += 1
            numeric_vals.append(f_val)
            if "." in val:
                decimal_count += 1
            else:
                integer_count += 1
                
            # HSN check: pure digits, length 4, 6, or 8, no decimal, no letters
            if re.fullmatch(r"\d{4}|\d{6}|\d{8}", cleaned):
                hsn_like_count += 1

            # Quantity check
            billed, free = parse_compound_qty(val)
            if billed > 0 or free > 0 or (0.0 < f_val <= 10000 and (f_val.is_integer() or f_val in [0.5, 1.5, 2.5, 5.0])):
                quantity_like_count += 1
                
            # Free Qty check
            if f_val == 0.0 or free > 0 or (0.0 <= f_val <= 50 and f_val.is_integer()):
                free_qty_like_count += 1

            # Percentage checks (Discount vs GST)
            if 0.0 <= f_val <= 100.0:
                percentage_count += 1
                if f_val in [0.0, 5.0, 12.0, 18.0, 28.0, 2.5, 6.0, 9.0, 14.0]:
                    gst_like_count += 1
                if 0.0 <= f_val <= 50.0:
                    discount_like_count += 1

            # Monetary check (MRP, Rate, Amount)
            if f_val > 0 and (decimal_count > 0 or f_val >= 10.0):
                mrp_rate_like_count += 1
                if f_val >= 50.0:
                    amount_like_count += 1
        else:
            # Text check
            if not is_date:
                text_count += 1

        # Alphanumeric Batch check
        if re.search(r"[A-Za-z]", val) and re.search(r"\d", val) and 3 <= len(val) <= 15:
            batch_like_count += 1
        elif re.match(r"^[A-Z0-9/-]{4,12}$", val) and not re.fullmatch(r"\d+", val):
            batch_like_count += 1

        # Pack check
        if PACK_PATTERN.search(val) or val.upper() in ["10S", "10'S", "15S", "100ML", "60ML", "5GM", "10ML"]:
            pack_like_count += 1

        # Company check: short uppercase code
        if 2 <= len(val) <= 8 and val.isupper() and re.search(r"[A-Z]{2,}", val) and not re.search(r"\d{3,}", val):
            company_like_count += 1

        # Item Name check: longer text with letters or pharma dosage forms
        has_pharma_word = any(pw in val.lower().split() for pw in PHARMA_ITEM_WORDS)
        if (len(val) >= 7 and re.search(r"[A-Za-z]{3,}", val)) or has_pharma_word:
            item_name_like_count += 1

    return {
        "col_idx": col_idx,
        "header_raw": header_raw,
        "x0": x0,
        "x1": x1,
        "center_x": (x0 + x1) / 2.0 if (x0 is not None and x1 is not None) else None,
        "width": (x1 - x0) if (x0 is not None and x1 is not None) else None,
        "relative_pos": (col_idx / max(1, (total_cols - 1))) if total_cols else 0.5,
        "non_empty_count": n_count,
        "total_count": total,
        "fill_ratio": n_count / max(1, total),
        "unique_ratio": len(unique_vals) / max(1, n_count),
        "avg_length": sum(lengths) / max(1, len(lengths)),
        "numeric_ratio": numeric_count / max(1, n_count),
        "decimal_ratio": decimal_count / max(1, n_count),
        "integer_ratio": integer_count / max(1, n_count),
        "text_ratio": text_count / max(1, n_count),
        "date_ratio": date_count / max(1, n_count),
        "hsn_ratio": hsn_like_count / max(1, n_count),
        "expiry_ratio": expiry_like_count / max(1, n_count),
        "quantity_ratio": quantity_like_count / max(1, n_count),
        "free_qty_ratio": free_qty_like_count / max(1, n_count),
        "discount_ratio": discount_like_count / max(1, n_count),
        "gst_ratio": gst_like_count / max(1, n_count),
        "mrp_rate_ratio": mrp_rate_like_count / max(1, n_count),
        "amount_ratio": amount_like_count / max(1, n_count),
        "company_ratio": company_like_count / max(1, n_count),
        "pack_ratio": pack_like_count / max(1, n_count),
        "item_name_ratio": item_name_like_count / max(1, n_count),
        "batch_ratio": batch_like_count / max(1, n_count),
        "sample_values": non_empty[:5],
        "empty": False,
    }

def score_column_candidate_fields(profile, all_profiles, all_rows):
    if profile.get("empty"):
        return []
    
    candidates = []
    
    # 1. HSN Candidate
    hsn_score = 0.0
    hsn_evidence = []
    if profile["hsn_ratio"] >= 0.60:
        hsn_score += profile["hsn_ratio"] * 0.70
        hsn_evidence.append(f"{profile['hsn_ratio']:.0%} values match 4/6/8-digit pure integer HSN format")
        if profile["text_ratio"] == 0.0:
            hsn_score += 0.15
            hsn_evidence.append("zero text contamination")
        if profile["decimal_ratio"] == 0.0:
            hsn_score += 0.10
            hsn_evidence.append("zero decimal values")
        candidates.append({"field": "hsnCode", "score": min(0.99, hsn_score), "evidence": hsn_evidence})

    # 2. Expiry Candidate
    if profile["expiry_ratio"] >= 0.60:
        exp_score = profile["expiry_ratio"] * 0.85
        candidates.append({"field": "expiryDate", "score": min(0.99, exp_score), "evidence": [f"{profile['expiry_ratio']:.0%} values match date format"]})

    # 3. Batch Candidate
    if profile["batch_ratio"] >= 0.50 or (profile["text_ratio"] >= 0.50 and profile["unique_ratio"] >= 0.70 and 3 <= profile["avg_length"] <= 14):
        b_score = max(profile["batch_ratio"], profile["unique_ratio"] * 0.70) * 0.80
        candidates.append({"field": "batchNo", "score": min(0.95, b_score), "evidence": [f"alphanumeric batch pattern with {profile['unique_ratio']:.0%} uniqueness"]})

    # 4. Item Name Candidate
    if profile["item_name_ratio"] >= 0.50 or (profile["text_ratio"] >= 0.70 and profile["avg_length"] >= 8):
        it_score = max(profile["item_name_ratio"], profile["text_ratio"]) * 0.85
        if profile["avg_length"] >= 10:
            it_score += 0.10
        candidates.append({"field": "itemName", "score": min(0.99, it_score), "evidence": [f"descriptive product name text (avg len {profile['avg_length']:.1f})"]})

    # 5. Quantity Candidate
    if profile["quantity_ratio"] >= 0.60 and profile["hsn_ratio"] < 0.50:
        qty_score = profile["quantity_ratio"] * 0.75
        candidates.append({"field": "quantity", "score": min(0.95, qty_score), "evidence": [f"{profile['quantity_ratio']:.0%} small numeric/compound quantities"]})

    # 6. Free Quantity Candidate
    if profile["free_qty_ratio"] >= 0.60 and profile["hsn_ratio"] < 0.50:
        free_score = profile["free_qty_ratio"] * 0.65
        candidates.append({"field": "freeQuantity", "score": min(0.90, free_score), "evidence": [f"{profile['free_qty_ratio']:.0%} zero/scheme quantities"]})

    # 7. Pack Candidate
    if profile["pack_ratio"] >= 0.40 or (profile["avg_length"] <= 8 and profile["text_ratio"] >= 0.30 and any("S" in str(v).upper() or "ML" in str(v).upper() for v in profile["sample_values"])):
        pack_score = max(profile["pack_ratio"], 0.60) * 0.80
        candidates.append({"field": "pack", "score": min(0.95, pack_score), "evidence": ["packaging format (e.g. 10's, 100ml)"]})

    # 8. Company / Manufacturer Candidate
    if profile["company_ratio"] >= 0.50 and profile["avg_length"] <= 8:
        comp_score = profile["company_ratio"] * 0.80
        candidates.append({"field": "company", "score": min(0.95, comp_score), "evidence": ["short uppercase manufacturer codes"]})

    # 9. Discount vs GST Candidate
    if profile["discount_ratio"] >= 0.60 and profile["hsn_ratio"] < 0.40:
        disc_score = profile["discount_ratio"] * 0.70
        candidates.append({"field": "discountPercent", "score": min(0.90, disc_score), "evidence": [f"{profile['discount_ratio']:.0%} percentage discount values"]})

    if profile["gst_ratio"] >= 0.60 and profile["hsn_ratio"] < 0.40:
        gst_score = profile["gst_ratio"] * 0.75
        candidates.append({"field": "gstPercent", "score": min(0.92, gst_score), "evidence": [f"{profile['gst_ratio']:.0%} standard GST rate values"]})

    # 10. Monetary (Rate, MRP, Amount) Candidates
    if profile["mrp_rate_ratio"] >= 0.60 and profile["hsn_ratio"] < 0.30:
        candidates.append({"field": "rate", "score": profile["mrp_rate_ratio"] * 0.70, "evidence": ["monetary purchase rate values"]})
        candidates.append({"field": "mrp", "score": profile["mrp_rate_ratio"] * 0.68, "evidence": ["monetary retail price values"]})
        if profile["amount_ratio"] >= 0.60:
            candidates.append({"field": "amount", "score": profile["amount_ratio"] * 0.72, "evidence": ["monetary line amount values"]})

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates

def test_inference_on_all_samples():
    from extractor import extract_pdf_table, ensure_named_headers
    samples = sorted(glob.glob("Sample Invoices/*.[pP][dD][fF]"))
    print("==================================================================")
    print("TESTING DYNAMIC COLUMN SEMANTIC INFERENCE ON ALL SAMPLE INVOICES")
    print("==================================================================")
    for s in samples:
        bname = os.path.basename(s)
        meta, hdrs, maps, rows = extract_pdf_table(s)
        print(f"\n[INVOICE]: {bname} ({len(rows)} rows, {len(hdrs)} columns)")
        print(f"  Headers: {hdrs}")
        print(f"  Initial Mappings: {maps}")
        
        # Profile every column
        profiles = []
        for col_i, h in enumerate(hdrs):
            col_vals = [r[col_i] if col_i < len(r) else "" for r in rows]
            p = profile_single_column(col_i, h, col_vals, total_cols=len(hdrs))
            profiles.append(p)
            candidates = score_column_candidate_fields(p, profiles, rows)
            if candidates:
                top = candidates[0]
                print(f"  Col {col_i:2d} ({h:15s}): Top Candidate -> {top['field']:15s} (Score: {top['score']:.2f}) | Evidence: {top['evidence']}")

if __name__ == "__main__":
    test_inference_on_all_samples()
