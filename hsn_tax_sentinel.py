"""
MediAstra Pharma PDF Purchase Import Engine - HSN & Statutory GST Tax Audit Sentinel
Validates pharmaceutical HSN codes, Indian statutory GST tax slabs (0%, 5%, 12%, 18%, 28%),
CGST/SGST/IGST tax splits, line-level calculation invariance, and GST Input Tax Credit (ITC) eligibility.
"""
import re
import logging
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

# Valid Indian Statutory GST Tax Slabs for Pharma and Medical Retail
STATUTORY_GST_SLABS = {0.0, 5.0, 12.0, 18.0, 28.0}

# Common Pharmaceutical & Healthcare HSN Chapters and Prefixes
STANDARD_PHARMA_HSN_CHAPTERS = {
    "3001": "Glands, organs, extracts of animal origin",
    "3002": "Human blood, antisera, vaccines, toxins, cultures",
    "3003": "Medicaments unmixed (bulk therapeutic use)",
    "3004": "Medicaments consisting of mixed or unmixed products for therapeutic use",
    "3005": "Wadding, gauze, bandages, surgical dressings, plasters",
    "3006": "Pharmaceutical goods (sterile sutures, dental cements, first-aid kits)",
    "2106": "Food preparations, nutraceuticals, dietary supplements",
    "3304": "Beauty or make-up preparations, skin-care",
    "3305": "Preparations for use on the hair",
    "3306": "Oral or dental hygiene preparations",
    "3401": "Soap, medicated organic surface-active products",
    "3808": "Insecticides, disinfectants, sanitizers",
    "3822": "Diagnostic or laboratory reagents",
    "9018": "Instruments and appliances used in medical, surgical, dental or veterinary sciences",
    "9019": "Mechano-therapy appliances, massage apparatus",
    "9021": "Orthopaedic appliances, splints, artificial parts of the body",
}


def validate_hsn_code(hsn: Any) -> Dict[str, Any]:
    """
    Validates the format and pharma domain validity of an HSN code.
    - Standard Indian GST HSN codes are 4, 6, or 8 digits.
    - Validates against standard pharma chapters (3004, 3002, 3006, 2106, 9018, etc.).
    """
    if not hsn:
        return {
            "hsn_code": "",
            "is_valid": False,
            "hsn_status": "MISSING_HSN",
            "message": "⚠️ Missing HSN code on line item.",
            "chapter_description": None,
        }

    hsn_clean = re.sub(r"[^\d]", "", str(hsn).strip())

    if not hsn_clean or len(hsn_clean) not in (4, 6, 8):
        return {
            "hsn_code": str(hsn),
            "is_valid": False,
            "hsn_status": "INVALID_FORMAT",
            "message": f"🚨 Invalid HSN format '{hsn}'. Expected 4, 6, or 8 digits.",
            "chapter_description": None,
        }

    # Check 4-digit chapter prefix
    chapter_prefix = hsn_clean[:4]
    desc = STANDARD_PHARMA_HSN_CHAPTERS.get(chapter_prefix)

    if desc:
        return {
            "hsn_code": hsn_clean,
            "is_valid": True,
            "hsn_status": "STANDARD_PHARMA_HSN",
            "message": f"✓ Valid Pharma HSN ({desc}).",
            "chapter_description": desc,
        }
    else:
        return {
            "hsn_code": hsn_clean,
            "is_valid": True,
            "hsn_status": "NON_STANDARD_CHAPTER",
            "message": f"ℹ️ Valid digits but non-standard pharma chapter '{chapter_prefix}'.",
            "chapter_description": "Other Goods",
        }


def validate_gst_tax_slab(gst_percent: Any) -> Dict[str, Any]:
    """
    Validates that the given GST rate matches Indian statutory tax slabs.
    """
    try:
        val = float(gst_percent or 0.0)
    except (ValueError, TypeError):
        return {
            "gst_percent": 0.0,
            "is_statutory": False,
            "status": "NON_NUMERIC_GST",
            "message": f"🚨 Non-numeric GST percentage '{gst_percent}'.",
        }

    # Match against statutory slabs with float tolerance
    is_statutory = any(abs(val - s) < 0.01 for s in STATUTORY_GST_SLABS)

    if is_statutory:
        return {
            "gst_percent": val,
            "is_statutory": True,
            "status": "STATUTORY_SLAB",
            "message": f"✓ Statutory GST rate ({val:.1f}%).",
        }
    else:
        return {
            "gst_percent": val,
            "is_statutory": False,
            "status": "NON_STATUTORY_RATE",
            "message": f"🚨 Non-statutory GST rate ({val:.2f}%). Expected 0%, 5%, 12%, 18%, or 28%.",
        }


