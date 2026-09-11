import re
import pdfplumber
import pandas as pd
from rapidfuzz import process, fuzz


# Canonical system columns used by the purchase import engine.
ALIAS_DICT = {
    "itemName": [
        "product name", "item description", "particulars", "product nmae",
        "item name", "product", "description", "item"
    ],
    "pack": [
        "pack", "packing", "pkg", "unit", "boxs", "pack size"
    ],
    "batchNo": [
        "batch", "batch no", "batchno", "batch no.", "batch number", "lot", "lot no"
    ],
    "expiryDate": [
        "exp", "expiry", "exp date", "exp.", "e.x.p", "ex", "ex...", "expiry date"
    ],
    "quantity": [
        "qty", "quantity", "billed qty", "billed", "units", "bld qty", "qty.",
        "quantity billed", "qty+free", "qty/free"
    ],
    "freeQuantity": [
        "free", "free qty", "sch qty", "scheme qty", "f.qty", "free quantity"
    ],
    "discountPercent": [
        "dis", "disc", "disc.", "sch", "scheme", "idisper", "dis%", "disc%", "discount %"
    ],
    "rate": [
        "rate", "ptr", "pur rate", "purchase rate","Rate ", "p.t.r", "rate/unit", "pur. rate"
    ],
    "mrp": [
        "mrp", "m.r.p", "max retail price", "M.R.P", "M R P", "m r p" "m.r.p.", "old mrp"
    ],
    "hsnCode": [
        "hsn", "hsn/sac", "hsn code", "hsncode", "sac code", "hsn/sac code"
    ],
    "amount": [
        "amount", "gross amt", "gross amount", "total", "item amt"
    ],
    "taxableAmount": [
        "taxable", "taxable amt", "taxable value"
    ],
    "netAmount": [
        "net", "net amount", "net value", "net amt", "bill amt"
    ],
    "cgstPercent": [
        "cgst", "cgst%", "cgst per", "cgstper", "cgst rate"
    ],
    "sgstPercent": [
        "sgst", "sgst%", "sgst per", "sgstper", "sgst rate"
    ],
    "gstPercent": [
        "gst", "gst%", "gst rate", "total gst", "igst", "tax%"
    ],
    "company": [
        "mfr", "mfg", "mkt by", "mfname", "mfgby", "company", "mfac mkt by", "mfac/ mkt by"
    ],
}

SERIAL_NUMBER_ALIASES = ["s", "sn", "sno", "s.no", "sl no", "sr no", "sl.no", "s no", "sr.no"]

FOOTER_STOP_WORDS = [
    "remark:", "bank name", "amount in words", "continued",
    "sub total", "subtotal", "grand total", "tax%", "declaration",
    "tot items", "total items", "mr value", "mrp value", "total tax amt",
    "rupees", "ifsc", "terms", "condition", "authorised signatory",
    "authorized signatory", "taxable amt", "taxable value",
    "outstanding", "for oustanding", "for outstanding",
]

# Letterhead / party / page chrome that must never become line items.
LETTERHEAD_SKIP_WORDS = [
    "jp logistics", "pharma hubb", "gst invoice", "tax inv.no", "tax inv no",
    "page 2", "page 1", "page no", "page of", "d.l.no", "dl no", "d.l no",
    "credit", "sales executive", "original for recipient",
    "invoice date", "due date", "order no", "ref id", "route nam",
    "gstin:", "gstin ", "phone:", "email id", "udyam", "whatsapp",
    "new bhoiguda", "secunderabad", "secudrab", "authorised", "authorized",
]

# Repeated column-header cues on continuation pages.
REPEATED_HEADER_WORDS = [
    "item description", "product name", "product nmae", "m.r.p", "mrp",
    "quantity", "billed free", "pack batch", "hsn /sac", "old mrp",
    "mfac/ mkt", "exp date",
]

