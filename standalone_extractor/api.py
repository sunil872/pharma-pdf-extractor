import os
from .models import StatedInvoice
from .table_engine import TableExtractionEngine

def extract_stated_invoice(pdf_path: str) -> StatedInvoice:
    """
    Main programmatic interface to extract stated values from a pharmaceutical invoice PDF.
    Preserves exact stated numbers from the document without synthetic re-calculations.
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"Invoice PDF not found at: {pdf_path}")

    engine = TableExtractionEngine(pdf_path)
    items, summary, tax_slabs = engine.extract()

    return StatedInvoice(
        supplier_name=summary.get("supplier_name"),
        supplier_gstin=summary.get("supplier_gstin"),
        recipient_name=summary.get("recipient_name"),
        recipient_gstin=summary.get("recipient_gstin"),
        invoice_number=summary.get("invoice_number"),
        invoice_date=summary.get("invoice_date"),
        stated_gross_amount=summary.get("stated_gross_amount"),
        stated_discount_total=summary.get("stated_discount_total"),
        stated_taxable_total=summary.get("stated_taxable_total"),
        stated_cgst_total=summary.get("stated_cgst_total"),
        stated_sgst_total=summary.get("stated_sgst_total"),
        stated_total_gst=summary.get("stated_total_gst"),
        stated_round_off=summary.get("stated_round_off"),
        stated_grand_total=summary.get("stated_grand_total"),
        tax_slabs=tax_slabs,
        line_items=items,
        total_items_count=len(items),
        raw_file_name=os.path.basename(pdf_path),
        extraction_strategy="native_stated_extractor"
    )