def audit_line_item_tax(
    item: Dict[str, Any],
    is_interstate: bool = False,
) -> Dict[str, Any]:
    """
    Audits an individual invoice line item for tax compliance:
    1. HSN code validity
    2. GST tax slab validity
    3. Mathematical consistency between Taxable Amount, GST%, and GST Amount
    4. Proper CGST/SGST (50/50 split) or IGST (100%) distribution
    5. MRP vs Rate overcharge check
    """
    def _to_float(v: Any, default: float = 0.0) -> float:
        try:
            return float(re.sub(r"[^\d\.]", "", str(v))) if v is not None else default
        except Exception:
            return default

    hsn_raw = item.get("hsnCode") or item.get("hsn_code") or item.get("hsn")
    gst_pct = _to_float(item.get("gstPercent") or item.get("gst_percent") or item.get("gst"))
    taxable_amt = _to_float(item.get("taxableAmount") or item.get("taxable_amount") or item.get("amount"))
    stated_gst_amt = _to_float(item.get("gstAmount") or item.get("gst_amount"))
    net_amt = _to_float(item.get("netAmount") or item.get("line_net_amount") or item.get("net"))
    rate = _to_float(item.get("rate") or item.get("ptr_rate") or item.get("ptr"))
    mrp = _to_float(item.get("mrp"))

    hsn_val = validate_hsn_code(hsn_raw)
    gst_val = validate_gst_tax_slab(gst_pct)

    # Compute expected GST Amount
    expected_gst_amt = round(taxable_amt * (gst_pct / 100.0), 2)
    calc_net_amt = round(taxable_amt + expected_gst_amt, 2)

    tax_calc_variance = 0.0
    has_gst_math_error = False
    if stated_gst_amt > 0 and taxable_amt > 0:
        tax_calc_variance = abs(stated_gst_amt - expected_gst_amt)
        if tax_calc_variance > 0.10:  # More than 10 paise variance
            has_gst_math_error = True

    # Statutory CGST/SGST/IGST breakdown
    if is_interstate:
        igst_rate = gst_pct
        cgst_rate = 0.0
        sgst_rate = 0.0
        igst_amount = expected_gst_amt if stated_gst_amt == 0 else stated_gst_amt
        cgst_amount = 0.0
        sgst_amount = 0.0
    else:
        igst_rate = 0.0
        cgst_rate = gst_pct / 2.0
        sgst_rate = gst_pct / 2.0
        effective_gst = stated_gst_amt if stated_gst_amt > 0 else expected_gst_amt
        cgst_amount = round(effective_gst / 2.0, 2)
        sgst_amount = round(effective_gst - cgst_amount, 2)  # Invariance: cgst + sgst == total
        igst_amount = 0.0

    # Overcharge check
    is_price_inverted = False
    if mrp > 0 and rate > mrp:
        is_price_inverted = True

    alerts = []
    if not hsn_val["is_valid"]:
        alerts.append(hsn_val["message"])
    if not gst_val["is_statutory"]:
        alerts.append(gst_val["message"])
    if has_gst_math_error:
        alerts.append(f"🚨 GST Amount Mismatch: Stated ₹{stated_gst_amt:.2f} vs Computed ₹{expected_gst_amt:.2f} (diff ₹{tax_calc_variance:.2f}).")
    if is_price_inverted:
        alerts.append(f"🚨 Price Inversion: Purchase Rate (₹{rate:.2f}) > MRP (₹{mrp:.2f}).")

    return {
        "hsn_validation": hsn_val,
        "gst_validation": gst_val,
        "taxable_amount": taxable_amt,
        "gst_percent": gst_pct,
        "stated_gst_amount": stated_gst_amt,
        "computed_gst_amount": expected_gst_amt,
        "tax_variance": round(tax_calc_variance, 2),
        "has_gst_math_error": has_gst_math_error,
        "is_interstate": is_interstate,
        "cgst_rate": cgst_rate,
        "cgst_amount": cgst_amount,
        "sgst_rate": sgst_rate,
        "sgst_amount": sgst_amount,
        "igst_rate": igst_rate,
        "igst_amount": igst_amount,
        "itc_eligible_amount": stated_gst_amt if stated_gst_amt > 0 else expected_gst_amt,
        "is_price_inverted": is_price_inverted,
        "alerts": alerts,
        "is_compliant": (hsn_val["is_valid"] and gst_val["is_statutory"] and not has_gst_math_error and not is_price_inverted),
    }


