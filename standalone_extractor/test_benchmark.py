"""
Benchmark test script for Standalone Stated-Value Extraction Engine.
Runs on key sample invoices and displays extracted line items and stated figures.
"""
import os
import sys
from decimal import Decimal

# Ensure standalone_extractor is on path
curr_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(curr_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from standalone_extractor.api import extract_stated_invoice

def test_samples():
    sample_dir = os.path.join(parent_dir, "Sample Invoices")
    test_files = [
        "PHUB_L22014.pdf",
        "invoice (1).pdf",
        "Invoice.pdf",
        "307800_26_I_260007300287653.pdf",
        "SI26-000698.pdf"
    ]

    print("=" * 80)
    print("STANDALONE STATED-VALUE EXTRACTION BENCHMARK")
    print("=" * 80)

    for fname in test_files:
        fpath = os.path.join(sample_dir, fname)
        if not os.path.exists(fpath):
            print(f"Skipping {fname} (not found)")
            continue

        print(f"\n>>> Processing: {fname}")
        invoice = extract_stated_invoice(fpath)

        print(f"  Supplier GSTIN: {invoice.supplier_gstin}")
        print(f"  Invoice Number: {invoice.invoice_number} | Date: {invoice.invoice_date}")
        print(f"  Stated Grand Total: {invoice.stated_grand_total}")
        print(f"  Extracted Line Items: {invoice.total_items_count}")

        # Show first 3 sample items
        for idx, item in enumerate(invoice.line_items[:3]):
            print(f"    Item {idx+1}: {item.product_name[:30]:30} | Batch: {item.batch_number or 'N/A':10} | Exp: {item.expiry_date or 'N/A':7} | Qty: {item.stated_billed_qty}+{item.stated_free_qty} | Rate: {item.stated_rate} | Net: {item.stated_net_amount} | Disc: {item.stated_discount_raw or '0'}")

        if invoice.total_items_count > 3:
            print(f"    ... and {invoice.total_items_count - 3} more items.")

    print("\n" + "=" * 80)
    print("Benchmark complete.")

if __name__ == "__main__":
    test_samples()
