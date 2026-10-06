import os, sys, glob, re
sys.path.insert(0, os.getcwd())
import pandas as pd
from rapidfuzz import process, fuzz
from extractor import (
    ALIAS_DICT, SYSTEM_COLUMNS, match_column_name, clean_text,
    parse_compound_qty, standardize_date, _to_float, is_serial_number_header,
    extract_pdf_table, ensure_named_headers
)

PACK_PATTERN = re.compile(r"(?i)\b(\d+['`’]s|\d+\s*s|\d+x\d+|\d+\*\d+|\d+\s*(?:ml|gm|mg|tab|cap|vial|amp|btl|strip|box|ltr|kg))\b")
PHARMA_ITEM_WORDS = {
    "tab", "caps", "cap", "syp", "inj", "gel", "susp", "oint", "drops", "cream",
    "tablet", "capsule", "syrup", "injection", "ointment", "powder", "lotion",
    "solution", "emulsion", "pharma", "mg", "ml", "gm", "forte", "plus", "duo",
    "ds", "dry", "dt", "sr", "er", "cr", "xl", "xr", "mr", "resp", "inhaler"
}
GST_STANDARD_RATES = {0.0, 5.0, 12.0, 18.0, 28.0, 0.25, 1.5, 2.5, 6.0, 9.0, 14.0}

def profile_column(col_idx, header_raw, values, x0=None, x1=None, total_cols=None):
    total = len(values)
    non_empty = [str(v).strip() for v in values if v is not None and str(v).strip() != ""]
    n_count = len(non_empty)
    if n_count == 0:
        return {
            "col_idx": col_idx,
            "header_raw": header_raw,
            "header_normalized": clean_text(header_raw),
            "x0": x0,
            "x1": x1,
            "center_x": (x0 + x1) / 2.0 if (x0 is not None and x1 is not None) else None,
            "width": (x1 - x0) if (x0 is not None and x1 is not None) else None,
            "relative_pos": (col_idx / max(1, (total_cols - 1))) if total_cols else 0.5,
            "non_empty_count": 0,
            "total_count": total,
            "empty": True,
            "sample_values": [],
            "numeric_values": [],
        }

    numeric_count = 0
    decimal_count = 0
    integer_count = 0
    text_count = 0
    date_count = 0
    percentage_count = 0
    
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
            has_decimal = "." in val
            if has_decimal:
                decimal_count += 1
            else:
                integer_count += 1
                
            # HSN check: pure digits, length 4, 6, or 8, no decimal, no letters
            if not has_decimal and re.fullmatch(r"\d{4}|\d{6}|\d{8}", cleaned):
                hsn_like_count += 1

            # Quantity check: integer, compound quantity, or fractional quantity
            billed, free = parse_compound_qty(val)
            if billed > 0 or free > 0 or (0.0 < f_val <= 10000 and (f_val.is_integer() or f_val in [0.5, 1.5, 2.5, 5.0])):
                quantity_like_count += 1
                
            # Free Qty check
            if f_val == 0.0 or free > 0 or (0.0 <= f_val <= 50 and f_val.is_integer()):
                free_qty_like_count += 1

            # Percentage checks
            if 0.0 <= f_val <= 100.0:
                percentage_count += 1
                if f_val in GST_STANDARD_RATES:
                    gst_like_count += 1
                if 0.0 <= f_val <= 50.0:
                    discount_like_count += 1

            # Monetary check: has explicit decimal points, or values in typical unit price / mrp range
            if f_val > 0:
                if has_decimal or f_val >= 25.0:
                    mrp_rate_like_count += 1
                if f_val >= 50.0:
                    amount_like_count += 1
        else:
            # Text check
            if not is_date:
                text_count += 1

        # Pack check: short string representing packaging unit (<= 10 chars)
        is_pack = bool(len(val.strip()) <= 10 and (PACK_PATTERN.search(val) or val.upper() in ["10S", "10'S", "15S", "100ML", "60ML", "5GM", "10ML"]))
        if is_pack:
            pack_like_count += 1

        # Alphanumeric Batch check (single token manufacturing codes, not multi-word product titles or packs)
        is_multiword = " " in val.strip() and len(val.strip().split()) > 1
        if not is_pack and not is_multiword:
            if re.search(r"[A-Za-z]", val) and re.search(r"\d", val) and 3 <= len(val) <= 15:
                batch_like_count += 1
            elif re.match(r"^[A-Z0-9/-]{4,12}$", val) and not re.fullmatch(r"\d+", val):
                batch_like_count += 1

        # Company check: short uppercase code or manufacturer abbreviation
        cleaned_c = clean_text(val)
        if 2 <= len(val.strip()) <= 10 and not re.search(r"\d{2,}", val) and not is_pack and not is_date and (val.isupper() or (len(cleaned_c) >= 2 and re.match(r"^[A-Za-z0-9&.\s/-]{2,10}$", val.strip()))):
            company_like_count += 1

        # Item Name check: longer descriptive text with letters or pharma dosage forms
        has_pharma_word = any(pw in val.lower().split() for pw in PHARMA_ITEM_WORDS)
        if (len(val) >= 7 and re.search(r"[A-Za-z]{3,}", val)) or has_pharma_word:
            item_name_like_count += 1

    return {
        "col_idx": col_idx,
        "header_raw": header_raw,
        "header_normalized": clean_text(header_raw),
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
        "numeric_values": numeric_vals,
        "empty": False,
    }

