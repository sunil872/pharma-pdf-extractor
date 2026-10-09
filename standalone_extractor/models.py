"""
Standalone Stated-Value Extraction Engine for Pharmaceutical Invoices.
Extracts printed ground-truth values without synthetic re-calculations.
"""
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field

class StatedLineItem(BaseModel):
    line_number: Optional[int] = None
    product_name: str
    manufacturer: Optional[str] = None
    pack: Optional[str] = None
    hsn_code: Optional[str] = None
    batch_number: Optional[str] = None
    expiry_date: Optional[str] = None
    
    # Exact quantities as printed (supports fractional schemes e.g. 2.5 + 0.5)
    stated_billed_qty: Optional[Decimal] = None
    stated_free_qty: Optional[Decimal] = Decimal("0.0")
    
    # Pricing fields as printed on the bill
    stated_mrp: Optional[Decimal] = None
    stated_rate: Optional[Decimal] = None
    stated_ptr: Optional[Decimal] = None
    
    # Discount preserved exactly as stated (handles raw string e.g. '-205.40', '5%', '1.50')
    stated_discount_raw: Optional[str] = None
    stated_discount_amount: Optional[Decimal] = None
    
    # Stated amounts (Ground Truth from invoice - NO synthetic re-calculation)
    stated_taxable_amount: Optional[Decimal] = None
    stated_cgst_amount: Optional[Decimal] = None
    stated_sgst_amount: Optional[Decimal] = None
    stated_igst_amount: Optional[Decimal] = None
    stated_gst_rate_pct: Optional[Decimal] = None
    stated_total_gst_amount: Optional[Decimal] = None
    
    # Final row total exactly as printed
    stated_net_amount: Optional[Decimal] = None

class StatedTaxSlab(BaseModel):
    slab_pct: Decimal
    taxable_amount: Optional[Decimal] = None
    cgst_amount: Optional[Decimal] = None
    sgst_amount: Optional[Decimal] = None
    igst_amount: Optional[Decimal] = None
    total_tax: Optional[Decimal] = None

class StatedInvoice(BaseModel):
    supplier_name: Optional[str] = None
    supplier_gstin: Optional[str] = None
    recipient_name: Optional[str] = None
    recipient_gstin: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    
    # Stated financial summary (directly from the invoice summary block)
    stated_gross_amount: Optional[Decimal] = None
    stated_discount_total: Optional[Decimal] = None
    stated_taxable_total: Optional[Decimal] = None
    stated_cgst_total: Optional[Decimal] = None
    stated_sgst_total: Optional[Decimal] = None
    stated_igst_total: Optional[Decimal] = None
    stated_total_gst: Optional[Decimal] = None
    stated_round_off: Optional[Decimal] = None
    stated_grand_total: Optional[Decimal] = None
    
    tax_slabs: List[StatedTaxSlab] = Field(default_factory=list)
    line_items: List[StatedLineItem] = Field(default_factory=list)
    
    total_items_count: int = 0
    raw_file_name: str
    extraction_strategy: str = "native_stated_extractor"
