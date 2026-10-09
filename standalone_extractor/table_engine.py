"""
Native Geometric Table and Stated-Value Extraction Engine.
Extracts pharmaceutical invoice line items preserving exact printed numbers.
Handles:
  1. Multi-line cell blocks (e.g., Shri Ajay, Sri Harsha)
  2. Horizontal coordinate-band lines (e.g., JP Logistics, Divya Pharma)
  3. Multi-page spanning tables
  4. Compound fractional schemes (e.g., 2.5 + 0.5, 13.5 + 1.5)
  5. Negative discounts (-1.50, -205.40) and split CGST/SGST vs single GST
"""
import os
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple
import fitz
import pdfplumber

from .models import StatedLineItem, StatedTaxSlab
from .normalizers import (
    extract_gstin,
    normalize_expiry,
    parse_compound_quantity,
    parse_decimal,
    parse_discount
)
from .column_classifier import classify_header, disambiguate_column_by_content

class TableExtractionEngine:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)

    def extract(self) -> Tuple[List[StatedLineItem], Dict[str, Any], List[StatedTaxSlab]]:
        """
        Main extraction routine.
        Tries cell-block table extraction first; if fewer than 2 items found,
        falls back to geometric coordinate-line extraction.
        """
        line_items, summary, tax_slabs = self._try_cell_block_extraction()
        if len(line_items) < 2:
            geo_items, geo_summary, geo_slabs = self._try_geometric_line_extraction()
            if len(geo_items) > len(line_items):
                line_items = geo_items
                summary = {**summary, **geo_summary}
                tax_slabs = geo_slabs if geo_slabs else tax_slabs

        # Enrich summary with header/footer regex lookups
        header_summary = self._extract_header_summary_metadata()
        for k, v in header_summary.items():
            if v is not None and summary.get(k) is None:
                summary[k] = v

        return line_items, summary, tax_slabs

    def _try_cell_block_extraction(self) -> Tuple[List[StatedLineItem], Dict[str, Any], List[StatedTaxSlab]]:
        """
        Handles ERP outputs where a table has a header row followed by
        data cells containing newline-separated lists of items.
        (e.g., Shri Ajay Medical Agencies, Sri Harsha Pharma).
        """
        all_items: List[StatedLineItem] = []
        summary: Dict[str, Any] = {}
        tax_slabs: List[StatedTaxSlab] = []

        try:
            with pdfplumber.open(self.pdf_path) as pdf:
                for page_idx, page in enumerate(pdf.pages):
                    tables = page.extract_tables()
                    for table in tables:
                        if not table or len(table) < 2:
                            continue

                        # Find the header row
                        header_row_idx = None
                        canonical_columns: Dict[int, str] = {}

                        for r_idx, row in enumerate(table[:5]):
                            non_empty = [c for c in row if c]
                            classified = {}
                            for col_idx, cell in enumerate(row):
                                col_key = classify_header(cell)
                                if col_key:
                                    classified[col_idx] = col_key

                            # If at least 3 essential pharma columns identified
                            essentials = {"product_name", "billed_qty", "batch_number", "rate", "mrp", "taxable_amount"}
                            if len(set(classified.values()) & essentials) >= 2:
                                header_row_idx = r_idx
                                canonical_columns = classified
                                break

                        if header_row_idx is None or header_row_idx + 1 >= len(table):
                            continue

                        data_row = table[header_row_idx + 1]

                        # Check if data_row cells contain newline-separated text lists
                        col_lines: Dict[str, List[str]] = {}
                        max_lines = 0

                        for col_idx, col_key in canonical_columns.items():
                            if col_idx < len(data_row) and data_row[col_idx]:
                                cell_text = str(data_row[col_idx])
                                # Filter out line dividers like '_________'
                                raw_lines = [
                                    line.strip() for line in cell_text.split('\n')
                                    if line.strip() and not line.strip().startswith('__') and not line.strip().startswith('**')
                                ]
                                col_lines[col_key] = raw_lines
                                if len(raw_lines) > max_lines:
                                    max_lines = len(raw_lines)

                        # Also look for unmapped columns and disambiguate by content
                        for col_idx, cell in enumerate(data_row):
                            if col_idx not in canonical_columns and cell:
                                raw_lines = [l.strip() for l in str(cell).split('\n') if l.strip()]
                                guessed_key = disambiguate_column_by_content(raw_lines)
                                if guessed_key and guessed_key not in col_lines:
                                    col_lines[guessed_key] = raw_lines

                        # Anchor by batch_number or rate or product_name
                        anchor_key = "batch_number" if "batch_number" in col_lines else "rate"
                        if anchor_key not in col_lines and "product_name" in col_lines:
                            anchor_key = "product_name"

                        if anchor_key in col_lines:
                            total_rows = len(col_lines[anchor_key])
                            for i in range(total_rows):
                                p_name = col_lines.get("product_name", [""])[i] if i < len(col_lines.get("product_name", [])) else None
                                if not p_name or p_name.upper().startswith("TOTAL") or p_name.upper().startswith("GST"):
                                    continue

                                # Quantities (including compound schemes e.g. 2.5 + 0.5)
                                raw_qty = col_lines.get("billed_qty", [""])[i] if i < len(col_lines.get("billed_qty", [])) else None
                                raw_free = col_lines.get("free_qty", [""])[i] if i < len(col_lines.get("free_qty", [])) else None
                                b_qty, f_qty = parse_compound_quantity(raw_qty or "")
                                if raw_free and f_qty == Decimal("0.0"):
                                    _, f_qty = parse_compound_quantity(raw_free)

                                # Rates and Pricing
                                rate_str = col_lines.get("rate", [""])[i] if i < len(col_lines.get("rate", [])) else None
                                mrp_str = col_lines.get("mrp", [""])[i] if i < len(col_lines.get("mrp", [])) else None
                                ptr_str = col_lines.get("ptr", [""])[i] if i < len(col_lines.get("ptr", [])) else None
                                stated_rate = parse_decimal(rate_str)
                                stated_mrp = parse_decimal(mrp_str)
                                stated_ptr = parse_decimal(ptr_str)

                                # Discount (handles negative like -1.50)
                                raw_disc = col_lines.get("discount", [""])[i] if i < len(col_lines.get("discount", [])) else None
                                gross_for_disc = (b_qty * stated_rate) if (b_qty and stated_rate) else None
                                disc_raw, disc_amt = parse_discount(raw_disc, gross_for_disc)

                                # Amounts
                                tax_str = col_lines.get("taxable_amount", [""])[i] if i < len(col_lines.get("taxable_amount", [])) else None
                                net_str = col_lines.get("net_amount", [""])[i] if i < len(col_lines.get("net_amount", [])) else None
                                stated_taxable = parse_decimal(tax_str)
                                stated_net = parse_decimal(net_str) or stated_taxable

                                # Taxes
                                cgst_str = col_lines.get("cgst_amount", [""])[i] if i < len(col_lines.get("cgst_amount", [])) else None
                                sgst_str = col_lines.get("sgst_amount", [""])[i] if i < len(col_lines.get("sgst_amount", [])) else None
                                gst_rate_str = col_lines.get("gst_rate", [""])[i] if i < len(col_lines.get("gst_rate", [])) else None

                                item = StatedLineItem(
                                    line_number=len(all_items) + 1,
                                    product_name=p_name,
                                    manufacturer=col_lines.get("mfg", [""])[i] if i < len(col_lines.get("mfg", [])) else None,
                                    pack=col_lines.get("pack", [""])[i] if i < len(col_lines.get("pack", [])) else None,
                                    hsn_code=col_lines.get("hsn_code", [""])[i] if i < len(col_lines.get("hsn_code", [])) else None,
                                    batch_number=col_lines.get("batch_number", [""])[i] if i < len(col_lines.get("batch_number", [])) else None,
                                    expiry_date=normalize_expiry(col_lines.get("expiry_date", [""])[i]) if i < len(col_lines.get("expiry_date", [])) else None,
                                    stated_billed_qty=b_qty,
                                    stated_free_qty=f_qty,
                                    stated_mrp=stated_mrp,
                                    stated_rate=stated_rate,
                                    stated_ptr=stated_ptr,
                                    stated_discount_raw=disc_raw,
                                    stated_discount_amount=disc_amt,
                                    stated_taxable_amount=stated_taxable,
                                    stated_cgst_amount=parse_decimal(cgst_str),
                                    stated_sgst_amount=parse_decimal(sgst_str),
                                    stated_gst_rate_pct=parse_decimal(gst_rate_str),
                                    stated_net_amount=stated_net
                                )
                                all_items.append(item)

        except Exception as e:
            # Silently catch and fallback to geometric line extraction
            pass

        return all_items, summary, tax_slabs

    def _try_geometric_line_extraction(self) -> Tuple[List[StatedLineItem], Dict[str, Any], List[StatedTaxSlab]]:
        """
        Handles table lines where each medicine row is a horizontal coordinate band
        (e.g., JP Logistics, Divya Pharma Distributors).
        """
        all_items: List[StatedLineItem] = []
        summary: Dict[str, Any] = {}
        tax_slabs: List[StatedTaxSlab] = []

        for page_idx in range(len(self.doc)):
            page = self.doc[page_idx]
            words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, word_no)

            # Cluster words into horizontal lines with 3.2pt Y tolerance
            line_clusters: Dict[float, List[Any]] = {}
            for w in words:
                y_coord = w[1]
                # Filter out header/footer regions (focus on y between 140 and 650)
                if 140 <= y_coord <= 660:
                    matched = False
                    for existing_y in line_clusters:
                        if abs(y_coord - existing_y) < 3.2:
                            line_clusters[existing_y].append(w)
                            matched = True
                            break
                    if not matched:
                        line_clusters[y_coord] = [w]

            for y_key in sorted(line_clusters.keys()):
                lw = line_clusters[y_key]
                lw.sort(key=lambda w: w[0])  # sort left-to-right by X
                row_text = " ".join(w[4] for w in lw).strip()

                # Skip header repetitions, summary lines, notes
                if any(k in row_text.upper() for k in [
                    "MFAC/", "ITEM DESCRIPTION", "QUANTITY", "BILLED", "SUB TOTAL",
                    "TAXABLE", "TOTAL BILLS", "AMOUNT IN WORDS", "ROUND OFF", "BANK NAME"
                ]):
                    continue

                # An item row typically contains:
                # 1. Product description
                # 2. Batch string or Expiry (MM-YY or MM/YY)
                # 3. Numeric rate, MRP, and net
                has_expiry = bool(re.search(r'\b\d{2}[-/]\d{2,4}\b', row_text))
                has_numbers = len(re.findall(r'\b\d+(?:\.\d+)?\b', row_text)) >= 3

                if has_expiry and has_numbers:
                    item = self._parse_horizontal_line_tokens(lw)
                    if item and item.product_name:
                        item.line_number = len(all_items) + 1
                        all_items.append(item)

        return all_items, summary, tax_slabs

    def _parse_horizontal_line_tokens(self, words: List[Any]) -> Optional[StatedLineItem]:
        """
        Parses a horizontal word list into a structured item by matching
        expiry, batch, quantities, and numeric rates by position & regex.
        """
        tokens = [w[4] for w in words]
        row_str = " ".join(tokens)

        # 1. Locate Expiry token (e.g. 08-26, 12-27, 05/27)
        exp_idx = None
        exp_raw = None
        for i, t in enumerate(tokens):
            if re.match(r'^\d{2}[-/]\d{2,4}$', t):
                exp_idx = i
                exp_raw = t
                break

        if exp_idx is None:
            return None

        # 2. Batch is almost always immediately preceding Expiry
        batch_raw = tokens[exp_idx - 1] if exp_idx > 0 else None

        # 3. Numbers following Expiry: typically MRP, PTR, Rate, Amount, Discount, HSN, Net
        post_exp_numbers = []
        discount_val = None
        hsn_val = None

        for t in tokens[exp_idx + 1:]:
            clean = t.replace(",", "")
            if clean.startswith("-") and parse_decimal(clean) is not None:
                discount_val = clean  # Negative discount found e.g. -1.50
            elif re.match(r'^300\d{3,5}$', clean):
                hsn_val = clean
            elif parse_decimal(clean) is not None:
                post_exp_numbers.append(clean)

        stated_mrp = parse_decimal(post_exp_numbers[0]) if len(post_exp_numbers) > 0 else None
        stated_ptr = parse_decimal(post_exp_numbers[1]) if len(post_exp_numbers) > 1 else None
        stated_rate = parse_decimal(post_exp_numbers[2]) if len(post_exp_numbers) > 2 else stated_ptr
        stated_amount = parse_decimal(post_exp_numbers[3]) if len(post_exp_numbers) > 3 else None
        stated_net = parse_decimal(post_exp_numbers[-1]) if post_exp_numbers else stated_amount

        # 4. Tokens before Batch contain: Manufacturer, Rack, Quantity, Product Name, Pack
        pre_batch_tokens = tokens[:exp_idx - 1] if exp_idx > 1 else []

        # Find quantity: could be "1", "40", "2.5 +0.5", "14+1"
        qty_val = None
        free_val = Decimal("0.0")
        name_tokens = []

        # Search for compound quantity e.g. "2.5", "+0.5"
        for i, t in enumerate(pre_batch_tokens):
            if re.match(r'^\d+(?:\.\d+)?\+\d+(?:\.\d+)?$', t):
                b, f = parse_compound_quantity(t)
                qty_val, free_val = b, f
            elif re.match(r'^\d+(?:\.\d+)?$', t) and qty_val is None and i < 4:
                # If next token is "+0.5"
                if i + 1 < len(pre_batch_tokens) and pre_batch_tokens[i+1].startswith("+"):
                    compound = f"{t}{pre_batch_tokens[i+1]}"
                    b, f = parse_compound_quantity(compound)
                    qty_val, free_val = b, f
                else:
                    qty_val = parse_decimal(t)
            elif not re.match(r'^[A-Z]\d{4}$', t):  # skip rack like A0204
                name_tokens.append(t)

        prod_name = " ".join(name_tokens).strip()

        # Discount parsing
        gross = (qty_val * stated_rate) if (qty_val and stated_rate) else None
        disc_raw, disc_amt = parse_discount(discount_val, gross)

        return StatedLineItem(
            product_name=prod_name if prod_name else "UNKNOWN PRODUCT",
            batch_number=batch_raw,
            expiry_date=normalize_expiry(exp_raw),
            hsn_code=hsn_val,
            stated_billed_qty=qty_val,
            stated_free_qty=free_val,
            stated_mrp=stated_mrp,
            stated_ptr=stated_ptr,
            stated_rate=stated_rate,
            stated_discount_raw=disc_raw,
            stated_discount_amount=disc_amt,
            stated_taxable_amount=stated_amount,
            stated_net_amount=stated_net
        )

    def _extract_header_summary_metadata(self) -> Dict[str, Any]:
        """
        Extracts invoice header metadata (GSTINs, Inv Number, Date)
        and summary figures (Grand Total, Tax Total, Round Off).
        """
        meta: Dict[str, Any] = {}
        full_text = ""
        for page in self.doc:
            full_text += page.get_text() + "\n"

        # Supplier and Recipient GSTINs
        gstins = re.findall(r'\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}\b', full_text)
        if len(gstins) > 0:
            meta["supplier_gstin"] = gstins[0]
        if len(gstins) > 1:
            meta["recipient_gstin"] = gstins[1]

        # Invoice Number
        inv_no_match = re.search(r'(?:Inv(?:oice)?\s*No\.?|Tax\s*Inv\.No\.?)\s*[:.-]?\s*([A-Za-z0-9\/-]+)', full_text, re.IGNORECASE)
        if inv_no_match:
            meta["invoice_number"] = inv_no_match.group(1).strip()

        # Invoice Date
        date_match = re.search(r'(?:Inv(?:oice)?\s*Date|Date)\s*[:.-]?\s*(\d{1,2}[-\/][A-Za-z0-9]{2,3}[-\/]\d{2,4})', full_text, re.IGNORECASE)
        if date_match:
            meta["invoice_date"] = date_match.group(1).strip()

        # Grand Total
        gt_match = re.search(r'(?:Grand\s*Total|NETAmount|Net\s*Amount|Net\s*Payable|Bill\s*Amount)\s*[:.-]?\s*(?:Rs\.?)?\s*([0-9,]+\.\d{2})', full_text, re.IGNORECASE)
        if gt_match:
            meta["stated_grand_total"] = parse_decimal(gt_match.group(1))

        # Round Off
        ro_match = re.search(r'Round\s*off\s*[:.-]?\s*([0-9.-]+)', full_text, re.IGNORECASE)
        if ro_match:
            meta["stated_round_off"] = parse_decimal(ro_match.group(1))

        # Total Tax
        tax_match = re.search(r'(?:Total\s*Tax\s*Amt\.?|Total\s*GST)\s*[:.-]?\s*([0-9,]+\.\d{2})', full_text, re.IGNORECASE)
        if tax_match:
            meta["stated_total_gst"] = parse_decimal(tax_match.group(1))

        return meta