def check_arithmetic_relationship(col_a_idx, col_b_idx, col_c_idx, rows, tolerance=0.15):
    """Checks if Col_A * Col_B ≈ Col_C across rows."""
    matches = 0
    total = 0
    for r in rows:
        if max(col_a_idx, col_b_idx, col_c_idx) < len(r):
            a = _to_float(r[col_a_idx])
            b = _to_float(r[col_b_idx])
            c = _to_float(r[col_c_idx])
            if a is not None and b is not None and c is not None and a > 0 and b > 0 and c > 0:
                total += 1
                calc = a * b
                if abs(calc - c) <= max(tolerance, calc * 0.02):
                    matches += 1
    return (matches / total) if total >= 2 else 0.0

def score_column_candidates(profile, all_profiles, all_rows, claimed_fields=None):
    if profile.get("empty"):
        return []
    claimed = claimed_fields or set()
    candidates = []
    col_i = profile["col_idx"]

    # 1. HSN Candidate
    if profile["hsn_ratio"] >= 0.55 and profile["decimal_ratio"] == 0.0:
        hsn_score = profile["hsn_ratio"] * 0.70
        hsn_evidence = [f"{profile['hsn_ratio']:.0%} values match 4/6/8-digit HSN codes"]
        if profile["text_ratio"] == 0.0:
            hsn_score += 0.15
            hsn_evidence.append("100% pure numeric values (0% text)")
        # Check neighboring columns
        neighbor_boost = False
        for offset in (-1, 1):
            n_idx = col_i + offset
            if 0 <= n_idx < len(all_profiles):
                n_prof = all_profiles[n_idx]
                if n_prof.get("gst_ratio", 0) >= 0.6 or n_prof.get("amount_ratio", 0) >= 0.6:
                    neighbor_boost = True
                    break
        if neighbor_boost:
            hsn_score += 0.10
            hsn_evidence.append("positioned adjacent to financial/tax columns")
        if "hsnCode" not in claimed:
            candidates.append({"field": "hsnCode", "score": min(0.99, hsn_score), "evidence": hsn_evidence})

    # 2. Expiry Candidate
    if profile["expiry_ratio"] >= 0.55:
        exp_score = profile["expiry_ratio"] * 0.85
        exp_ev = [f"{profile['expiry_ratio']:.0%} values match date format (MM/YY, MM/YYYY)"]
        if "expiryDate" not in claimed:
            candidates.append({"field": "expiryDate", "score": min(0.99, exp_score), "evidence": exp_ev})

    # 3. Batch Candidate
    if profile["batch_ratio"] >= 0.45 or (profile["text_ratio"] >= 0.50 and profile["unique_ratio"] >= 0.65 and 3 <= profile["avg_length"] <= 14):
        b_score = max(profile["batch_ratio"], profile["unique_ratio"] * 0.70) * 0.80
        b_ev = [f"alphanumeric batch pattern (uniqueness: {profile['unique_ratio']:.0%}, avg len: {profile['avg_length']:.1f})"]
        if "batchNo" not in claimed:
            candidates.append({"field": "batchNo", "score": min(0.95, b_score), "evidence": b_ev})

    # 4. Item Name Candidate
    if profile["item_name_ratio"] >= 0.45 or (profile["text_ratio"] >= 0.70 and profile["avg_length"] >= 7):
        it_score = max(profile["item_name_ratio"], profile["text_ratio"]) * 0.85
        it_ev = [f"descriptive product name text (avg length: {profile['avg_length']:.1f})"]
        if profile["avg_length"] >= 10:
            it_score += 0.10
            it_ev.append("typical multi-word product title length")
        if "itemName" not in claimed:
            candidates.append({"field": "itemName", "score": min(0.99, it_score), "evidence": it_ev})

    # 5. Quantity Candidate
    if profile["quantity_ratio"] >= 0.55 and profile["hsn_ratio"] < 0.50:
        qty_score = profile["quantity_ratio"] * 0.75
        qty_ev = [f"{profile['quantity_ratio']:.0%} numeric quantities"]
        if profile["integer_ratio"] >= 0.80 and all(v <= 5000 for v in profile["numeric_values"]):
            qty_score += 0.15
            qty_ev.append("consistent with standard purchase unit counts (<= 5000)")
        if "quantity" not in claimed:
            candidates.append({"field": "quantity", "score": min(0.95, qty_score), "evidence": qty_ev})

    # 6. Free Quantity Candidate
    if profile["free_qty_ratio"] >= 0.60 and profile["hsn_ratio"] < 0.40 and profile["mrp_rate_ratio"] < 0.60:
        free_score = profile["free_qty_ratio"] * 0.65
        free_ev = [f"{profile['free_qty_ratio']:.0%} scheme/zero quantities"]
        if "freeQuantity" not in claimed:
            candidates.append({"field": "freeQuantity", "score": min(0.90, free_score), "evidence": free_ev})

    # 7. Pack Candidate
    if profile["pack_ratio"] >= 0.40 or (profile["avg_length"] <= 8 and profile["text_ratio"] >= 0.30 and any(PACK_PATTERN.search(str(v)) for v in profile["sample_values"])):
        pack_score = profile["pack_ratio"] * 0.85
        if profile["pack_ratio"] >= 0.70:
            pack_score += 0.12
        pack_ev = ["packaging size format (e.g., 10's, 100ml, 1*10)"]
        if "pack" not in claimed:
            candidates.append({"field": "pack", "score": min(0.98, pack_score), "evidence": pack_ev})

    # 8. Company Candidate
    if profile["company_ratio"] >= 0.45 and profile["avg_length"] <= 8:
        comp_score = profile["company_ratio"] * 0.80
        comp_ev = ["short uppercase manufacturer codes"]
        if "company" not in claimed:
            candidates.append({"field": "company", "score": min(0.95, comp_score), "evidence": comp_ev})

    # 9. Discount vs GST Candidate
    if profile["discount_ratio"] >= 0.55 and profile["hsn_ratio"] < 0.40:
        disc_score = profile["discount_ratio"] * 0.70
        disc_ev = [f"{profile['discount_ratio']:.0%} percentage discount values"]
        
        # Check if GST is already claimed elsewhere
        if "gstPercent" in claimed or "cgstPercent" in claimed:
            disc_score += 0.15
            disc_ev.append("GST field already identified elsewhere in invoice")
            
        # Check scale relative to other monetary columns
        other_m_cols = [p for i, p in enumerate(all_profiles) if i != col_i and p.get("mrp_rate_ratio", 0) >= 0.5]
        if other_m_cols and profile.get("numeric_values"):
            c_avg = sum(profile["numeric_values"]) / len(profile["numeric_values"])
            o_avg = max(sum(p["numeric_values"])/len(p["numeric_values"]) for p in other_m_cols if p.get("numeric_values"))
            if o_avg > c_avg * 2.5:
                disc_score += 0.10
                disc_ev.append(f"value scale ({c_avg:.1f}) is fractional relative to monetary fields ({o_avg:.1f})")

        if "discountPercent" not in claimed:
            candidates.append({"field": "discountPercent", "score": min(0.95, disc_score), "evidence": disc_ev})

    if profile["gst_ratio"] >= 0.55 and profile["hsn_ratio"] < 0.40:
        gst_score = profile["gst_ratio"] * 0.75
        gst_ev = [f"{profile['gst_ratio']:.0%} standard statutory GST rates ({profile['sample_values']})"]
        
        # Statutory GST slab perfection boost
        if profile["gst_ratio"] >= 0.90 and all(v in GST_STANDARD_RATES for v in profile.get("numeric_values", [])):
            gst_score += 0.18
            gst_ev.append("100% of values match statutory Indian GST slabs (0, 5, 12, 18, 28%)")

        # Scale relative to monetary fields
        other_m_cols = [p for i, p in enumerate(all_profiles) if i != col_i and p.get("mrp_rate_ratio", 0) >= 0.5]
        if other_m_cols and profile.get("numeric_values"):
            c_avg = sum(profile["numeric_values"]) / len(profile["numeric_values"])
            o_avg = max(sum(p["numeric_values"])/len(p["numeric_values"]) for p in other_m_cols if p.get("numeric_values"))
            if o_avg > c_avg * 2.5:
                gst_score += 0.05
                gst_ev.append(f"value scale ({c_avg:.1f}) is fractional relative to monetary fields ({o_avg:.1f})")

        if "gstPercent" not in claimed:
            candidates.append({"field": "gstPercent", "score": min(0.98, gst_score), "evidence": gst_ev})

    # 10. Monetary (Rate, MRP, Amount) Candidates
    if profile["mrp_rate_ratio"] >= 0.50 and profile["hsn_ratio"] < 0.40:
        curr_vals = profile.get("numeric_values", [])
        c_avg = sum(curr_vals) / len(curr_vals) if curr_vals else 0
        
        # Check if this column is actually a small percentage column
        is_small_pct = profile["discount_ratio"] >= 0.75 and c_avg <= 25.0
        
        if not is_small_pct:
            r_ev = ["monetary purchase rate values"]
            m_ev = ["monetary maximum retail price values"]
            a_ev = ["monetary line amount values"]
            
            r_score = 0.70
            m_score = 0.68
            a_score = 0.60

            # Check for relational and arithmetic evidence with other columns
            for other_idx, other_prof in enumerate(all_profiles):
                if other_idx != col_i and other_prof.get("numeric_ratio", 0) >= 0.5:
                    other_vals = other_prof.get("numeric_values", [])
                    if other_vals and curr_vals:
                        o_avg = sum(other_vals) / len(other_vals)
                        if c_avg > o_avg * 1.05 and c_avg <= o_avg * 3.0:
                            m_score += 0.22
                            m_ev.append(f"consistently higher than neighbor monetary col_{other_idx} (MRP >= Rate relationship)")
                        elif c_avg < o_avg * 0.95:
                            r_score += 0.20
                            r_ev.append(f"consistently lower than neighbor monetary col_{other_idx} (Rate <= MRP relationship)")

                    # Arithmetic relationship (Qty * Rate ≈ Amount)
                    for third_idx, third_prof in enumerate(all_profiles):
                        if third_idx not in (col_i, other_idx) and third_prof.get("numeric_ratio", 0) >= 0.5:
                            if check_arithmetic_relationship(other_idx, col_i, third_idx, all_rows) >= 0.6:
                                r_score += 0.25
                                r_ev.append(f"arithmetic verified: Qty(col_{other_idx}) * Rate(col_{col_i}) ≈ Amount(col_{third_idx})")
                            if check_arithmetic_relationship(other_idx, third_idx, col_i, all_rows) >= 0.6:
                                a_score += 0.35
                                a_ev.append(f"arithmetic verified: Qty(col_{other_idx}) * Rate(col_{third_idx}) ≈ Amount(col_{col_i})")

            if "rate" not in claimed:
                candidates.append({"field": "rate", "score": min(0.98, r_score), "evidence": r_ev})
            if "mrp" not in claimed:
                candidates.append({"field": "mrp", "score": min(0.95, m_score), "evidence": m_ev})
            if "amount" not in claimed:
                candidates.append({"field": "amount", "score": min(0.98, a_score), "evidence": a_ev})

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates

