import os
import sys
import json
import re
from rapidfuzz import fuzz, process

sys.path.insert(0, ".")

import extractor
from extractor import (
    ALIAS_DICT, clean_text, normalize_split_header_text, is_serial_number_header,
    _to_float, parse_compound_qty, GST_STANDARD_RATES, PHARMA_ITEM_WORDS, PACK_PATTERN,
    extract_page_words, detect_coordinate_header_row, determine_column_boundaries,
    detect_logical_subcolumns, assign_tokens_to_columns, _merge_continuation_rows,
    _is_genuine_product_row, _is_footer_row, _is_letterhead_row, standardize_date,
    profile_column, check_arithmetic_relationship, ensure_named_headers, extract_pdf_table
)

AUXILIARY_HEADER_PATTERNS = {
    r"(?i)\b(?:s|sn|sno|s\.no|sl\s*no|sr\s*no|sl\.no|s\s*no|sr\.no|s\.)\b": "serialNumber",
    r"(?i)\b(?:dis|disc|discount|sch)\s*(?:amt|amount|val|value)\b": "discountAmount",
    r"(?i)\b(?:gst|tax|cgst|sgst|igst|total\s*tax)\s*(?:amt|amount|val|value)\b": "gstAmount",
    r"(?i)\b(?:rack|location|bin|slot)\b": "rackLocation",
    r"(?i)\b(?:box|boxs|boxes|outer|case|cases)\b": "boxPackaging",
    r"(?i)\b(?:old|old\s*mrp|old\s*m\.r\.p|prev\s*mrp|prev\s*m\.r\.p)\b": "oldMrp",
    r"(?i)\b(?:r\.mar|rmar|margin|profit|markup)\b": "margin",
    r"(?i)\b(?:item\s*code|itemcode|prod\s*code|pcode)\b": "itemCode",
}

def is_auxiliary_header(header_raw: str) -> bool:
    if not header_raw:
        return False
    norm = normalize_split_header_text(header_raw)
    cleaned = clean_text(norm)
    if is_serial_number_header(norm):
        return True
    for pat in AUXILIARY_HEADER_PATTERNS:
        if re.search(pat, norm) or re.search(pat, header_raw):
            return True
    if cleaned in {
        "disamt", "discamt", "discountamount", "schamt", "discamount",
        "gstamt", "taxamt", "totaltaxamt", "gstamount", "cgstamt", "sgstamt", "taxamount",
        "rack", "location", "bin", "slot",
        "box", "boxs", "boxes", "outer", "case", "cases",
        "old", "oldmrp", "oldmrsp", "prevmrp", "rmar", "margin",
    }:
        return True
    return False

