import sys
import os
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

from extractor import extract_pdf_table, reconcile_invoice_grand_totals, solve_row_accounting_constraints
import pandas as pd

metadata, headers, column_mappings, all_rows = extract_pdf_table("Sample Invoices/invoice (1).pdf")
print("Invoice Metadata:", metadata)
print("Extracted Row Count:", len(all_rows))

field_map = {}
for h, info in column_mappings.items():
    m = info.get("mapped_to") if isinstance(info, dict) else info
    if m and h in headers:
        field_map[m] = headers.index(h)

processed_rows = []
for idx, r in enumerate(all_rows):
    row_dict = {}
    for f, col_i in field_map.items():
        if col_i < len(r):
            row_dict[f] = r[col_i]
    solved = solve_row_accounting_constraints(row_dict)
    processed_rows.append(solved)

df = pd.DataFrame(processed_rows)
print("\nFirst 5 rows:")
print(df.head().to_string())

print("\nRow 30-33 (around 31):")
print(df.iloc[28:34].to_string())

recon = reconcile_invoice_grand_totals(processed_rows, metadata)
print("\nReconciliation Result:", recon["reconciliation_status"])
print(recon["reconciliation_message"])
print("Calculated Totals:", recon["calculated_line_totals"])
print("Invoice Stated:", recon["invoice_summary_values"])
