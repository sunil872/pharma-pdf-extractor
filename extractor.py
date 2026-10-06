import os
import json
import hashlib
import re
import logging
from datetime import datetime
import pdfplumber
import pandas as pd
from rapidfuzz import process, fuzz

try:
    import ocr_engine
except ImportError:
    ocr_engine = None

logger = logging.getLogger(__name__)



# Canonical system columns used by the purchase import engine.
ALIAS_DICT = {
    "itemName": [
        "product name", "item description", "particulars", "product nmae",
        "item name", "product", "description", "item", "product/item", "item/product"
    ],
    "pack": [
        "pack", "packing", "packs", "pack size", "packsize", "packing size", "pkg", "pk", "unit", "uom"
    ],
    "batchNo": [
        "batch", "batch no", "batchno", "batch no.", "batch number", "lot", "lot no", "lot no.", "lot.no", "batch/lot", "b.no", "b.no."
    ],
    "expiryDate": [
        "exp", "expiry", "exp date", "exp.", "e.x.p", "ex", "ex...", "expiry date", "exp.date", "val date", "validity"
    ],
    "quantity": [
        "qty", "quantity", "billed qty", "billed", "units", "bld qty", "qty.",
        "quantity billed", "qty+free", "qty/free", "nos", "no", "nos.", "no."
    ],
    "freeQuantity": [
        "free", "free qty", "sch qty", "scheme qty", "f.qty", "free quantity", "bonus", "sch.qty"
        # NOTE: bare "sch"/"scheme" are intentionally excluded — they map to discountPercent
        # (SCH = scheme discount %).  "sch qty" / "scheme qty" remain for unambiguous free-qty headers.
    ],
    "discountPercent": [
        "dis", "disc", "disc.", "sch", "scheme", "idisper", "dis%", "disc%", "discount %", "discount", "discount%", "sch%", "scheme%"
    ],
    "rate": [
        "rate", "rat e", "ptr", "pur rate", "purchase rate", "Rate ", "p.t.r", "rate/unit", "pur. rate", "p.t.r.", "unit rate", "net rate", "price to retailer"
    ],
    "mrp": [
        "mrp", "m.r.p", "max retail price", "M.R.P", "M R P", "m r p", "m.r.p.", "old mrp", "old m.r.p", "maximum retail price", "mrp rs"
    ],
    "hsnCode": [
        "hsn", "hsn/sac", "hsn code", "hsncode", "sac code", "hsn/sac code", "hsn code/sac", "hsn/saccode", "hsn/sc", "hsn code/sac code"
    ],
    "amount": [
        "amount", "gross amt", "gross amount", "total", "item amt", "amt", "value", "gross value"
    ],
    "taxableAmount": [
        "taxable", "taxable amt", "taxable value", "taxable amount", "taxable val", "taxable val."
    ],
    "netAmount": [
        "net", "net amount", "net value", "net amt", "bill amt", "net payable", "net pay", "invoice amt"
    ],
    "cgstPercent": [
        "cgst", "cgst%", "cgst per", "cgstper", "cgst rate", "c.gst", "c.gst%"
    ],
    "sgstPercent": [
        "sgst", "sgst%", "sgst per", "sgstper", "sgst rate", "s.gst", "s.gst%", "utgst", "utgst%"
    ],
    "gstPercent": [
        "gst", "gst%", "gst rate", "total gst", "igst", "tax%", "tax", "tax rate", "vat%"
    ],
    "company": [
        "mfr", "mfg", "mkt by", "mfname", "mfgby", "company", "mfac mkt by", "mfac/ mkt by", "mfac/", "manufacturer", "mfg.by", "mfr."
    ],
}

SERIAL_NUMBER_ALIASES = ["s", "sn", "sno", "s.no", "sl no", "sr no", "sl.no", "s no", "sr.no"]

PACK_PATTERN = re.compile(
    r"(?i)\b(\d+['`’]s|\d+\s*s|\d+x\d+|\d+\*\d+|\d+\s*(?:ml|gm|mg|tab|cap|vial|amp|btl|strip|box|ltr|kg))\b"
)
PHARMA_ITEM_WORDS = {
    "tab", "caps", "cap", "syp", "inj", "gel", "susp", "oint", "drops", "cream",
    "tablet", "capsule", "syrup", "injection", "ointment", "powder", "lotion",
    "solution", "emulsion", "pharma", "mg", "ml", "gm", "forte", "plus", "duo",
    "ds", "dry", "dt", "sr", "er", "cr", "xl", "xr", "mr", "resp", "inhaler",
}
GST_STANDARD_RATES = {0.0, 5.0, 12.0, 18.0, 28.0, 0.25, 1.5, 2.5, 6.0, 9.0, 14.0}

FOOTER_STOP_WORDS = [
    "remark:", "bank name", "amount in words", "continued", "continue",
    "continue page", "continued on", "contd", "cont.",
    "sub total", "subtotal", "grand total", "tax%", "declaration",
    "tot items", "total items", "total qty", "mr value", "mrp value", "total tax amt",
    "rupees", "rs.", "ifsc", "terms", "condition", "authorised signatory",
    "authorized signatory", "taxable amt", "taxable value",
    "outstanding", "for oustanding", "for outstanding",
    "picked by", "checked by", "packed by", "delivery by",
]

# Letterhead / party / page chrome that must never become line items.
LETTERHEAD_SKIP_WORDS = [
    "logistics", "pharma hub", "gst invoice", "tax inv.no", "tax inv no",
    "page 2", "page 1", "page no", "page of", "d.l.no", "dl no", "d.l no",
    "credit", "sales executive", "original for recipient",
    "invoice date", "due date", "order no", "ref id", "route nam",
    "gstin:", "gstin ", "phone:", "email id", "udyam", "whatsapp",
    "authorised", "authorized",
]

# Repeated column-header cues on continuation pages.
REPEATED_HEADER_WORDS = [
    "item description", "product name", "product nmae", "m.r.p", "mrp",
    "quantity", "billed free", "pack batch", "hsn /sac", "old mrp",
    "mfac/ mkt", "exp date",
]

SYSTEM_COLUMNS = {
    "itemName": {"label": "Item Name", "required": True, "description": "Name of the item/product"},
    "pack": {"label": "Pack", "required": False, "description": "Pack size/quantity information"},
    "batchNo": {"label": "Batch Number", "required": False, "description": "Batch number of the item"},
    "expiryDate": {"label": "Expiry Date", "required": False, "description": "Expiry date of the item"},
    "quantity": {"label": "Quantity", "required": True, "description": "Quantity of items"},
    "freeQuantity": {"label": "Free Quantity", "required": False, "description": "Free quantity offered"},
    "discountPercent": {"label": "Discount %", "required": False, "description": "Discount percentage"},
    "rate": {"label": "Rate", "required": True, "description": "Purchase rate per unit"},
    "mrp": {"label": "MRP", "required": False, "description": "Maximum Retail Price (optional as many suppliers omit MRP)"},
    "hsnCode": {"label": "HSN Code", "required": False, "description": "Harmonized System of Nomenclature code"},
    "amount": {"label": "Amount", "required": False, "description": "Gross amount (qty × rate); auto-calculated when missing"},
    "taxableAmount": {"label": "Taxable Amount", "required": False, "description": "Taxable value after discount; auto-calculated when missing"},
    "netAmount": {"label": "Net Amount", "required": False, "description": "Net payable including GST; auto-calculated when missing"},
    "cgstPercent": {"label": "CGST %", "required": False, "description": "Central GST percentage"},
    "sgstPercent": {"label": "SGST %", "required": False, "description": "State GST percentage"},
    "gstPercent": {"label": "GST %", "required": False, "description": "Flat / total GST percentage (includes IGST aliases)"},
    "company": {"label": "Company", "required": False, "description": "Company/Manufacturer name of the item"},
}

SYSTEM_FIELD_ORDER = [
    "itemName", "pack", "batchNo", "expiryDate", "quantity", "freeQuantity",
    "discountPercent", "rate", "mrp", "hsnCode", "amount", "taxableAmount",
    "gstPercent", "cgstPercent", "sgstPercent", "netAmount", "company",
]

PREVIEW_COLUMN_ORDER = [
    "itemName", "pack", "batchNo", "expiryDate", "quantity", "freeQuantity",
    "rate", "mrp", "discountPercent", "hsnCode", "amount", "taxableAmount",
    "gstPercent", "cgstPercent", "sgstPercent", "netAmount", "company",
]

DEFAULT_EXPIRY_DATE_FORMAT = "MM/YYYY"


def clean_text(text: str) -> str:
    """Normalize text for consistent matching by removing non-alphanumeric characters."""
    return re.sub(r'[^a-z0-9]', '', str(text).lower())


def normalize_split_header_text(raw_header: str) -> str:
    """
    Normalizes spaced, broken, or multi-line header strings:
    E.g. 'M R P' -> 'MRP', 'P T R' -> 'PTR', 'P. T. R' -> 'P.T.R', 'BAT CH' -> 'BATCH',
    'EX P' -> 'EXP', 'RA TE' -> 'RATE', 'G S T' -> 'GST', 'Q T Y' -> 'QTY', 'H S N' -> 'HSN'.
    """
    if raw_header is None:
        return ""
    s = " ".join(str(raw_header).replace("\r", " ").replace("\n", " ").split()).strip()
    if not s:
        return ""

    # Compress single-letter spaced acronyms (e.g. M R P -> MRP, P T R -> PTR, G S T -> GST)
    s_comp = re.sub(r"\b([A-Za-z])\s+([A-Za-z])\s+([A-Za-z])\b", r"\1\2\3", s)
    s_comp = re.sub(r"\b([A-Za-z])\s+([A-Za-z])\b", r"\1\2", s_comp)

    # Specific common split header patterns
    splits = {
        r"(?i)\bm\s*r\s*p\b": "MRP",
        r"(?i)\bp\s*t\s*r\b": "PTR",
        r"(?i)\bp\s*\.\s*t\s*\.\s*r\b": "P.T.R",
        r"(?i)\bbat\s*ch\b": "BATCH",
        r"(?i)\bex\s*p\b": "EXP",
        r"(?i)\bra\s*te\b": "RATE",
        r"(?i)\bg\s*s\s*t\b": "GST",
        r"(?i)\bh\s*s\s*n\b": "HSN",
        r"(?i)\bq\s*t\s*y\b": "QTY",
        r"(?i)\bdi\s*sc\b": "DISC",
        r"(?i)\bprod\s*uct\b": "PRODUCT",
        r"(?i)\bpack\s*ing\b": "PACKING",
    }
    for pat, rep in splits.items():
        s_comp = re.sub(pat, rep, s_comp)
    return s_comp


def is_serial_number_header(raw_header: str) -> bool:
    if raw_header is None:
        return False
    norm = normalize_split_header_text(raw_header)
    cleaned = clean_text(norm)
    if not cleaned:
        return False
    return cleaned in {clean_text(a) for a in SERIAL_NUMBER_ALIASES}


def match_column_name(raw_header: str, saved_template: dict = None):
    if raw_header is None:
        return None

    raw_str = normalize_split_header_text(raw_header)
    if not raw_str:
        return None

    if is_serial_number_header(raw_str):
        return None

    cleaned_header = clean_text(raw_str)

    # Specific auxiliary exclusions (do not map non-canonical auxiliary terms to canonical fields)
    if cleaned_header in {"disamt", "discamt", "discountamount", "discamt", "schamt"}:
        return None
    if cleaned_header in {"gstamt", "taxamt", "totaltaxamt", "gstamount", "cgstamt", "sgstamt", "taxamount"}:
        return None
    if cleaned_header in {"rack", "location", "bin", "slot"}:
        return None
    if cleaned_header in {"box", "boxs", "boxes", "outer", "case", "cases"}:
        return None
    if cleaned_header in {"old", "oldmrp", "oldm.r.p", "prevmrp"}:
        return None

    # 1. Exact alias match against canonical ALIAS_DICT
    for system_field, aliases in ALIAS_DICT.items():
        for alias in aliases:
            if clean_text(alias) == cleaned_header:
                return system_field

    # 2. Saved template / supplier profile prior (as prior signal if not unmapped/auxiliary)
    if saved_template and raw_str in saved_template:
        mapped = saved_template[raw_str]
        if mapped and mapped not in ("itemCode", "igstPercent", "saleRate", "boxs", "old"):
            return mapped
    if saved_template and str(raw_header) in saved_template:
        mapped = saved_template[str(raw_header)]
        if mapped and mapped not in ("itemCode", "igstPercent", "saleRate", "boxs", "old"):
            return mapped

    # 3. Fuzzy similarity match
    flat_aliases = []
    alias_to_field = {}
    for system_field, aliases in ALIAS_DICT.items():
        for alias in aliases:
            flat_aliases.append(alias)
            alias_to_field[alias] = system_field

    result = process.extractOne(
        raw_str.lower(),
        flat_aliases,
        scorer=fuzz.token_sort_ratio,
    )
    if result is None:
        return None

    best_match, score, _ = result
    min_score = 90.0 if len(cleaned_header) <= 4 else 75.0
    if score >= min_score:
        return alias_to_field[best_match]
    return None


def _header_field_priority_score(system_field: str, raw_header: str) -> float:
    raw_norm = normalize_split_header_text(raw_header)
    cleaned = clean_text(raw_norm)

    if system_field == "rate":
        # RATE is the purchase/import rate; PTR is related but must not win over RATE
        # when both columns exist (PHUB and similar dual-column invoices).
        if cleaned == "rate":
            return 1000.0
        if cleaned in {"ptr", "p.t.r", "p.t.r.", "pricetoretailer"}:
            return 700.0
        if cleaned in {"purrate", "purchaserate", "pur.rate", "unitrate"}:
            return 800.0
        if cleaned == "netrate":
            return 500.0
    if system_field == "mrp":
        if cleaned in {"mrp", "m.r.p", "m.r.p.", "maxretailprice", "maximumretailprice"}:
            return 1000.0
        if cleaned in {"oldmrp", "oldm.r.p", "old"}:
            return 100.0
    if system_field == "pack":
        if cleaned in {"pack", "packing", "packs", "packsize", "packingsize", "pkg", "pk"}:
            return 1000.0
        if cleaned in {"unit", "uom", "size"}:
            return 500.0
        if cleaned in {"boxs", "boxes", "box"}:
            return 0.0
    if system_field == "quantity":
        if cleaned in {"billedqty", "quantitybilled", "billed"}:
            return 1000.0
        if cleaned in {"qty", "quantity", "units", "nos"}:
            return 950.0
        if cleaned in {"rack", "location"}:
            return 0.0
    if system_field == "discountPercent":
        if cleaned in {"dis%", "disc%", "discount%", "sch%", "scheme%"}:
            return 1000.0
        if cleaned in {"dis", "disc", "discount", "sch", "scheme"}:
            return 900.0
        if "amt" in cleaned or "amount" in cleaned:
            return 0.0
    if system_field == "amount":
        if cleaned in {"amount", "grossamt", "grossamount", "grossvalue"}:
            return 1000.0
        if cleaned in {"amt", "total", "itemamt", "value"}:
            return 900.0
        if "gst" in cleaned or "tax" in cleaned or "dis" in cleaned:
            return 0.0
    if system_field == "gstPercent":
        if cleaned in {"gst%", "gstrate", "tax%", "taxrate", "totalgst", "igst"}:
            return 1000.0
        if cleaned in {"gst", "tax"}:
            return 900.0
        if "amt" in cleaned or "amount" in cleaned:
            return 0.0

    primary = ALIAS_DICT.get(system_field, [system_field])[0]
    return float(fuzz.ratio(cleaned, clean_text(primary)))


def resolve_column_mappings(headers, saved_template: dict = None) -> dict:
    tentative = [(h, match_column_name(h, saved_template)) for h in headers]
    by_field = {}
    for header, field in tentative:
        if field:
            by_field.setdefault(field, []).append(header)

    winners = {}
    for field, candidates in by_field.items():
        if len(candidates) == 1:
            winners[candidates[0]] = field
        else:
            best = max(candidates, key=lambda h: _header_field_priority_score(field, h))
            winners[best] = field

    return {header: winners.get(header) for header, _ in tentative}


def ensure_named_headers(header_row):
    named = []
    for idx, cell in enumerate(header_row):
        text = "" if cell is None else str(cell).strip()
        named.append(text if text else f"Unnamed_Col_{idx}")
    return named


def profile_column(col_idx, header_raw, values, x0=None, x1=None, total_cols=None):
    """
    Builds a statistical, geometric, and pattern profile for a physical column across all product rows.
    """
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

            # HSN check: pure digits, length 4, 6, or 8, starting with standard Pharma/GST chapters (30, 21, 38, 90, 33, 34, 29)
            is_valid_hsn_chapter = cleaned.startswith(("30", "21", "38", "90", "33", "34", "29", "19", "40", "48"))
            if not has_decimal and re.fullmatch(r"\d{4}|\d{6}|\d{8}", cleaned) and is_valid_hsn_chapter:
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

            # Monetary check: explicit decimal or typical unit price / mrp range
            if f_val > 0:
                if has_decimal or f_val >= 25.0:
                    mrp_rate_like_count += 1
                if f_val >= 50.0:
                    amount_like_count += 1
        else:
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
    """
    Scores all canonical SYSTEM_COLUMNS as candidates for an unresolved column.
    """
    if profile.get("empty"):
        return []

    # ── Serial-number column guard ──────────────────────────────────────────────
    # Columns whose values form a monotonically increasing integer sequence
    # starting at a low number (1, 2, 3 …) are serial-number columns — they must
    # never be assigned a canonical pharma field.  Values 1-50 are otherwise
    # indistinguishable from discount-percent candidates by ratio alone.
    _sn_vals = profile.get("numeric_values", [])
    if (
        _sn_vals
        and len(_sn_vals) >= 2
        and profile.get("integer_ratio", 0) >= 0.90
        and profile.get("decimal_ratio", 1.0) == 0.0
    ):
        _int_vals = sorted(int(v) for v in _sn_vals if v == int(v))
        _expected = list(range(_int_vals[0], _int_vals[0] + len(_int_vals)))
        if _int_vals == _expected and _int_vals[0] <= 5 and _int_vals[-1] <= 500:
            return []  # serial-number column — no canonical field assignment

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
        hdr_raw = profile.get("header_raw", "")
        if not is_serial_number_header(hdr_raw):
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