SYSTEM_COLUMNS = {
    "itemName": {"label": "Item Name", "required": True, "description": "Name of the item/product"},
    "pack": {"label": "Pack", "required": True, "description": "Pack size/quantity information"},
    "batchNo": {"label": "Batch Number", "required": True, "description": "Batch number of the item"},
    "expiryDate": {"label": "Expiry Date", "required": True, "description": "Expiry date of the item"},
    "quantity": {"label": "Quantity", "required": True, "description": "Quantity of items"},
    "freeQuantity": {"label": "Free Quantity", "required": True, "description": "Free quantity offered"},
    "discountPercent": {"label": "Discount %", "required": True, "description": "Discount percentage"},
    "rate": {"label": "Rate", "required": True, "description": "Purchase rate per unit"},
    "mrp": {"label": "MRP", "required": True, "description": "Maximum Retail Price"},
    "hsnCode": {"label": "HSN Code", "required": True, "description": "Harmonized System of Nomenclature code"},
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
    "rate", "mrp", "discountPercent", "amount", "taxableAmount",
    "gstPercent", "cgstPercent", "sgstPercent", "netAmount",
]

DEFAULT_EXPIRY_DATE_FORMAT = "MM/YYYY"


def clean_text(text: str) -> str:
    """Normalize text for consistent matching by removing non-alphanumeric characters."""
    return re.sub(r'[^a-z0-9]', '', str(text).lower())


def is_serial_number_header(raw_header: str) -> bool:
    if raw_header is None:
        return False
    cleaned = clean_text(raw_header)
    if not cleaned:
        return False
    return cleaned in {clean_text(a) for a in SERIAL_NUMBER_ALIASES}


def match_column_name(raw_header: str, saved_template: dict = None):
    if raw_header is None:
        return None

    raw_str = " ".join(str(raw_header).replace("\r", "\n").split())
    if not raw_str:
        return None

    if is_serial_number_header(raw_str):
        return None

    if saved_template and raw_str in saved_template:
        mapped = saved_template[raw_str]
        return None if mapped in ("itemCode", "igstPercent", "saleRate") else mapped
    if saved_template and str(raw_header) in saved_template:
        mapped = saved_template[str(raw_header)]
        return None if mapped in ("itemCode", "igstPercent", "saleRate") else mapped

    cleaned_header = clean_text(raw_str)

    for system_field, aliases in ALIAS_DICT.items():
        for alias in aliases:
            if clean_text(alias) == cleaned_header:
                return system_field

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
    cleaned = clean_text(raw_header)
    if system_field == "rate":
        if cleaned == "rate":
            return 1000.0
        if cleaned in {"ptr", "purrate", "purchaserate"}:
            return 100.0
    if system_field == "mrp":
        if cleaned == "mrp":
            return 1000.0
        if cleaned == "oldmrp":
            return 100.0
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


def parse_compound_qty(val):
    if val is None:
        return (0.0, 0.0)

    text = str(val).strip().replace(",", "")
    if not text:
        return (0.0, 0.0)

    free_only = re.match(r"^\+\s*(\d*\.?\d+)\s*$", text)
    if free_only:
        try:
            return (0.0, float(free_only.group(1)))
        except ValueError:
            return (0.0, 0.0)

    compound = re.match(
        r"^\s*(\d+(?:\.\d+)?|\.\d+)\s*\+\s*(\d+(?:\.\d+)?|\.\d+)\s*$",
        text,
    )
    if compound:
        try:
            return (float(compound.group(1)), float(compound.group(2)))
        except ValueError:
            return (0.0, 0.0)

    return (0.0, 0.0)


def _to_float(val, default=0.0):
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
    match = re.search(r"-?\d*\.?\d+", text)
    if not match:
        return default
    try:
        return float(match.group(0))
    except ValueError:
        return default


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

    return row_dict