def score_header_candidates(header_raw: str, saved_template: dict = None) -> list:
    if not header_raw or is_auxiliary_header(header_raw):
        return []
    
    norm = normalize_split_header_text(header_raw)
    cleaned = clean_text(norm)
    if not cleaned:
        return []
    
    candidates = []
    
    # 1. Exact canonical alias matches
    for field, aliases in ALIAS_DICT.items():
        for alias in aliases:
            c_alias = clean_text(alias)
            if cleaned == c_alias:
                p_score = 0.95
                ev = [f"Exact alias match for '{alias}'"]
                
                # Specific priority scores
                if field == "rate":
                    if cleaned in {"ptr", "pricetoretailer", "purrate", "p.t.r", "p.t.r."}:
                        p_score = 1.00
                        ev.append("Base purchase rate (PTR)")
                    elif cleaned == "rate":
                        p_score = 0.92
                elif field == "mrp":
                    if cleaned in {"mrp", "maxretailprice", "maximumretailprice", "m.r.p", "m.r.p."}:
                        p_score = 1.00
                elif field == "discountPercent":
                    if "%" in header_raw or cleaned in {"dis%", "disc%", "discount%"}:
                        p_score = 1.00
                    elif cleaned in {"dis", "disc", "discount"}:
                        p_score = 0.92
                    elif cleaned in {"sch", "scheme"}:
                        p_score = 0.85
                elif field == "gstPercent":
                    if "%" in header_raw or "rate" in norm.lower():
                        p_score = 1.00
                    elif cleaned == "gst":
                        p_score = 0.92
                elif field == "amount":
                    if cleaned in {"amount", "grossamt", "grossamount", "grossvalue"}:
                        p_score = 1.00
                    elif cleaned in {"amt", "value", "total", "itemamt"}:
                        p_score = 0.88
                elif field == "freeQuantity":
                    if cleaned in {"free", "freeqty", "bonus"}:
                        p_score = 1.00
                    elif cleaned in {"sch", "scheme"}:
                        p_score = 0.80
                elif field == "quantity":
                    if cleaned in {"billedqty", "quantitybilled", "billed"}:
                        p_score = 1.00
                    elif cleaned in {"qty", "quantity", "units", "nos"}:
                        p_score = 0.96
                elif field == "taxableAmount":
                    if cleaned in {"taxable", "taxableamt", "taxablevalue", "taxableamount"}:
                        p_score = 1.00
                elif field == "netAmount":
                    if cleaned in {"net", "netamount", "netamt", "netvalue", "billamt", "netpayable"}:
                        p_score = 1.00
                elif field == "company":
                    if cleaned in {"mfr", "mfg", "mktby", "mfac", "manufacturer", "company"}:
                        p_score = 1.00
                elif field == "pack":
                    if cleaned in {"pack", "packing", "packs", "packsize", "packingsize", "pkg", "pk"}:
                        p_score = 1.00
                elif field == "batchNo":
                    if cleaned in {"batch", "batchno", "batchnumber", "lot", "lotno"}:
                        p_score = 1.00
                elif field == "expiryDate":
                    if cleaned in {"exp", "expiry", "expdate", "expirydate"}:
                        p_score = 1.00
                elif field == "hsnCode":
                    if cleaned in {"hsn", "hsncode", "hsnsac", "hsnsaccode"}:
                        p_score = 1.00
                elif field == "itemName":
                    if cleaned in {"productname", "itemdescription", "itemname", "product", "description", "particulars"}:
                        p_score = 1.00

                candidates.append({
                    "field": field,
                    "score": p_score,
                    "evidence": ev,
                    "source": "CURRENT_HEADER"
                })
                break

    # 2. Saved template prior (as secondary candidate)
    if saved_template:
        mapped = saved_template.get(norm) or saved_template.get(header_raw)
        if mapped and mapped in ALIAS_DICT and not is_auxiliary_header(norm):
            if not any(c["field"] == mapped for c in candidates):
                candidates.append({
                    "field": mapped,
                    "score": 0.82,
                    "evidence": ["Matched historical supplier profile template prior"],
                    "source": "PROFILE_PRIOR"
                })

    # 3. Fuzzy match if no candidate
    if not candidates:
        flat_aliases = []
        alias_to_field = {}
        for f, aliases in ALIAS_DICT.items():
            for a in aliases:
                flat_aliases.append(a)
                alias_to_field[a] = f
        res = process.extractOne(norm.lower(), flat_aliases, scorer=fuzz.token_sort_ratio)
        if res:
            best_match, score, _ = res
            min_score = 90.0 if len(cleaned) <= 4 else 78.0
            if score >= min_score:
                f_match = alias_to_field[best_match]
                candidates.append({
                    "field": f_match,
                    "score": round(score / 100.0 * 0.85, 2),
                    "evidence": [f"Fuzzy match '{best_match}' ({score:.0f}%)"],
                    "source": "CURRENT_HEADER"
                })

    return candidates

