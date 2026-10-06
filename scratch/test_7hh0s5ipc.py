import sys, os
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
from extractor import extract_pdf_table

sample = "Sample Invoices/INVOICE_7HH0S5IPC.PDF"
metadata, headers, column_mappings, all_rows = extract_pdf_table(sample)

print("=" * 60)
print(f"Extraction Results for {sample}")
print("=" * 60)
print("Metadata:", metadata)
print("\nHeaders (Logical Columns):")
for i, h in enumerate(headers):
    mapping = column_mappings.get(h, {})
    mapped_field = mapping.get("mapped_to")
    status = mapping.get("status")
    conf = mapping.get("confidence")
    print(f"  Col {i:2d}: {h:20} -> {str(mapped_field):15} (status={status}, conf={conf})")

print(f"\nTotal genuine rows extracted: {len(all_rows)}")
print("\nFirst 5 rows:")
for r in all_rows[:5]:
    print("  " + " | ".join(r))
