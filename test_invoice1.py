from extractor import extract_pdf_table

metadata, headers, column_mappings, all_rows = extract_pdf_table("Sample Invoices/invoice (1).pdf")
print("Headers:", headers)
print("Row count:", len(all_rows))
for i, r in enumerate(all_rows):
    if i >= 28 and i <= 33:
        print(f"Row {i}: {r}")