def infer_unresolved_column_semantics(headers, rows, columns_coord_info=None, saved_template=None, debug=False) -> dict:
    named_headers = ensure_named_headers(headers)
    total_cols = len(named_headers)
    results = {}
    
    # 1. First priority: Explicit Headers & Saved Templates
    claimed_fields = set()
    for idx, raw_h in enumerate(named_headers):
        x0 = columns_coord_info[idx].get("x0") if (columns_coord_info and idx < len(columns_coord_info)) else None
        x1 = columns_coord_info[idx].get("x1") if (columns_coord_info and idx < len(columns_coord_info)) else None
        
        mapped_field = match_column_name(raw_h, saved_template)
        is_unnamed = str(raw_h).startswith("Unnamed_Col_")
        
        if mapped_field and not is_unnamed:
            claimed_fields.add(mapped_field)
            results[raw_h] = {
                "mapped_to": mapped_field,
                "status": "known_header",
                "confidence": 100.0,
                "candidates": [{"field": mapped_field, "score": 1.0, "evidence": ["Explicit header matched canonical alias"]}],
                "evidence": ["Explicit header matched canonical alias"],
                "col_idx": idx,
                "x0": x0,
                "x1": x1,
            }
        else:
            results[raw_h] = {
                "mapped_to": None,
                "status": "unresolved",
                "confidence": 0.0,
                "candidates": [],
                "evidence": [],
                "col_idx": idx,
                "x0": x0,
                "x1": x1,
            }

    # 2. Build Column Profiles
    profiles = []
    for idx, raw_h in enumerate(named_headers):
        col_vals = [row[idx] if idx < len(row) else None for row in rows]
        x0 = results[raw_h]["x0"]
        x1 = results[raw_h]["x1"]
        prof = profile_column(idx, raw_h, col_vals, x0=x0, x1=x1, total_cols=total_cols)
        profiles.append(prof)

    # 3. Score Candidates for Unresolved Columns
    unresolved_cols = [raw_h for raw_h, res in results.items() if res["status"] == "unresolved"]
    
    for raw_h in unresolved_cols:
        idx = results[raw_h]["col_idx"]
        prof = profiles[idx]
        candidates = score_column_candidates(prof, profiles, rows, claimed_fields=claimed_fields)
        results[raw_h]["candidates"] = candidates

    # 4. Global Resolution Pass
    scored_cols = []
    for raw_h in unresolved_cols:
        cands = results[raw_h]["candidates"]
        if cands:
            top_score = cands[0]["score"]
            scored_cols.append((raw_h, top_score, cands))
    
    scored_cols.sort(key=lambda x: x[1], reverse=True)

    for raw_h, top_score, cands in scored_cols:
        idx = results[raw_h]["col_idx"]
        prof = profiles[idx]
        
        valid_cands = [c for c in cands if c["field"] not in claimed_fields]
        if not valid_cands:
            results[raw_h]["status"] = "unresolved"
            continue

        best = valid_cands[0]
        second = valid_cands[1] if len(valid_cands) > 1 else None

        # MRP vs Rate disambiguation
        if best["field"] in ("rate", "mrp") and second and second["field"] in ("rate", "mrp"):
            other_m_cols = [p for i, p in enumerate(profiles) if i != idx and p.get("mrp_rate_ratio", 0) >= 0.5]
            if other_m_cols:
                other_prof = other_m_cols[0]
                curr_avg = sum(prof["numeric_values"]) / max(1, len(prof["numeric_values"])) if prof["numeric_values"] else 0
                other_avg = sum(other_prof["numeric_values"]) / max(1, len(other_prof["numeric_values"])) if other_prof.get("numeric_values") else 0
                if curr_avg > other_avg * 1.05 and "mrp" not in claimed_fields:
                    best = next((c for c in valid_cands if c["field"] == "mrp"), best)
                elif curr_avg < other_avg * 0.95 and "rate" not in claimed_fields:
                    best = next((c for c in valid_cands if c["field"] == "rate"), best)

        # Discount vs GST disambiguation
        if best["field"] in ("discountPercent", "gstPercent") and second and second["field"] in ("discountPercent", "gstPercent"):
            if prof["gst_ratio"] >= 0.8 and all(v in GST_STANDARD_RATES for v in prof["numeric_values"]):
                best = next((c for c in valid_cands if c["field"] == "gstPercent"), best)
            else:
                best = next((c for c in valid_cands if c["field"] == "discountPercent"), best)

        # Check confidence margin against ambiguity
        margin = (best["score"] - second["score"]) if second else 1.0
        min_conf = 0.65
        
        if best["score"] >= min_conf and margin >= 0.10:
            results[raw_h]["mapped_to"] = best["field"]
            results[raw_h]["status"] = "inferred"
            results[raw_h]["confidence"] = round(best["score"] * 100.0, 1)
            results[raw_h]["evidence"] = best["evidence"]
            claimed_fields.add(best["field"])
        else:
            results[raw_h]["status"] = "ambiguous" if best["score"] >= 0.50 else "unresolved"
            results[raw_h]["confidence"] = round(best["score"] * 100.0, 1)
            results[raw_h]["evidence"] = [f"Score ({best['score']:.2f}) or margin ({margin:.2f}) below threshold"]

    return results

