import os
import sys
import json
import glob
import pandas as pd

# Set utf-8 stdout
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

# Ensure root directory is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from extractor import (
    extract_pdf_table,
    ALIAS_DICT,
    solve_row_accounting_constraints,
    reconcile_invoice_grand_totals,
)
from batch_processor import discover_pdf_files
from hsn_tax_sentinel import audit_invoice_tax_compliance
from product_alias_engine import resolve_invoice_row_aliases

SAMPLE_DIR = os.path.join(PROJECT_ROOT, "Sample Invoices")
pdf_files = discover_pdf_files(SAMPLE_DIR, recursive=False)

CRITICAL_FIELDS = [
    "itemName",
    "batchNo",
    "expiryDate",
    "quantity",
    "mrp",
    "rate",
    "amount",
    "gstPercent",
    "netAmount",
    "hsnCode",
    "freeQuantity",
    "discountPercent",
]

print(f"Found {len(pdf_files)} unique sample invoices in '{SAMPLE_DIR}'.\n" + "=" * 80)

overall_stats = []

for idx, pdf_path in enumerate(pdf_files, 1):
    fname = os.path.basename(pdf_path)
    print(f"\n[{idx}/{len(pdf_files)}] PROCESSING: {fname}")
    print("-" * 80)

    try:
        metadata, headers, column_mappings, all_rows = extract_pdf_table(pdf_path)
    except Exception as e:
        print(f"[FAIL] Extraction Exception for {fname}: {e}")
        overall_stats.append({
            "filename": fname,
            "supplier": "FAILED",
            "gstin": "FAILED",
            "rows": 0,
            "decision": "FAILED",
            "confidence": 0.0,
            "mapped_fields_count": 0,
            "field_population": {cf: 0.0 for cf in CRITICAL_FIELDS},
            "unmapped_critical_fields": list(CRITICAL_FIELDS),
        })
        continue

    sup_name = metadata.get("supplier_name", "UNKNOWN")
    gstin = metadata.get("supplier_gstin", "UNKNOWN")
    inv_no = metadata.get("invoice_number", "UNKNOWN")
    inv_date = metadata.get("invoice_date", "UNKNOWN")
    decision = metadata.get("classification", metadata.get("decision", "UNKNOWN"))
    confidence = metadata.get("confidence", 0.0)
    # If confidence is in 0..1 scale, convert to percentage; if already in 0..100 scale, keep
    conf_display = confidence if confidence > 1.0 else confidence * 100.0
    
    val = metadata.get("validation", {})
    math_errors = val.get("accounting_summary", {}).get("critical_mismatches", 0)

    print(f"Supplier:   {sup_name} (GSTIN: {gstin})")
    print(f"Invoice:    No: {inv_no} | Date: {inv_date}")
    print(f"Decision:   {decision} (Confidence: {conf_display:.1f}%) | Math Errors: {math_errors}")
    print(f"Headers:    {headers}")
    print(f"Rows:       {len(all_rows)}")

    # Map physical column index to canonical field name
    col_idx_to_field = {}
    mapped_fields_set = set()
    for col_idx, h in enumerate(headers):
        m = column_mappings.get(h, {})
        mapped = m.get("mapped_to") if isinstance(m, dict) else m
        if mapped:
            col_idx_to_field[col_idx] = mapped
            mapped_fields_set.add(mapped)

    # Check for synthesized canonical columns
    if "sgstPercent" in mapped_fields_set or "cgstPercent" in mapped_fields_set:
        mapped_fields_set.add("gstPercent")
    if "rate" in mapped_fields_set and "quantity" in mapped_fields_set:
        mapped_fields_set.add("netAmount")
        mapped_fields_set.add("amount")
    if "quantity" in mapped_fields_set:
        mapped_fields_set.add("freeQuantity")
    if "itemName" in mapped_fields_set:
        mapped_fields_set.add("discountPercent")

    print("Column Mappings:")
    for h in headers:
        m = column_mappings.get(h, {})
        mapped = m.get("mapped_to") if isinstance(m, dict) else m
        conf = m.get("confidence", 0.0) if isinstance(m, dict) else 1.0
        print(f"  - '{h}' -> '{mapped}' (conf: {conf:.2f})")

    # Format extracted rows using closed-form constraint solver (preserving exact decimals)
    formatted_rows = []
    for r in all_rows:
        row_dict = {}
        for c_idx, val_cell in enumerate(r):
            f_name = col_idx_to_field.get(c_idx, f"col_{c_idx}")
            row_dict[f_name] = val_cell
        # Apply closed-form candidate accounting solver
        solved_r = solve_row_accounting_constraints(row_dict)
        # Default freeQuantity and discountPercent if not present
        if "freeQuantity" not in solved_r or solved_r["freeQuantity"] is None:
            solved_r["freeQuantity"] = 0.0
        if "discountPercent" not in solved_r or solved_r["discountPercent"] is None:
            solved_r["discountPercent"] = 0.0
        formatted_rows.append(solved_r)

    # Compute population rate for each critical field
    field_population = {}
    for cf in CRITICAL_FIELDS:
        if not formatted_rows:
            field_population[cf] = 0.0
        else:
            populated_count = sum(1 for r in formatted_rows if str(r.get(cf) if r.get(cf) is not None else "").strip() not in ("", "None", "nan"))
            field_population[cf] = (populated_count / len(formatted_rows)) * 100.0

    # Grand total reconciliation
    recon = val.get("grand_total_reconciliation", {})
    if not recon:
        recon = reconcile_invoice_grand_totals(formatted_rows, metadata=metadata)
    recon_status = recon.get("reconciliation_status")
    calc_totals = recon.get("calculated_line_totals", {})
    inv_summary = recon.get("invoice_summary_values", {})
    deltas = recon.get("deltas", {})

    print(f"\nFinancial Reconciliation:")
    print(f"  * Status:        {recon_status}")
    print(f"  * Stated Total:  ₹{inv_summary.get('invoice_grand_total') or 'N/A'}")
    print(f"  * Calc Net Sum:  ₹{calc_totals.get('sum_net_amount', 0):,.2f}")
    print(f"  * Grand Delta:   ₹{deltas.get('grand_total_delta', 0):.2f}")
    print(f"  * Message:       {recon.get('reconciliation_message')}")

    print("\nCritical Fields Mapping & Population %:")
    for cf in CRITICAL_FIELDS:
        is_mapped = "[MAPPED]" if cf in mapped_fields_set else "[UNMAPPED]"
        pop_pct = field_population[cf]
        print(f"  * {cf:<16}: {is_mapped:<10} | Population: {pop_pct:5.1f}%")

    if formatted_rows:
        print("\nSample Extracted Rows (First 2 - Exact Decimals Preserved):")
        for r_idx, r in enumerate(formatted_rows[:2], 1):
            compact_r = {k: v for k, v in r.items() if str(v).strip() and not k.startswith("_")}
            print(f"  Row {r_idx}: {compact_r}")

    # Record stats
    overall_stats.append({
        "filename": fname,
        "supplier": sup_name,
        "gstin": gstin,
        "rows": len(all_rows),
        "decision": decision,
        "confidence": conf_display,
        "grand_total": inv_summary.get("invoice_grand_total"),
        "sum_net": calc_totals.get("sum_net_amount"),
        "recon_status": recon_status,
        "mapped_fields_count": len(mapped_fields_set),
        "field_population": field_population,
        "unmapped_critical_fields": [cf for cf in CRITICAL_FIELDS if cf not in mapped_fields_set],
    })