def compute_row_accounting(row):
    data = fix_column_bleeding(dict(row) if not isinstance(row, dict) else dict(row))

    quantity = _to_float(data.get("quantity"), 0.0)
    rate = _to_float(data.get("rate"), 0.0)
    discount_percent = _to_float(data.get("discountPercent"), 0.0)
    gst_percent = _to_float(data.get("gstPercent"), 0.0)
    cgst_percent = _to_float(data.get("cgstPercent"), 0.0)
    sgst_percent = _to_float(data.get("sgstPercent"), 0.0)
    amount = _to_float(data.get("amount"), 0.0)
    net_amount = _to_float(data.get("netAmount"), 0.0)
    taxable_amount = _to_float(data.get("taxableAmount"), 0.0)

    if (not gst_percent) and (cgst_percent or sgst_percent):
        gst_percent = cgst_percent + sgst_percent
    elif gst_percent and (not cgst_percent) and (not sgst_percent):
        cgst_percent = gst_percent / 2.0
        sgst_percent = gst_percent / 2.0

    if not amount:
        amount = round(quantity * rate, 2)

    if net_amount and not amount:
        divisor = 1.0 + (gst_percent / 100.0)
        taxable_amount = round(net_amount / divisor, 2) if divisor else 0.0
        discount_divisor = 1.0 - (discount_percent / 100.0)
        amount = round(taxable_amount / discount_divisor, 2) if discount_divisor else taxable_amount
    else:
        if not taxable_amount:
            discount_factor = discount_percent / 100.0
            taxable_amount = round(amount - (amount * discount_factor), 2)
        if not net_amount:
            gst_val = round(taxable_amount * (gst_percent / 100.0), 2)
            net_amount = round(taxable_amount + gst_val, 2)

    data["quantity"] = quantity
    data["rate"] = rate
    data["discountPercent"] = discount_percent
    data["gstPercent"] = round(gst_percent, 4)
    data["cgstPercent"] = round(cgst_percent, 4)
    data["sgstPercent"] = round(sgst_percent, 4)
    data["amount"] = amount
    data["taxableAmount"] = taxable_amount
    data["netAmount"] = net_amount
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
    r"pharma\s*hubb|"  # known buyer on sample invoices
    r"bill\s*to|ship\s*to|sold\s*to|consignee|buyer|customer|party\s*name|"
    r"gst\s*invoice|tax\s*invoice|original\s*for\s*recipient|"
    r"^page\s*\d|^invoice\s*(no|number|date)|^date\s*:|^gstin|^phone|"
    r"^email|^mobile|^tel\.?|^dl\.?\s*no|^fssai|^due\s*date|^credit|"
    r"^debit|^irn\b|^ack\b|^einvoice|^e-?invoice|^taxable|"
    r"^hsn|^particulars|^description|^s\.?\s*no|^qty\b|^mrp\b|^rate\b|"
    r"^amount\b|^net\s*amount|^grand\s*total|^authori[sz]ed\s*sign"
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
    text = "".join(c.get("text", "") for c in chars)
    text = re.sub(r"\s+", " ", text).strip()
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
            # Longer / more specific tokens weigh more.
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

    # Prefer top-left brand block (seller header); buyer is often top-right.
    top_ratio = metrics["top"] / max(page_height, 1.0)
    mid_x_ratio = metrics["mid_x"] / max(page_width, 1.0)
    if top_ratio > 0.42:
        return -1e9
    if mid_x_ratio > 0.62:
        return -1e9

    score = 0.0
    score += metrics["max_size"] * 6.0
    score += metrics["avg_size"] * 2.0
    score += metrics["bold_frac"] * 35.0
    score += (1.0 - top_ratio) * 40.0
    score += (1.0 - mid_x_ratio) * 25.0
    score += _supplier_keyword_boost(text)

    # Short trade names beat long address-like blobs that slipped through.
    if 3 <= len(text) <= 48:
        score += 12.0
    elif len(text) > 70:
        score -= 20.0

    # All-caps company names are common on Indian GST invoices.
    letters = re.sub(r"[^A-Za-z]", "", text)
    if letters and letters.isupper() and len(letters) >= 4:
        score += 8.0

    return score


def detect_supplier_name_from_page(page):
    """
    Pick the seller/supplier trade name from the first page.

    Heuristic (typical Indian pharma GST invoice):
    - Top-left header block
    - Larger + bold font vs address lines
    - Name often contains pharma/medical/logistics/agency/distributor cues
    """
    page_width = float(page.width or 1.0)
    page_height = float(page.height or 1.0)
    chars = page.chars or []

    best = None
    best_score = -1e9

    if chars:
        top_band = page_height * 0.42
        left_band = page_width * 0.62
        region_chars = [
            c for c in chars
            if float(c.get("top", 9999)) <= top_band
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
    with pdfplumber.open(pdf_path) as pdf:
        first_page = pdf.pages[0]
        text = first_page.extract_text() or ""
        supplier_info = detect_supplier_name_from_page(first_page)

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
        "supplier_name": supplier_info.get("detected_name"),
        "supplier_confidence": supplier_info.get("confidence"),
        "supplier_is_editable": supplier_info.get("is_editable", True),
        "supplier_gstin": gstin_match.group(0) if gstin_match else None,
        "invoice_number": invoice_number_match.group(1) if invoice_number_match else None,
        "invoice_date": invoice_date_match.group(1) if invoice_date_match else None,
        "expiry_date_format": DEFAULT_EXPIRY_DATE_FORMAT,
    }