def audit_invoice_tax_compliance(
    items: List[Dict[str, Any]],
    invoice_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Performs comprehensive statutory GST and HSN audit for an entire invoice.
    Produces:
    - Aggregate Tax Breakdown by Statutory Slab (5%, 12%, 18%, etc.)
    - Total Taxable, CGST, SGST, IGST, and Total Tax
    - Input Tax Credit (ITC) Eligible Claim
    - Compliance Summary & Flagged Issues
    """
    if invoice_meta is None:
        invoice_meta = {}

    supplier_gstin = str(invoice_meta.get("supplier_gstin") or invoice_meta.get("gstin") or "")
    buyer_gstin = str(invoice_meta.get("buyer_gstin") or "")

    # Interstate determination: If supplier and buyer state codes (first 2 digits of GSTIN) differ
    is_interstate = False
    if len(supplier_gstin) >= 2 and len(buyer_gstin) >= 2:
        is_interstate = (supplier_gstin[:2] != buyer_gstin[:2])

    slab_aggregates: Dict[float, Dict[str, float]] = {}
    for slab in sorted(STATUTORY_GST_SLABS):
        slab_aggregates[slab] = {
            "taxable_amount": 0.0,
            "cgst_amount": 0.0,
            "sgst_amount": 0.0,
            "igst_amount": 0.0,
            "total_gst_amount": 0.0,
            "item_count": 0,
        }

    total_taxable = 0.0
    total_cgst = 0.0
    total_sgst = 0.0
    total_igst = 0.0
    total_gst = 0.0
    total_itc_eligible = 0.0

    all_alerts = []
    audited_lines = []

    for idx, it in enumerate(items):
        line_audit = audit_line_item_tax(it, is_interstate=is_interstate)
        audited_lines.append(line_audit)

        gst_p = line_audit["gst_percent"]
        taxable = line_audit["taxable_amount"]
        cgst = line_audit["cgst_amount"]
        sgst = line_audit["sgst_amount"]
        igst = line_audit["igst_amount"]
        line_gst = line_audit["itc_eligible_amount"]

        # Add to matching slab
        matched_slab = None
        for s in STATUTORY_GST_SLABS:
            if abs(gst_p - s) < 0.01:
                matched_slab = s
                break

        if matched_slab is not None:
            slab_aggregates[matched_slab]["taxable_amount"] += taxable
            slab_aggregates[matched_slab]["cgst_amount"] += cgst
            slab_aggregates[matched_slab]["sgst_amount"] += sgst
            slab_aggregates[matched_slab]["igst_amount"] += igst
            slab_aggregates[matched_slab]["total_gst_amount"] += line_gst
            slab_aggregates[matched_slab]["item_count"] += 1
        else:
            # Non-statutory rate bucket
            if gst_p not in slab_aggregates:
                slab_aggregates[gst_p] = {
                    "taxable_amount": 0.0,
                    "cgst_amount": 0.0,
                    "sgst_amount": 0.0,
                    "igst_amount": 0.0,
                    "total_gst_amount": 0.0,
                    "item_count": 0,
                }
            slab_aggregates[gst_p]["taxable_amount"] += taxable
            slab_aggregates[gst_p]["cgst_amount"] += cgst
            slab_aggregates[gst_p]["sgst_amount"] += sgst
            slab_aggregates[gst_p]["igst_amount"] += igst
            slab_aggregates[gst_p]["total_gst_amount"] += line_gst
            slab_aggregates[gst_p]["item_count"] += 1

        total_taxable += taxable
        total_cgst += cgst
        total_sgst += sgst
        total_igst += igst
        total_gst += line_gst
        total_itc_eligible += line_audit["itc_eligible_amount"]

        for alt in line_audit["alerts"]:
            item_name = it.get("itemName") or it.get("product_name") or f"Item #{idx + 1}"
            all_alerts.append(f"Row {idx + 1} ({item_name}): {alt}")

    # Round all slab values
    cleaned_slabs = {}
    for s, data in slab_aggregates.items():
        if data["item_count"] > 0 or data["taxable_amount"] > 0:
            cleaned_slabs[f"{s:.1f}%"] = {
                "slab_percent": s,
                "taxable_amount": round(data["taxable_amount"], 2),
                "cgst_amount": round(data["cgst_amount"], 2),
                "sgst_amount": round(data["sgst_amount"], 2),
                "igst_amount": round(data["igst_amount"], 2),
                "total_gst_amount": round(data["total_gst_amount"], 2),
                "item_count": data["item_count"],
            }

    is_overall_compliant = len(all_alerts) == 0

    return {
        "is_interstate": is_interstate,
        "is_overall_compliant": is_overall_compliant,
        "total_taxable_amount": round(total_taxable, 2),
        "total_cgst_amount": round(total_cgst, 2),
        "total_sgst_amount": round(total_sgst, 2),
        "total_igst_amount": round(total_igst, 2),
        "total_gst_amount": round(total_gst, 2),
        "total_itc_claimable": round(total_itc_eligible, 2),
        "tax_slab_breakdown": cleaned_slabs,
        "compliance_alerts_count": len(all_alerts),
        "compliance_alerts": all_alerts,
        "line_audits": audited_lines,
    }
