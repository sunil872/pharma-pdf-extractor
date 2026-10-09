"""
Semantic column classifier for pharmaceutical invoices.
Maps disparate distributor header naming conventions to canonical schema keys.
Handles split characters caused by narrow PDF table column lines.
"""
import re
from typing import Dict, List, Optional
from rapidfuzz import fuzz

HEADER_ALIASES = {
    "line_number": ["S.", "S.NO", "SR.", "SL", "SL.NO", "ITEM NO"],
    "billed_qty": [
        "QTY", "QUANTITY", "BILLED", "BILLED QTY", "B.QTY", "QTY.", "B QTY",
        "QTY+FREE PACK", "SALE QTY"
    ],
    "free_qty": [
        "FREE", "SCHEME", "SCH", "F.QTY", "FREE QTY", "SCM", "FR.QTY", "F QTY"
    ],
    "mfg": [
        "MFG", "MFGBY", "MFR", "MFAC", "MFAC/RACK", "MKT BY", "MFR.", "COMPANY"
    ],
    "rack": [
        "RACK", "RACK NO", "RACK/NO", "SHELF"
    ],
    "pack": [
        "PACK", "PKG", "BOXS", "PACKING", "UNIT", "PK"
    ],
    "product_name": [
        "PRODUCT NAME", "ITEM DESCRIPTION", "DESCRIPTION", "PARTICULARS",
        "ITEM NAME", "PRODUCT", "ITEM"
    ],
    "hsn_code": [
        "HSN", "HSNCODE", "HSN/SAC", "HSN CODE", "HSN NO", "SAC"
    ],
    "batch_number": [
        "BATCH", "BATCH NO", "BATCH NO.", "B.NO", "B.NO.", "LOT", "LOT NO"
    ],
    "expiry_date": [
        "EXP", "EXPIRY", "EXP DT", "EXP.DATE", "EXP. DT", "E.X.P", "EXP DATE",
        "EXPIRY DATE", "E.X", "EX"
    ],
    "mrp": [
        "MRP", "M.R.P", "M.R.P.", "M. R. P."
    ],
    "ptr": [
        "PTR", "P.T.R", "P.T.R.", ".P P.T", "P PT", "P.T"
    ],
    "rate": [
        "RATE", "PUR.RATE", "P.RATE", "PRICE", "UNIT RATE", "P RATE",
        ".R RA", "R RA", "R.RA"
    ],
    "discount": [
        "DISC", "DIS", "DIS%", "DISCOUNT", "SCH.DISC", "DIS.AMT", "LESS",
        "SCH DISC", "DIS AMT", "UNT D", "UNT.D"
    ],
    "taxable_amount": [
        "AMOUNT", "TAXABLE", "TAXABLE AMT", "ASS.VAL", "ASS VAL", "AMT",
        "VALUE", "TAXABLE VALUE", "NET AMOUNT", "TE AMO", "TE.AMO"
    ],
    "gst_rate": [
        "GST", "GST%", "GST RATE", "TAX%", "TAX RATE", "ISC GST", "ISCGST"
    ],
    "cgst_rate": ["CGST%", "CGST %"],
    "sgst_rate": ["SGST%", "SGST %"],
    "cgst_amount": [
        "CGST", "CGST AMT", "CGST PAYBLE", "CGST AMOUNT"
    ],
    "sgst_amount": [
        "SGST", "SGST AMT", "SGST PAYBLE", "SGST AMOUNT"
    ],
    "igst_amount": [
        "IGST", "IGST AMT", "IGST AMOUNT"
    ],
    "net_amount": [
        "NET", "NET AMOUNT", "NET VALUE", "TOTAL", "NET AMT", "NET VAL",
        "TOTAL VALUE"
    ]
}

def clean_header_text(text: Optional[str]) -> str:
    """Normalizes header string for fuzzy matching."""
    if not text:
        return ""
    cleaned = re.sub(r'[\r\n\t]+', ' ', str(text))
    cleaned = re.sub(r'[^a-zA-Z0-9%\/\.\s]', '', cleaned)
    return cleaned.strip().upper()

def classify_header(raw_header: Optional[str]) -> Optional[str]:
    """
    Classifies a raw table header into a canonical field name.
    Uses exact match, substring match, and rapidfuzz ratio.
    """
    cleaned = clean_header_text(raw_header)
    if not cleaned:
        return None

    # 1. Exact or starts-with matches
    for canonical_name, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if cleaned == alias or cleaned.replace(".", "") == alias.replace(".", ""):
                return canonical_name
    
    # 2. Check if alias is a prominent substring in the header
    for canonical_name, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if re.search(r'\b' + re.escape(alias) + r'\b', cleaned):
                return canonical_name

    # 3. Fuzzy match fallback
    best_score = 0
    best_match = None
    for canonical_name, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            score = fuzz.ratio(cleaned, alias)
            if score > best_score and score >= 80:
                best_score = score
                best_match = canonical_name

    return best_match

def disambiguate_column_by_content(sample_values: List[str]) -> Optional[str]:
    """
    Fallback classifier: examines sample column values when header is missing or vague.
    """
    clean_vals = [v.strip() for v in sample_values if v and v.strip() and not v.startswith('_')]
    if not clean_vals:
        return None

    # Check for Expiry Date format: MM/YY, MM-YY
    date_matches = sum(1 for v in clean_vals if re.match(r'^\d{2}[/-]\d{2,4}$', v))
    if date_matches / len(clean_vals) > 0.5:
        return "expiry_date"

    # Check for HSN: 6 to 8 digit integers (e.g. 300490)
    hsn_matches = sum(1 for v in clean_vals if re.match(r'^300[0-9]{3,5}$', v))
    if hsn_matches / len(clean_vals) > 0.5:
        return "hsn_code"

    # Check for GST Rate: 5, 12, 18, 28
    gst_matches = sum(1 for v in clean_vals if v in ["5", "5.0", "5.00", "12", "12.0", "18", "18.0", "28", "28.0"])
    if gst_matches / len(clean_vals) > 0.6:
        return "gst_rate"

    # Check for negative discount numbers: -1.50, -2.00
    disc_matches = sum(1 for v in clean_vals if re.match(r'^-\d+(?:\.\d+)?$', v))
    if disc_matches / len(clean_vals) > 0.5:
        return "discount"

    return None