def score_column_evidence(col_idx, raw_h, prof, all_profiles, rows, saved_template=None) -> list:
    candidates_dict = {}
    
    # 1. Header Candidates
    h_cands = score_header_candidates(raw_h, saved_template=saved_template)
    for c in h_cands:
        candidates_dict[c["field"]] = {
            "field": c["field"],
            "score": c["score"],
            "evidence": list(c["evidence"]),
            "source": c["source"],
            "header_score": c["score"],
            "body_score": 0.0,
            "arithmetic_score": 0.0,
        }
        
    # Check if this column is a serial number column by values (sequential 1, 2, 3...)
    sample_vals = [str(v).strip() for v in prof.get("sample_values", []) if str(v).strip()]
    is_seq_ints = False
    if sample_vals and all(v.isdigit() for v in sample_vals):
        int_vals = [int(v) for v in sample_vals]
        if int_vals == list(range(1, len(int_vals) + 1)) or int_vals == list(range(int_vals[0], int_vals[0] + len(int_vals))):
            is_seq_ints = True

    if is_seq_ints or is_serial_number_header(raw_h):
        return []

    if prof.get("empty") or prof.get("non_empty_count", 0) == 0:
        return list(candidates_dict.values())

    non_empty_ratio = prof.get("fill_ratio", 0.0)
    if non_empty_ratio < 0.20 and not candidates_dict:
        return []

    # HSN Candidate
    if prof["hsn_ratio"] >= 0.55 and prof["decimal_ratio"] == 0.0 and not is_seq_ints:
        hsn_score = prof["hsn_ratio"] * 0.80
        hsn_ev = [f"{prof['hsn_ratio']:.0%} values match 4/6/8-digit HSN codes"]
        if prof["text_ratio"] == 0.0:
            hsn_score += 0.15
            hsn_ev.append("100% pure numeric values (0% text)")
        if "hsnCode" in candidates_dict:
            candidates_dict["hsnCode"]["score"] = max(candidates_dict["hsnCode"]["score"], min(0.99, hsn_score + 0.10))
            candidates_dict["hsnCode"]["evidence"].extend(hsn_ev)
            candidates_dict["hsnCode"]["source"] = "COMBINED_EVIDENCE"
        else:
            candidates_dict["hsnCode"] = {
                "field": "hsnCode", "score": min(0.99, hsn_score), "evidence": hsn_ev,
                "source": "CURRENT_BODY", "header_score": 0.0, "body_score": hsn_score, "arithmetic_score": 0.0
            }

    # Expiry Candidate
    if prof["expiry_ratio"] >= 0.50:
        exp_score = prof["expiry_ratio"] * 0.90
        exp_ev = [f"{prof['expiry_ratio']:.0%} values match date format (MM/YY, MM/YYYY)"]
        if "expiryDate" in candidates_dict:
            candidates_dict["expiryDate"]["score"] = max(candidates_dict["expiryDate"]["score"], min(0.99, exp_score + 0.08))
            candidates_dict["expiryDate"]["evidence"].extend(exp_ev)
            candidates_dict["expiryDate"]["source"] = "COMBINED_EVIDENCE"
        else:
            candidates_dict["expiryDate"] = {
                "field": "expiryDate", "score": min(0.99, exp_score), "evidence": exp_ev,
                "source": "CURRENT_BODY", "header_score": 0.0, "body_score": exp_score, "arithmetic_score": 0.0
            }

    # Batch Candidate
    if (prof["batch_ratio"] >= 0.40 or (prof["text_ratio"] >= 0.50 and prof["unique_ratio"] >= 0.65 and 3 <= prof["avg_length"] <= 14)) and not is_seq_ints:
        b_score = max(prof["batch_ratio"], prof["unique_ratio"] * 0.70) * 0.85
        b_ev = [f"alphanumeric batch pattern (uniqueness: {prof['unique_ratio']:.0%}, avg len: {prof['avg_length']:.1f})"]
        if "batchNo" in candidates_dict:
            candidates_dict["batchNo"]["score"] = max(candidates_dict["batchNo"]["score"], min(0.98, b_score + 0.08))
            candidates_dict["batchNo"]["evidence"].extend(b_ev)
            candidates_dict["batchNo"]["source"] = "COMBINED_EVIDENCE"
        else:
            candidates_dict["batchNo"] = {
                "field": "batchNo", "score": min(0.95, b_score), "evidence": b_ev,
                "source": "CURRENT_BODY", "header_score": 0.0, "body_score": b_score, "arithmetic_score": 0.0
            }

    # Item Name Candidate
    if prof["item_name_ratio"] >= 0.45 or (prof["text_ratio"] >= 0.70 and prof["avg_length"] >= 7):
        it_score = max(prof["item_name_ratio"], prof["text_ratio"]) * 0.88
        it_ev = [f"descriptive product name text (avg length: {prof['avg_length']:.1f})"]
        if prof["avg_length"] >= 10:
            it_score += 0.10
            it_ev.append("typical multi-word product title length")
        if "itemName" in candidates_dict:
            candidates_dict["itemName"]["score"] = max(candidates_dict["itemName"]["score"], min(0.99, it_score + 0.08))
            candidates_dict["itemName"]["evidence"].extend(it_ev)
            candidates_dict["itemName"]["source"] = "COMBINED_EVIDENCE"
        else:
            candidates_dict["itemName"] = {
                "field": "itemName", "score": min(0.99, it_score), "evidence": it_ev,
                "source": "CURRENT_BODY", "header_score": 0.0, "body_score": it_score, "arithmetic_score": 0.0
            }

    # Quantity Candidate
    if prof["quantity_ratio"] >= 0.55 and prof["hsn_ratio"] < 0.40 and not is_seq_ints and not is_auxiliary_header(raw_h):
        qty_score = prof["quantity_ratio"] * 0.80
        qty_ev = [f"{prof['quantity_ratio']:.0%} numeric quantities"]
        if prof["integer_ratio"] >= 0.80 and all(v <= 5000 for v in prof["numeric_values"]):
            qty_score += 0.15
            qty_ev.append("consistent with standard purchase unit counts (<= 5000)")
        if "quantity" in candidates_dict:
            candidates_dict["quantity"]["score"] = max(candidates_dict["quantity"]["score"], min(0.99, qty_score + 0.08))
            candidates_dict["quantity"]["evidence"].extend(qty_ev)
            candidates_dict["quantity"]["source"] = "COMBINED_EVIDENCE"
        else:
            candidates_dict["quantity"] = {
                "field": "quantity", "score": min(0.95, qty_score), "evidence": qty_ev,
                "source": "CURRENT_BODY", "header_score": 0.0, "body_score": qty_score, "arithmetic_score": 0.0
            }

    # Free Quantity Candidate
    if prof["free_qty_ratio"] >= 0.60 and prof["hsn_ratio"] < 0.40 and prof["mrp_rate_ratio"] < 0.60 and not is_seq_ints and not is_auxiliary_header(raw_h):
        free_score = prof["free_qty_ratio"] * 0.70
        free_ev = [f"{prof['free_qty_ratio']:.0%} scheme/zero quantities"]
        if "freeQuantity" in candidates_dict:
            candidates_dict["freeQuantity"]["score"] = max(candidates_dict["freeQuantity"]["score"], min(0.98, free_score + 0.08))
            candidates_dict["freeQuantity"]["evidence"].extend(free_ev)
            candidates_dict["freeQuantity"]["source"] = "COMBINED_EVIDENCE"
        else:
            candidates_dict["freeQuantity"] = {
                "field": "freeQuantity", "score": min(0.92, free_score), "evidence": free_ev,
                "source": "CURRENT_BODY", "header_score": 0.0, "body_score": free_score, "arithmetic_score": 0.0
            }

    # Pack Candidate
    if (prof["pack_ratio"] >= 0.40 or (prof["avg_length"] <= 8 and prof["text_ratio"] >= 0.30 and any(PACK_PATTERN.search(str(v)) for v in prof["sample_values"]))) and not is_auxiliary_header(raw_h):
        pack_score = prof["pack_ratio"] * 0.85
        if prof["pack_ratio"] >= 0.70:
            pack_score += 0.12
        pack_ev = ["packaging size format (e.g. 10's, 100ml, 15s)"]
        if "pack" in candidates_dict:
            candidates_dict["pack"]["score"] = max(candidates_dict["pack"]["score"], min(0.99, pack_score + 0.08))
            candidates_dict["pack"]["evidence"].extend(pack_ev)
            candidates_dict["pack"]["source"] = "COMBINED_EVIDENCE"
        else:
            candidates_dict["pack"] = {
                "field": "pack", "score": min(0.98, pack_score), "evidence": pack_ev,
                "source": "CURRENT_BODY", "header_score": 0.0, "body_score": pack_score, "arithmetic_score": 0.0
            }

    # Company Candidate
    if prof["company_ratio"] >= 0.45 and prof["avg_length"] <= 8 and not is_auxiliary_header(raw_h):
        comp_score = prof["company_ratio"] * 0.85
        comp_ev = ["short uppercase manufacturer codes"]
        if "company" in candidates_dict:
            candidates_dict["company"]["score"] = max(candidates_dict["company"]["score"], min(0.99, comp_score + 0.08))
            candidates_dict["company"]["evidence"].extend(comp_ev)
            candidates_dict["company"]["source"] = "COMBINED_EVIDENCE"
        else:
            candidates_dict["company"] = {
                "field": "company", "score": min(0.95, comp_score), "evidence": comp_ev,
                "source": "CURRENT_BODY", "header_score": 0.0, "body_score": comp_score, "arithmetic_score": 0.0
            }

    # Discount% vs GST%
    if prof["discount_ratio"] >= 0.50 and prof["hsn_ratio"] < 0.40 and not is_seq_ints and not is_auxiliary_header(raw_h):
        disc_score = prof["discount_ratio"] * 0.75
        disc_ev = [f"{prof['discount_ratio']:.0%} percentage discount values"]
        if "discountPercent" in candidates_dict:
            candidates_dict["discountPercent"]["score"] = max(candidates_dict["discountPercent"]["score"], min(0.99, disc_score + 0.10))
            candidates_dict["discountPercent"]["evidence"].extend(disc_ev)
            candidates_dict["discountPercent"]["source"] = "COMBINED_EVIDENCE"
        else:
            candidates_dict["discountPercent"] = {
                "field": "discountPercent", "score": min(0.95, disc_score), "evidence": disc_ev,
                "source": "CURRENT_BODY", "header_score": 0.0, "body_score": disc_score, "arithmetic_score": 0.0
            }

    if prof["gst_ratio"] >= 0.50 and prof["hsn_ratio"] < 0.40 and not is_seq_ints and not is_auxiliary_header(raw_h):
        gst_score = prof["gst_ratio"] * 0.80
        gst_ev = [f"{prof['gst_ratio']:.0%} standard statutory GST rates ({prof['sample_values']})"]
        if prof["gst_ratio"] >= 0.90 and all(v in GST_STANDARD_RATES for v in prof.get("numeric_values", [])):
            gst_score += 0.18
            gst_ev.append("100% of values match statutory Indian GST slabs (0, 5, 12, 18, 28%)")
        if "gstPercent" in candidates_dict:
            candidates_dict["gstPercent"]["score"] = max(candidates_dict["gstPercent"]["score"], min(0.99, gst_score + 0.10))
            candidates_dict["gstPercent"]["evidence"].extend(gst_ev)
            candidates_dict["gstPercent"]["source"] = "COMBINED_EVIDENCE"
        else:
            candidates_dict["gstPercent"] = {
                "field": "gstPercent", "score": min(0.98, gst_score), "evidence": gst_ev,
                "source": "CURRENT_BODY", "header_score": 0.0, "body_score": gst_score, "arithmetic_score": 0.0
            }

    # Monetary (Rate, MRP, Amount, Taxable, Net)
    if prof["mrp_rate_ratio"] >= 0.50 and prof["hsn_ratio"] < 0.40 and not is_seq_ints and not is_auxiliary_header(raw_h):
        curr_vals = prof.get("numeric_values", [])
        c_avg = sum(curr_vals) / len(curr_vals) if curr_vals else 0
        is_small_pct = prof["discount_ratio"] >= 0.75 and c_avg <= 25.0

        if not is_small_pct:
            for other_idx, other_prof in enumerate(all_profiles):
                if other_idx != col_idx and other_prof.get("numeric_ratio", 0) >= 0.5:
                    other_vals = other_prof.get("numeric_values", [])
                    if other_vals and curr_vals:
                        o_avg = sum(other_vals) / len(other_vals)
                        if c_avg > o_avg * 1.05 and c_avg <= o_avg * 3.0:
                            if "mrp" in candidates_dict:
                                candidates_dict["mrp"]["score"] = min(0.99, candidates_dict["mrp"]["score"] + 0.15)
                                candidates_dict["mrp"]["evidence"].append(f"consistently higher than col_{other_idx} (MRP >= Rate)")
                        elif c_avg < o_avg * 0.95 and c_avg >= 5.0:
                            if "rate" in candidates_dict:
                                candidates_dict["rate"]["score"] = min(0.99, candidates_dict["rate"]["score"] + 0.15)
                                candidates_dict["rate"]["evidence"].append(f"consistently lower than col_{other_idx} (Rate <= MRP)")

                    for third_idx, third_prof in enumerate(all_profiles):
                        if third_idx not in (col_idx, other_idx) and third_prof.get("numeric_ratio", 0) >= 0.5:
                            if check_arithmetic_relationship(other_idx, col_idx, third_idx, rows) >= 0.6:
                                if "rate" in candidates_dict:
                                    candidates_dict["rate"]["score"] = min(0.99, candidates_dict["rate"]["score"] + 0.20)
                                    candidates_dict["rate"]["evidence"].append(f"arithmetic verified: Qty(col_{other_idx}) * Rate(col_{col_idx}) ≈ Amount(col_{third_idx})")
                                    candidates_dict["rate"]["source"] = "CURRENT_ARITHMETIC"
                            if check_arithmetic_relationship(other_idx, third_idx, col_idx, rows) >= 0.6:
                                if "amount" in candidates_dict:
                                    candidates_dict["amount"]["score"] = min(0.99, candidates_dict["amount"]["score"] + 0.20)
                                    candidates_dict["amount"]["evidence"].append(f"arithmetic verified: Qty(col_{other_idx}) * Rate(col_{third_idx}) ≈ Amount(col_{col_idx})")
                                    candidates_dict["amount"]["source"] = "CURRENT_ARITHMETIC"

    c_list = list(candidates_dict.values())
    c_list.sort(key=lambda x: x["score"], reverse=True)
    return c_list

