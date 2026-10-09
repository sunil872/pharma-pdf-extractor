"""
Data normalization utilities for pharmaceutical invoices.
Preserves exact stated figures while normalizing formats.
"""
import re
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple

MONTH_MAP = {
    'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
    'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08',
    'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'
}

def parse_decimal(raw_val: Optional[str]) -> Optional[Decimal]:
    """Parses numeric string to Decimal, stripping commas and currency symbols."""
    if not raw_val:
        return None
    clean = str(raw_val).strip()
    clean = re.sub(r'[^\d.-]', '', clean)
    if not clean or clean == '-' or clean == '.':
        return None
    try:
        return Decimal(clean)
    except InvalidOperation:
        return None

def parse_compound_quantity(raw_str: str) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    """
    Parses compound or simple quantities.
    Examples:
      '2.5 + 0.5'  -> (Decimal('2.5'), Decimal('0.5'))
      '13.5 + 1.5' -> (Decimal('13.5'), Decimal('1.5'))
      '10+2'       -> (Decimal('10'), Decimal('2'))
      '10.0'       -> (Decimal('10.0'), Decimal('0.0'))
      '5'          -> (Decimal('5'), Decimal('0.0'))
    """
    if not raw_str:
        return None, Decimal("0.0")
    
    clean = str(raw_str).strip().replace(" ", "")
    # Check for X+Y format
    compound_match = re.match(r"^(\d+(?:\.\d+)?)\+(\d+(?:\.\d+)?)$", clean)
    if compound_match:
        return Decimal(compound_match.group(1)), Decimal(compound_match.group(2))
    
    # Simple quantity
    dec_val = parse_decimal(clean)
    return dec_val, Decimal("0.0")

def parse_discount(raw_str: Optional[str], gross_amount: Optional[Decimal] = None) -> Tuple[Optional[str], Optional[Decimal]]:
    """
    Preserves stated discount format and computes absolute reduction.
    Examples:
      '-205.40' -> ('-205.40', Decimal('205.40'))
      '1.50'    -> ('1.50', Decimal('1.50'))
      '5.00%'   -> ('5.00%', gross * 0.05 if gross else None)
    """
    if not raw_str:
        return None, None
    clean = str(raw_str).strip()
    if not clean or clean == '0' or clean == '0.00':
        return clean, Decimal("0.0")
    
    if '%' in clean:
        pct_val = parse_decimal(clean.replace('%', ''))
        if pct_val is not None and gross_amount is not None:
            amt = round(gross_amount * (pct_val / Decimal("100")), 2)
            return clean, amt
        return clean, None
    
    dec_val = parse_decimal(clean)
    if dec_val is not None:
        # In Indian pharma bills, discounts printed as -1.50 mean reduction of 1.50
        return clean, abs(dec_val)
    
    return clean, None

def normalize_expiry(raw_str: Optional[str]) -> Optional[str]:
    """
    Converts various expiry date strings to ISO YYYY-MM format.
    Examples:
      '05/27'    -> '2027-05'
      '08-27'    -> '2027-08'
      '11/30'    -> '2030-11'
      'OCT-28'   -> '2028-10'
      '05/2027'  -> '2027-05'
    """
    if not raw_str:
        return None
    clean = str(raw_str).strip().upper()
    
    # Check for MON-YY or MON/YY e.g. OCT-28
    for mon_name, mon_num in MONTH_MAP.items():
        if mon_name in clean:
            match = re.search(r'(\d{2,4})', clean)
            if match:
                yr = match.group(1)
                full_yr = f"20{yr}" if len(yr) == 2 else yr
                return f"{full_yr}-{mon_num}"
    
    # Check for MM/YY or MM-YY or MM/YYYY
    match = re.search(r'(\d{1,2})[\/\.-](\d{2,4})', clean)
    if match:
        m, y = match.group(1).zfill(2), match.group(2)
        full_yr = f"20{y}" if len(y) == 2 else y
        # Sanity check: valid month 01-12
        if 1 <= int(m) <= 12:
            return f"{full_yr}-{m}"
    
    return clean

def extract_gstin(text: str) -> Optional[str]:
    """Extracts 15-character Indian GSTIN."""
    match = re.search(r'\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b', text)
    return match.group(0) if match else None