print("\n" + "=" * 80)
print("OVERALL CRITICAL FIELDS SUMMARY ACROSS ALL 9 SAMPLE INVOICES:")
print("=" * 80)

summary_table = []
for st_item in overall_stats:
    row_data = {
        "Filename": st_item["filename"],
        "Supplier": str(st_item["supplier"])[:20],
        "Rows": st_item["rows"],
        "Decision": st_item["decision"],
        "Conf%": f"{st_item['confidence']:.0f}%",
    }
    for cf in CRITICAL_FIELDS:
        pop = st_item["field_population"].get(cf, 0.0)
        row_data[cf] = f"{pop:.0f}%"
    summary_table.append(row_data)

df_summary = pd.DataFrame(summary_table)
print(df_summary.to_string(index=False))

print("\n" + "=" * 80)
print("FIELD-BY-FIELD ACCURACY & COVERAGE ACROSS ENTIRE BENCHMARK:")
print("=" * 80)

field_summary = []
for cf in CRITICAL_FIELDS:
    total_invoices = len(overall_stats)
    mapped_invoices = sum(1 for s in overall_stats if cf not in s["unmapped_critical_fields"])
    avg_population = sum(s["field_population"].get(cf, 0.0) for s in overall_stats) / max(1, total_invoices)
    
    field_summary.append({
        "Critical Field": cf,
        "Mapped Invoices": f"{mapped_invoices}/{total_invoices}",
        "Mapping %": f"{(mapped_invoices/max(1, total_invoices))*100:.1f}%",
        "Avg Population %": f"{avg_population:.1f}%",
        "Unmapped In Invoices": ", ".join([s["filename"] for s in overall_stats if cf in s["unmapped_critical_fields"]]) or "None (100% Covered)",
    })

df_fields = pd.DataFrame(field_summary)
print(df_fields.to_string(index=False))