def generic_global_semantic_assignment(headers, rows, columns_coord_info=None, saved_template=None, debug: bool = False) -> dict:
    named_headers = ensure_named_headers(headers)
    total_cols = len(named_headers)

    profiles = []
    for idx, raw_h in enumerate(named_headers):
        col_vals = [row[idx] if idx < len(row) else None for row in rows]
        x0 = columns_coord_info[idx].get("x0") if (columns_coord_info and idx < len(columns_coord_info)) else None
        x1 = columns_coord_info[idx].get("x1") if (columns_coord_info and idx < len(columns_coord_info)) else None
        prof = profile_column(idx, raw_h, col_vals, x0=x0, x1=x1, total_cols=total_cols)
        profiles.append(prof)

    col_candidates = []
    for idx, raw_h in enumerate(named_headers):
        cands = score_column_evidence(idx, raw_h, profiles[idx], profiles, rows, saved_template=saved_template)
        col_candidates.append(cands)

    all_pairs = []
    for col_idx, cands in enumerate(col_candidates):
        for c in cands:
            all_pairs.append((c["score"], col_idx, c["field"], c))

    all_pairs.sort(key=lambda x: x[0], reverse=True)

    assigned_cols = {}
    claimed_fields = {}

    for score, col_idx, field, c_info in all_pairs:
        if col_idx in assigned_cols:
            continue
        if field in claimed_fields:
            continue
        
        min_thresh = 0.50
        if score < min_thresh:
            continue

        other_cands = [c for c in col_candidates[col_idx] if c["field"] != field and c["field"] not in claimed_fields]
        second_score = other_cands[0]["score"] if other_cands else 0.0
        alt_field = other_cands[0]["field"] if other_cands else None
        margin = round(score - second_score, 3)

        assigned_cols[col_idx] = {
            "mapped_to": field,
            "status": "known_header" if c_info["source"] == "CURRENT_HEADER" else ("inferred" if c_info["source"] in ("CURRENT_BODY", "CURRENT_ARITHMETIC") else "profile_prior"),
            "confidence": round(score * 100.0, 1),
            "evidence": c_info["evidence"],
            "source": c_info["source"],
            "margin": margin,
            "alternative": alt_field,
            "alternative_score": round(second_score * 100.0, 1) if second_score > 0 else None,
            "candidates": col_candidates[col_idx],
        }
        claimed_fields[field] = col_idx

    results = {}
    for idx, raw_h in enumerate(named_headers):
        x0 = profiles[idx].get("x0")
        x1 = profiles[idx].get("x1")
        if idx in assigned_cols:
            res = dict(assigned_cols[idx])
            res["col_idx"] = idx
            res["x0"] = x0
            res["x1"] = x1
            results[raw_h] = res
        else:
            cands = col_candidates[idx]
            top_cand = cands[0] if cands else None
            results[raw_h] = {
                "mapped_to": None,
                "status": "unresolved",
                "confidence": round(top_cand["score"] * 100.0, 1) if top_cand else 0.0,
                "evidence": top_cand["evidence"] if top_cand else ["No viable canonical candidate found"],
                "source": top_cand["source"] if top_cand else None,
                "margin": 0.0,
                "alternative": top_cand["field"] if top_cand else None,
                "candidates": cands,
                "col_idx": idx,
                "x0": x0,
                "x1": x1,
            }

    return results

# Monkey patch extractor.infer_unresolved_column_semantics for testing
extractor.infer_unresolved_column_semantics = generic_global_semantic_assignment

from evaluation.field_accuracy import evaluate_canonical_field_accuracy

print("="*70)
print("RUNNING FIELD ACCURACY EVALUATION WITH PROMPT 19 GLOBAL SEMANTICS")
print("="*70)
res = evaluate_canonical_field_accuracy()
print(f"Overall Accuracy: {res.overall_field_accuracy}%")
print(f"Critical Accuracy: {res.overall_critical_field_accuracy}%")
print(f"Financial Accuracy: {res.overall_financial_field_accuracy}%")
print(f"Fully Correct Rows: {res.fully_correct_rows}")
print(f"Partially Correct Rows: {res.partially_correct_rows}")
print(f"Critical Error Rows: {res.critical_error_rows}")
print("\nDocument Breakdown:")
for doc in res.document_reports:
    print(f"  {doc.filename:35s} | Acc: {doc.overall_field_accuracy:6.2f}% | Crit: {doc.critical_field_accuracy:6.2f}% | Fin: {doc.financial_field_accuracy:6.2f}% | Decision: {doc.decision:15s}")