def run_case_tests():
    print("==================================================================")
    print("RUNNING AUTOMATED CASE TESTS (A through O)")
    print("==================================================================")
    
    # CASE A: Explicit HSN Header
    res_a = infer_unresolved_column_semantics(["Product", "HSN Code", "Qty"], [["Paracetamol 500mg", "30049099", "10"]])
    assert res_a["HSN Code"]["status"] == "known_header" and res_a["HSN Code"]["mapped_to"] == "hsnCode"
    print("  [PASS] CASE A: Header explicitly says HSN -> known_header (hsnCode)")

    # CASE B: Header missing but values consistently HSN-like
    hsn_rows = [
        ["Paracetamol 500mg", "30049099", "10", "150.00"],
        ["Amoxicillin 250mg", "30041010", "20", "220.00"],
        ["Azithromycin 500", "30042010", "15", "310.00"],
        ["Cough Syrup 100ml", "30049032", "5", "85.00"],
        ["Ibuprofen 400mg", "30049099", "30", "110.00"],
    ]
    res_b = infer_unresolved_column_semantics(["Product", "Unnamed_Col_1", "Qty", "Amount"], hsn_rows)
    assert res_b["Unnamed_Col_1"]["status"] == "inferred" and res_b["Unnamed_Col_1"]["mapped_to"] == "hsnCode"
    print("  [PASS] CASE B: Missing header with HSN-like values -> inferred (hsnCode)")

    # CASE C: HSN in different physical positions (first, middle, last)
    # First:
    res_c_first = infer_unresolved_column_semantics(["Unnamed_Col_0", "Product", "Qty", "Rate"], [["30049099", "Med A", "10", "50.0"] for _ in range(5)])
    assert res_c_first["Unnamed_Col_0"]["mapped_to"] == "hsnCode"
    # Middle:
    res_c_mid = infer_unresolved_column_semantics(["Product", "Unnamed_Col_1", "Qty", "Rate"], [["Med A", "30049099", "10", "50.0"] for _ in range(5)])
    assert res_c_mid["Unnamed_Col_1"]["mapped_to"] == "hsnCode"
    # Last:
    res_c_last = infer_unresolved_column_semantics(["Product", "Qty", "Rate", "Unnamed_Col_3"], [["Med A", "10", "50.0", "30049099"] for _ in range(5)])
    assert res_c_last["Unnamed_Col_3"]["mapped_to"] == "hsnCode"
    print("  [PASS] CASE C: HSN in first/middle/last position -> dynamically mapped correctly")

    # CASE D: HSN header fuzzy/misspelled
    res_d = infer_unresolved_column_semantics(["Product", "HSN/SAC CODE", "Qty"], [["Med A", "30049099", "10"]])
    assert res_d["HSN/SAC CODE"]["mapped_to"] == "hsnCode"
    print("  [PASS] CASE D: HSN header fuzzy/misspelled -> mapped to hsnCode")

    # CASE E: 8-digit numeric identifier in non-HSN context
    res_e = infer_unresolved_column_semantics(
        ["Product", "HSN", "Unnamed_Col_2", "Qty"],
        [["Med A", "30049099", "98765432", "10"] for _ in range(5)]
    )
    # Unnamed_Col_2 cannot steal hsnCode because HSN is already claimed by explicit header
    assert res_e["Unnamed_Col_2"]["mapped_to"] != "hsnCode"
    print("  [PASS] CASE E: Another 8-digit number when HSN is known -> does NOT steal HSN")

    # CASE F: Unnamed Quantity column
    qty_rows = [
        ["Med A", "10", "100.00", "1000.00"],
        ["Med B", "20", "50.00", "1000.00"],
        ["Med C", "5", "80.00", "400.00"],
        ["Med D", "15", "120.00", "1800.00"],
        ["Med E", "25", "40.00", "1000.00"],
    ]
    res_f = infer_unresolved_column_semantics(["Product", "Unnamed_Col_1", "Rate", "Amount"], qty_rows)
    assert res_f["Unnamed_Col_1"]["mapped_to"] == "quantity"
    print("  [PASS] CASE F: Unnamed Quantity column -> inferred as quantity")

    # CASE G: Unnamed Rate column
    rate_rows = [
        ["Med A", "10", "95.50", "955.00"],
        ["Med B", "5", "120.00", "600.00"],
        ["Med C", "20", "45.25", "905.00"],
        ["Med D", "12", "110.00", "1320.00"],
    ]
    res_g = infer_unresolved_column_semantics(["Product", "Qty", "Unnamed_Col_2", "Amount"], rate_rows)
    assert res_g["Unnamed_Col_2"]["mapped_to"] in ("rate", "mrp")
    print(f"  [PASS] CASE G: Unnamed Rate column -> inferred as {res_g['Unnamed_Col_2']['mapped_to']}")

    # CASE H: Unnamed MRP column
    mrp_rows = [
        ["Med A", "150.00", "110.00", "10"],
        ["Med B", "220.00", "165.00", "20"],
        ["Med C", "85.00", "62.50", "15"],
        ["Med D", "310.00", "240.00", "5"],
    ]
    res_h = infer_unresolved_column_semantics(["Product", "Unnamed_Col_1", "Rate", "Qty"], mrp_rows)
    assert res_h["Unnamed_Col_1"]["mapped_to"] == "mrp"
    print("  [PASS] CASE H: Unnamed MRP column -> inferred as mrp")

    # CASE I: Unnamed Discount column vs GST
    disc_rows = [
        ["Med A", "10", "100.00", "3.50", "12.00"],
        ["Med B", "20", "50.00", "5.00", "12.00"],
        ["Med C", "5", "80.00", "7.25", "12.00"],
        ["Med D", "15", "120.00", "2.00", "12.00"],
    ]
    res_i = infer_unresolved_column_semantics(["Product", "Qty", "Rate", "Unnamed_Col_3", "GST%"], disc_rows)
    assert res_i["Unnamed_Col_3"]["mapped_to"] == "discountPercent"
    print("  [PASS] CASE I: Unnamed Discount column -> distinguished from GST and inferred as discountPercent")

    # CASE J: Unnamed GST column
    gst_rows = [
        ["Med A", "10", "100.00", "12.00"],
        ["Med B", "20", "50.00", "12.00"],
        ["Med C", "5", "80.00", "5.00"],
        ["Med D", "15", "120.00", "18.00"],
    ]
    res_j = infer_unresolved_column_semantics(["Product", "Qty", "Rate", "Unnamed_Col_3"], gst_rows)
    assert res_j["Unnamed_Col_3"]["mapped_to"] == "gstPercent"
    print("  [PASS] CASE J: Unnamed GST column -> inferred as gstPercent")

    # CASE K: Unnamed Manufacturer column
    comp_rows = [
        ["CIPLA", "Paracetamol 500mg", "10", "50.00"],
        ["SUN", "Amoxicillin 250mg", "20", "110.00"],
        ["LUPIN", "Azithromycin 500", "15", "155.00"],
        ["MANKIND", "Cough Syrup 100ml", "5", "42.50"],
    ]
    res_k = infer_unresolved_column_semantics(["Unnamed_Col_0", "Product", "Qty", "Rate"], comp_rows)
    assert res_k["Unnamed_Col_0"]["mapped_to"] == "company"
    print("  [PASS] CASE K: Unnamed Manufacturer column -> inferred as company")

    # CASE L: Unnamed Pack column
    pack_rows = [
        ["Paracetamol 500mg", "10'S", "10", "50.00"],
        ["Amoxicillin 250mg", "100ML", "20", "110.00"],
        ["Azithromycin 500", "6 TAB", "15", "155.00"],
        ["Cough Syrup", "60ML", "5", "42.50"],
    ]
    res_l = infer_unresolved_column_semantics(["Product", "Unnamed_Col_1", "Qty", "Rate"], pack_rows)
    assert res_l["Unnamed_Col_1"]["mapped_to"] == "pack"
    print("  [PASS] CASE L: Unnamed Pack column -> inferred as pack")

    # CASE M: Unnamed Product Name column
    item_rows = [
        ["AZITHRAL 500MG TAB", "10", "155.00"],
        ["AUGMENTIN 625MG DUO", "20", "220.00"],
        ["CALPOL 650MG TABLET", "15", "35.00"],
        ["BENADRYL SYRUP 100ML", "5", "85.00"],
    ]
    res_m = infer_unresolved_column_semantics(["Unnamed_Col_0", "Qty", "Rate"], item_rows)
    print("DEBUG CASE M:", res_m["Unnamed_Col_0"])
    assert res_m["Unnamed_Col_0"]["mapped_to"] == "itemName"
    print("  [PASS] CASE M: Unnamed Product Name column -> inferred as itemName")

    # CASE N: Multiple unnamed columns inferred jointly
    multi_rows = [
        ["CIPLA", "AZITHRAL 500MG TAB", "10'S", "30049099", "10", "155.00"],
        ["SUN", "AUGMENTIN 625MG DUO", "10'S", "30041010", "20", "220.00"],
        ["GSK", "CALPOL 650MG TABLET", "15'S", "30049099", "15", "35.00"],
        ["J&J", "BENADRYL SYRUP", "100ML", "30049032", "5", "85.00"],
    ]
    res_n = infer_unresolved_column_semantics(
        ["Unnamed_Col_0", "Unnamed_Col_1", "Unnamed_Col_2", "Unnamed_Col_3", "Qty", "Rate"],
        multi_rows
    )
    assert res_n["Unnamed_Col_0"]["mapped_to"] == "company"
    assert res_n["Unnamed_Col_1"]["mapped_to"] == "itemName"
    assert res_n["Unnamed_Col_2"]["mapped_to"] == "pack"
    assert res_n["Unnamed_Col_3"]["mapped_to"] == "hsnCode"
    print("  [PASS] CASE N: Multiple unnamed columns (Company, Item, Pack, HSN) inferred jointly")

    # CASE O: Weak / Ambiguous data -> unresolved / ambiguous
    weak_rows = [
        ["Med A", "ABC", "10"],
        ["Med B", "1234", "20"],
        ["Med C", "-", "15"],
        ["Med D", "XYZ-99", "5"],
    ]
    res_o = infer_unresolved_column_semantics(["Product", "Unnamed_Col_1", "Qty"], weak_rows)
    assert res_o["Unnamed_Col_1"]["status"] in ("unresolved", "ambiguous")
    print("  [PASS] CASE O: Weak / ambiguous data left as unresolved/ambiguous")

    print("\nALL CASES A THROUGH O PASSED SUCCESSFULLY!\n")