def _normalize_cell(cell, join_lines: bool = False):
    if cell is None:
        return ""
    text = str(cell).replace("\r", "\n").strip()
    if not text:
        return ""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if not lines:
        return ""
    value = " ".join(lines) if join_lines else lines[0]
    parts = value.split()
    if len(parts) == 2 and parts[0].upper() == parts[1].upper():
        value = parts[0]
    return value


def _normalize_row(row, join_lines: bool = False):
    if not row:
        return []
    return [_normalize_cell(cell, join_lines=join_lines) for cell in row]


def _row_joined_text(row) -> str:
    return " ".join(str(cell or "") for cell in (row or [])).strip()


def _is_footer_row(row):
    if not row:
        return False
    joined = _row_joined_text(row).lower()
    if not joined:
        return False
    return any(w in joined for w in FOOTER_STOP_WORDS)


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
        _is_letterhead_row(row)
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
    values = _normalize_row(row)
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


def extract_pdf_table(pdf_file, saved_template: dict = None):
    """
    Extract line-item tables from every page of an invoice PDF.

    Master headers come from the first valid header on page 1. Later pages keep
    contributing product rows while letterheads, repeated headers, blank grid
    rows, and footers are filtered. Footer hits only stop the current table —
    the outer page loop always continues.
    """
    metadata = extract_invoice_metadata(pdf_file)

    headers = []
    all_rows = []
    column_mappings = {}
    expected_cols = None
    item_idx = None

    if hasattr(pdf_file, "seek"):
        pdf_file.seek(0)

    with pdfplumber.open(pdf_file) as pdf:
        if not pdf.pages:
            return metadata, [], {}, []

        for page_idx, page in enumerate(pdf.pages):
            tables = _extract_best_tables(
                page, saved_template, expected_cols=expected_cols
            )
            for table in tables:
                if not table:
                    continue

                local_header_row = None

                # --- Page 1: lock master headers from the first valid header band ---
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
                    column_mappings = resolve_column_mappings(headers, saved_template)
                    item_idx = None
                    for i, h in enumerate(headers):
                        if _mapping_field(column_mappings, h) == "itemName":
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
                    normalized = _normalize_row(row)
                    joined = _row_joined_text(normalized)
                    if not joined.strip():
                        continue

                    # Footer / totals: stop THIS table only — keep scanning later pages.
                    if _is_footer_row(normalized):
                        break

                    # Repeated column headers (common on page 2+).
                    if _is_repeated_header_row(row, saved_template):
                        if local_header_row is None:
                            local_header_row = _normalize_row(row, join_lines=True)
                        continue

                    # Letterhead / party / page chrome.
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

    # --- Content-Based Inference for Missing Headers ---
    for idx, raw_col in enumerate(headers):
        current_map = column_mappings.get(raw_col)
        conf = (
            current_map.get("confidence", 0)
            if isinstance(current_map, dict)
            else (100.0 if current_map else 0)
        )
        if conf < 85 or str(raw_col).startswith("Unnamed_Col_"):
            hsn_match_count = 0
            valid_cell_count = 0

            for row in all_rows[:8]:
                if idx < len(row):
                    cell_val = str(row[idx]).strip()
                    if cell_val:
                        valid_cell_count += 1
                        if re.match(r"^\d{4,8}$", clean_text(cell_val)):
                            hsn_match_count += 1

            if valid_cell_count > 0 and (hsn_match_count / valid_cell_count) >= 0.8:
                column_mappings[raw_col] = {
                    "mapped_to": "hsnCode",
                    "confidence": 100.0,
                }

    return metadata, headers, column_mappings, all_rows


if __name__ == "__main__":
    import os

    sample = os.path.join("Sample Invoices", "Invoice.pdf")
    if not os.path.exists(sample):
        sample = "Invoice.pdf"
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
