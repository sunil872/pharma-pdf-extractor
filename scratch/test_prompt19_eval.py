import os
import sys
import json
import re
from rapidfuzz import fuzz, process

sys.path.insert(0, ".")

from extractor import (
    ALIAS_DICT, clean_text, normalize_split_header_text, is_serial_number_header,
    _to_float, parse_compound_qty, GST_STANDARD_RATES, PHARMA_ITEM_WORDS, PACK_PATTERN,
    extract_page_words, detect_coordinate_header_row, determine_column_boundaries,
    detect_logical_subcolumns, assign_tokens_to_columns, _merge_continuation_rows,
    _is_genuine_product_row, _is_footer_row, _is_letterhead_row, standardize_date,
    profile_column, check_arithmetic_relationship, ensure_named_headers
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
        "old", "oldmrp", "oldmrp", "oldmrsp", "prevmrp", "rmar", "margin",
    }:
        return True
    return False

def score_header_for_canonical_fields(header_raw: str, saved_template: dict = None) -> list:
    """
    Evaluates header text against canonical fields with specific priorities.
    Returns list of (field, score, evidence).
    """
    if not header_raw:
        return []
    
    if is_auxiliary_header(header_raw):
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
                # Calculate priority score
                p_score = 0.95
                ev = [f"Exact alias match for '{alias}'"]
                
                # Priority adjustments for specific headers
                if field == "rate":
                    if cleaned in {"ptr", "pricetoretailer", "purrate"}:
                        p_score = 1.00
                        ev.append("High priority base purchase rate header (PTR)")
                    elif cleaned == "rate":
                        p_score = 0.90
                elif field == "mrp":
                    if cleaned in {"mrp", "maxretailprice", "maximumretailprice"}:
                        p_score = 1.00
                elif field == "discountPercent":
                    if "%" in header_raw or cleaned in {"dis", "disc", "discount"}:
                        p_score = 0.98 if "%" in header_raw else 0.90
                elif field == "gstPercent":
                    if "%" in header_raw or "rate" in norm.lower():
                        p_score = 0.98
                    elif cleaned == "gst":
                        p_score = 0.90
                elif field == "amount":
                    if cleaned in {"amount", "grossamt", "grossamount", "grossvalue"}:
                        p_score = 0.98
                    elif cleaned in {"amt", "value", "total"}:
                        p_score = 0.88
                elif field == "freeQuantity":
                    if cleaned in {"free", "freeqty", "bonus"}:
                        p_score = 0.98
                    elif cleaned in {"sch", "scheme"}:
                        p_score = 0.85  # Scheme can be qty or discount %
                
                candidates.append((field, p_score, ev, "CURRENT_HEADER"))
                break

    # 2. Saved template prior
    if saved_template:
        mapped = saved_template.get(norm) or saved_template.get(header_raw)
        if mapped and mapped in ALIAS_DICT and not is_auxiliary_header(norm):
            if not any(c[0] == mapped for c in candidates):
                candidates.append((mapped, 0.80, ["Matched historical template prior"], "PROFILE_PRIOR"))

    # 3. Fuzzy matching if no exact alias
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
                candidates.append((f_match, round(score / 100.0 * 0.85, 2), [f"Fuzzy match '{best_match}' (score {score:.0f}%)"], "CURRENT_HEADER"))

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates

print("Auxiliary and Header scoring loaded successfully.")