def run_sample_invoices():
    print("==================================================================")
    print("RUNNING ALL 9 SAMPLE INVOICES WITH GENERIC SEMANTIC INFERENCE")
    print("==================================================================")
    samples = sorted(glob.glob("Sample Invoices/*.[pP][dD][fF]"))
    
    for s in samples:
        bname = os.path.basename(s)
        meta, hdrs, maps, rows = extract_pdf_table(s)
        sem_res = infer_unresolved_column_semantics(hdrs, rows)
        
        inferred = [f"{h} -> {v['mapped_to']} ({v['status']}, conf={v['confidence']}%)" for h, v in sem_res.items() if v['status'] == 'inferred']
        known = [f"{h} -> {v['mapped_to']}" for h, v in sem_res.items() if v['status'] == 'known_header']
        unres = [h for h, v in sem_res.items() if v['status'] in ('unresolved', 'ambiguous')]
        
        print(f"\n[INVOICE]: {bname}")
        print(f"  Supplier: {meta.get('seller_trade_name')}")
        print(f"  Row count: {len(rows)}, Columns: {len(hdrs)}")
        print(f"  Known headers ({len(known)}): {', '.join(known[:5])}{'...' if len(known) > 5 else ''}")
        if inferred:
            print(f"  Inferred columns ({len(inferred)}): {', '.join(inferred)}")
        if unres:
            print(f"  Unresolved columns ({len(unres)}): {', '.join(unres)}")

if __name__ == "__main__":
    run_case_tests()
    run_sample_invoices()