def infer_unresolved_column_semantics(headers, rows, columns_coord_info=None, saved_template=None, debug: bool = False) -> dict:
    """
    Generic dynamic column semantic inference engine.
    Profiles every physical column across all product rows, generates candidate
    semantic matches across all canonical fields, and resolves them globally.
    """
    named_headers = ensure_named_headers(headers)
    total_cols = len(named_headers)
    results = {}

    # 1. First priority: Explicit Headers & Saved Templates
    # Use a two-pass deduplication approach so that when two headers both match
    # the same canonical field (e.g. P.T.R & RATE both → "rate", FREE & SCH both
    # → "freeQuantity"), the one with the higher _header_field_priority_score
    # wins and the other falls through to body-evidence inference.
    claimed_fields = set()

    # --- Pass A: collect all tentative header→field mappings (no dedup yet) ---
    _tentative = {}  # raw_h → field
    for idx, raw_h in enumerate(named_headers):
        is_unnamed = str(raw_h).startswith("Unnamed_Col_")
        _tentative[raw_h] = None if is_unnamed else match_column_name(raw_h, saved_template)

    # --- Pass B: resolve collisions using priority + body fill-rate ---
    _field_to_headers = {}
    for raw_h, field in _tentative.items():
        if field:
            _field_to_headers.setdefault(field, []).append(raw_h)

    # Build a quick fill-rate lookup: fraction of non-empty numeric values per header
    def _col_fill_rate(raw_h: str) -> float:
        """Returns fraction of rows where this column has a non-empty value."""
        h_idx = named_headers.index(raw_h) if raw_h in named_headers else -1
        if h_idx < 0 or not rows:
            return 0.0
        non_empty = sum(1 for r in rows if h_idx < len(r) and str(r[h_idx]).strip())
        return non_empty / max(1, len(rows))

    _header_winner = {}  # raw_h → field (after dedup)
    for field, candidates_list in _field_to_headers.items():
        if len(candidates_list) == 1:
            _header_winner[candidates_list[0]] = field
        else:
            # Score = header_priority_score * 0.7 + body_fill_rate * 0.3
            # This ensures an empty-column winner (PTR with no values) loses to
            # a well-populated runner-up (RATE with actual numeric rates).
            def _combined_score(h, fld=field):
                pri = _header_field_priority_score(fld, h) / 1000.0  # normalise to [0,1]
                fill = _col_fill_rate(h)
                return pri * 0.7 + fill * 0.3

            best_h = max(candidates_list, key=_combined_score)
            _header_winner[best_h] = field
            # Losers become unresolved and fall through to body-evidence inference

    # --- Build initial results dict ---
    for idx, raw_h in enumerate(named_headers):
        x0 = columns_coord_info[idx].get("x0") if (columns_coord_info and idx < len(columns_coord_info)) else None
        x1 = columns_coord_info[idx].get("x1") if (columns_coord_info and idx < len(columns_coord_info)) else None

        mapped_field = _header_winner.get(raw_h)  # None for losers & unresolved

        if mapped_field:
            claimed_fields.add(mapped_field)
            results[raw_h] = {
                "mapped_to": mapped_field,
                "status": "known_header",
                "confidence": 100.0,
                "candidates": [{"field": mapped_field, "score": 1.0, "evidence": ["Explicit header matched canonical alias (deduplication winner)"]}],
                "evidence": ["Explicit header matched canonical alias (deduplication winner)"],
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


# ==============================================================================
# PROMPT 6: GLOBAL VALIDATION, RECONCILIATION & CONFIDENCE ENGINE
# ==============================================================================

def load_saved_templates_dict() -> dict:
    """Loads saved supplier templates from templates.json if available."""
    template_file = "templates.json"
    if os.path.exists(template_file):
        try:
            with open(template_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def validate_field_quality(field_name: str, values: list, header_str: str = "", profile: dict = None) -> dict:
    """
    Computes quality, validity, consistency, and contradiction metrics for a canonical field across rows.
    """
    total_rows = len(values)
    non_empty = [v for v in values if v is not None and str(v).strip() != ""]
    val_count = len(non_empty)

    present_ratio = val_count / max(1, total_rows)

    if val_count == 0:
        return {
            "field": field_name,
            "value_present_ratio": 0.0,
            "format_valid_ratio": 0.0,
            "row_consistency": 0.0,
            "geometry_consistency": 1.0,
            "missing_count": total_rows,
            "contradiction_count": 0,
            "suspicious_count": 0,
            "quality_score": 0.0,
        }

    valid_format_count = 0
    contradiction_count = 0
    suspicious_count = 0

    for v in non_empty:
        s = str(v).strip()
        f_num = _to_float(s)

        if field_name == "quantity":
            billed, free = parse_compound_qty(s)
            if billed > 0 or (f_num is not None and f_num >= 0):
                valid_format_count += 1
            else:
                contradiction_count += 1
            if f_num is not None and f_num > 50000:
                suspicious_count += 1

        elif field_name == "freeQuantity":
            billed, free = parse_compound_qty(s)
            if free > 0 or (f_num is not None and f_num >= 0):
                valid_format_count += 1
            else:
                contradiction_count += 1
            if f_num is not None and f_num > 5000:
                suspicious_count += 1

        elif field_name in ("rate", "mrp", "amount", "taxableAmount", "netAmount"):
            if f_num is not None and f_num >= 0:
                valid_format_count += 1
            else:
                contradiction_count += 1
            if f_num is not None and f_num == 0 and field_name in ("rate", "mrp"):
                suspicious_count += 1

        elif field_name == "discountPercent":
            if f_num is not None and 0.0 <= f_num <= 100.0:
                valid_format_count += 1
            else:
                contradiction_count += 1

        elif field_name in ("gstPercent", "cgstPercent", "sgstPercent"):
            if f_num is not None and (f_num in GST_STANDARD_RATES or (0.0 <= f_num <= 35.0)):
                valid_format_count += 1
            else:
                contradiction_count += 1

        elif field_name == "expiryDate":
            if standardize_date(s) is not None or bool(re.search(r"\d{1,2}[/-]\d{2,4}", s)):
                valid_format_count += 1
            else:
                contradiction_count += 1

        elif field_name == "hsnCode":
            is_digits = bool(re.fullmatch(r"\d{4}|\d{6}|\d{8}", s))
            is_ch = s.startswith(("30", "21", "38", "90", "33", "34", "29", "19", "40", "48"))
            if is_digits and is_ch:
                valid_format_count += 1
            elif is_digits:
                suspicious_count += 1
            else:
                contradiction_count += 1

        elif field_name == "batchNo":
            if len(s) >= 2 and not bool(re.fullmatch(r"\d{1,2}[/-]\d{2,4}", s)):
                valid_format_count += 1
            else:
                contradiction_count += 1

        elif field_name == "itemName":
            if len(s) >= 2 and not bool(re.match(r"^\d+(?:\.\d+)?$", s)):
                valid_format_count += 1
            else:
                contradiction_count += 1

        else:
            valid_format_count += 1

    format_ratio = valid_format_count / max(1, val_count)
    missing_count = total_rows - val_count
    row_consistency = format_ratio

    quality_score = min(1.0, (format_ratio * 0.6) + (present_ratio * 0.4) - (contradiction_count * 0.1))
    quality_score = max(0.0, quality_score)

    return {
        "field": field_name,
        "value_present_ratio": round(present_ratio, 3),
        "format_valid_ratio": round(format_ratio, 3),
        "row_consistency": round(row_consistency, 3),
        "geometry_consistency": 1.0,
        "missing_count": missing_count,
        "contradiction_count": contradiction_count,
        "suspicious_count": suspicious_count,
        "quality_score": round(quality_score, 3),
    }


def detect_and_resolve_field_swaps(headers: list, logical_columns: list, column_mappings: dict, rows: list) -> tuple[dict, list]:
    """
    Generic cross-field candidate swap detection and resolution.
    Compares alternate assignments globally using multi-dimensional evidence.
    """
    resolved_mappings = {h: dict(info) for h, info in column_mappings.items()}
    swap_log = []

    field_to_hdrs = {}
    for h, info in resolved_mappings.items():
        m = info.get("mapped_to")
        if m:
            field_to_hdrs.setdefault(m, []).append(h)

    # 1. Check Rate <-> MRP swap
    if "rate" in field_to_hdrs and "mrp" in field_to_hdrs:
        r_hdr = field_to_hdrs["rate"][0]
        m_hdr = field_to_hdrs["mrp"][0]
        r_idx = headers.index(r_hdr) if r_hdr in headers else None
        m_idx = headers.index(m_hdr) if m_hdr in headers else None

        if r_idx is not None and m_idx is not None:
            r_vals = [_to_float(row[r_idx]) for row in rows if r_idx < len(row)]
            m_vals = [_to_float(row[m_idx]) for row in rows if m_idx < len(row)]
            valid_pairs = [(rv, mv) for rv, mv in zip(r_vals, m_vals) if rv is not None and mv is not None and rv > 0 and mv > 0]

            if valid_pairs:
                rate_greater_count = sum(1 for rv, mv in valid_pairs if rv > mv * 1.05)
                if (rate_greater_count / len(valid_pairs)) >= 0.80:
                    resolved_mappings[r_hdr]["mapped_to"] = "mrp"
                    resolved_mappings[r_hdr]["evidence"] = resolved_mappings[r_hdr].get("evidence", []) + ["Swapped to MRP (MRP >= Rate constraint)"]
                    resolved_mappings[m_hdr]["mapped_to"] = "rate"
                    resolved_mappings[m_hdr]["evidence"] = resolved_mappings[m_hdr].get("evidence", []) + ["Swapped to Rate (Rate <= MRP constraint)"]
                    swap_log.append({"swap": "rate <-> mrp", "reason": f"Rate was greater than MRP in {rate_greater_count}/{len(valid_pairs)} rows"})
                    field_to_hdrs["rate"] = [m_hdr]
                    field_to_hdrs["mrp"] = [r_hdr]

    # 2. Check Qty <-> Free Qty swap
    if "quantity" in field_to_hdrs and "freeQuantity" in field_to_hdrs:
        q_hdr = field_to_hdrs["quantity"][0]
        f_hdr = field_to_hdrs["freeQuantity"][0]
        q_idx = headers.index(q_hdr) if q_hdr in headers else None
        f_idx = headers.index(f_hdr) if f_hdr in headers else None

        if q_idx is not None and f_idx is not None:
            q_vals = [_to_float(row[q_idx], 0.0) for row in rows if q_idx < len(row)]
            f_vals = [_to_float(row[f_idx], 0.0) for row in rows if f_idx < len(row)]

            q_pos = sum(1 for v in q_vals if v and v > 0)
            f_pos = sum(1 for v in f_vals if v and v > 0)

            if q_pos == 0 and f_pos > 0:
                resolved_mappings[q_hdr]["mapped_to"] = "freeQuantity"
                resolved_mappings[f_hdr]["mapped_to"] = "quantity"
                swap_log.append({"swap": "quantity <-> freeQuantity", "reason": "Quantity column was all zeros while Free quantity had positive values"})
                field_to_hdrs["quantity"] = [f_hdr]
                field_to_hdrs["freeQuantity"] = [q_hdr]

    # 3. Check Amount <-> GST swap
    if "amount" in field_to_hdrs and "gstPercent" in field_to_hdrs:
        a_hdr = field_to_hdrs["amount"][0]
        g_hdr = field_to_hdrs["gstPercent"][0]
        a_idx = headers.index(a_hdr) if a_hdr in headers else None
        g_idx = headers.index(g_hdr) if g_hdr in headers else None

        if a_idx is not None and g_idx is not None:
            a_vals = [_to_float(row[a_idx]) for row in rows if a_idx < len(row)]
            g_vals = [_to_float(row[g_idx]) for row in rows if g_idx < len(row)]

            a_clean = [v for v in a_vals if v is not None]
            g_clean = [v for v in g_vals if v is not None]

            a_gst_like = sum(1 for v in a_clean if v in GST_STANDARD_RATES)
            if a_clean and (a_gst_like / len(a_clean)) >= 0.90 and max(a_clean) <= 28.0 and g_clean and max(g_clean) > 50.0:
                resolved_mappings[a_hdr]["mapped_to"] = "gstPercent"
                resolved_mappings[g_hdr]["mapped_to"] = "amount"
                swap_log.append({"swap": "amount <-> gstPercent", "reason": "Amount column contained standard GST slabs and GST column contained large monetary amounts"})
                field_to_hdrs["amount"] = [g_hdr]
                field_to_hdrs["gstPercent"] = [a_hdr]

    # 4. Check Batch <-> Expiry swap
    if "batchNo" in field_to_hdrs and "expiryDate" in field_to_hdrs:
        b_hdr = field_to_hdrs["batchNo"][0]
        e_hdr = field_to_hdrs["expiryDate"][0]
        b_idx = headers.index(b_hdr) if b_hdr in headers else None
        e_idx = headers.index(e_hdr) if e_hdr in headers else None

        if b_idx is not None and e_idx is not None:
            b_vals = [str(row[b_idx]).strip() for row in rows if b_idx < len(row) and row[b_idx]]
            e_vals = [str(row[e_idx]).strip() for row in rows if e_idx < len(row) and row[e_idx]]

            b_dates = sum(1 for v in b_vals if standardize_date(v) is not None or bool(re.search(r"\d{1,2}[/-]\d{2,4}", v)))
            e_dates = sum(1 for v in e_vals if standardize_date(v) is not None or bool(re.search(r"\d{1,2}[/-]\d{2,4}", v)))

            if b_vals and (b_dates / len(b_vals)) >= 0.80 and (e_dates / max(1, len(e_vals))) <= 0.20:
                resolved_mappings[b_hdr]["mapped_to"] = "expiryDate"
                resolved_mappings[e_hdr]["mapped_to"] = "batchNo"
                swap_log.append({"swap": "batchNo <-> expiryDate", "reason": "Batch column contained date formats and Expiry column contained alphanumeric codes"})
                field_to_hdrs["batchNo"] = [e_hdr]
                field_to_hdrs["expiryDate"] = [b_hdr]

    # 5. Check Expiry <-> HSN swap
    if "expiryDate" in field_to_hdrs and "hsnCode" in field_to_hdrs:
        e_hdr = field_to_hdrs["expiryDate"][0]
        h_hdr = field_to_hdrs["hsnCode"][0]
        e_idx = headers.index(e_hdr) if e_hdr in headers else None
        h_idx = headers.index(h_hdr) if h_hdr in headers else None

        if e_idx is not None and h_idx is not None:
            e_vals = [str(row[e_idx]).strip() for row in rows if e_idx < len(row) and row[e_idx]]
            h_vals = [str(row[h_idx]).strip() for row in rows if h_idx < len(row) and row[h_idx]]

            e_is_hsn = sum(1 for v in e_vals if re.fullmatch(r"\d{4}|\d{6}|\d{8}", v) and v.startswith(("30", "21", "38", "90")))
            h_is_date = sum(1 for v in h_vals if standardize_date(v) is not None or bool(re.search(r"\d{1,2}[/-]\d{2,4}", v)))

            if e_vals and (e_is_hsn / len(e_vals)) >= 0.80 and (h_is_date / max(1, len(h_vals))) >= 0.80:
                resolved_mappings[e_hdr]["mapped_to"] = "hsnCode"
                resolved_mappings[h_hdr]["mapped_to"] = "expiryDate"
                swap_log.append({"swap": "expiryDate <-> hsnCode", "reason": "Expiry column contained HSN digits and HSN column contained expiry dates"})
                field_to_hdrs["expiryDate"] = [h_hdr]
                field_to_hdrs["hsnCode"] = [e_hdr]

    return resolved_mappings, swap_log


def validate_cross_field_accounting(rows: list, column_mappings: dict, headers: list, tolerance: float = 0.10) -> tuple[list, dict]:
    """
    Performs non-destructive cross-field accounting validation across all rows.
    Returns: (row_discrepancies, accounting_summary)
    """
    row_discrepancies = []
    total_mismatches = 0
    total_valid_rows = 0

    field_indices = {}
    for h, info in column_mappings.items():
        m = info.get("mapped_to")
        if m and h in headers:
            field_indices[m] = headers.index(h)

    q_idx = field_indices.get("quantity")
    r_idx = field_indices.get("rate")
    a_idx = field_indices.get("amount")
    d_idx = field_indices.get("discountPercent")
    t_idx = field_indices.get("taxableAmount")
    g_idx = field_indices.get("gstPercent")
    n_idx = field_indices.get("netAmount")

    for r_num, row in enumerate(rows):
        disc_list = []
        qty = _to_float(row[q_idx]) if (q_idx is not None and q_idx < len(row)) else None
        rate = _to_float(row[r_idx]) if (r_idx is not None and r_idx < len(row)) else None
        amount = _to_float(row[a_idx]) if (a_idx is not None and a_idx < len(row)) else None
        discount = _to_float(row[d_idx], 0.0) if (d_idx is not None and d_idx < len(row)) else 0.0
        taxable = _to_float(row[t_idx]) if (t_idx is not None and t_idx < len(row)) else None
        gst = _to_float(row[g_idx]) if (g_idx is not None and g_idx < len(row)) else None
        net = _to_float(row[n_idx]) if (n_idx is not None and n_idx < len(row)) else None

        # 1. Amount validation (Qty * Rate ≈ Amount)
        if qty is not None and rate is not None and qty > 0 and rate > 0 and amount is not None:
            expected_amt = round(qty * rate, 2)
            diff = abs(amount - expected_amt)
            if diff > 0.0:
                if diff <= 0.05:
                    disc_list.append({
                        "field": "amount", "extracted": amount, "expected": expected_amt,
                        "diff": round(diff, 2), "rule": "qty * rate ≈ amount", "severity": "INFO"
                    })
                    total_valid_rows += 1
                elif diff <= max(1.0, expected_amt * 0.02):
                    disc_list.append({
                        "field": "amount", "extracted": amount, "expected": expected_amt,
                        "diff": round(diff, 2), "rule": "qty * rate ≈ amount", "severity": "WARNING"
                    })
                    total_valid_rows += 1
                else:
                    disc_list.append({
                        "field": "amount", "extracted": amount, "expected": expected_amt,
                        "diff": round(diff, 2), "rule": "qty * rate ≈ amount", "severity": "CRITICAL"
                    })
                    total_mismatches += 1
            else:
                total_valid_rows += 1

        # 2. Taxable amount validation (Amount * (1 - Disc/100) ≈ Taxable)
        if amount is not None and taxable is not None and discount is not None:
            expected_taxable = round(amount * (1.0 - (discount / 100.0)), 2)
            diff = abs(taxable - expected_taxable)
            if diff > max(tolerance, expected_taxable * 0.02):
                disc_list.append({
                    "field": "taxableAmount", "extracted": taxable, "expected": expected_taxable,
                    "diff": round(diff, 2), "rule": "amount * (1 - disc/100) ≈ taxable", "severity": "WARNING"
                })

        # 3. Net amount validation (Taxable * (1 + GST/100) ≈ Net)
        if taxable is not None and net is not None and gst is not None:
            expected_net = round(taxable * (1.0 + (gst / 100.0)), 2)
            diff = abs(net - expected_net)
            if diff > max(tolerance, expected_net * 0.02):
                disc_list.append({
                    "field": "netAmount", "extracted": net, "expected": expected_net,
                    "diff": round(diff, 2), "rule": "taxable * (1 + gst/100) ≈ net", "severity": "WARNING"
                })

        row_discrepancies.append(disc_list)

    total_checked = total_valid_rows + total_mismatches
    health = (total_valid_rows / max(1, total_checked)) if total_checked > 0 else 1.0

    summary = {
        "total_rows_checked": len(rows),
        "arithmetic_valid_rows": total_valid_rows,
        "critical_mismatches": total_mismatches,
        "accounting_health": round(health, 3),
    }

    return row_discrepancies, summary


def compute_layout_signature(headers: list, logical_columns: list = None, rows: list = None, page_width: float = 612.0) -> dict:
    """
    Computes a position-aware, coordinate-normalized layout signature.
    """
    header_clean = [clean_text(h) for h in headers]
    rel_x = []
    if logical_columns and len(logical_columns) == len(headers):
        rel_x = [round(c.get("x0", 0.0) / page_width, 3) for c in logical_columns]

    sig_str = "|".join(header_clean) + "_" + str(len(headers))
    sig_hash = hashlib.sha256(sig_str.encode("utf-8")).hexdigest()[:16]

    return {
        "column_count": len(headers),
        "header_fingerprint": header_clean,
        "relative_x_positions": rel_x,
        "signature_hash": sig_hash,
    }


# ==============================================================================
# PROMPT 7: GENERIC SUPPLIER + LAYOUT PROFILE MEMORY ENGINE (200+ SUPPLIERS)
# ==============================================================================

PROFILES_STORAGE_FILE = "supplier_profiles.json"
TEMPLATES_STORAGE_FILE = "templates.json"


def load_supplier_profiles(storage_path: str = PROFILES_STORAGE_FILE) -> dict:
    """
    Loads generic supplier and layout profiles memory.
    If supplier_profiles.json does not exist, auto-migrates existing templates.json.
    """
    existing_data = None
    if os.path.exists(storage_path):
        try:
            with open(storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "profiles" in data:
                    existing_data = data
                elif isinstance(data, dict):
                    existing_data = {"version": 1, "profiles": data}
        except Exception:
            pass

    container = existing_data if existing_data is not None else {"version": 1, "profiles": {}}
    profiles = container.setdefault("profiles", {})

    # Auto-migration from legacy templates.json for any supplier not yet in profiles
    if storage_path == PROFILES_STORAGE_FILE and os.path.exists(TEMPLATES_STORAGE_FILE):
        try:
            with open(TEMPLATES_STORAGE_FILE, "r", encoding="utf-8") as f:
                legacy_templates = json.load(f)
                for sup_key, mapping in legacy_templates.items():
                    if sup_key in profiles:
                        continue
                    clean_headers = [clean_text(h) for h in mapping.keys()]
                    sig_str = "|".join(clean_headers) + "_" + str(len(clean_headers))
                    sig_hash = hashlib.sha256(sig_str.encode("utf-8")).hexdigest()[:16]
                    
                    is_gstin = bool(re.match(r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z0-9]{1}Z[A-Z0-9]{1}$", str(sup_key).strip().upper()))
                    
                    layout_v1 = {
                        "layout_id": f"layout_{sig_hash}",
                        "layout_signature": sig_hash,
                        "header_sequence": list(mapping.keys()),
                        "logical_column_count": len(mapping),
                        "relative_column_positions": [],
                        "semantic_mapping": mapping,
                        "field_reliability": {
                            (field if isinstance(field, str) else str(field)): {
                                "observed_count": 1,
                                "confirmed_count": 1,
                                "inferred_count": 0,
                                "contradiction_count": 0,
                                "reliability_score": 1.0,
                            }
                            for field in mapping.values() if field
                        },
                        "multi_value_patterns": {},
                        "known_optional_fields": ["hsnCode", "discountPercent", "freeQuantity"],
                        "known_required_fields": ["itemName", "quantity", "rate", "amount"],
                        "successful_document_count": 1,
                        "review_count": 0,
                        "failure_count": 0,
                        "created_at": datetime.now().isoformat(),
                        "last_seen": datetime.now().isoformat(),
                    }

                    profiles[sup_key] = {
                        "supplier_identity": sup_key,
                        "supplier_key": sup_key,
                        "supplier_name": None if is_gstin else sup_key,
                        "gstin": sup_key if is_gstin else None,
                        "successful_document_count": 1,
                        "reviewed_document_count": 0,
                        "failure_document_count": 0,
                        "last_seen": datetime.now().isoformat(),
                        "profile_confidence": 0.90,
                        "layout_profiles": {
                            layout_v1["layout_id"]: layout_v1
                        }
                    }
        except Exception:
            pass

    if storage_path == PROFILES_STORAGE_FILE and existing_data is None:
        save_supplier_profiles(container, storage_path=storage_path, sync_templates=False)
    return container


def save_supplier_profiles(
    profiles_data: dict,
    storage_path: str = PROFILES_STORAGE_FILE,
    sync_templates: bool = True,
    expected_version: int = None,
) -> dict:
    """
    Saves supplier profiles to disk safely, non-destructively, and atomically.
    Implements optimistic concurrency conflict detection if expected_version is provided.
    Optionally syncs active mappings to templates.json for backward compatibility.
    """
    if expected_version is not None and os.path.exists(storage_path):
        try:
            with open(storage_path, "r", encoding="utf-8") as f:
                disk_data = json.load(f)
                disk_version = disk_data.get("version", 1) if isinstance(disk_data, dict) else 1
                if disk_version != expected_version:
                    logger.warning(f"Profile version conflict: disk version {disk_version} != expected {expected_version}")
                    return {
                        "success": False,
                        "error": "PROFILE_VERSION_CONFLICT",
                        "message": f"Stale write detected. Disk version ({disk_version}) differs from expected version ({expected_version}). Reconciliation required.",
                    }
        except Exception as e:
            logger.warning(f"Error checking profile version for conflict: {e}")

    # Monotonically increment version
    curr_v = profiles_data.get("version", 1)
    profiles_data["version"] = curr_v + 1

    temp_path = storage_path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(profiles_data, f, indent=2)
        if os.path.exists(storage_path):
            os.replace(temp_path, storage_path)
        else:
            os.rename(temp_path, storage_path)
    except Exception as e:
        logger.error(f"Error saving supplier profiles: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        return {"success": False, "error": str(e)}

    if sync_templates and storage_path == PROFILES_STORAGE_FILE:
        try:
            legacy_view = {}
            if os.path.exists(TEMPLATES_STORAGE_FILE):
                try:
                    with open(TEMPLATES_STORAGE_FILE, "r", encoding="utf-8") as f:
                        legacy_view = json.load(f)
                except Exception:
                    legacy_view = {}

            for sup_key, prof in profiles_data.get("profiles", {}).items():
                layouts = prof.get("layout_profiles", {})
                if layouts:
                    best_layout = max(layouts.values(), key=lambda l: (l.get("successful_document_count", 0), l.get("last_seen", "")))
                    legacy_view[sup_key] = best_layout.get("semantic_mapping", {})

            temp_tmpl = TEMPLATES_STORAGE_FILE + ".tmp"
            with open(temp_tmpl, "w", encoding="utf-8") as f:
                json.dump(legacy_view, f, indent=2)
            if os.path.exists(TEMPLATES_STORAGE_FILE):
                os.replace(temp_tmpl, TEMPLATES_STORAGE_FILE)
            else:
                os.rename(temp_tmpl, TEMPLATES_STORAGE_FILE)
        except Exception as e:
            logger.error(f"Error syncing legacy templates: {e}")

    return {"success": True, "version": profiles_data["version"]}


def load_saved_templates_dict() -> dict:
    """Loads saved supplier templates from memory store."""
    profiles_data = load_supplier_profiles()
    legacy_view = {}
    for sup_key, prof in profiles_data.get("profiles", {}).items():
        layouts = prof.get("layout_profiles", {})
        if layouts:
            best_layout = max(layouts.values(), key=lambda l: (l.get("successful_document_count", 0), l.get("last_seen", "")))
            legacy_view[sup_key] = best_layout.get("semantic_mapping", {})
    return legacy_view


def calculate_header_sequence_similarity(seq1: list, seq2: list) -> float:
    """
    Computes composite similarity between two header sequences based on:
    - Jaccard set overlap
    - Position/sequence order alignment
    - Token edit distance
    """
    clean1 = [clean_text(h) for h in seq1 if clean_text(h)]
    clean2 = [clean_text(h) for h in seq2 if clean_text(h)]
    if not clean1 and not clean2:
        return 1.0
    if not clean1 or not clean2:
        return 0.0

    set1, set2 = set(clean1), set(clean2)
    jaccard = len(set1 & set2) / max(1, len(set1 | set2))

    # Sequence alignment score (LCS / order match)
    matches_in_order = 0
    idx2 = 0
    for h1 in clean1:
        if h1 in clean2[idx2:]:
            matches_in_order += 1
            idx2 = clean2.index(h1, idx2) + 1
            if idx2 >= len(clean2):
                break
    seq_score = matches_in_order / max(len(clean1), len(clean2))

    # Length consistency
    len_score = 1.0 - abs(len(clean1) - len(clean2)) / max(len(clean1), len(clean2))

    return round(0.40 * jaccard + 0.40 * seq_score + 0.20 * len_score, 3)


def match_supplier_layout_profile(
    supplier_key: str,
    current_sig: dict,
    profiles_data: dict = None,
    headers: list = None,
    logical_columns: list = None,
    rows: list = None,
) -> dict:
    """
    Finds and ranks matching layout profiles for a supplier.
    Distinguishes:
    - EXACT_MATCH
    - MINOR_DRIFT
    - MAJOR_DRIFT
    - NEW_LAYOUT
    - NEW_SUPPLIER (with cross-supplier layout similarity if applicable)
    """
    if profiles_data is None:
        profiles_data = load_supplier_profiles()

    profiles = profiles_data.get("profiles", {})
    curr_headers = headers or current_sig.get("header_fingerprint", [])
    curr_sig_hash = current_sig.get("signature_hash", "")

    # 1. Match supplier profile by key / GSTIN / Name
    matched_supplier_prof = None
    if supplier_key:
        if supplier_key in profiles:
            matched_supplier_prof = profiles[supplier_key]
        else:
            # Case-insensitive / normalized lookup
            norm_key = clean_text(supplier_key).upper()
            for k, p in profiles.items():
                if clean_text(k).upper() == norm_key or (p.get("gstin") and p["gstin"].upper() == norm_key) or (p.get("supplier_name") and clean_text(p["supplier_name"]).upper() == norm_key):
                    matched_supplier_prof = p
                    break

    if matched_supplier_prof is None:
        # Check cross-supplier layout similarity (similar layout from another supplier as prior, WITHOUT merging identity)
        cross_best = None
        cross_score = 0.0
        for other_key, other_prof in profiles.items():
            for l_id, l_prof in other_prof.get("layout_profiles", {}).items():
                sim = calculate_header_sequence_similarity(curr_headers, l_prof.get("header_sequence", []))
                if sim > cross_score:
                    cross_score = sim
                    cross_best = l_prof

        return {
            "drift_status": "NEW_SUPPLIER",
            "similarity_score": round(cross_score, 3) if cross_best else 0.0,
            "supplier_profile": None,
            "matched_layout": cross_best if cross_score >= 0.75 else None,
            "is_cross_supplier_layout": bool(cross_best and cross_score >= 0.75),
            "details": [f"New supplier detected. Cross-supplier template similarity: {cross_score:.1%}" if cross_best else "First invoice for this supplier (no prior profile)"],
            "ranked_layouts": [],
        }

    # 2. Evaluate all layout versions for this supplier
    layout_profiles = matched_supplier_prof.get("layout_profiles", {})
    if not layout_profiles:
        return {
            "drift_status": "NEW_LAYOUT",
            "similarity_score": 0.0,
            "supplier_profile": matched_supplier_prof,
            "matched_layout": None,
            "is_cross_supplier_layout": False,
            "details": ["Supplier profile exists but contains no layout versions."],
            "ranked_layouts": [],
        }

    ranked_candidates = []
    for l_id, l_prof in layout_profiles.items():
        sim = calculate_header_sequence_similarity(curr_headers, l_prof.get("header_sequence", []))
        sig_match = (curr_sig_hash and curr_sig_hash == l_prof.get("layout_signature"))
        if sig_match:
            sim = 1.0

        ranked_candidates.append({
            "layout_id": l_id,
            "layout_profile": l_prof,
            "similarity_score": sim,
            "signature_match": sig_match,
        })

    ranked_candidates.sort(key=lambda c: (c["signature_match"], c["similarity_score"]), reverse=True)
    best = ranked_candidates[0]
    best_sim = best["similarity_score"]
    best_layout = best["layout_profile"]

    # Classify drift details
    details = []
    hist_headers = [clean_text(h) for h in best_layout.get("header_sequence", [])]
    clean_curr = [clean_text(h) for h in curr_headers]

    if len(clean_curr) != len(hist_headers):
        details.append(f"Column count changed: {len(hist_headers)} -> {len(clean_curr)}")
    for h in clean_curr:
        if h not in hist_headers:
            details.append(f"New column detected: '{h}'")
    for h in hist_headers:
        if h not in clean_curr:
            details.append(f"Historical column missing: '{h}'")

    if best["signature_match"] or (best_sim >= 0.95 and len(details) == 0):
        status = "EXACT_MATCH"
    elif best_sim >= 0.75:
        status = "MINOR_DRIFT"
    elif best_sim >= 0.45:
        status = "MAJOR_DRIFT"
    else:
        status = "NEW_LAYOUT"

    return {
        "drift_status": status,
        "similarity_score": round(best_sim, 3),
        "supplier_profile": matched_supplier_prof,
        "matched_layout": best_layout,
        "is_cross_supplier_layout": False,
        "details": details or ["Layout matches historical profile perfectly"],
        "ranked_layouts": ranked_candidates,
    }


def detect_layout_drift(current_signature: dict, supplier_key: str, saved_templates: dict = None) -> dict:
    """
    Bridge function for layout drift detection using the profile memory manager.
    Supports both rich profiles dict and flat legacy templates dict.
    """
    curr_headers = current_signature.get("header_fingerprint", [])
    
    if saved_templates is not None and not (isinstance(saved_templates, dict) and "profiles" in saved_templates):
        # Legacy flat template dictionary passed explicitly
        if not saved_templates or not supplier_key or supplier_key not in saved_templates:
            return {
                "drift_status": "NEW_SUPPLIER",
                "similarity_score": 1.0,
                "details": ["First invoice processed for this supplier (no historical prior)"],
            }
        template_mapping = saved_templates[supplier_key]
        template_headers = [clean_text(h) for h in template_mapping.keys()]
        matches = sum(1 for h in curr_headers if h in template_headers)
        sim = matches / max(1, max(len(curr_headers), len(template_headers)))
        details = []
        if len(curr_headers) != len(template_headers):
            details.append(f"Column count changed: {len(template_headers)} -> {len(curr_headers)}")
        for h in curr_headers:
            if h not in template_headers:
                details.append(f"New column detected: '{h}'")
        for h in template_headers:
            if h not in curr_headers:
                details.append(f"Historical column missing: '{h}'")

        if sim >= 0.85 and len(details) == 0:
            status = "SAME_LAYOUT"
        elif sim >= 0.40:
            status = "LAYOUT_DRIFT"
        else:
            status = "LAYOUT_REDESIGN"

        return {
            "drift_status": status,
            "similarity_score": round(sim, 3),
            "details": details or ["Layout matches historical supplier profile"],
        }

    match_res = match_supplier_layout_profile(supplier_key, current_signature, profiles_data=saved_templates, headers=curr_headers)
    return {
        "drift_status": match_res["drift_status"],
        "similarity_score": match_res["similarity_score"],
        "details": match_res["details"],
        "matched_layout_id": match_res["matched_layout"].get("layout_id") if match_res.get("matched_layout") else None,
        "is_cross_supplier_layout": match_res.get("is_cross_supplier_layout", False),
    }


def update_supplier_profile_memory(
    supplier_key: str,
    supplier_name: str,
    gstin: str,
    headers: list,
    logical_columns: list,
    resolved_mappings: dict,
    rows: list,
    validation_result: dict,
    is_user_reviewed: bool = False,
    expected_version: int = None,
    profiles_storage_path: str = PROFILES_STORAGE_FILE,
) -> dict:
    """
    Safely and non-destructively learns/updates supplier profile memory.
    Only updates when result is AUTO_ACCEPT or confirmed via human review.
    Creates new layout versions on MAJOR_DRIFT or NEW_LAYOUT without destroying historical versions.
    Supports optimistic concurrency locking via expected_version.
    """
    # 1. Validation Gate: Never learn from unverified or low-confidence data
    doc_conf = validation_result.get("document_confidence", 0.0)
    classification = validation_result.get("classification", "UNRESOLVED")
    critical_mismatches = validation_result.get("accounting_summary", {}).get("critical_mismatches", 0)

    is_safe_auto_accept = (classification == "AUTO_ACCEPT" and doc_conf >= 80.0 and critical_mismatches == 0)
    if not is_user_reviewed and not is_safe_auto_accept:
        return {
            "updated": False,
            "reason": f"Validation gate not passed (Classification: {classification}, Confidence: {doc_conf:.1f}%, Critical Errors: {critical_mismatches}). Human review required to update profile memory.",
        }

    if not supplier_key:
        supplier_key = supplier_name or gstin
    if not supplier_key:
        return {"updated": False, "reason": "No valid supplier identifier (GSTIN or Name)."}

    profiles_data = load_supplier_profiles(storage_path=profiles_storage_path)
    profiles = profiles_data.setdefault("profiles", {})

    current_sig = compute_layout_signature(headers, logical_columns, rows)
    sig_hash = current_sig["signature_hash"]
    clean_headers = [clean_text(h) for h in headers]

    # Build semantic mapping dictionary
    flat_mapping = {}
    for h in headers:
        m = resolved_mappings.get(h, {})
        flat_mapping[h] = m.get("mapped_to")

    now_iso = datetime.now().isoformat()

    # Field reliability accumulator
    field_rel = {}
    for h, m_info in resolved_mappings.items():
        f = m_info.get("mapped_to")
        if f:
            field_rel[f] = {
                "observed_count": 1,
                "confirmed_count": 1 if is_user_reviewed else 0,
                "inferred_count": 1 if m_info.get("status") == "inferred" else 0,
                "contradiction_count": 0,
                "reliability_score": 1.0,
            }

    # 2. Check if supplier profile already exists
    matched_prof = None
    if supplier_key in profiles:
        matched_prof = profiles[supplier_key]
    else:
        norm_key = clean_text(supplier_key).upper()
        for k, p in profiles.items():
            if clean_text(k).upper() == norm_key:
                matched_prof = p
                supplier_key = k
                break

    if matched_prof is None:
        # Create brand new supplier profile with layout_v1
        layout_id = f"layout_v1_{sig_hash}"
        # Field reliability initialization
        init_field_rel = {}
        for f, rel_data in field_rel.items():
            init_field_rel[f] = {
                "observed_count": 1,
                "algorithm_confirmed_count": 0 if is_user_reviewed else 1,
                "human_confirmed_count": 1 if is_user_reviewed else 0,
                "inferred_count": rel_data.get("inferred_count", 0),
                "contradiction_count": 0,
                "review_correction_count": 1 if is_user_reviewed else 0,
                "reliability_score": 1.0,
            }

        profiles[supplier_key] = {
            "supplier_identity": supplier_key,
            "supplier_key": supplier_key,
            "supplier_name": supplier_name,
            "gstin": gstin,
            "successful_document_count": 1,
            "reviewed_document_count": 1 if is_user_reviewed else 0,
            "failure_document_count": 0,
            "last_seen": now_iso,
            "profile_confidence": round(doc_conf / 100.0, 2),
            "layout_profiles": {
                layout_id: {
                    "layout_id": layout_id,
                    "layout_signature": sig_hash,
                    "header_sequence": list(headers),
                    "logical_column_count": len(headers),
                    "relative_column_positions": current_sig.get("relative_x_positions", []),
                    "semantic_mapping": flat_mapping,
                    "field_reliability": init_field_rel,
                    "multi_value_patterns": {},
                    "known_optional_fields": ["hsnCode", "discountPercent", "freeQuantity"],
                    "known_required_fields": ["itemName", "quantity", "rate", "amount"],
                    "successful_document_count": 1,
                    "review_count": 1 if is_user_reviewed else 0,
                    "failure_count": 0,
                    "review_history": [],
                    "created_at": now_iso,
                    "last_seen": now_iso,
                }
            }
        }
        save_res = save_supplier_profiles(profiles_data, storage_path=profiles_storage_path, expected_version=expected_version)
        if not save_res.get("success", True):
            return {"updated": False, "reason": save_res.get("error", "PROFILE_VERSION_CONFLICT"), "conflict": True}
        return {
            "updated": True,
            "action": "NEW_SUPPLIER_PROFILE_CREATED",
            "layout_id": layout_id,
            "supplier_key": supplier_key,
        }

    # 3. Existing Supplier: Match layout
    match_res = match_supplier_layout_profile(supplier_key, current_sig, profiles_data=profiles_data, headers=headers)
    drift_status = match_res["drift_status"]
    matched_layout = match_res.get("matched_layout")

    matched_prof["last_seen"] = now_iso
    matched_prof["successful_document_count"] = matched_prof.get("successful_document_count", 0) + 1
    if is_user_reviewed:
        matched_prof["reviewed_document_count"] = matched_prof.get("reviewed_document_count", 0) + 1

    if drift_status in ("EXACT_MATCH", "MINOR_DRIFT") and matched_layout:
        # Update existing layout profile non-destructively
        l_id = matched_layout["layout_id"]
        target_layout = matched_prof["layout_profiles"][l_id]
        target_layout["last_seen"] = now_iso
        target_layout["successful_document_count"] = target_layout.get("successful_document_count", 0) + 1
        if is_user_reviewed:
            target_layout["review_count"] = target_layout.get("review_count", 0) + 1
            target_layout["semantic_mapping"].update(flat_mapping)

        # Accumulate granular field reliability
        target_rel = target_layout.setdefault("field_reliability", {})
        for f, rel_data in field_rel.items():
            if f in target_rel:
                cur_f = target_rel[f]
                cur_f["observed_count"] = cur_f.get("observed_count", 0) + 1
                if is_user_reviewed:
                    cur_f["human_confirmed_count"] = cur_f.get("human_confirmed_count", 0) + 1
                    cur_f["review_correction_count"] = cur_f.get("review_correction_count", 0) + 1
                else:
                    cur_f["algorithm_confirmed_count"] = cur_f.get("algorithm_confirmed_count", 0) + 1
            else:
                target_rel[f] = {
                    "observed_count": 1,
                    "algorithm_confirmed_count": 0 if is_user_reviewed else 1,
                    "human_confirmed_count": 1 if is_user_reviewed else 0,
                    "inferred_count": rel_data.get("inferred_count", 0),
                    "contradiction_count": 0,
                    "review_correction_count": 1 if is_user_reviewed else 0,
                    "reliability_score": 1.0,
                }

        save_res = save_supplier_profiles(profiles_data, storage_path=profiles_storage_path, expected_version=expected_version)
        if not save_res.get("success", True):
            return {"updated": False, "reason": save_res.get("error", "PROFILE_VERSION_CONFLICT"), "conflict": True}
        return {
            "updated": True,
            "action": "LAYOUT_PROFILE_UPDATED",
            "layout_id": l_id,
            "supplier_key": supplier_key,
        }
    else:
        # Major drift or completely new layout -> Create NEW layout version, keeping previous versions intact!
        version_num = len(matched_prof.get("layout_profiles", {})) + 1
        new_layout_id = f"layout_v{version_num}_{sig_hash}"
        init_field_rel = {}
        for f, rel_data in field_rel.items():
            init_field_rel[f] = {
                "observed_count": 1,
                "algorithm_confirmed_count": 0 if is_user_reviewed else 1,
                "human_confirmed_count": 1 if is_user_reviewed else 0,
                "inferred_count": rel_data.get("inferred_count", 0),
                "contradiction_count": 0,
                "review_correction_count": 1 if is_user_reviewed else 0,
                "reliability_score": 1.0,
            }

        new_layout_profile = {
            "layout_id": new_layout_id,
            "layout_signature": sig_hash,
            "header_sequence": list(headers),
            "logical_column_count": len(headers),
            "relative_column_positions": current_sig.get("relative_x_positions", []),
            "semantic_mapping": flat_mapping,
            "field_reliability": init_field_rel,
            "multi_value_patterns": {},
            "known_optional_fields": ["hsnCode", "discountPercent", "freeQuantity"],
            "known_required_fields": ["itemName", "quantity", "rate", "amount"],
            "successful_document_count": 1,
            "review_count": 1 if is_user_reviewed else 0,
            "failure_count": 0,
            "review_history": [],
            "created_at": now_iso,
            "last_seen": now_iso,
        }
        matched_prof.setdefault("layout_profiles", {})[new_layout_id] = new_layout_profile
        save_res = save_supplier_profiles(profiles_data, storage_path=profiles_storage_path, expected_version=expected_version)
        if not save_res.get("success", True):
            return {"updated": False, "reason": save_res.get("error", "PROFILE_VERSION_CONFLICT"), "conflict": True}
        return {
            "updated": True,
            "action": "NEW_LAYOUT_VERSION_CREATED",
            "layout_id": new_layout_id,
            "supplier_key": supplier_key,
        }


# ==============================================================================
# PROMPT 8: GENERIC HUMAN REVIEW, CORRECTION & SAFE LEARNING ENGINE
# ==============================================================================

def validate_supplier_identity_safety(supplier_name: str, gstin: str, name_confidence: float = 1.0) -> dict:
    """
    Validates supplier identity certainty to prevent cross-supplier profile pollution.
    Returns: 'EXACT_GSTIN', 'VERIFIED_NAME', 'SUPPLIER_IDENTITY_REVIEW_REQUIRED', or 'NO_IDENTITY'.
    """
    clean_gstin = re.sub(r"[^A-Z0-9]", "", str(gstin or "").upper().strip())
    is_valid_gstin = bool(re.match(r"^\d{2}[A-Z]{5}\d{4}[A-Z]{1}[A-Z0-9]{1}Z[A-Z0-9]{1}$", clean_gstin))
    
    clean_name = clean_text(supplier_name or "")
    has_valid_name = len(clean_name) >= 3 and not re.match(r"^[\d\W]+$", clean_name)
    
    if is_valid_gstin:
        return {
            "status": "EXACT_GSTIN",
            "supplier_key": clean_gstin,
            "is_safe_to_attach": True,
            "details": f"Valid GSTIN identified: {clean_gstin}",
        }
    elif has_valid_name and (name_confidence is None or name_confidence >= 0.70):
        return {
            "status": "VERIFIED_NAME",
            "supplier_key": clean_name.upper(),
            "is_safe_to_attach": True,
            "details": f"Supplier name verified with confidence {float(name_confidence or 1.0):.0%}",
        }
    elif has_valid_name:
        return {
            "status": "SUPPLIER_IDENTITY_REVIEW_REQUIRED",
            "supplier_key": clean_name.upper(),
            "is_safe_to_attach": False,
            "details": "Low confidence on detected supplier name. Human review required before attaching to profile memory.",
        }
    else:
        return {
            "status": "NO_IDENTITY",
            "supplier_key": None,
            "is_safe_to_attach": False,
            "details": "No valid GSTIN or Supplier Name detected.",
        }


def create_review_session(
    metadata: dict,
    headers: list,
    logical_columns: list,
    column_mappings: dict,
    rows: list,
    invoice_id: str = None,
) -> dict:
    """
    Constructs a comprehensive, immutable review session snapshot.
    Preserves: RAW -> ORIGINAL INFERENCE -> HUMAN CORRECTION -> VALIDATED RESULT.
    """
    inv_id = invoice_id or metadata.get("invoice_number") or f"inv_{hashlib.sha256(str(headers).encode()).hexdigest()[:8]}"
    sup_name = metadata.get("supplier_name")
    gstin = metadata.get("supplier_gstin")
    identity_safety = validate_supplier_identity_safety(sup_name, gstin, metadata.get("supplier_confidence"))
    
    validation_info = metadata.get("validation", {})
    drift_info = metadata.get("drift_report", {})
    
    unresolved_cols = [h for h, m in column_mappings.items() if not m.get("mapped_to") or m.get("status") in ("unresolved", "ambiguous")]
    suspected_swaps = validation_info.get("swap_audit_log", [])
    
    now_iso = datetime.now().isoformat()
    rev_id = f"rev_{hashlib.sha256((inv_id + now_iso).encode()).hexdigest()[:12]}"
    
    session = {
        "review_id": rev_id,
        "invoice_id": inv_id,
        "supplier_identity": identity_safety.get("supplier_key"),
        "supplier_name": sup_name,
        "gstin": gstin,
        "identity_safety": identity_safety,
        "layout_id": drift_info.get("matched_layout_id"),
        "layout_status": drift_info.get("drift_status", "UNKNOWN"),
        "original_decision": validation_info.get("classification", metadata.get("classification", "REVIEW_REQUIRED")),
        "original_confidence": validation_info.get("document_confidence", metadata.get("confidence", 0.0)),
        "original_headers": list(headers),
        "logical_columns": logical_columns or [],
        "original_semantic_mapping": dict(column_mappings),
        "original_rows": list(rows),
        "field_diagnostics": validation_info.get("field_diagnostics", {}),
        "validation_discrepancies": validation_info.get("row_discrepancies", []),
        "accounting_summary": validation_info.get("accounting_summary", {}),
        "suspected_swaps": suspected_swaps,
        "unresolved_columns": unresolved_cols,
        "review_status": "PENDING_REVIEW",
        "reviewed_by": None,
        "reviewed_at": None,
        "corrections": [],
        "validated_result": None,
        "profile_update_status": "NOT_UPDATED",
    }
    return session


def check_duplicate_field_assignments(proposed_mappings: dict) -> tuple:
    """
    Checks if multiple headers are assigned to the same canonical system field.
    Returns (has_duplicates: bool, duplicate_map: dict of {field: [header1, header2]}).
    """
    field_to_headers = {}
    for h, f in proposed_mappings.items():
        if f and isinstance(f, str) and f.strip():
            field_to_headers.setdefault(f, []).append(h)
            
    duplicates = {f: headers for f, headers in field_to_headers.items() if len(headers) > 1}
    return len(duplicates) > 0, duplicates


def apply_and_validate_review_corrections(
    review_session: dict,
    proposed_mappings: dict,
    reviewer_id: str = "human_operator",
) -> dict:
    """
    Applies proposed human corrections to the review session and re-runs global validation.
    Does NOT bypass validation.
    Returns review outcome: 'CORRECTION_VALIDATED', 'CORRECTION_HAS_WARNINGS', or 'CORRECTION_REJECTED'.
    """
    headers = review_session["original_headers"]
    logical_cols = review_session["logical_columns"]
    rows = review_session["original_rows"]
    orig_mappings = review_session["original_semantic_mapping"]
    
    # 1. Duplicate Field Assignment Prevention
    has_dups, dup_fields = check_duplicate_field_assignments(proposed_mappings)
    if has_dups:
        dup_details = [f"Field '{f}' assigned to multiple columns: {', '.join(hdrs)}" for f, hdrs in dup_fields.items()]
        return {
            "status": "CORRECTION_REJECTED",
            "outcome": "REVIEW_NOT_CONFIRMED",
            "error_type": "DUPLICATE_FIELD_ASSIGNMENT",
            "reasons": dup_details,
            "validated_result": None,
            "updated_session": review_session,
        }

    # 2. Track corrections diff
    corrections_list = []
    now_iso = datetime.now().isoformat()
    new_resolved_mappings = {}
    
    for h in headers:
        old_m = orig_mappings.get(h, {})
        old_f = old_m.get("mapped_to")
        new_f = proposed_mappings.get(h)
        
        if new_f != old_f:
            corrections_list.append({
                "logical_column": h,
                "old_field": old_f,
                "new_field": new_f,
                "reason": "human_correction",
                "original_confidence": old_m.get("confidence", 0.0),
                "corrected_at": now_iso,
            })
            new_resolved_mappings[h] = {
                "mapped_to": new_f,
                "status": "user_confirmed" if new_f else "unresolved",
                "confidence": 100.0 if new_f else 0.0,
                "evidence": ["Explicit human review mapping"],
            }
        else:
            new_resolved_mappings[h] = dict(old_m)

    # 3. Re-run Global Validation Engine on Corrected Mappings
    val_metadata = {
        "supplier_name": review_session.get("supplier_name"),
        "supplier_gstin": review_session.get("gstin"),
        "invoice_number": review_session.get("invoice_id"),
    }
    
    revalidated = compute_global_validation_and_confidence(
        headers=headers,
        logical_columns=logical_cols,
        column_mappings=new_resolved_mappings,
        rows=rows,
        metadata=val_metadata,
    )
    
    # 4. Determine Review Outcome Status
    has_critical_acct = revalidated.get("accounting_summary", {}).get("critical_mismatches", 0) > 0
    contradiction_count = sum(d.get("contradiction_count", 0) for d in revalidated.get("field_diagnostics", {}).values())
    
    # Mandatory fields check: itemName, quantity or amount
    mapped_set = {m.get("mapped_to") for m in revalidated["resolved_mappings"].values() if m.get("mapped_to")}
    has_mandatory = "itemName" in mapped_set and ("quantity" in mapped_set or "amount" in mapped_set)
    
    if not has_mandatory or contradiction_count > max(1, len(headers) * 0.5):
        status = "CORRECTION_REJECTED"
        outcome = "REVIEW_NOT_CONFIRMED"
    elif has_critical_acct or contradiction_count > 0:
        status = "CORRECTION_HAS_WARNINGS"
        outcome = "REVIEW_CONFIRMED_WITH_WARNINGS"
    else:
        status = "CORRECTION_VALIDATED"
        outcome = "REVIEW_CONFIRMED"

    # Update session object non-destructively
    updated_session = dict(review_session)
    updated_session["reviewed_by"] = reviewer_id
    updated_session["reviewed_at"] = now_iso
    updated_session["corrections"] = corrections_list
    updated_session["review_status"] = outcome
    updated_session["validated_result"] = {
        "status": status,
        "outcome": outcome,
        "revalidated_mappings": revalidated["resolved_mappings"],
        "field_diagnostics": revalidated["field_diagnostics"],
        "accounting_summary": revalidated["accounting_summary"],
        "row_discrepancies": revalidated["row_discrepancies"],
        "revalidated_confidence": revalidated["document_confidence"],
        "confirmation_status": "HUMAN_CONFIRMED",
    }
    
    return {
        "status": status,
        "outcome": outcome,
        "updated_session": updated_session,
        "revalidated_confidence": revalidated["document_confidence"],
        "corrections_count": len(corrections_list),
        "validated_result": updated_session["validated_result"],
    }


def commit_reviewed_layout_to_profile_memory(
    review_session: dict,
    expected_version: int = None,
    profiles_storage_path: str = PROFILES_STORAGE_FILE,
) -> dict:
    """
    Safely commits human-confirmed corrections into supplier profile memory.
    Ensures:
    1. Supplier identity is safe.
    2. Increments human_confirmed_count on mapped fields.
    3. Appends an audit event to review_history in the layout profile.
    4. Non-destructively creates a new layout version if layout drifted.
    5. Detects concurrent stale writes via expected_version.
    """
    identity_safety = review_session.get("identity_safety", {})
    if not identity_safety.get("is_safe_to_attach", True):
        return {
            "committed": False,
            "reason": f"Cannot safely attach to supplier memory: {identity_safety.get('details')}",
        }
        
    val_res = review_session.get("validated_result")
    if not val_res or val_res.get("outcome") not in ("REVIEW_CONFIRMED", "REVIEW_CONFIRMED_WITH_WARNINGS"):
        return {
            "committed": False,
            "reason": "Cannot commit unverified or rejected review corrections.",
        }

    supplier_key = review_session.get("supplier_identity") or review_session.get("supplier_name") or review_session.get("gstin")
    supplier_name = review_session.get("supplier_name")
    gstin = review_session.get("gstin")
    headers = review_session["original_headers"]
    logical_cols = review_session["logical_columns"]
    rows = review_session["original_rows"]
    resolved_mappings = val_res["revalidated_mappings"]
    
    val_dict = {
        "classification": "AUTO_ACCEPT",
        "document_confidence": val_res.get("revalidated_confidence", 100.0),
        "accounting_summary": val_res.get("accounting_summary", {}),
    }
    
    res = update_supplier_profile_memory(
        supplier_key=supplier_key,
        supplier_name=supplier_name,
        gstin=gstin,
        headers=headers,
        logical_columns=logical_cols,
        resolved_mappings=resolved_mappings,
        rows=rows,
        validation_result=val_dict,
        is_user_reviewed=True,
        expected_version=expected_version,
        profiles_storage_path=profiles_storage_path,
    )
    
    if res.get("updated"):
        # Append review audit history event to the active layout profile
        profiles_data = load_supplier_profiles(storage_path=profiles_storage_path)
        prof = profiles_data.get("profiles", {}).get(supplier_key)
        if prof:
            layout_id = res.get("layout_id")
            layout_prof = prof.get("layout_profiles", {}).get(layout_id)
            if layout_prof:
                audit_event = {
                    "review_id": review_session.get("review_id"),
                    "invoice_id": review_session.get("invoice_id"),
                    "reviewed_by": review_session.get("reviewed_by", "human_operator"),
                    "reviewed_at": review_session.get("reviewed_at", datetime.now().isoformat()),
                    "changed_fields_count": len(review_session.get("corrections", [])),
                    "corrections": review_session.get("corrections", []),
                    "outcome": val_res.get("outcome"),
                }
                layout_prof.setdefault("review_history", []).append(audit_event)
                save_supplier_profiles(profiles_data, storage_path=profiles_storage_path)
        
        review_session["profile_update_status"] = "UPDATED"
        return {"committed": True, "action": res.get("action"), "layout_id": res.get("layout_id")}
    else:
        return {"committed": False, "reason": res.get("reason"), "conflict": res.get("conflict", False)}


def compute_global_validation_and_confidence(headers: list, logical_columns: list, column_mappings: dict, rows: list, saved_template: dict = None, metadata: dict = None, page_width: float = 612.0) -> dict:
    """
    Synthesizes multi-dimensional validation evidence into field, row, and document confidence.
    Classifies the extraction outcome as AUTO_ACCEPT, REVIEW_REQUIRED, or UNRESOLVED.
    """
    # 1. Detect and resolve field swaps
    resolved_mappings, swap_log = detect_and_resolve_field_swaps(headers, logical_columns, column_mappings, rows)

    # 2. Cross-field accounting validation
    row_discrepancies, acct_summary = validate_cross_field_accounting(rows, resolved_mappings, headers)

    # 3. Field-level quality profiling
    field_diagnostics = {}
    for col_i, h in enumerate(headers):
        m_field = resolved_mappings.get(h, {}).get("mapped_to")
        col_vals = [row[col_i] if col_i < len(row) else "" for row in rows]
        if m_field:
            q_info = validate_field_quality(m_field, col_vals, header_str=h)
            field_diagnostics[h] = q_info

    # 4. Layout signature and drift
    supplier_name = metadata.get("supplier_name") if metadata else None
    supplier_gstin = metadata.get("supplier_gstin") if metadata else None
    supplier_key = supplier_name or supplier_gstin

    current_sig = compute_layout_signature(headers, logical_columns, rows, page_width=page_width)
    saved_templates = load_saved_templates_dict()
    drift_info = detect_layout_drift(current_sig, supplier_key, saved_templates)

    # 5. Multi-dimensional Score Components (0.0 to 1.0)
    mapped_count = sum(1 for h in headers if resolved_mappings.get(h, {}).get("mapped_to"))
    known_count = sum(1 for h in headers if resolved_mappings.get(h, {}).get("status") == "known_header")
    header_score = (known_count * 1.0 + (mapped_count - known_count) * 0.8) / max(1, len(headers))

    layout_score = 0.95 if (logical_columns and len(logical_columns) == len(headers)) else 0.80

    if field_diagnostics:
        value_pattern_score = sum(d["quality_score"] for d in field_diagnostics.values()) / len(field_diagnostics)
    else:
        value_pattern_score = 0.50

    row_consistency_score = min(1.0, len(rows) / 5.0) if len(rows) < 5 else 0.95
    arithmetic_score = acct_summary.get("accounting_health", 1.0)
    template_prior_score = drift_info.get("similarity_score", 0.90)

    total_contradictions = sum(d.get("contradiction_count", 0) for d in field_diagnostics.values())
    contradiction_penalty = min(0.30, total_contradictions * 0.05)

    ambiguous_count = sum(1 for h in headers if resolved_mappings.get(h, {}).get("status") == "ambiguous")
    ambiguity_penalty = min(0.25, ambiguous_count * 0.08)

    raw_doc_score = (
        0.25 * header_score +
        0.15 * layout_score +
        0.25 * value_pattern_score +
        0.15 * row_consistency_score +
        0.15 * arithmetic_score +
        0.05 * template_prior_score
    ) - contradiction_penalty - ambiguity_penalty

    doc_confidence = round(max(0.0, min(1.0, raw_doc_score)) * 100.0, 1)

    mapped_fields_set = {info.get("mapped_to") for info in resolved_mappings.values() if info.get("mapped_to")}
    has_mandatory = "itemName" in mapped_fields_set and ("quantity" in mapped_fields_set or "amount" in mapped_fields_set)

    # 6. Strict 12-Point Deterministic AUTO_ACCEPT Safety Gate
    auto_accept_blockers = []

    # 1. Mandatory core fields: itemName + (quantity or amount)
    if not has_mandatory:
        auto_accept_blockers.append("Missing mandatory fields (itemName and quantity/amount)")

    # 2. Duplicate canonical field assignments across distinct physical columns
    flat_mappings = {h: (m.get("mapped_to") if isinstance(m, dict) else m) for h, m in resolved_mappings.items()}
    has_duplicates, duplicates = check_duplicate_field_assignments(flat_mappings)
    if has_duplicates:
        for f, h_list in duplicates.items():
            if f in ("itemName", "quantity", "amount"):
                auto_accept_blockers.append(f"Duplicate mapping for critical canonical field '{f}' in headers {h_list}")
            else:
                clean_hdrs = [clean_text(h).upper() for h in h_list]
                has_exact = any(c == f.upper() or c in [clean_text(a).upper() for a in ALIAS_DICT.get(f, [])[:2]] for c in clean_hdrs)
                has_aux = any("OLD" in c or "PREV" in c or "BOX" in c or "OUTER" in c or "PTR" in c or "PUR" in c for c in clean_hdrs)
                if not (has_exact and has_aux):
                    auto_accept_blockers.append(f"Duplicate mapping for canonical field '{f}' in headers {h_list}")

    # 3. Critical field collision / swap ambiguity
    if swap_log:
        unresolved_swaps = [s for s in swap_log if s.get("status") == "unresolved_collision"]
        if unresolved_swaps:
            auto_accept_blockers.append(f"Unresolved field swap collision: {[s.get('fields') for s in unresolved_swaps]}")

    # 4. Unresolved logical sub-column ambiguity
    ambiguous_subcols = []
    if logical_columns:
        for lc in logical_columns:
            if lc.get("status") == "ambiguous":
                ambiguous_subcols.append(lc.get("header_text", "unknown"))
    if ambiguous_subcols:
        auto_accept_blockers.append(f"Unresolved sub-column ambiguity in: {ambiguous_subcols}")

    # 5. Arithmetic / accounting validation failures
    if acct_summary.get("critical_mismatches", 0) > 0:
        auto_accept_blockers.append(f"Accounting critical mismatch count: {acct_summary.get('critical_mismatches')}")
    if acct_summary.get("accounting_health", 1.0) < 0.70 and len(rows) >= 3:
        auto_accept_blockers.append("Low accounting health score (< 0.70)")

    # 6. Field value contradictions
    if contradiction_penalty > 0.05:
        auto_accept_blockers.append(f"Field contradictions detected (penalty: {contradiction_penalty:.2f})")

    # 7. Ambiguous mapping penalty
    if ambiguity_penalty > 0.05:
        auto_accept_blockers.append(f"Ambiguous column mappings (penalty: {ambiguity_penalty:.2f})")

    # 8. Supplier Identity Safety
    if supplier_name or supplier_gstin:
        id_safety = validate_supplier_identity_safety(
            supplier_name or "", supplier_gstin or "",
            name_confidence=metadata.get("supplier_confidence", 1.0) if metadata else 1.0
        )
        if not id_safety.get("is_safe_to_attach", True):
            auto_accept_blockers.append(f"Supplier identity safety risk: {id_safety.get('details')}")

    # 9. Layout profile drift compatibility
    if drift_info.get("status") == "incompatible_layout":
        auto_accept_blockers.append("Incompatible layout profile drift")

    # 10. Critical numeric fields consistency
    if "rate" in mapped_fields_set and "amount" in mapped_fields_set and "quantity" in mapped_fields_set:
        if any(d.get("status") == "potential_swap" for d in field_diagnostics.values()):
            auto_accept_blockers.append("Potential numeric field swap warning")

    # 11. Row-level extraction quality
    if len(rows) == 0:
        auto_accept_blockers.append("Zero product rows extracted")

    # 12. Confidence score threshold
    if doc_confidence < 80.0:
        auto_accept_blockers.append(f"Confidence score {doc_confidence:.1f}% below AUTO_ACCEPT threshold (80.0%)")

    # 13. Deterministic Compound Quantity Safety Gate
    for r_idx, row in enumerate(rows):
        for col_i, h in enumerate(headers):
            m_field = resolved_mappings.get(h, {}).get("mapped_to")
            val = row[col_i] if col_i < len(row) else ""
            if not val:
                continue
            tok = tokenize_compound_quantity(val)
            if not tok["is_compound"] and "+" in str(val) and m_field in ("quantity", "freeQuantity"):
                auto_accept_blockers.append(f"Row {r_idx+1}: Unresolved or malformed compound quantity expression '{val}' in column '{h}'")

    if any(any(d.get("status") in ("UNRESOLVED_COMPOUND", "LOST_FREE_QUANTITY") for d in r) for r in row_discrepancies if isinstance(r, list)):
        auto_accept_blockers.append("Critical unresolved compound quantity discrepancy detected")

    # 14. Truncated / pack-only itemName values are critical ambiguity —
    # never AUTO_ACCEPT when product names collapse to form tokens (TAB./CAP./CREAM).
    item_header = next(
        (h for h in headers if (resolved_mappings.get(h) or {}).get("mapped_to") == "itemName"),
        None,
    )
    if item_header is not None:
        item_idx_aa = headers.index(item_header)
        pack_only = re.compile(
            r"(?i)^(tabs?|caps?|cream|syp|syrup|inj|gel|drops?|ointment|softgel|susp)(\b.*)?$"
        )
        truncated = 0
        for row in rows:
            item = str(row[item_idx_aa] if item_idx_aa < len(row) else "").strip()
            if not item:
                continue
            # Brand+form is OK; form-only or form+size without leading brand letters is not.
            letters = re.sub(r"[^A-Za-z]", "", item)
            if pack_only.match(item) and len(letters) <= 12:
                # If the string is essentially a pack/form token (no multi-letter brand prefix)
                # e.g. "TAB.", "CAP.", "CREAM <10gm>"
                if not re.match(r"(?i)^[A-Za-z]{3,}.*\s+(tab|cap|cream|syp|inj)", item):
                    truncated += 1
        if truncated >= 1:
            auto_accept_blockers.append(
                f"Critical itemName truncation suspected in {truncated} row(s); human review required"
            )

    # Final Classification Decision
    if len(auto_accept_blockers) == 0 and doc_confidence >= 80.0:
        classification = "AUTO_ACCEPT"
    elif has_mandatory and doc_confidence >= 55.0:
        classification = "REVIEW_REQUIRED"
    else:
        classification = "UNRESOLVED"

    return {
        "classification": classification,
        "document_confidence": doc_confidence,
        "auto_accept_blockers": auto_accept_blockers,
        "score_components": {
            "header_score": round(header_score, 3),
            "layout_score": round(layout_score, 3),
            "value_pattern_score": round(value_pattern_score, 3),
            "row_consistency_score": round(row_consistency_score, 3),
            "arithmetic_score": round(arithmetic_score, 3),
            "template_prior_score": round(template_prior_score, 3),
            "contradiction_penalty": round(contradiction_penalty, 3),
            "ambiguity_penalty": round(ambiguity_penalty, 3),
        },
        "resolved_mappings": resolved_mappings,
        "field_diagnostics": field_diagnostics,
        "accounting_summary": acct_summary,
        "row_discrepancies": row_discrepancies,
        "layout_signature": current_sig,
        "drift_report": drift_info,
        "swap_audit_log": swap_log,
    }



def tokenize_compound_quantity(val) -> dict:
    """
    Deterministically tokenizes a cell value into compound quantity components.
    Recognizes patterns such as:
    - 23+2, 10+2, 2.500+.500, 10 + 2, 23 + 2, 2.500 + .500, 23+0, 0+2, 23+0.5, .500+.250
    - +2 (free only)

    Rejects malformed/unrelated expressions:
    - A+B, ABC+DEF, 10+ABC, 10++2, ++, 10+, +

    Returns structured dict:
    {
        "is_compound": bool,
        "left": float or None,
        "right": float or None,
        "left_raw": str,
        "right_raw": str,
        "operator": "+" or None,
        "raw_value": str,
        "pattern": str or None,
        "confidence": float
    }
    """
    default_res = {
        "is_compound": False,
        "left": None,
        "right": None,
        "left_raw": "",
        "right_raw": "",
        "operator": None,
        "raw_value": str(val) if val is not None else "",
        "pattern": None,
        "confidence": 0.0,
    }
    if val is None:
        return default_res

    text = str(val).strip().replace(",", "")
    if not text:
        return default_res

    default_res["raw_value"] = str(val).strip()

    # 1. Check free-only "+N" (e.g. "+2", "+ 2", "+.500")
    free_match = re.match(r"^\+\s*(\d+(?:\.\d+)?|\.\d+)\s*$", text)
    if free_match:
        r_str = free_match.group(1)
        try:
            r_val = float(r_str)
            return {
                "is_compound": True,
                "left": 0.0,
                "right": r_val,
                "left_raw": "0",
                "right_raw": r_str,
                "operator": "+",
                "raw_value": text,
                "pattern": "free_only_quantity",
                "confidence": 0.95,
            }
        except ValueError:
            return default_res

    # 2. Strict Compound Qty Pattern "A + B"
    compound_match = re.match(
        r"^\s*(\d+(?:\.\d+)?|\.\d+)\s*\+\s*(\d+(?:\.\d+)?|\.\d+)\s*$",
        text,
    )
    if compound_match:
        l_str = compound_match.group(1)
        r_str = compound_match.group(2)
        try:
            l_val = float(l_str)
            r_val = float(r_str)
            return {
                "is_compound": True,
                "left": l_val,
                "right": r_val,
                "left_raw": l_str,
                "right_raw": r_str,
                "operator": "+",
                "raw_value": text,
                "pattern": "quantity_plus_free_quantity",
                "confidence": 1.0,
            }
        except ValueError:
            return default_res

    return default_res


def parse_compound_qty(val):
    """
    Backwards-compatible tuple return (billed, free) wrapping tokenize_compound_quantity.
    """
    tok = tokenize_compound_quantity(val)
    if tok["is_compound"]:
        return (
            tok["left"] if tok["left"] is not None else 0.0,
            tok["right"] if tok["right"] is not None else 0.0,
        )
    return (0.0, 0.0)


def _to_float(val, default=None):
    """
    Convert a value to float while distinguishing:
    - None / '' -> default (typically None, meaning missing)
    - '0' / 0 / 0.0 -> 0.0 (explicit zero)
    - '.500' / '0.50' -> 0.5 (handles leading decimal dots)
    - '123.45' -> 123.45 (extracted number)
    - unparseable string -> default
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        try:
            if pd.isna(val):
                return default
        except Exception:
            pass
        return float(val)

    text = str(val).strip().replace(",", "")
    if not text:
        return default
    match = re.search(r"[-+]?(?:\d+\.?\d*|\.\d+)", text)
    if not match:
        return default
    try:
        return float(match.group(0))
    except ValueError:
        return default


def normalize_quantity_value(val, is_free: bool = False, billed_val: float = None):
    """
    Standardizes quantity and freeQuantity values into clean, minimal numbers:
    - Strips noisy trailing zeros: 6.500 -> 6.5, 8.50 -> 8.5, 2.00 -> 2
    - Handles leading dot decimals: .500 -> 0.5, .600 -> 0.6, .70 -> 0.7
    - Handles faint/missing dot anomalies on free quantities (e.g. 500 when billed is 2.5 -> 0.5)
    """
    if val is None or val == "" or str(val).strip().lower() in ("none", "nan", "null"):
        return None
    text = str(val).strip().replace(",", "")
    if not text:
        return None

    # Check for compound quantity token first
    tok = tokenize_compound_quantity(text)
    if tok["is_compound"]:
        target = tok["right"] if is_free else tok["left"]
        if target is None:
            return None
        return int(target) if target.is_integer() else round(target, 4)

    match = re.search(r"[-+]?(?:\d+\.?\d*|\.\d+)", text)
    if not match:
        return None
    try:
        num = float(match.group(0))
        # Anomaly guard: freeQuantity printed as 500/600/700 for .500/.600/.700
        if is_free and num in (100.0, 200.0, 250.0, 300.0, 400.0, 500.0, 600.0, 700.0, 750.0, 800.0, 900.0):
            if billed_val is not None and billed_val < 50:
                num = num / 1000.0
        elif is_free and num >= 100 and "." not in text and (billed_val is not None and billed_val < 50):
            num = num / 1000.0

        if num.is_integer():
            return int(num)
        return round(num, 4)
    except ValueError:
        return None



def split_leading_serial_product_token(text):
    """
    Split a single glued token like '4MGD3', '6VSL#3', '5TOPAMAC' into
    (serial_digits, product_fragment). Returns (None, None) when ambiguous.
    Does not use product dictionaries or document-specific rules.
    """
    if text is None:
        return None, None
    s = str(text).strip()
    if not s or re.search(r"\s", s):
        return None, None
    m = re.match(r"^(\d{1,3})([A-Za-z].+)$", s)
    if not m:
        return None, None
    serial, rest = m.group(1), m.group(2)
    letters = re.sub(r"[^A-Za-z]", "", rest)
    if len(letters) < 2:
        return None, None
    # Reject pure form tokens after serial (e.g. '1TAB') — too ambiguous alone.
    if letters.lower() in {
        "tab", "tabs", "cap", "caps", "cream", "gel", "syp", "inj", "ml", "gm", "mg"
    } and len(rest) <= 6:
        return None, None
    return serial, rest


def reconstruct_serial_glued_product_names(headers, rows, column_mappings=None):
    """
    Generic repair for SN|ProductName glued tokens:
      SN='4MGD3' + ProductName='TAB.'  -> SN='4', ProductName='MGD3 TAB.'
      ProductName='1BECOSULES CAP.' with empty/matching SN -> ProductName='BECOSULES CAP.'

    Only peels leading serial digits from a product-like fragment. Never moves
    arbitrary alphabetic SN cells. Records provenance; does not raise confidence.
    """
    if not headers or not rows:
        return rows, []

    sn_idx = None
    item_idx = None
    for i, h in enumerate(headers):
        mapped = None
        if column_mappings and h in column_mappings:
            entry = column_mappings[h]
            mapped = entry.get("mapped_to") if isinstance(entry, dict) else entry
        if mapped is None:
            mapped = match_column_name(h)
        if is_serial_number_header(h):
            sn_idx = i
        if mapped == "itemName":
            item_idx = i

    if item_idx is None:
        return rows, []

    provenance = []
    out = []
    for r_idx, row in enumerate(rows):
        row = list(row)
        while len(row) < len(headers):
            row.append("")

        sn_val = str(row[sn_idx]).strip() if sn_idx is not None else ""
        item_val = str(row[item_idx]).strip() if item_idx < len(row) else ""

        # Case A: SN cell is serial+brand glue; ProductName holds continuation/form.
        if sn_idx is not None and sn_val:
            serial, brand = split_leading_serial_product_token(sn_val)
            if serial and brand:
                if item_val and item_val.upper().startswith(brand.upper()):
                    new_item = item_val
                elif item_val:
                    new_item = f"{brand} {item_val}".strip()
                else:
                    new_item = brand
                before_sn, before_item = sn_val, item_val
                row[sn_idx] = serial
                row[item_idx] = new_item
                provenance.append({
                    "row": r_idx,
                    "action": "peel_sn_glued_product",
                    "serial": serial,
                    "brand": brand,
                    "sn_before": before_sn,
                    "item_before": before_item,
                    "item_after": new_item,
                })
                item_val = new_item
                sn_val = serial

        # Case B: ProductName first token is serial+brand glue; SN empty or equals serial.
        if item_val:
            first_tok = item_val.split()[0]
            serial, rest_first = split_leading_serial_product_token(first_tok)
            if serial and rest_first:
                sn_now = str(row[sn_idx]).strip() if sn_idx is not None else ""
                if sn_idx is None or sn_now in ("", serial):
                    remainder = item_val[len(first_tok):].strip()
                    new_item = f"{rest_first} {remainder}".strip() if remainder else rest_first
                    provenance.append({
                        "row": r_idx,
                        "action": "peel_item_leading_serial",
                        "serial": serial,
                        "item_before": item_val,
                        "item_after": new_item,
                    })
                    row[item_idx] = new_item
                    if sn_idx is not None:
                        row[sn_idx] = serial

        out.append(row)
    return out, provenance


def fix_column_bleeding(row_dict):
    """Surgically separates merged cell data based on strict Regex data types."""
    if not isinstance(row_dict, dict):
        return row_dict

    # 1. Rule A: Separate Date trapped at the end of a Batch string (e.g., "306DB251811/27")
    if row_dict.get("batchNo"):
        batch_val = str(row_dict["batchNo"]).strip()
        date_match = re.search(r"(\d{1,2}[/-]\d{2,4})$", batch_val)
        if date_match:
            trapped_date = date_match.group(1)
            row_dict["batchNo"] = batch_val[:date_match.start()].strip()
            if not row_dict.get("expiryDate") or len(str(row_dict.get("expiryDate")).strip()) < 3:
                row_dict["expiryDate"] = trapped_date

    # 2. Rule B: Separate HSN trapped inside Expiry Date (e.g., "11/27 30049099" or "11/2730049099")
    if row_dict.get("expiryDate"):
        exp_str = str(row_dict["expiryDate"]).strip()
        hsn_match = re.match(r"^(\d{1,2}[/-]\d{2,4})\s*(\d{4,8})$", exp_str)
        if hsn_match:
            row_dict["expiryDate"] = hsn_match.group(1)
            row_dict["hsnCode"] = hsn_match.group(2)

    # 3. Rule C: Separate Numbers trapped together (e.g., "159.00 121.14" in mrp or rate)
    for num_col in ("mrp", "rate"):
        col_val = str(row_dict.get(num_col) or "").strip()
        num_match = re.match(r"^(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)$", col_val)
        if num_match:
            row_dict["mrp"] = num_match.group(1)
            row_dict["rate"] = num_match.group(2)
            break

    # 4. Rule D: Separate Compound Quantity in quantity (e.g., "23+2", "2.500+.500")
    if row_dict.get("quantity"):
        q_val = str(row_dict["quantity"]).strip()
        tok = tokenize_compound_quantity(q_val)
        if tok["is_compound"]:
            row_dict["quantity"] = tok["left_raw"]
            if not row_dict.get("freeQuantity") or str(row_dict.get("freeQuantity")).strip() in ("", "0", "0.0", "None"):
                row_dict["freeQuantity"] = tok["right_raw"]

    # 5. Rule E: Separate Discount % trapped with HSN Code (e.g., "-1.50 30049084" or "10.00 30049099")
    for disc_col in ("discountPercent", "hsnCode"):
        if row_dict.get(disc_col):
            val = str(row_dict[disc_col]).strip()
            m = re.match(r"^(-?\d+(?:\.\d+)?%?)\s+(\d{4,8})$", val)
            if m:
                row_dict["discountPercent"] = m.group(1).replace("%", "")
                if not row_dict.get("hsnCode") or len(str(row_dict.get("hsnCode")).strip()) < 4:
                    row_dict["hsnCode"] = m.group(2)
                break

    # 6. Rule F: Separate GST% + GST Amount + Net Amount trapped in netAmount/amount (e.g. "5 10.14 213.07")
    for net_col in ("netAmount", "amount"):
        if row_dict.get(net_col):
            val = str(row_dict[net_col]).strip()
            m = re.match(r"^(\d+(?:\.\d+)?%?)\s+(\d+(?:\.\d+)?)\s+([\d,]+(?:\.\d+)?)$", val)
            if m:
                g_pct = m.group(1).replace("%", "")
                g_amt = m.group(2)
                n_amt = m.group(3).replace(",", "")
                if not row_dict.get("gstPercent") or str(row_dict.get("gstPercent")).strip() in ("", "0", "0.0"):
                    row_dict["gstPercent"] = g_pct
                row_dict["netAmount"] = n_amt
                break

    # 7. Rule G: Separate Amount + GST% trapped in amount (e.g. "1000.00 18%" or "1000.00 18")
    if row_dict.get("amount"):
        amt_val = str(row_dict["amount"]).strip()
        m = re.match(r"^([\d,]+(?:\.\d+)?)\s+(\d+(?:\.\d+)?%?)$", amt_val)
        if m:
            v1, v2 = m.group(1), m.group(2)
            try:
                v2_num = float(v2.replace("%", ""))
                if v2.endswith("%") or v2_num in (0.0, 5.0, 12.0, 18.0, 28.0):
                    row_dict["amount"] = v1.replace(",", "")
                    if not row_dict.get("gstPercent") or str(row_dict.get("gstPercent")).strip() in ("", "0", "0.0"):
                        row_dict["gstPercent"] = str(int(v2_num) if v2_num.is_integer() else v2_num)
            except ValueError:
                pass

    # 8. Rule H: Separate Amount + Discount trapped in amount (e.g. "371.35 -1.50")
    if row_dict.get("amount"):
        amt_val = str(row_dict["amount"]).strip()
        m = re.match(r"^([\d,]+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?%?)$", amt_val)
        if m:
            v1, v2 = m.group(1), m.group(2)
            if v2.startswith("-") or v2.endswith("%"):
                row_dict["amount"] = v1.replace(",", "")
                old_disc = str(row_dict.get("discountPercent") or "").strip()
                if old_disc in ("5", "12", "18", "28", "5.0", "12.0", "18.0", "28.0") and (not row_dict.get("gstPercent") or str(row_dict.get("gstPercent")).strip() in ("", "0", "0.0")):
                    row_dict["gstPercent"] = old_disc
                row_dict["discountPercent"] = v2.replace("%", "")

    # 9. Rule I: Separate Discount% + Discount Amount (e.g. "5.00 18.57")
    for disc_col in ("discountPercent", "discountAmount"):
        if row_dict.get(disc_col):
            val = str(row_dict[disc_col]).strip()
            m = re.match(r"^(\d+(?:\.\d+)?%?)\s+(\d+(?:\.\d+)?)$", val)
            if m:
                row_dict["discountPercent"] = m.group(1).replace("%", "")
                if not row_dict.get("discountAmount"):
                    row_dict["discountAmount"] = m.group(2)
                break

    # 10. Rule J: Separate CGST + SGST (e.g. "6.00 6.00" or "9% 9%")
    for cgst_col in ("cgstPercent", "cgstAmount"):
        if row_dict.get(cgst_col):
            val = str(row_dict[cgst_col]).strip()
            m = re.match(r"^(\d+(?:\.\d+)?%?)\s+(\d+(?:\.\d+)?%?)$", val)
            if m:
                row_dict["cgstPercent"] = m.group(1).replace("%", "")
                if not row_dict.get("sgstPercent"):
                    row_dict["sgstPercent"] = m.group(2).replace("%", "")
                break

    return row_dict


def compute_row_accounting(row, tolerance: float = 0.10):
    """
    Processes line-item accounting values safely:
    - Preserves extracted financial values if present.
    - Derives missing financial values only when required inputs are available.
    - Validates relationships (e.g. qty * rate vs amount) and records validation discrepancies
      without destructively overwriting extracted values.
    - Preserves raw values under '_raw_values' key for traceability and auditability.
    - Reconstructs compound quantity values (e.g. '23+2' -> quantity=23, freeQuantity=2)
      with full provenance in '_compound_provenance'.
    - Preserves explicit taxes (CGST/SGST/IGST/GST) without inventing artificial splits.
    """
    data = dict(row) if isinstance(row, dict) else {}

    # Preserve snapshot of original raw values before any mutation
    if "_raw_values" not in data:
        data["_raw_values"] = {
            k: v for k, v in data.items()
            if k not in ("_raw_values", "validation_discrepancies", "_compound_provenance")
        }

    raw_qty_input = data.get("quantity")
    raw_free_input = data.get("freeQuantity")

    data = fix_column_bleeding(data)
    discrepancies = list(data.get("validation_discrepancies") or [])

    # Decompose compound quantity with full provenance
    qty_tok = tokenize_compound_quantity(raw_qty_input)
    free_tok = tokenize_compound_quantity(raw_free_input)

    if qty_tok["is_compound"]:
        qty_ext = qty_tok["left"]
        data["quantity"] = qty_ext
        curr_free_float = _to_float(data.get("freeQuantity"))
        if curr_free_float is None or curr_free_float == 0.0 or str(data.get("freeQuantity")).strip() in ("", "None", "0", "0.0"):
            data["freeQuantity"] = qty_tok["right"]
        data["_compound_provenance"] = {
            "quantity": f"Reconstructed from compound source cell '{qty_tok['raw_value']}' (billed={qty_tok['left_raw']})",
            "freeQuantity": f"Reconstructed from compound source cell '{qty_tok['raw_value']}' (free={qty_tok['right_raw']})",
        }
    elif raw_qty_input is not None and "+" in str(raw_qty_input):
        discrepancies.append({
            "field": "quantity",
            "raw_value": str(raw_qty_input),
            "status": "UNRESOLVED_COMPOUND",
            "message": f"Malformed or ambiguous compound quantity '{raw_qty_input}'",
        })
        qty_ext = _to_float(data.get("quantity"))
    else:
        qty_ext = _to_float(data.get("quantity"))

    if free_tok["is_compound"]:
        free_ext = free_tok["right"]
        data["freeQuantity"] = free_ext
        if qty_ext is None and free_tok["left"] is not None and free_tok["left"] > 0:
            qty_ext = free_tok["left"]
            data["quantity"] = qty_ext
    else:
        free_ext = _to_float(data.get("freeQuantity"))

    rate_ext = _to_float(data.get("rate"))
    disc_ext = _to_float(data.get("discountPercent"))
    gst_ext = _to_float(data.get("gstPercent"))
    cgst_ext = _to_float(data.get("cgstPercent"))
    sgst_ext = _to_float(data.get("sgstPercent"))
    amount_ext = _to_float(data.get("amount"))
    taxable_ext = _to_float(data.get("taxableAmount"))
    net_ext = _to_float(data.get("netAmount"))

    # 2. Tax Handling:
    # If CGST and SGST are both present, derive total GST if missing
    gst_val = gst_ext
    cgst_val = cgst_ext
    sgst_val = sgst_ext

    if gst_val is None and (cgst_val is not None or sgst_val is not None):
        gst_val = round((cgst_val or 0.0) + (sgst_val or 0.0), 4)
    elif gst_val is not None and cgst_val is not None and sgst_val is not None:
        sum_tax = round(cgst_val + sgst_val, 4)
        if abs(sum_tax - gst_val) > 0.05:
            discrepancies.append({
                "field": "gstPercent",
                "extracted": gst_val,
                "calculated": sum_tax,
                "status": "MISMATCH",
            })

    # 3. Amount Handling:
    amount_val = amount_ext
    if amount_val is not None:
        if qty_ext is not None and rate_ext is not None and qty_ext > 0 and rate_ext > 0:
            calc_amount = round(qty_ext * rate_ext, 2)
            if abs(amount_val - calc_amount) > max(tolerance, calc_amount * 0.01):
                discrepancies.append({
                    "field": "amount",
                    "extracted": amount_val,
                    "calculated": calc_amount,
                    "status": "MISMATCH",
                })
    else:
        if qty_ext is not None and rate_ext is not None:
            amount_val = round(qty_ext * rate_ext, 2)

    # 4. Taxable Amount Handling:
    taxable_val = taxable_ext
    if taxable_val is not None:
        if amount_val is not None and disc_ext is not None:
            calc_taxable = round(amount_val * (1.0 - (disc_ext / 100.0)), 2)
            if abs(taxable_val - calc_taxable) > max(tolerance, calc_taxable * 0.01):
                discrepancies.append({
                    "field": "taxableAmount",
                    "extracted": taxable_val,
                    "calculated": calc_taxable,
                    "status": "MISMATCH",
                })
    else:
        if amount_val is not None:
            d_pct = disc_ext if disc_ext is not None else 0.0
            taxable_val = round(amount_val * (1.0 - (d_pct / 100.0)), 2)
        elif net_ext is not None and gst_val is not None and gst_val > 0:
            divisor = 1.0 + (gst_val / 100.0)
            taxable_val = round(net_ext / divisor, 2)

    # 5. Net Amount Handling:
    net_val = net_ext
    if net_val is not None:
        if taxable_val is not None and gst_val is not None:
            calc_net = round(taxable_val * (1.0 + (gst_val / 100.0)), 2)
            if abs(net_val - calc_net) > max(tolerance, calc_net * 0.01):
                discrepancies.append({
                    "field": "netAmount",
                    "extracted": net_val,
                    "calculated": calc_net,
                    "status": "MISMATCH",
                })
    else:
        if taxable_val is not None:
            g_pct = gst_val if gst_val is not None else 0.0
            gst_amt = round(taxable_val * (g_pct / 100.0), 2)
            net_val = round(taxable_val + gst_amt, 2)

    # Assign values back to data dictionary, preserving explicit values or derived
    if qty_ext is not None:
        data["quantity"] = qty_ext
    if rate_ext is not None:
        data["rate"] = rate_ext
    if disc_ext is not None:
        data["discountPercent"] = disc_ext
    if gst_val is not None:
        data["gstPercent"] = round(gst_val, 4)
    if cgst_val is not None:
        data["cgstPercent"] = round(cgst_val, 4)
    if sgst_val is not None:
        data["sgstPercent"] = round(sgst_val, 4)
    if amount_val is not None:
        data["amount"] = amount_val
    if taxable_val is not None:
        data["taxableAmount"] = taxable_val
    if net_val is not None:
        data["netAmount"] = net_val

    if discrepancies:
        data["validation_discrepancies"] = discrepancies

    return data


def standardize_date(val):
    if val is None:
        return None

    text = str(val).strip()
    if not text:
        return None

    digits = re.sub(r"\D", "", text)
    if len(digits) >= 4:
        candidates = []
        if len(digits) >= 5 and digits[0] == "0":
            candidates.append((digits[1:3], digits[3:5]))
        candidates.append((digits[0:2], digits[2:4]))
        for month_s, year_s in candidates:
            try:
                month = int(month_s)
                year = 2000 + int(year_s)
            except ValueError:
                continue
            if 1 <= month <= 12 and 2020 <= year <= 2040:
                return f"{month:02d}/{year}"

    match = re.match(r"^(\d{1,2})[/-](\d{2,4})$", text)
    if not match:
        return None

    month = int(match.group(1))
    year_part = match.group(2)
    year = 2000 + int(year_part) if len(year_part) == 2 else int(year_part)
    if month < 1 or month > 12 or year < 2020 or year > 2040:
        return None
    return f"{month:02d}/{year}"


# Phrases that boost a top-left header as a likely pharma/medical supplier trade name.
SUPPLIER_NAME_KEYWORDS = (
    "medi", "medical", "medicare", "medihub", "pharma", "pharmaceutical",
    "pharmaceuticals", "logistics", "agencies", "agency", "distributors",
    "distributor", "distribution", "stockist", "stockists", "wholesaler",
    "wholesalers", "wholesale", "chemist", "chemists", "drugs", "drug",
    "healthcare", "health care", "enterprises", "enterprise", "trading",
    "traders", "stores", "mart", "medico", "medicos", "life sciences",
    "biosciences", "formulations", "remedies", "therapeutics", "wellness",
    "pharma hub", "medplus", "apollo", "retail", "suppliers", "supplier",
    "pvt", "private limited", "ltd", "llp", "opc",
)

# Labels / titles / buyer-side text that must never win as supplier name.
SUPPLIER_NAME_SKIP_PAT = re.compile(
    r"(?i)"
    r"pharma\s*hubb\b|"
    r"bill\s*to|ship\s*to|sold\s*to|consignee|buyer|customer|party\s*name|"
    r"gst\s*invoice|tax\s*invoice|original\s*for\s*recipient|"
    r"^page\s*\d|^invoice\s*(no|number|date)|^date\s*:|^gstin|^phone|"
    r"^email|^mobile|^tel\.?|^dl\.?\s*no|^fssai|^due\s*date|^credit|"
    r"^debit|^irn\b|^ack\b|^einvoice|^e-?invoice|^taxable|"
    r"^hsn|^particulars|^description|^s\.?\s*no|^qty\b|^mrp\b|^rate\b|"
    r"^amount\b|^net\s*amount|^grand\s*total|^authori[sz]ed\s*sign|"
    r"\bmfgby\b|\bhsncode\b|\bproduct\s*name\b|\bbatch\s*no\b|\bc/s\s*qty\b|"
    r"\bpregeb\b|\btabm10\b|\bgcef0004\b"
)

# Address / contact lines often bold under the supplier header — not the name.
SUPPLIER_ADDRESS_PAT = re.compile(
    r"(?i)"
    r"\b(plot|street|road|road\.|rd\.|floor|flr|nagar|colony|sector|"
    r"phase|block|building|bldg|near|opp\.?|beside|pin\s*:?|pincode|"
    r"dist\.?|district|state|india)\b|"
    r"\b\d{6}\b|"  # Indian PIN
    r"@|www\.|http|\+?\d[\d\s-]{8,}"
)

BARCODE_FONT_PAT = re.compile(r"(?i)free\s*3\s*of\s*9|barcode|code\s*39|code128")


def _is_bold_font(fontname: str) -> bool:
    name = (fontname or "").lower()
    return any(tok in name for tok in ("bold", "black", "heavy", "semibold", "demi"))


def _clean_seller_candidate_text(text: str) -> str:
    if not text:
        return ""
    # Strip buyer, invoice titles, or party labels appearing on the right side of the same line
    split_pat = r"(?i)\b(gst\s*invoice|tax\s*invoice|m/s\.?\s*pharma\s*hubb|m/s\.?\s*pharma|pharma\s*hubb|pharma\s*hub|original\s*for\s*recipient|inv\s*no|party\s*name|bill\s*to|ship\s*to)\b"
    m = re.search(split_pat, text)
    if m and m.start() >= 3:
        text = text[:m.start()]
    text = re.sub(r"(?i)\s*(gst|tax|inv|pharma\s*hubb?|m/s)\b.*$", "", text)
    text = re.sub(r"\s*\d{1,2}-\d{1,2}.*$", "", text)
    return text.strip(" :-|/\\,")


def _cluster_chars_into_lines(chars, y_tol: float = 2.5):
    """Group pdfplumber chars into reading-order text lines."""
    if not chars:
        return []

    ordered = sorted(chars, key=lambda c: (round(c.get("top", 0), 1), c.get("x0", 0)))
    lines = []
    current = []
    current_top = None

    for ch in ordered:
        top = float(ch.get("top", 0))
        if current_top is None or abs(top - current_top) <= y_tol:
            current.append(ch)
            if current_top is None:
                current_top = top
            else:
                current_top = (current_top * (len(current) - 1) + top) / len(current)
        else:
            lines.append(current)
            current = [ch]
            current_top = top
    if current:
        lines.append(current)
    return lines


def _line_metrics(chars):
    chars = sorted(chars, key=lambda c: c.get("x0", 0))
    raw_text = "".join(c.get("text", "") for c in chars)
    raw_text = re.sub(r"\s+", " ", raw_text).strip()
    text = _clean_seller_candidate_text(raw_text)
    sizes = [float(c.get("size") or 0) for c in chars if c.get("size")]
    fonts = [c.get("fontname") or "" for c in chars]
    x0 = min(float(c.get("x0", 0)) for c in chars)
    x1 = max(float(c.get("x1", x0)) for c in chars)
    top = min(float(c.get("top", 0)) for c in chars)
    avg_size = sum(sizes) / len(sizes) if sizes else 0.0
    bold_frac = (
        sum(1 for f in fonts if _is_bold_font(f)) / len(fonts) if fonts else 0.0
    )
    barcode_frac = (
        sum(1 for f in fonts if BARCODE_FONT_PAT.search(f)) / len(fonts) if fonts else 0.0
    )
    return {
        "text": text,
        "avg_size": avg_size,
        "max_size": max(sizes) if sizes else 0.0,
        "bold_frac": bold_frac,
        "barcode_frac": barcode_frac,
        "x0": x0,
        "x1": x1,
        "top": top,
        "mid_x": (x0 + x1) / 2.0,
    }


def _supplier_keyword_boost(text: str) -> float:
    lowered = text.lower()
    boost = 0.0
    for kw in SUPPLIER_NAME_KEYWORDS:
        if kw in lowered:
            boost += 8.0 + min(len(kw), 12) * 0.4
    return min(boost, 55.0)


def _score_supplier_candidate(metrics, page_width, page_height) -> float:
    text = metrics["text"]
    if not text or len(text) < 3:
        return -1e9
    if not re.search(r"[A-Za-z]{2,}", text):
        return -1e9
    if metrics["barcode_frac"] > 0.4:
        return -1e9
    if SUPPLIER_NAME_SKIP_PAT.search(text):
        return -1e9
    if SUPPLIER_ADDRESS_PAT.search(text):
        return -1e9
    if re.fullmatch(r"[\d\W_]+", text):
        return -1e9
    if re.search(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]", text):
        return -1e9

    top_ratio = metrics["top"] / max(page_height, 1.0)
    mid_x_ratio = metrics["mid_x"] / max(page_width, 1.0)
    if top_ratio > 0.35:
        return -1e9
    if mid_x_ratio > 0.65:
        return -1e9

    score = 0.0
    score += metrics["max_size"] * 6.0
    score += metrics["avg_size"] * 2.0
    score += metrics["bold_frac"] * 35.0
    score += (1.0 - top_ratio) * 40.0
    score += (1.0 - min(1.0, mid_x_ratio)) * 25.0
    score += _supplier_keyword_boost(text)

    if 3 <= len(text) <= 48:
        score += 15.0
    elif len(text) > 70:
        score -= 20.0

    letters = re.sub(r"[^A-Za-z]", "", text)
    if letters and letters.isupper() and len(letters) >= 4:
        score += 8.0

    return score


def detect_supplier_name_from_page(page):
    """
    Pick the seller/supplier trade name from the first page.
    Heuristic: Top-left header block strictly above the product table.
    """
    page_width = float(page.width or 1.0)
    page_height = float(page.height or 1.0)
    chars = page.chars or []

    # Detect table header row to bound the supplier search region
    words = extract_page_words(page)
    _, header_top, _, _ = detect_coordinate_header_row(words, page_height)
    top_limit = (header_top - 2.0) if (header_top and header_top > 40.0) else (page_height * 0.28)

    best = None
    best_score = -1e9

    if chars:
        left_band = page_width * 0.65
        region_chars = [
            c for c in chars
            if float(c.get("top", 9999)) <= top_limit
            and float(c.get("x0", 9999)) <= left_band
        ]
        for line_chars in _cluster_chars_into_lines(region_chars):
            metrics = _line_metrics(line_chars)
            score = _score_supplier_candidate(metrics, page_width, page_height)
            if score > best_score:
                best_score = score
                best = metrics["text"]

    # Text fallback when char fonts are missing / sparse (some generators).
    if best is None or best_score < 40:
        text = page.extract_text() or ""
        fallback = extract_supplier_name_from_text(text)
        if fallback and (best is None or best_score < 55):
            return {
                "detected_name": fallback,
                "confidence": 0.55 if best is None else 0.65,
                "is_editable": True,
            }

    if not best:
        return {
            "detected_name": None,
            "confidence": 0.0,
            "is_editable": True,
        }

    # Soft confidence from score bands observed on sample invoices.
    if best_score >= 120:
        confidence = 0.95
    elif best_score >= 90:
        confidence = 0.85
    elif best_score >= 60:
        confidence = 0.7
    else:
        confidence = 0.5

    return {
        "detected_name": best,
        "confidence": confidence,
        "is_editable": True,
    }


def extract_supplier_name_from_text(text: str):
    if not text:
        return None

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    scored = []
    for idx, line in enumerate(lines[:20]):
        if not re.search(r"[A-Za-z]{2,}", line):
            continue
        if SUPPLIER_NAME_SKIP_PAT.search(line):
            continue
        if SUPPLIER_ADDRESS_PAT.search(line):
            continue
        if re.fullmatch(r"\*?\d+\*?", line):
            continue
        if len(line) < 3 or len(line) > 80:
            continue

        score = (20 - idx) * 2.0 + _supplier_keyword_boost(line)
        letters = re.sub(r"[^A-Za-z]", "", line)
        if letters and letters.isupper() and len(letters) >= 4:
            score += 8.0
        scored.append((score, line))

    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def extract_supplier_name(text: str):
    """Backward-compatible text-only helper."""
    return extract_supplier_name_from_text(text)


def extract_invoice_metadata(pdf_path):
    if hasattr(pdf_path, "seek"):
        pdf_path.seek(0)

    is_image = False
    if isinstance(pdf_path, (str, bytes, os.PathLike)):
        str_path = str(pdf_path).lower()
        if str_path.endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp")):
            is_image = True

    text = ""
    supplier_info = {}

    if not is_image:
        try:
            with pdfplumber.open(pdf_path) as pdf:
                if pdf.pages:
                    first_page = pdf.pages[0]
                    text = first_page.extract_text() or ""
                    supplier_info = detect_supplier_name_from_page(first_page)
        except Exception:
            is_image = True

    # Fallback to OCR if text is sparse or input is an image
    if (is_image or len(text.strip()) < 30) and ocr_engine is not None:
        try:
            if is_image:
                text = ocr_engine.extract_text_from_image(pdf_path)
            elif ocr_engine.fitz is not None:
                imgs = ocr_engine.render_pdf_to_images(pdf_path)
                if imgs:
                    text = ocr_engine.extract_text_from_image(imgs[0])
            if text:
                supplier_info = extract_supplier_name_from_text(text)
        except Exception as e:
            logger.warning(f"OCR metadata fallback exception: {e}")

    gstin_match = re.search(
        r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b",
        text,
    )
    invoice_number_match = re.search(
        r"(?i)(?:inv(?:oice)?\s*\.?\s*no\s*\.?\s*[:-]?\s*)([A-Z0-9/-]+)",
        text,
    )
    invoice_date_match = re.search(
        r"(?i)(?:(?:inv(?:oice)?\s*\.?\s*)?d[a|t]te?\s*\.?\s*[:-]?\s*)(\d{2}[-/\.]\d{2}[-/\.]\d{2,4}|\d{2}-[A-Za-z]{3}-\d{2,4})",
        text,
    )

    return {
        "supplier_name": supplier_info.get("detected_name") if isinstance(supplier_info, dict) else (supplier_info or None),
        "supplier_confidence": supplier_info.get("confidence") if isinstance(supplier_info, dict) else (0.8 if supplier_info else None),
        "supplier_is_editable": supplier_info.get("is_editable", True) if isinstance(supplier_info, dict) else True,
        "supplier_gstin": gstin_match.group(0) if gstin_match else None,
        "invoice_number": invoice_number_match.group(1) if invoice_number_match else None,
        "invoice_date": invoice_date_match.group(1) if invoice_date_match else None,
        "expiry_date_format": DEFAULT_EXPIRY_DATE_FORMAT,
    }


def _normalize_cell(cell, join_lines: bool = False, is_item_name: bool = False):
    if cell is None:
        return ""
    text = str(cell).replace("\r", "\n").strip()
    if not text:
        return ""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return ""
    # Preserve full multi-line description for product names or when join_lines is explicitly requested
    if join_lines or is_item_name:
        value = " ".join(lines)
    else:
        value = lines[0]
    parts = value.split()
    if len(parts) == 2 and parts[0].upper() == parts[1].upper():
        value = parts[0]
    return value


def _normalize_row(row, join_lines: bool = False, item_idx: int = None):
    if not row:
        return []
    return [
        _normalize_cell(
            cell,
            join_lines=join_lines,
            is_item_name=(item_idx is not None and idx == item_idx),
        )
        for idx, cell in enumerate(row)
    ]


def _row_joined_text(row) -> str:
    return " ".join(str(cell or "") for cell in (row or [])).strip()


def _is_footer_row(row):
    if not row:
        return False
    joined = _row_joined_text(row).lower()
    if not joined:
        return False
    if any(w in joined for w in FOOTER_STOP_WORDS):
        return True
    # Generic amount-in-words patterns: e.g. "thousand and", "hundred and", "rupees only", "lakh only"
    if re.search(r"\b(thousand|hundred|lakh|crore)\b", joined) and re.search(r"\b(only|and|rupees|rs\.?)\b", joined):
        return True
    # Generic page continuation cues: e.g. "continue page", "page.. 2", "continued on", "contd"
    if re.search(r"\b(continue|continued|contd|cont\.)\b|\bpage\s*\.{2,}\b|\bpage\s*\d+\s*of\s*\d+\b", joined):
        return True
    return False


def _is_letterhead_row(row) -> bool:
    joined = _row_joined_text(row).lower()
    if not joined:
        return False
    return any(w in joined for w in LETTERHEAD_SKIP_WORDS)


def _is_repeated_header_row(row, saved_template=None) -> bool:
    """True when a continuation-page row is a duplicate column header band."""
    if not row or not any(row):
        return False
    if _is_valid_header_row(_normalize_row(row, join_lines=True), saved_template):
        return True
    joined = _row_joined_text(row).lower()
    hits = sum(1 for w in REPEATED_HEADER_WORDS if w in joined)
    # Strong header phrases or several header tokens together.
    strong = any(
        kw in joined
        for kw in (
            "item description",
            "product name",
            "m.r.p",
            "billed",
            "quantity",
        )
    ) and any(
        kw in joined
        for kw in ("rate", "mrp", "m.r.p", "pack", "batch", "hsn", "qty", "amount")
    )
    return strong or hits >= 3


def _is_skippable_row(row):
    if not row:
        return True
    joined = _row_joined_text(row).lower()
    return bool(
        _is_footer_row(row)
        or _is_letterhead_row(row)
        or re.search(r"\b(terms\s*&?\s*conditions|amount in words)\b", joined)
    )


def _mapping_field(column_mappings: dict, header: str):
    val = (column_mappings or {}).get(header)
    if isinstance(val, dict):
        return val.get("mapped_to")
    return val


def _is_genuine_product_row(row, item_idx=None) -> bool:
    """
    Genuine medication line: non-blank, valid item text, at least one number,
    and not letterhead/header chrome.
    """
    if not row or not any(str(c or "").strip() for c in row):
        return False
    if _is_footer_row(row) or _is_letterhead_row(row) or _is_repeated_header_row(row):
        return False

    joined = _row_joined_text(row)
    joined_l = joined.lower()
    if not re.search(r"\d", joined):
        return False
    # Address / contact blocks often bleed into page-2 tables.
    if re.search(
        r"(?i)\b(gstin|pan\s*no|phone|email|udyam|whatsapp|pin-?\s*\d{3}|state code)\b",
        joined_l,
    ):
        return False
    if "@" in joined or "www." in joined_l:
        return False
    # Amount in words or continuation footer leak
    if re.search(r"\b(thousand|hundred|lakh|crore)\b", joined_l) and re.search(r"\b(only|rupees|rs\.?)\b", joined_l):
        return False
    if re.search(r"\b(continue|continued|contd)\b", joined_l):
        return False

    item_text = ""
    if item_idx is not None and item_idx < len(row):
        item_text = str(row[item_idx] or "").strip()
    else:
        for cell in row:
            text = str(cell or "").strip()
            if text and re.search(r"[A-Za-z]{2,}", text) and not match_column_name(text):
                item_text = text
                break

    if not item_text or not re.search(r"[A-Za-z]{2,}", item_text):
        return False
    item_l = item_text.lower()
    if any(w in item_l for w in LETTERHEAD_SKIP_WORDS):
        return False
    if any(
        kw in item_l
        for kw in (
            "item description",
            "product name",
            "m.r.p",
            "quantity",
            "particulars",
            "invoice date",
            "due date",
            "order no",
            "ref id",
            "route",
        )
    ):
        return False
    # Prefer rows that also look like stock lines (pack/batch/qty cues nearby).
    if item_idx is not None and not _looks_like_primary_item_row(row, item_idx=item_idx):
        return False
    return True


def _is_valid_header_row(row, saved_template=None):
    if not row or not any(row):
        return False
    mapped = [match_column_name(cell, saved_template) for cell in row if cell]
    mapped = [m for m in mapped if m]
    return len(set(mapped)) >= 2


def _merge_subheader_into_headers(headers, subheader):
    merged = list(headers)
    for idx, cell in enumerate(subheader):
        if not cell or idx >= len(merged):
            continue
        parent = merged[idx]
        parent_field = match_column_name(parent) if parent else None
        child_field = match_column_name(cell)
        if not parent:
            merged[idx] = cell
        elif parent_field == "quantity" and child_field in {"quantity", "freeQuantity"}:
            merged[idx] = cell
    return merged


def _row_nonempty_count(row):
    return sum(1 for cell in row if cell)


def _looks_like_item_row(row, item_idx=None):
    if _is_footer_row(row):
        return False
    if _row_nonempty_count(row) < 3:
        return False
    if item_idx is not None and item_idx < len(row):
        item = row[item_idx]
        if item and re.search(r"[A-Za-z]{3,}", item):
            return True
    letter_cells = [
        cell for cell in row
        if cell and re.search(r"[A-Za-z]{3,}", cell) and not match_column_name(cell)
    ]
    return len(letter_cells) >= 1 and _row_nonempty_count(row) >= 4


def _looks_like_primary_item_row(row, item_idx=None):
    if not _looks_like_item_row(row, item_idx=item_idx):
        return False
    # When item column is known, require a real product name there.
    # Avoid counting misaligned borderless rows (name landed in a neighbor cell).
    if item_idx is not None and item_idx < len(row):
        item = row[item_idx]
        return bool(item and re.search(r"[A-Za-z]{3,}", item))
    return sum(1 for cell in row[:3] if cell) >= 2


def _merge_continuation_rows(rows, item_idx=None):
    if not rows:
        return []
    merged = []
    for row in rows:
        if not any(row):
            continue
        is_primary = _looks_like_item_row(row, item_idx=item_idx)
        if not merged or is_primary:
            merged.append(list(row))
            continue
        prev = merged[-1]
        width = max(len(prev), len(row))
        prev.extend([""] * (width - len(prev)))
        row = list(row) + [""] * (width - len(row))
        for i, cell in enumerate(row):
            if cell and not prev[i]:
                prev[i] = cell
            elif cell and prev[i] and item_idx is not None and i == item_idx:
                prev[i] = f"{prev[i]} {cell}".strip()
    return merged


def _max_cell_len(table) -> int:
    longest = 0
    for row in table or []:
        for cell in row or []:
            longest = max(longest, len(str(cell or "")))
    return longest


def _score_extracted_table(table, saved_template=None, expected_cols=None):
    if not table or len(table) < 2:
        return -1
    header_idx = None
    # Header may sit below invoice metadata (GSTIN / bill-to), not in the first few rows.
    scan_limit = min(len(table), 25)
    for idx, row in enumerate(table[:scan_limit]):
        if _is_valid_header_row(_normalize_row(row, join_lines=True), saved_template):
            header_idx = idx
            break
    if header_idx is None:
        return -1

    headers = _normalize_row(table[header_idx], join_lines=True)
    item_idx = None
    mapped_fields = set()
    for i, h in enumerate(headers):
        field = match_column_name(h, saved_template)
        if field:
            mapped_fields.add(field)
        if field == "itemName":
            item_idx = i

    if "itemName" not in mapped_fields:
        return -1

    primary_rows = 0
    continuation_rows = 0
    for row in table[header_idx + 1:]:
        normalized = _normalize_row(row)
        if _looks_like_primary_item_row(normalized, item_idx=item_idx):
            primary_rows += 1
        elif _looks_like_item_row(normalized, item_idx=item_idx):
            continuation_rows += 1

    if primary_rows == 0:
        return -1

    # Borderless invoices often collapse into one mega-row when horizontal
    # strategy is "lines"; heavily penalize giant concatenated cells.
    mega = _max_cell_len(table)
    mega_penalty = 0
    if mega >= 200:
        mega_penalty = 80 + min(mega // 20, 120)
    elif mega >= 100:
        mega_penalty = 30

    score = (
        primary_rows * 20
        + len(mapped_fields) * 3
        - continuation_rows * 5
        - mega_penalty
        + min(len(table), 80)
    )

    # Continuation pages: prefer grids whose width matches the page-1 master.
    if expected_cols and table and table[0] is not None:
        drift = abs(len(table[0]) - expected_cols)
        if drift == 0:
            score += 50
        elif drift <= 2:
            score += 35
        elif drift <= 4:
            score += 10
        else:
            score -= drift * 18

    return score


# Multi-pass pdfplumber strategies. Borderless invoices have vertical rules but
# missing horizontal separators — use text baselines to force row splits.
BORDERLESS_TABLE_SETTINGS = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "text",
    "intersection_y_tolerance": 15,
    "intersection_x_tolerance": 3,
}

TABLE_EXTRACTION_STRATEGIES = [
    ("borderless", BORDERLESS_TABLE_SETTINGS),
    (
        "text",
        {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "intersection_tolerance": 15,
        },
    ),
    (
        "lines_strict",
        {
            "vertical_strategy": "lines_strict",
            "horizontal_strategy": "lines_strict",
        },
    ),
    (
        "lines",
        {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
        },
    ),
    ("default", {}),
]


def _project_row_onto_master(row, local_headers, master_headers):
    """Map a page-local row onto the master header order by name / system field."""
    local = ensure_named_headers(_normalize_row(local_headers, join_lines=True))
    local_item_idx = None
    for i, h in enumerate(local):
        if match_column_name(h) == "itemName":
            local_item_idx = i
            break
    values = _normalize_row(row, item_idx=local_item_idx)
    if len(values) < len(local):
        values = values + [""] * (len(local) - len(values))

    by_clean = {}
    by_field = {}
    for i, h in enumerate(local):
        key = clean_text(h)
        if key and key not in by_clean:
            by_clean[key] = i
        field = match_column_name(h)
        if field and field not in by_field and i < len(values) and values[i]:
            by_field[field] = i

    out = []
    for mh in master_headers:
        val = ""
        key = clean_text(mh)
        if key and key in by_clean:
            li = by_clean[key]
            if li < len(values):
                val = values[li]
        if not val:
            field = match_column_name(mh)
            if field and field in by_field:
                li = by_field[field]
                if li < len(values):
                    val = values[li]
        out.append(val)
    return out


def _extract_best_tables(page, saved_template=None, expected_cols=None):
    """
    Multi-pass table extraction: try borderless (lines + text baselines) first,
    then fall back to text/text, lines_strict, lines, and default. Keep the
    highest-scoring usable table set so borderless invoices do not collapse
    into a single massive row.

    When expected_cols is set (page 2+), column-width drift from the page-1
    master is scored so misaligned grids lose to matching ones.
    """
    best_tables = []
    best_score = -1
    for _name, settings in TABLE_EXTRACTION_STRATEGIES:
        try:
            tables = page.extract_tables(table_settings=settings) or []
        except Exception:
            continue
        score = 0
        usable = []
        for table in tables:
            table_score = _score_extracted_table(
                table, saved_template, expected_cols=expected_cols
            )
            if table_score > 0:
                usable.append(table)
                score += table_score
        if usable and score > best_score:
            best_score = score
            best_tables = usable
    return best_tables


# ==============================================================================
# COORDINATE-AWARE EXTRACTION CONSTANTS & CONFIGURATION
# ==============================================================================
COORD_HEADER_Y_TOLERANCE = 3.5
COORD_HEADER_X_GAP_TOLERANCE = 8.0
COORD_ROW_Y_TOLERANCE = 4.5
COORD_ITEM_CONTINUATION_Y_GAP = 12.0
COORD_COL_BOUNDARY_MARGIN = 3.0
COORD_MIN_CONFIDENCE = 0.50


def extract_page_words(page):
    """
    Extracts words from a pdfplumber page with complete coordinate geometry:
    x0, x1, top, bottom, center_x, center_y, width, height, doctop.
    """
    raw_words = page.extract_words(
        x_tolerance=2, y_tolerance=2,
        keep_blank_chars=False, use_text_flow=False
    ) or []
    words = []
    for w in raw_words:
        x0 = float(w["x0"])
        x1 = float(w["x1"])
        top = float(w["top"])
        bottom = float(w["bottom"])
        words.append({
            "text": str(w["text"]).strip(),
            "x0": x0,
            "x1": x1,
            "top": top,
            "bottom": bottom,
            "center_x": (x0 + x1) / 2.0,
            "center_y": (top + bottom) / 2.0,
            "width": float(w.get("width", x1 - x0)),
            "height": float(w.get("height", bottom - top)),
            "doctop": float(w.get("doctop", top)),
        })
    return words


def reconstruct_header_tokens(words, x_gap_tolerance: float = COORD_HEADER_X_GAP_TOLERANCE, y_tolerance: float = COORD_HEADER_Y_TOLERANCE, saved_template: dict = None):
    """
    Groups words into lines and merges horizontal sub-tokens that belong to the same header.
    Generic spatial proximity & lexical joining:
    - Joins broken visual fragments (e.g., MR + P -> MRP, PT + R -> PTR, BAT + CH -> BATCH, EX + P -> EXP, RA + TE -> RATE)
    - Supports spaced abbreviations (e.g., P . T . R, M . R . P, S . N o)
    - CRITICAL: Never merges adjacent words if both belong to distinct, different canonical fields
      (e.g., PACK + QTY + FREE or AMOUNT + GST or QTY + FREE or MRP + RATE).
    - Preserves legitimate separate headers separated by significant horizontal whitespace.
    """
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: (round(w["top"] / y_tolerance) * y_tolerance, w["x0"]))
    lines = []
    curr_line = []
    curr_y = None
    for w in sorted_words:
        if curr_y is None or abs(w["top"] - curr_y) <= y_tolerance:
            curr_line.append(w)
            curr_y = w["top"] if curr_y is None else (curr_y * len(curr_line) + w["top"]) / (len(curr_line) + 1)
        else:
            lines.append(sorted(curr_line, key=lambda x: x["x0"]))
            curr_line = [w]
            curr_y = w["top"]
    if curr_line:
        lines.append(sorted(curr_line, key=lambda x: x["x0"]))

    reconstructed_lines = []
    for line in lines:
        merged = []
        i = 0
        while i < len(line):
            curr = dict(line[i])
            while i + 1 < len(line):
                nxt = line[i + 1]
                gap = nxt["x0"] - curr["x1"]
                combined_no_space = curr["text"] + nxt["text"]
                combined_space = curr["text"] + " " + nxt["text"]

                f_curr = match_column_name(curr["text"], saved_template)
                f_nxt = match_column_name(nxt["text"], saved_template)
                f_comb_space = match_column_name(combined_space, saved_template)
                f_comb_nospace = match_column_name(combined_no_space, saved_template)

                # Never merge if both curr and nxt are distinct canonical fields
                if f_curr is not None and f_nxt is not None and f_curr != f_nxt:
                    break

                is_small_gap = 0 <= gap <= x_gap_tolerance
                is_kerning_gap = 0 <= gap <= 2.5
                is_large_gap = gap > max(x_gap_tolerance, 12.0)

                if is_large_gap:
                    break

                # Case A: Combined text matches a known canonical alias (no space, e.g. MR + P, PT + R, BAT + CH, EX + P, RA + TE)
                is_known_split = f_comb_nospace is not None and is_small_gap and (f_curr is None or f_nxt is None or f_curr == f_comb_nospace or f_nxt == f_comb_nospace)
                
                # Case B: Combined text matches a multi-word alias phrase (with space, e.g. PRODUCT + NAME, BATCH + NO, EXP + DATE)
                is_phrase_header = f_comb_space is not None and is_small_gap and (f_curr is None or f_nxt is None or f_curr == f_comb_space)
                
                # Case C: Single character / tiny fragment joining with kerning gap (e.g. P + A + CK, S + C + H, G + S + T)
                is_fragment_join = is_kerning_gap and (len(curr["text"]) <= 2 or len(nxt["text"]) <= 2) and (f_curr is None or f_nxt is None)

                if is_known_split or is_phrase_header or is_fragment_join:
                    if is_known_split or (is_fragment_join and f_comb_space is None):
                        curr["text"] = combined_no_space
                    else:
                        curr["text"] = combined_space
                    curr["x1"] = max(curr["x1"], nxt["x1"])
                    curr["bottom"] = max(curr["bottom"], nxt["bottom"])
                    curr["center_x"] = (curr["x0"] + curr["x1"]) / 2.0
                    curr["center_y"] = (curr["top"] + curr["bottom"]) / 2.0
                    i += 1
                else:
                    break
            merged.append(curr)
            i += 1
        reconstructed_lines.append(merged)
    return reconstructed_lines


# Common pharma header vocabulary for structural scoring
COMMON_HEADER_WORDS = {
    "sno", "s.no", "sr", "sr.no", "sn", "sl", "slno", "s", "item", "code", "mfg", "mfgby", "mfr", "make", "mfg.",
    "product", "productname", "description", "itemdescription", "particulars", "name",
    "pack", "packing", "pk", "pkg", "unit", "boxs", "case", "size",
    "hsn", "hsncode", "hsn/sac", "sac",
    "batch", "batchno", "batch.no", "lot", "b.no", "bno",
    "exp", "expiry", "exp.", "expdate", "e.x.p", "dt", "date",
    "mrp", "m.r.p", "m.r.p.", "ptr", "p.t.r", "p.t.r.", "pts", "p.t.s", "rate", "price", "unitprice", "pur.rate",
    "qty", "quantity", "billed", "free", "freeqty", "fr", "sch", "scheme", "f.qty", "b.qty",
    "disc", "disc%", "discount", "dis", "dis%", "sch%", "cd", "cd%", "td", "td%",
    "taxable", "taxableval", "taxablevalue", "taxableamt", "baseamt", "value",
    "gst", "gst%", "cgst", "cgst%", "sgst", "sgst%", "igst", "igst%", "tax", "tax%",
    "amount", "amt", "net", "netamt", "netamount", "total", "val", "gross", "old", "r.mar", "mktby", "rack", "dis"
}

METADATA_KEY_PATTERN = re.compile(
    r"(?i)\b(phone|ph|ph\.no|contact|email|dlno|dl|d\.l|d\.l\.no|lic|licence|license|foodlic|fssai|gstin|pan|irn|irnno|ack|ackno|ack\s*dt|cin|tan|invno|inv\s*no|invoice\s*no|inv\s*date|invoice\s*date|date|time|page|page\s*no|remby|repname|sales\s*man|sales\s*exec|salesman|route|veh|vehicle|order|po\s*no|cust|customer|buyer|consignee|patient|doctor|dr)\s*[:.]",
    re.UNICODE,
)
PAGE_NUMBER_PATTERN = re.compile(
    r"(?i)(\bpage\s*(no|no\.)?\s*[:.]?\s*\d+\s*(of|/)\s*\d+|\bpage\s*[:.]?\s*\d+|\b\d+\s*/\s*\d+\b)",
    re.UNICODE,
)
PHONE_PATTERN = re.compile(
    r"\b\d{10}\b|\b\d{3,5}[-\s]?\d{6,8}\b|\b\d{10}/\d{10}\b",
    re.UNICODE,
)
PROSE_ADDR_PATTERN = re.compile(
    r"(?i)\b(road|street|mandal|dist|floor|beside|near|opp|colony|nagar|bazar|market|complex|building|shop|pincode|state\s*code|state|telangana|andhra|hyderabad|mumbai|delhi|bangalore|chennai)\b",
    re.UNICODE,
)


def _is_likely_header_token(text: str, saved_template: dict = None) -> bool:
    """Checks if token matches common table header terminology or canonical aliases."""
    t_clean = re.sub(r"[^\w%./]", "", str(text).strip().lower())
    if t_clean in COMMON_HEADER_WORDS:
        return True
    if match_column_name(text, saved_template):
        return True
    return False


def _score_candidate_header_line(line: list, all_lines: list, line_idx: int, saved_template: dict = None) -> float:
    """
    Computes a generic structural score for a candidate table header line.
    Positive evidence: header vocabulary density, canonical diversity, column distribution, product row alignment.
    Negative evidence: key-value colon patterns, page numbers, phone numbers, prose address text.
    """
    if not line:
        return -100.0

    line_text = " ".join(w["text"] for w in line)
    total_tokens = len(line)

    header_tokens = [w for w in line if _is_likely_header_token(w["text"], saved_template)]
    mapped_fields = set(match_column_name(w["text"], saved_template) for w in line if match_column_name(w["text"], saved_template))
    unique_canonical = len(mapped_fields)

    meta_keys = len(METADATA_KEY_PATTERN.findall(line_text))
    has_page_num = 1 if PAGE_NUMBER_PATTERN.search(line_text) else 0
    has_phone = 1 if PHONE_PATTERN.search(line_text) else 0
    prose_matches = len(PROSE_ADDR_PATTERN.findall(line_text))
    colon_count = line_text.count(":")

    x_span = max(w["x1"] for w in line) - min(w["x0"] for w in line)

    # Alignment with subsequent product rows (look ahead 1 to 5 lines)
    subsequent_rows = all_lines[line_idx + 1 : line_idx + 6]
    row_alignment_score = 0.0
    if subsequent_rows:
        alignments = []
        for r in subsequent_rows:
            num_tokens = sum(1 for w in r if re.search(r"\d", w["text"]))
            if num_tokens >= 3:
                matched_cols = 0
                for hw in line:
                    h_center = hw["center_x"]
                    if any(abs(rw["center_x"] - h_center) <= 25.0 or (rw["x0"] <= h_center <= rw["x1"]) for rw in r):
                        matched_cols += 1
                alignments.append(matched_cols / max(1, len(line)))
        if alignments:
            row_alignment_score = max(alignments)

    score = 0.0
    score += len(header_tokens) * 10.0
    score += unique_canonical * 15.0
    if "itemName" in mapped_fields:
        score += 25.0
    if unique_canonical >= 5:
        score += 30.0
    if total_tokens >= 8:
        score += 15.0
    if x_span > 250:
        score += 10.0
    score += row_alignment_score * 30.0

    # Negative evidence penalties
    if colon_count >= 2:
        score -= colon_count * 15.0
    elif colon_count == 1:
        score -= 5.0
    if meta_keys > 0:
        score -= meta_keys * 30.0
    if has_page_num:
        score -= 35.0
    if has_phone:
        score -= 40.0
    if prose_matches >= 2:
        score -= prose_matches * 15.0

    header_ratio = len(header_tokens) / total_tokens if total_tokens > 0 else 0
    if header_ratio < 0.40 and total_tokens >= 4:
        score -= 25.0

    return score


def detect_coordinate_header_row(words, page_height: float, saved_template: dict = None):
    """
    Identifies the physical header row band using multi-evidence structural scoring,
    product row alignment, and strict invoice metadata isolation.
    """
    lines = reconstruct_header_tokens(words)
    if not lines:
        return None, None, None, 0.0

    scored_lines = []
    scan_limit_y = page_height * 0.65
    for idx, line in enumerate(lines):
        if not line or line[0]["top"] > scan_limit_y:
            continue
        score = _score_candidate_header_line(line, lines, idx, saved_template)
        if score > 20.0:
            scored_lines.append((score, idx, line))

    if not scored_lines:
        return None, None, None, 0.0

    scored_lines.sort(key=lambda x: x[0], reverse=True)
    best_score, best_idx, best_line = scored_lines[0]

    # Collect all lines within the cohesive vertical header band
    band_lines = [best_line]
    band_top = min(w["top"] for w in best_line)
    band_bottom = max(w["bottom"] for w in best_line)

    # Preceding line in header band: merge ONLY if structural header without metadata
    if best_idx > 0:
        prev_line = lines[best_idx - 1]
        if prev_line and abs(best_line[0]["top"] - prev_line[0]["bottom"]) <= 15.0:
            prev_text = " ".join(w["text"] for w in prev_line)
            prev_meta = (
                len(METADATA_KEY_PATTERN.findall(prev_text)) > 0
                or bool(PAGE_NUMBER_PATTERN.search(prev_text))
                or bool(PHONE_PATTERN.search(prev_text))
                or prev_text.count(":") >= 2
                or len(PROSE_ADDR_PATTERN.findall(prev_text)) >= 2
            )
            prev_hdrs = [w for w in prev_line if _is_likely_header_token(w["text"], saved_template)]
            if prev_hdrs and not prev_meta:
                band_lines.insert(0, prev_line)
                band_top = min(band_top, min(w["top"] for w in prev_line))

    # Succeeding line in header band: merge ONLY if structural subheader without product data
    if best_idx + 1 < len(lines):
        next_line = lines[best_idx + 1]
        if next_line and abs(next_line[0]["top"] - band_bottom) <= 15.0:
            next_text = " ".join(w["text"] for w in next_line)
            numeric_cells = sum(1 for w in next_line if re.search(r"^\d+(\.\d+)?$", w["text"].strip()))
            has_dates = any(re.search(r"\b\d{1,2}[/-]\d{2,4}\b", w["text"]) for w in next_line)
            is_data_row = (numeric_cells >= 3) or (numeric_cells >= 2 and has_dates)
            next_meta = (
                len(METADATA_KEY_PATTERN.findall(next_text)) > 0
                or bool(PAGE_NUMBER_PATTERN.search(next_text))
                or bool(PHONE_PATTERN.search(next_text))
                or next_text.count(":") >= 2
            )
            next_hdrs = [w for w in next_line if _is_likely_header_token(w["text"], saved_template)]
            if next_hdrs and not is_data_row and not next_meta:
                band_lines.append(next_line)
                band_bottom = max(band_bottom, max(w["bottom"] for w in next_line))

    all_band_words = []
    for l in band_lines:
        for w in l:
            w_text = w["text"].strip()
            if re.match(r"(?i)^(page\s*[:\d]|page\s*of|credit|sales\s*exec|udyam|gstin|email|phone|ph:|irnno:|remby:)$", w_text):
                continue
            all_band_words.append(w)
    all_band_words.sort(key=lambda w: w["x0"])

    # Cluster overlapping/vertical words into cohesive column headers
    header_clusters = []
    for w in all_band_words:
        f_w = match_column_name(w["text"], saved_template)
        placed = False
        for cl in header_clusters:
            cl_min_x = min(item["x0"] for item in cl)
            cl_max_x = max(item["x1"] for item in cl)
            cl_center = sum(item["center_x"] for item in cl) / len(cl)

            overlap = min(w["x1"], cl_max_x) - max(w["x0"], cl_min_x)
            is_vertically_aligned = abs(w["center_x"] - cl_center) <= 12.0 or (
                overlap > 0 and overlap >= 0.40 * min(w["x1"] - w["x0"], cl_max_x - cl_min_x)
            )

            cl_fields = [match_column_name(item["text"], saved_template) for item in cl]
            cl_valid_fields = [f for f in cl_fields if f]
            comb_text = " ".join([item["text"] for item in cl] + [w["text"]])
            f_comb = match_column_name(comb_text, saved_template)

            can_merge = False
            if is_vertically_aligned:
                if not cl_valid_fields or not f_w or f_w in cl_valid_fields or f_comb:
                    can_merge = True

            if can_merge:
                cl.append(w)
                placed = True
                break

        if not placed:
            header_clusters.append([w])

    header_tokens = []
    for cl in header_clusters:
        cl.sort(key=lambda item: item["top"])
        combined_text = " ".join(item["text"] for item in cl).strip()
        field = match_column_name(combined_text, saved_template)
        if not field:
            for item in cl:
                f_item = match_column_name(item["text"], saved_template)
                if f_item:
                    field = f_item
                    break

        x0 = min(item["x0"] for item in cl)
        x1 = max(item["x1"] for item in cl)
        top = min(item["top"] for item in cl)
        bottom = max(item["bottom"] for item in cl)
        center_x = (x0 + x1) / 2.0

        header_tokens.append({
            "raw": combined_text,
            "text": combined_text,
            "field": field,
            "x0": x0,
            "x1": x1,
            "center_x": center_x,
            "top": top,
            "bottom": bottom,
        })

    header_tokens.sort(key=lambda h: h["center_x"])
    header_top = band_top
    header_bottom = band_bottom
    conf = min(1.0, best_score / 120.0)
    return header_tokens, header_top, header_bottom, conf


def determine_column_boundaries(
    header_tokens,
    page_width: float,
    table_bbox=None,
    body_words=None,
    page_lines=None,
    page_rects=None,
):
    """
    Computes adaptive physical column boundaries [x0, x1] for each reconstructed header.
    Uses multi-signal evidence: vertical ruling lines, whitespace valleys between body words,
    header bounding boxes, and header centers.
    Dynamically discovers unnamed columns when body word clusters exist beyond headers.
    Enforces strict monotonic ordering to prevent column collapse.
    """
    if not header_tokens:
        return []

    sorted_headers = sorted(header_tokens, key=lambda h: h["center_x"])
    left_bound = table_bbox[0] if table_bbox else 10.0
    right_bound = table_bbox[2] if table_bbox else page_width - 10.0

    n = len(sorted_headers)
    cut_points = [0.0] * (n + 1)

    # Vertical ruling lines from page that span the body table region
    ruling_x = []
    body_min_top = min((w["top"] for w in body_words), default=0.0) if body_words else 0.0
    body_max_bot = max((w["bottom"] for w in body_words), default=page_width) if body_words else page_width

    if page_lines:
        for l in page_lines:
            if abs(l.get("x0", 0) - l.get("x1", 0)) < 1.0:  # vertical line
                length = abs(l.get("bottom", 0) - l.get("top", 0))
                l_top = l.get("top", 0)
                l_bot = l.get("bottom", 0)
                if length > 20.0 and l_top <= body_min_top + 30.0 and l_bot >= body_min_top + 10.0:
                    ruling_x.append((l["x0"] + l["x1"]) / 2.0)
    if page_rects:
        for r in page_rects:
            if r.get("height", 0) > 20.0 and r.get("width", 0) > 10.0:
                r_top = r.get("top", r.get("y0", 0))
                r_bot = r.get("bottom", r.get("y1", 0))
                if r_top <= body_min_top + 30.0 and r_bot >= body_min_top + 10.0:
                    ruling_x.append(r["x0"])
                    ruling_x.append(r["x1"])

    # Leftmost cut (cut_0)
    left_words = [w for w in body_words if w.get("center_x", (w.get("x0", 0) + w.get("x1", 0)) / 2.0) <= sorted_headers[0]["center_x"] + 10.0] if body_words else []
    cand_left = min([sorted_headers[0]["x0"]] + [w["x0"] for w in left_words]) - COORD_COL_BOUNDARY_MARGIN if left_words else sorted_headers[0]["x0"] - COORD_COL_BOUNDARY_MARGIN
    cut_points[0] = max(0.0, min(left_bound, cand_left))

    # Rightmost cut (cut_n)
    right_words = [w for w in body_words if w.get("center_x", (w.get("x0", 0) + w.get("x1", 0)) / 2.0) >= sorted_headers[-1]["center_x"] - 10.0] if body_words else []
    cand_right = max([sorted_headers[-1]["x1"]] + [w["x1"] for w in right_words]) + COORD_COL_BOUNDARY_MARGIN if right_words else sorted_headers[-1]["x1"] + COORD_COL_BOUNDARY_MARGIN
    cut_points[n] = min(page_width, max(right_bound, cand_right))

    # Intermediate cuts: find the best candidate boundary between adjacent headers
    for i in range(n - 1):
        h_left = sorted_headers[i]
        h_right = sorted_headers[i + 1]

        # Valid range for cut point.
        # Numeric body values are often right-aligned and sit LEFT of the header
        # glyph box. Restricting cuts to [h_left.x1, h_right.x0] therefore excludes
        # the true whitespace valley (PHUB AMOUNT/Disc/GST). Allow the band between
        # header centers so repeated-row body gaps can win.
        is_left_product = (
            h_left.get("field") == "itemName"
            or match_column_name(h_left.get("text") or h_left.get("raw") or "") == "itemName"
        )
        left_field = h_left.get("field") or match_column_name(
            h_left.get("text") or h_left.get("raw") or ""
        )
        right_field = h_right.get("field") or match_column_name(
            h_right.get("text") or h_right.get("raw") or ""
        )
        numeric_pair = left_field in {
            "rate", "mrp", "amount", "taxableAmount", "netAmount",
            "quantity", "freeQuantity", "discountPercent", "gstPercent", "hsnCode",
        } and right_field in {
            "rate", "mrp", "amount", "taxableAmount", "netAmount",
            "quantity", "freeQuantity", "discountPercent", "gstPercent", "hsnCode",
        }

        if h_left["x1"] < h_right["x0"]:
            if numeric_pair:
                min_allowed_cut = min(h_left["center_x"] + 1.0, h_left["x1"] - 1.0)
                max_allowed_cut = max(h_right["center_x"] - 1.0, h_right["x0"] + 1.0)
                if min_allowed_cut > max_allowed_cut:
                    min_allowed_cut = h_left["center_x"] + 1.0
                    max_allowed_cut = h_right["center_x"] - 1.0
            else:
                min_allowed_cut = max(h_left["x1"] - 2.0, h_left["center_x"] + 2.0)
                max_allowed_cut = min(h_right["x0"] + 2.0, h_right["center_x"] - 2.0)
            if is_left_product:
                default_cut = max(min_allowed_cut, h_right["x0"] - 4.0)
            else:
                default_cut = (h_left["x1"] + h_right["x0"]) / 2.0
        else:
            min_allowed_cut = h_left["center_x"] + 2.0
            max_allowed_cut = h_right["center_x"] - 2.0
            default_cut = (h_left["center_x"] + h_right["center_x"]) / 2.0

        if min_allowed_cut >= max_allowed_cut:
            min_allowed_cut = min(h_left["center_x"], h_left["x1"])
            max_allowed_cut = max(h_right["center_x"], h_right["x0"])
            default_cut = (min_allowed_cut + max_allowed_cut) / 2.0

        default_cut = max(min_allowed_cut, min(max_allowed_cut, default_cut))
        candidates = [(default_cut, 10.0)]  # (cut_x, score)

        # Signal 1: Vertical ruling lines
        for rx in ruling_x:
            if min_allowed_cut <= rx <= max_allowed_cut:
                candidates.append((rx, 50.0))

        # Signal 2: Whitespace valleys between body words
        if body_words:
            ws_min = max(min_allowed_cut, h_right["x0"] - 25.0) if is_left_product else min_allowed_cut
            region_words = [
                w for w in body_words
                if w["x1"] >= ws_min - 3.0 and w["x0"] <= max_allowed_cut + 3.0
            ]
            if len(region_words) >= 2:
                intervals = sorted(
                    [(w["x0"], w["x1"]) for w in region_words], key=lambda x: x[0]
                )
                merged = []
                for iv in intervals:
                    if not merged or iv[0] > merged[-1][1]:
                        merged.append(list(iv))
                    else:
                        merged[-1][1] = max(merged[-1][1], iv[1])

                for j in range(len(merged) - 1):
                    gap_start = merged[j][1]
                    gap_end = merged[j + 1][0]
                    gap_width = gap_end - gap_start
                    if gap_width >= 1.0:
                        mid = (gap_start + gap_end) / 2.0
                        if ws_min <= mid <= max_allowed_cut:
                            dist = abs(mid - default_cut)
                            # Prefer body valleys more strongly for narrow numeric pairs
                            # (AMOUNT/Disc/GST) where header-midpoint cuts are unreliable.
                            base = 40.0 if numeric_pair else 25.0
                            score = base + min(25.0, gap_width * 3.0) - dist * 0.1
                            candidates.append((mid, score))

            # Signal 3: Repeated-row left/right clusters near the two header centers.
            # Place cut in the median gap between the left-header cluster and the
            # right-header cluster so missing values stay empty and values do not bleed.
            if numeric_pair:
                row_gaps = []
                # Approximate rows by y-tolerance banding
                y_tol = 3.0
                bands = {}
                for w in body_words:
                    key = round(w["top"] / y_tol) * y_tol
                    bands.setdefault(key, []).append(w)
                for band_words in bands.values():
                    left_cluster = [
                        w for w in band_words
                        if abs(w.get("center_x", (w["x0"] + w["x1"]) / 2.0) - h_left["center_x"])
                        <= abs(w.get("center_x", (w["x0"] + w["x1"]) / 2.0) - h_right["center_x"])
                        and w["x0"] < h_right["center_x"]
                    ]
                    right_cluster = [
                        w for w in band_words
                        if abs(w.get("center_x", (w["x0"] + w["x1"]) / 2.0) - h_right["center_x"])
                        < abs(w.get("center_x", (w["x0"] + w["x1"]) / 2.0) - h_left["center_x"])
                        and w["x1"] > h_left["center_x"]
                    ]
                    if not left_cluster or not right_cluster:
                        continue
                    gap_start = max(w["x1"] for w in left_cluster)
                    gap_end = min(w["x0"] for w in right_cluster)
                    if gap_end - gap_start >= 1.0:
                        mid = (gap_start + gap_end) / 2.0
                        if min_allowed_cut <= mid <= max_allowed_cut:
                            row_gaps.append(mid)
                if len(row_gaps) >= 3:
                    row_gaps.sort()
                    median_cut = row_gaps[len(row_gaps) // 2]
                    # High confidence: consistent across many product rows
                    candidates.append((median_cut, 55.0 + min(15.0, len(row_gaps))))

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

    # Discover unnamed physical columns beyond the rightmost header
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
    Considers interval overlap, center containment, center proximity, and semantic type affinity.
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

    is_numeric = bool(re.match(r"^[-+]?\d+(\.\d+)?%?$", w_text))
    is_date = bool(re.match(r"^\d{1,2}[/\-\.]\d{2,4}$", w_text))
    is_pure_alpha = bool(re.match(r"^[A-Za-z\s\(\)\/\-\+]+$", w_text) and not is_numeric)

    score = overlap_ratio * 60.0
    if center_contained:
        score += 30.0
    score -= center_dist * 0.15

    # Near-boundary numeric tokens: strengthen header-center attraction so values
    # that slightly overhang a wrong wide neighbor still prefer the nearer column.
    if is_numeric and not center_contained and center_dist < 40.0:
        score += max(0.0, 12.0 - center_dist * 0.25)

    # 3. Type Affinity / Protection
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


def assign_tokens_to_columns(group: list, columns: list, debug: bool = False) -> tuple:
    """
    Assigns row word tokens to columns using interval overlap, center proximity, and type affinity.
    Returns (cell_words_dict, diagnostics_list).
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
        if debug or is_ambiguous:
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


def get_token_column_assignment_diagnostics(page_words: list, columns: list, assigned_rows: list = None) -> list:
    """
    Diagnostic helper for Section 24: returns structured token-to-column assignment evidence.
    """
    diagnostics = []
    for w in page_words:
        col_scores = []
        for col_i, col in enumerate(columns):
            s = score_token_column_assignment(w, col)
            col_scores.append((col_i, col["header_text"], col.get("field"), s))
        col_scores.sort(key=lambda x: x[3], reverse=True)
        best_col_idx, best_hdr, best_fld, best_score = col_scores[0]
        second_hdr = col_scores[1][1] if len(col_scores) > 1 else None
        second_score = col_scores[1][3] if len(col_scores) > 1 else -1e9
        is_amb = (best_score - second_score < 8.0) and (best_score > 10.0)

        diagnostics.append({
            "token": w.get("text", ""),
            "x0": round(w.get("x0", 0.0), 2),
            "x1": round(w.get("x1", 0.0), 2),
            "center_x": round(w.get("center_x", 0.0), 2),
            "width": round(w.get("width", w.get("x1", 0.0) - w.get("x0", 0.0)), 2),
            "assigned_column": best_hdr,
            "assigned_field": best_fld,
            "assignment_score": round(best_score, 2),
            "competing_column": second_hdr,
            "competing_score": round(second_score, 2),
            "is_ambiguous": is_amb,
            "boundary_distance": round(min(abs(w.get("center_x", 0) - columns[best_col_idx]["x0"]), abs(w.get("center_x", 0) - columns[best_col_idx]["x1"])), 2),
        })
    return diagnostics



def detect_logical_subcolumns(physical_columns: list, row_groups: list, saved_template: dict = None, debug: bool = False):
    """
    Reconstructs logical sub-columns within physical extraction columns.
    Uses horizontal word-coordinate clustering across rows, header token alignment,
    cross-row consistency, and semantic pattern diversity.
    
    Returns: (logical_columns, split_diagnostics)
    """
    if not physical_columns or not row_groups:
        return physical_columns, {}

    logical_columns = []
    split_diagnostics = {}
    next_logical_idx = 0

    for phys_col in physical_columns:
        p_idx = phys_col["index"]
        p_x0 = phys_col["x0"]
        p_x1 = phys_col["x1"]
        p_header = str(phys_col.get("header_text", "")).strip()
        p_field = phys_col.get("field") or match_column_name(p_header, saved_template)

        # 1. Product Name / Item Description column naturally contains multi-word strings -> Never split
        if p_field == "itemName":
            logical_columns.append({
                "physical_column_index": p_idx,
                "logical_index": next_logical_idx,
                "header_raw": phys_col["header_raw"],
                "header_text": phys_col["header_text"],
                "field": "itemName",
                "x0": p_x0,
                "x1": p_x1,
                "center_x": phys_col.get("center_x", (p_x0 + p_x1) / 2.0),
                "provenance": "direct_physical_column",
                "split_confidence": None,
                "split_evidence": [],
                "status": "clean",
            })
            next_logical_idx += 1
            continue

        raw_header_tokens = [t.strip() for t in re.split(r"[\s+/&]+", str(p_header)) if t.strip()]
        if not raw_header_tokens:
            raw_header_tokens = [p_header]
        num_header_tokens = len(raw_header_tokens)

        # Check if header tokens belong to the SAME single canonical field (e.g. BATCH NO, EXP DATE, NET AMOUNT)
        token_fields = [match_column_name(tok, saved_template) for tok in raw_header_tokens]
        valid_token_fields = [f for f in token_fields if f]
        unique_token_fields = set(valid_token_fields)

        # If header is a known single-field multi-word phrase, do not split
        is_single_field_phrase = (p_field is not None and len(unique_token_fields) <= 1 and num_header_tokens > 1 and len(p_header.split()) > 1)

        # Collect words for this physical column across all product rows
        row_words = []
        for g in row_groups:
            words_in_col = [w for w in g if (p_x0 <= w["center_x"] < p_x1) or (p_x0 <= (w["x0"]+w["x1"])/2.0 <= p_x1)]
            row_words.append(words_in_col)

        non_empty_rows = [w_list for w_list in row_words if w_list]
        multi_word_rows = [w_list for w_list in row_words if len(w_list) >= 2]
        multi_ratio = len(multi_word_rows) / max(1, len(non_empty_rows))

        # Distinct multi-field header check (e.g. PACK QTY FREE or AMOUNT GST)
        has_multi_field_header = len(unique_token_fields) >= 2

        # Candidate check
        is_candidate = (has_multi_field_header and len(multi_word_rows) >= 1) or (
            not is_single_field_phrase and multi_ratio >= 0.50 and len(multi_word_rows) >= 3
        )

        best_split = None
        best_conf = 0.0
        best_evidence = []

        if is_candidate:
            all_xs = [w["center_x"] for w_list in non_empty_rows for w in w_list]
            if len(all_xs) >= 4:
                # Test k = 2 and k = 3 clusters
                for k in [2, 3]:
                    if num_header_tokens >= 2 and num_header_tokens != k and not has_multi_field_header:
                        continue
                    
                    # 1D Quantile-based initial centroids
                    sorted_xs = sorted(all_xs)
                    n = len(sorted_xs)
                    initial_centroids = [sorted_xs[int(n * (2 * j + 1) / (2 * k))] for j in range(k)]
                    
                    # K-means iterations
                    centroids = list(initial_centroids)
                    for _ in range(10):
                        clusters = {j: [] for j in range(k)}
                        for x in sorted_xs:
                            best_j = min(range(k), key=lambda j: abs(x - centroids[j]))
                            clusters[best_j].append(x)
                        new_centroids = [
                            sum(clusters[j]) / len(clusters[j]) if clusters[j] else centroids[j]
                            for j in range(k)
                        ]
                        if all(abs(new_centroids[j] - centroids[j]) < 0.1 for j in range(k)):
                            break
                        centroids = new_centroids

                    # Check separation and cluster quality
                    min_gap = min(centroids[j+1] - centroids[j] for j in range(k-1)) if k > 1 else 0.0
                    std_devs = [
                        (sum((x - centroids[j])**2 for x in clusters[j]) / max(1, len(clusters[j])))**0.5
                        if clusters[j] else 999.0
                        for j in range(k)
                    ]
                    max_std = max(std_devs)

                    # Row coverage: fraction of non-empty rows having a word near each centroid
                    covered_rows = {j: 0 for j in range(k)}
                    for w_list in non_empty_rows:
                        row_xs = [w["center_x"] for w_list_item in w_list for w in [w_list_item]]
                        for j in range(k):
                            if any(abs(rx - centroids[j]) <= max(12.0, min_gap * 0.40) for rx in row_xs):
                                covered_rows[j] += 1
                    min_coverage = min(covered_rows[j] / max(1, len(non_empty_rows)) for j in range(k))

                    # Value type analysis per cluster
                    cluster_samples = {j: [] for j in range(k)}
                    for w_list in non_empty_rows:
                        for w in w_list:
                            best_j = min(range(k), key=lambda j: abs(w["center_x"] - centroids[j]))
                            if len(cluster_samples[best_j]) < 5:
                                cluster_samples[best_j].append(w["text"])

                    # Deterministic split confidence scoring
                    h_score = 0.40 if has_multi_field_header else (0.15 if num_header_tokens == k else 0.0)
                    sep_score = 0.25 if (min_gap >= 12.0 and max_std <= 8.0) else (0.15 if min_gap >= 8.0 else 0.0)
                    cov_score = 0.25 if min_coverage >= 0.60 else (0.15 if min_coverage >= 0.40 else 0.0)
                    
                    # Pattern distinctiveness
                    types = []
                    for j in range(k):
                        vals = cluster_samples[j]
                        has_digits = any(re.search(r"\d", v) for v in vals)
                        has_pct = any("%" in v for v in vals)
                        has_pack = any(re.search(r"(tab|cap|amp|vial|syr|\*|'s)", v, re.I) for v in vals)
                        has_date = any(re.search(r"\d{1,2}[/-]\d{2,4}", v) for v in vals)
                        types.append((has_digits, has_pct, has_pack, has_date))
                    type_score = 0.15 if len(set(types)) >= 2 else 0.05

                    total_conf = h_score + sep_score + cov_score + type_score
                    if total_conf > best_conf:
                        best_conf = total_conf
                        best_split = (k, centroids, clusters, min_gap, max_std, min_coverage, cluster_samples)
                        best_evidence = [
                            f"Header multi-fields={has_multi_field_header} (score={h_score:.2f})",
                            f"Centroid gap={min_gap:.1f}pt, max_std={max_std:.1f}pt (score={sep_score:.2f})",
                            f"Row coverage={min_coverage:.0%} (score={cov_score:.2f})",
                            f"Value pattern diversity (score={type_score:.2f})",
                        ]

        # Decision: Split if confidence >= 0.65
        if best_split and best_conf >= 0.65 and not is_single_field_phrase:
            k, centroids, clusters, min_gap, max_std, min_coverage, cluster_samples = best_split
            split_diagnostics[p_header] = {
                "status": "split",
                "confidence": round(best_conf, 2),
                "clusters": k,
                "evidence": best_evidence,
            }

            for j in range(k):
                sub_x0 = p_x0 if j == 0 else (centroids[j-1] + centroids[j]) / 2.0
                sub_x1 = p_x1 if j == k - 1 else (centroids[j] + centroids[j+1]) / 2.0
                sub_h = raw_header_tokens[j] if (num_header_tokens == k) else f"{p_header}_{j+1}"
                sub_field = match_column_name(sub_h, saved_template)

                logical_columns.append({
                    "physical_column_index": p_idx,
                    "logical_index": next_logical_idx,
                    "header_raw": sub_h,
                    "header_text": sub_h,
                    "field": sub_field,
                    "x0": sub_x0,
                    "x1": sub_x1,
                    "center_x": centroids[j],
                    "provenance": "split_from_physical_column",
                    "split_confidence": round(best_conf, 2),
                    "split_evidence": best_evidence,
                    "status": "split",
                })
                next_logical_idx += 1
        else:
            status = "ambiguous" if (is_candidate and best_conf >= 0.40 and len(multi_word_rows) >= 2) else "clean"
            if is_candidate:
                split_diagnostics[p_header] = {
                    "status": status,
                    "confidence": round(best_conf, 2),
                    "evidence": best_evidence or ["Split confidence below threshold (0.65)"],
                }

            logical_columns.append({
                "physical_column_index": p_idx,
                "logical_index": next_logical_idx,
                "header_raw": phys_col.get("header_raw", phys_col.get("header_text", "")),
                "header_text": phys_col.get("header_text", phys_col.get("header_raw", "")),
                "field": p_field,
                "x0": p_x0,
                "x1": p_x1,
                "center_x": phys_col.get("center_x", (p_x0 + p_x1) / 2.0),
                "provenance": "direct_physical_column",
                "split_confidence": round(best_conf, 2) if is_candidate else None,
                "split_evidence": best_evidence if is_candidate else [],
                "status": status,
            })
            next_logical_idx += 1

    return logical_columns, split_diagnostics


def split_text_multi_value_columns(headers: list, rows: list, saved_template: dict = None, debug: bool = False):
    """
    Fallback text-based sub-column reconstruction for non-coordinate extractions.
    Detects when a physical text column contains multiple logical fields and splits it.
    """
    if not headers or not rows:
        return headers, rows, {}

    new_headers = []
    col_splits = {}
    split_diagnostics = {}

    for col_i, h in enumerate(headers):
        h_str = str(h).strip()
        h_tokens = h_str.split()
        col_vals = [row[col_i] if col_i < len(row) else "" for row in rows]
        non_empty = [v for v in col_vals if v and str(v).strip()]

        # Check candidate split across rows
        best_k = None
        if len(h_tokens) in (2, 3):
            k = len(h_tokens)
            split_matches = 0
            for v in non_empty:
                v_toks = str(v).strip().split()
                if len(v_toks) == k:
                    split_matches += 1
            if len(non_empty) >= 2 and (split_matches / len(non_empty)) >= 0.60:
                best_k = k

        if best_k:
            col_splits[col_i] = (best_k, h_tokens)
            split_diagnostics[h_str] = {
                "status": "split",
                "confidence": 0.90,
                "clusters": best_k,
                "evidence": [f"Text tokens ({best_k}) match header words ({' | '.join(h_tokens)}) across rows"],
            }
            for tok in h_tokens:
                new_headers.append(tok)
        else:
            col_splits[col_i] = (1, [h_str])
            new_headers.append(h_str)

    # Reconstruct rows with split cells
    new_rows = []
    for row in rows:
        new_row = []
        for col_i, (k, h_toks) in col_splits.items():
            val = row[col_i] if col_i < len(row) else ""
            if k > 1:
                v_toks = str(val).strip().split()
                if len(v_toks) == k:
                    new_row.extend(v_toks)
                elif len(v_toks) < k:
                    new_row.extend(v_toks + [""] * (k - len(v_toks)))
                else:
                    # More tokens than k: combine head and tail
                    new_row.extend(v_toks[:k-1] + [" ".join(v_toks[k-1:])])
            else:
                new_row.append(val)
        new_rows.append(new_row)

    return new_headers, new_rows, split_diagnostics


def extract_coordinate_table(page, saved_template=None, expected_cols=None, debug: bool = False):
    """
    Extracts line items from a page using physical bounding-box word coordinates.
    Reconstructs logical sub-columns dynamically from physical columns.
    Returns: (headers, genuine_rows, confidence, debug_dict)
    """
    words = extract_page_words(page)
    if not words:
        return [], [], 0.0, {}

    page_width = float(page.width or 612.0)
    page_height = float(page.height or 792.0)

    tables = page.find_tables()
    table_bbox = tables[0].bbox if tables else None

    header_tokens, header_top, header_bottom, header_conf = detect_coordinate_header_row(
        words, page_height, saved_template=saved_template
    )
    if not header_tokens or header_conf < 0.40:
        return [], [], 0.0, {}

    # Body words filtering
    body_words = [w for w in words if w["top"] >= header_bottom + 1.0]

    footer_top = page_height
    for w in body_words:
        lowered = w["text"].lower()
        if any(fw in lowered for fw in ["bank", "terms", "condition", "signatory", "authorised", "authorized", "subtotal", "sub-total", "continue", "continued", "contd", "outstanding", "declaration"]):
            if w["top"] < footer_top and w["top"] > header_bottom + 30.0:
                footer_top = min(footer_top, w["top"])

    body_words = [w for w in body_words if w["bottom"] <= footer_top + 2.0]

    page_lines = getattr(page, "lines", None) if page else None
    page_rects = getattr(page, "rects", None) if page else None

    physical_columns = determine_column_boundaries(
        header_tokens,
        page_width,
        table_bbox=table_bbox,
        body_words=body_words,
        page_lines=page_lines,
        page_rects=page_rects,
    )

    # Group words into line-item rows by Y coordinate
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

    # Reconstruct Logical Sub-Columns from Physical Columns
    logical_columns, split_diag = detect_logical_subcolumns(
        physical_columns, row_groups, saved_template=saved_template, debug=debug
    )

    headers = [c["header_text"] for c in logical_columns]
    item_idx = None
    for i, c in enumerate(logical_columns):
        if c.get("field") == "itemName" or match_column_name(c["header_text"], saved_template) == "itemName":
            item_idx = i
            break

    raw_rows = []
    row_records = []
    all_diagnostics = []
    total_ambiguous_tokens = 0

    for g_idx, group in enumerate(row_groups):
        cell_words, row_diag = assign_tokens_to_columns(group, logical_columns, debug=debug)
        all_diagnostics.extend(row_diag)
        row_cells = [""] * len(logical_columns)

        for col_i, words_in_col in cell_words.items():
            if words_in_col:
                words_in_col.sort(key=lambda x: x["x0"])
                row_cells[col_i] = " ".join(w["text"] for w in words_in_col).strip()

        if any(d.get("is_ambiguous") for d in row_diag):
            total_ambiguous_tokens += sum(1 for d in row_diag if d.get("is_ambiguous"))

        if _is_footer_row(row_cells) or _is_letterhead_row(row_cells):
            continue

        raw_rows.append(row_cells)
        row_records.append({
            "row_index": g_idx,
            "cells": {
                logical_columns[i]["header_text"]: {
                    "text": row_cells[i],
                    "words": cell_words[i],
                    "confidence": "HIGH" if cell_words[i] else "EMPTY",
                }
                for i in range(len(logical_columns))
            },
            "top": min(w["top"] for w in group) if group else 0.0,
            "bottom": max(w["bottom"] for w in group) if group else 0.0,
        })

    merged_rows = _merge_continuation_rows(raw_rows, item_idx=item_idx)
    genuine_rows = [r for r in merged_rows if _is_genuine_product_row(r, item_idx=item_idx)]

    ambiguity_penalty = min(0.15, total_ambiguous_tokens * 0.02)
    conf = header_conf * (1.0 if len(genuine_rows) >= 2 else (0.85 if len(genuine_rows) == 1 else 0.0)) - ambiguity_penalty
    conf = min(1.0, max(0.0, conf))

    debug_info = {
        "header_top": header_top,
        "header_bottom": header_bottom,
        "physical_columns": physical_columns,
        "logical_columns": logical_columns,
        "split_diagnostics": split_diag,
        "token_assignment_diagnostics": all_diagnostics,
        "row_records": row_records,
        "raw_rows_count": len(raw_rows),
        "genuine_rows_count": len(genuine_rows),
        "confidence": conf,
    } if debug else {}

    return headers, genuine_rows, conf, debug_info


def repair_row_accounting(row: list, headers: list, column_mappings: dict) -> list:
    """
    Closed-Form Accounting Constraint Solver:
    Validates and repairs row-level commercial values using pharma accounting invariants:
    - Amount = Qty * Rate
    - Taxable = Amount * (1 - Disc% / 100)
    - Net = Taxable * (1 + GST% / 100)
    If OCR misreads or misses one numeric field, solves the equation to restore precision.
    """
    if not row or not headers:
        return row

    field_indices = {}
    for h, info in column_mappings.items():
        m = info.get("mapped_to") if isinstance(info, dict) else info
        if m and h in headers:
            field_indices[m] = headers.index(h)

    q_idx = field_indices.get("quantity")
    r_idx = field_indices.get("rate")
    a_idx = field_indices.get("amount")
    d_idx = field_indices.get("discountPercent")
    t_idx = field_indices.get("taxableAmount")
    g_idx = field_indices.get("gstPercent")
    n_idx = field_indices.get("netAmount")

    row_copy = list(row)
    
    q = _to_float(row_copy[q_idx]) if (q_idx is not None and q_idx < len(row_copy)) else None
    r = _to_float(row_copy[r_idx]) if (r_idx is not None and r_idx < len(row_copy)) else None
    a = _to_float(row_copy[a_idx]) if (a_idx is not None and a_idx < len(row_copy)) else None
    d = _to_float(row_copy[d_idx]) if (d_idx is not None and d_idx < len(row_copy)) else 0.0
    t = _to_float(row_copy[t_idx]) if (t_idx is not None and t_idx < len(row_copy)) else None
    g = _to_float(row_copy[g_idx]) if (g_idx is not None and g_idx < len(row_copy)) else 0.0
    n = _to_float(row_copy[n_idx]) if (n_idx is not None and n_idx < len(row_copy)) else None

    # 1. Gross Amount (Qty * Rate)
    if (a is None or a <= 0) and q and r and q > 0 and r > 0:
        a = round(q * r, 2)
        if a_idx is not None and a_idx < len(row_copy):
            row_copy[a_idx] = f"{a:.2f}"
    elif (r is None or r <= 0) and q and a and q > 0 and a > 0:
        r = round(a / q, 2)
        if r_idx is not None and r_idx < len(row_copy):
            row_copy[r_idx] = f"{r:.2f}"

    # 2. Taxable Amount (Amount - Discount)
    if d is None:
        d = 0.0
    if (t is None or t <= 0) and a is not None and a > 0:
        t = round(a * (1.0 - d / 100.0), 2)
        if t_idx is not None and t_idx < len(row_copy):
            row_copy[t_idx] = f"{t:.2f}"
    elif (d == 0.0 or d is None) and a and t and a > t > 0:
        d = round(((a - t) / a) * 100.0, 2)
        if d_idx is not None and d_idx < len(row_copy):
            row_copy[d_idx] = f"{d:.2f}"

    # 3. Net Amount (Taxable + GST)
    if g is None:
        g = 0.0
    if (n is None or n <= 0) and t is not None and t > 0:
        n = round(t * (1.0 + g / 100.0), 2)
        if n_idx is not None and n_idx < len(row_copy):
            row_copy[n_idx] = f"{n:.2f}"

    return row_copy


def extract_image_or_scanned_table(file_input, saved_template: dict = None, debug: bool = False):
    """
    Extracts line-item table from image files or scanned PDFs using OCR spatial line reconstruction.
    """
    if ocr_engine is None:
        return {}, [], {}, []

    metadata = extract_invoice_metadata(file_input)
    
    images = []
    is_image = False
    if isinstance(file_input, (str, bytes, os.PathLike)):
        str_p = str(file_input).lower()
        if str_p.endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp")):
            try:
                images = [ocr_engine.load_image_to_pil(file_input)]
                is_image = True
            except Exception:
                pass

    if not is_image:
        try:
            images = ocr_engine.render_pdf_to_images(file_input)
        except Exception as e:
            logger.warning(f"Failed to render scanned PDF pages: {e}")
            return metadata, [], {}, []

    headers = []
    all_rows = []
    
    for img in images:
        try:
            ocr_df = ocr_engine.extract_ocr_dataframe_from_image(img)
            lines = ocr_engine.reconstruct_lines_from_ocr(ocr_df)
            
            for line_tokens in lines:
                if not line_tokens or len(line_tokens) < 3:
                    continue
                # Check if this line is header row
                if not headers and _is_valid_header_row(line_tokens, saved_template):
                    headers = line_tokens
                    continue
                
                if headers:
                    if len(line_tokens) < len(headers):
                        row_cells = line_tokens + [""] * (len(headers) - len(line_tokens))
                    else:
                        row_cells = line_tokens[:len(headers)]
                    
                    if _is_footer_row(row_cells) or _is_letterhead_row(row_cells):
                        continue
                    if _is_genuine_product_row(row_cells):
                        all_rows.append(row_cells)
        except Exception as e:
            logger.warning(f"Error extracting table from image page: {e}")

    column_mappings = infer_unresolved_column_semantics(
        headers,
        all_rows,
        columns_coord_info=None,
        saved_template=saved_template,
        debug=debug,
    )
    
    # Repair accounting across all extracted rows
    all_rows = [repair_row_accounting(r, headers, column_mappings) for r in all_rows]

    validation_results = compute_global_validation_and_confidence(
        headers,
        None,
        column_mappings,
        all_rows,
        saved_template=saved_template,
        metadata=metadata,
    )
    column_mappings = validation_results["resolved_mappings"]
    metadata["validation"] = validation_results
    metadata["confidence"] = validation_results["document_confidence"]
    metadata["classification"] = validation_results["classification"]
    
    return metadata, headers, column_mappings, all_rows


def extract_pdf_table(pdf_file, saved_template: dict = None, use_coordinates: bool = True, debug: bool = False):
    """
    Extract line-item tables from every page of an invoice PDF or Image.

    Coordinates-First Pipeline:
    - Checks for image files or scanned PDFs and routes to OCR if detected.
    - Runs coordinate-aware word extraction on each page.
    - If coordinate extraction finds clear headers and product rows (conf >= 0.50), uses it.
    - Otherwise gracefully falls back to multi-pass pdfplumber table extraction.
    - Automatically repairs row accounting with closed-form constraint solver.
    """
    is_image = False
    if isinstance(pdf_file, (str, bytes, os.PathLike)):
        str_p = str(pdf_file).lower()
        if str_p.endswith((".png", ".jpg", ".jpeg", ".tiff", ".bmp")):
            is_image = True

    if is_image:
        return extract_image_or_scanned_table(pdf_file, saved_template=saved_template, debug=debug)

    metadata = extract_invoice_metadata(pdf_file)

    headers = []
    all_rows = []
    column_mappings = {}
    expected_cols = None
    item_idx = None
    columns_coord_info = None

    if hasattr(pdf_file, "seek"):
        pdf_file.seek(0)

    try:
        pdf_ctx = pdfplumber.open(pdf_file)
    except Exception:
        # Fallback to OCR for non-standard or image formats
        return extract_image_or_scanned_table(pdf_file, saved_template=saved_template, debug=debug)

    with pdf_ctx as pdf:
        if not pdf.pages:
            return metadata, [], {}, []


        for page_idx, page in enumerate(pdf.pages):
            used_coordinates = False

            # --- 1. Try Coordinate-Aware Extraction ---
            if use_coordinates:
                c_hdrs, c_rows, c_conf, c_dbg = extract_coordinate_table(
                    page,
                    saved_template=saved_template,
                    expected_cols=expected_cols,
                    debug=True,
                )
                if c_conf >= COORD_MIN_CONFIDENCE and c_rows:
                    if expected_cols is None and page_idx == 0:
                        headers = ensure_named_headers(c_hdrs)
                        expected_cols = len(headers)
                        columns_coord_info = c_dbg.get("logical_columns", c_dbg.get("columns", []))
                        item_idx = None
                        for i, h in enumerate(headers):
                            if match_column_name(h, saved_template) == "itemName":
                                item_idx = i
                                break
                        all_rows.extend(c_rows)
                        used_coordinates = True
                    elif expected_cols is not None:
                        # Continuation page: project coordinate rows onto master headers
                        for r in c_rows:
                            proj = _project_row_onto_master(r, c_hdrs, headers)
                            if _is_genuine_product_row(proj, item_idx=item_idx):
                                all_rows.append(proj)
                        used_coordinates = True

            if used_coordinates:
                continue

            # --- 2. Graceful Fallback to Multi-Pass V1 Table Extraction ---
            tables = _extract_best_tables(
                page, saved_template, expected_cols=expected_cols
            )
            for table in tables:
                if not table:
                    continue

                local_header_row = None

                # Page 1: lock master headers
                if expected_cols is None:
                    if page_idx > 0:
                        continue

                    header_row = None
                    data_start_idx = 0
                    for idx, row in enumerate(table):
                        normalized = _normalize_row(row, join_lines=True)
                        if _is_valid_header_row(normalized, saved_template):
                            header_row = normalized
                            data_start_idx = idx + 1
                            if data_start_idx < len(table):
                                maybe_sub = _normalize_row(
                                    table[data_start_idx], join_lines=True
                                )
                                has_heavy_digits = any(
                                    re.search(r"\d{3,}", cell or "")
                                    for cell in maybe_sub
                                )
                                if (
                                    maybe_sub
                                    and not has_heavy_digits
                                    and _row_nonempty_count(maybe_sub) <= 6
                                ):
                                    header_row = _merge_subheader_into_headers(
                                        header_row, maybe_sub
                                    )
                                    data_start_idx += 1
                            break

                    if header_row is None:
                        continue

                    headers = ensure_named_headers(header_row)
                    expected_cols = len(headers)
                    item_idx = None
                    for i, h in enumerate(headers):
                        if match_column_name(h, saved_template) == "itemName":
                            item_idx = i
                            break
                    rows_to_process = table[data_start_idx:]
                else:
                    rows_to_process = []
                    for row in table:
                        if _is_valid_header_row(
                            _normalize_row(row, join_lines=True), saved_template
                        ):
                            local_header_row = _normalize_row(row, join_lines=True)
                            continue
                        rows_to_process.append(row)

                page_rows = []
                for row in rows_to_process:
                    normalized = _normalize_row(row, item_idx=item_idx)
                    joined = _row_joined_text(normalized)
                    if not joined.strip():
                        continue

                    if _is_footer_row(normalized):
                        break

                    if _is_repeated_header_row(row, saved_template):
                        if local_header_row is None:
                            local_header_row = _normalize_row(row, join_lines=True)
                        continue

                    if _is_letterhead_row(normalized) or _is_skippable_row(normalized):
                        continue

                    if local_header_row and headers:
                        normalized = _project_row_onto_master(
                            normalized, local_header_row, headers
                        )
                    elif expected_cols:
                        normalized = (normalized + [""] * expected_cols)[:expected_cols]

                    if not _is_genuine_product_row(normalized, item_idx=item_idx):
                        continue

                    page_rows.append(normalized)

                page_rows = _merge_continuation_rows(page_rows, item_idx=item_idx)
                for row in page_rows:
                    if _is_genuine_product_row(row, item_idx=item_idx):
                        all_rows.append(row)

        # In fallback mode, split text multi-value columns if any
        if not used_coordinates and headers and all_rows:
            headers, all_rows, _ = split_text_multi_value_columns(headers, all_rows, saved_template=saved_template)

    # --- 3. Generic Dynamic Column Semantic Inference Engine ---
    column_mappings = infer_unresolved_column_semantics(
        headers,
        all_rows,
        columns_coord_info=columns_coord_info,
        saved_template=saved_template,
        debug=debug,
    )

    # --- 3b. Generic SN+product glued-token reconstruction (provenance only; no conf boost) ---
    all_rows, sn_product_prov = reconstruct_serial_glued_product_names(
        headers, all_rows, column_mappings=column_mappings
    )
    # --- 3c. Closed-Form Mathematical Constraint Solver & Accounting Repair ---
    if headers and column_mappings and all_rows:
        all_rows = [repair_row_accounting(r, headers, column_mappings) for r in all_rows]

    # --- 4. Prompt 6: Global Validation, Reconciliation & Confidence Engine ---
    validation_results = compute_global_validation_and_confidence(
        headers,
        columns_coord_info,
        column_mappings,
        all_rows,
        saved_template=saved_template,
        metadata=metadata,
    )
    column_mappings = validation_results["resolved_mappings"]
    metadata["validation"] = validation_results
    metadata["confidence"] = validation_results["document_confidence"]
    metadata["classification"] = validation_results["classification"]
    metadata["layout_signature"] = validation_results["layout_signature"]
    metadata["drift_report"] = validation_results["drift_report"]

    # --- 5. Prompt 7: Update Supplier Profile Memory on Validated AUTO_ACCEPT ---
    supplier_name = metadata.get("supplier_name")
    supplier_gstin = metadata.get("supplier_gstin")
    supplier_key = supplier_name or supplier_gstin
    
    profile_memory_action = update_supplier_profile_memory(
        supplier_key=supplier_key,
        supplier_name=supplier_name,
        gstin=supplier_gstin,
        headers=headers,
        logical_columns=columns_coord_info,
        resolved_mappings=column_mappings,
        rows=all_rows,
        validation_result=validation_results,
        is_user_reviewed=False,
    )
    metadata["profile_memory"] = profile_memory_action

    return metadata, headers, column_mappings, all_rows


if __name__ == "__main__":
    import os
    import sys

    sample = sys.argv[1] if len(sys.argv) > 1 else None
    if sample and os.path.exists(sample):
        metadata, headers, column_mappings, all_rows = extract_pdf_table(sample)
        print("Sample:", sample)
        print("Metadata:", metadata)
        print("Headers:", headers)
        print("Rows extracted:", len(all_rows))
        print("Column mappings:")
        print(column_mappings)
        print("\nFirst 3 rows:")
        for row in all_rows[:3]:
            print(row)

