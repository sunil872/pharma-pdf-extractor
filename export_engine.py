"""
MediAstra Export Engine (export_engine.py)
----------------------------------------
Generates enterprise-grade, beautifully formatted Excel spreadsheets (.xlsx),
CSV files, and ERP-compatible structured payloads for retail pharmacy billing software.

Features:
- Professional Pharmacy Excel Styling: Dark Navy headers, clean typography, zebra striping.
- Live Excel Formulas: Auto-summed Taxable, GST, and Net Amount totals with '=SUM(...)'.
- Number & Currency Formatting: Correct currency ('₹ #,##0.00') and percentage ('0.00%') masks.
- Dynamic Column Auto-sizing: Prevents cell clipping ('###' errors).
- Metadata Header Banner: Distributor Name, GSTIN, Invoice Number, and Date.
"""

import io
import pandas as pd
from typing import Dict, Any, Optional, Union
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Palette & Fonts
HEADER_FILL = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")  # Slate 800
HEADER_FONT = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
TITLE_FONT = Font(name="Segoe UI", size=14, bold=True, color="0F172A")
META_LABEL_FONT = Font(name="Segoe UI", size=9, bold=True, color="475569")
META_VALUE_FONT = Font(name="Segoe UI", size=9, bold=False, color="0F172A")
ROW_FONT = Font(name="Segoe UI", size=10, color="1E293B")
TOTAL_FONT = Font(name="Segoe UI", size=11, bold=True, color="0F172A")
TOTAL_FILL = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")  # Slate 200
ZEBRA_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")  # Slate 50

THIN_BORDER_SIDE = Side(border_style="thin", color="CBD5E1")
THIN_BORDER = Border(left=THIN_BORDER_SIDE, right=THIN_BORDER_SIDE, top=THIN_BORDER_SIDE, bottom=THIN_BORDER_SIDE)
TOTAL_TOP_BORDER = Side(border_style="thin", color="64748B")
TOTAL_BOTTOM_BORDER = Side(border_style="double", color="0F172A")
TOTAL_BORDER = Border(top=TOTAL_TOP_BORDER, bottom=TOTAL_BOTTOM_BORDER, left=THIN_BORDER_SIDE, right=THIN_BORDER_SIDE)

# Column Display Configurations
COLUMN_DISPLAY_NAMES = {
    "itemName": "Product / Medicine Name",
    "company": "Mfr / Company",
    "pack": "Pack",
    "batchNo": "Batch No",
    "expiryDate": "Expiry Date",
    "hsnCode": "HSN Code",
    "quantity": "Billed Qty",
    "freeQuantity": "Free Qty",
    "mrp": "MRP (₹)",
    "rate": "PTR / Rate (₹)",
    "discountPercent": "Disc %",
    "discountAmount": "Disc Amt (₹)",
    "taxableAmount": "Taxable Amt (₹)",
    "gstPercent": "GST %",
    "sgstPercent": "SGST %",
    "cgstPercent": "CGST %",
    "gstAmount": "GST Amt (₹)",
    "amount": "Gross Amt (₹)",
    "netAmount": "Net Amt (₹)",
}

CURRENCY_COLUMNS = {"mrp", "rate", "discountAmount", "taxableAmount", "gstAmount", "amount", "netAmount"}
PERCENT_COLUMNS = {"discountPercent", "gstPercent", "sgstPercent", "cgstPercent"}
INT_COLUMNS = {"quantity", "freeQuantity"}
CENTER_COLUMNS = {"batchNo", "expiryDate", "hsnCode", "pack", "company"}


def export_to_formatted_excel(
    df: pd.DataFrame,
    metadata: Optional[Dict[str, Any]] = None,
    output_path: Optional[Union[str, Path]] = None,
) -> bytes:
    """
    Exports an extracted invoice DataFrame into a professionally styled Excel workbook.
    Returns bytes buffer (or saves to output_path if provided).
    """
    if metadata is None:
        metadata = {}

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase Invoice"
    ws.views.sheetView[0].showGridLines = True

    # 1. Title Banner
    ws.merge_cells("A1:H1")
    title_cell = ws["A1"]
    title_cell.value = "MEDIANSTRA PHARMA PURCHASE INVOICE"
    title_cell.font = TITLE_FONT
    title_cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 28

    # 2. Metadata Block
    supplier_name = metadata.get("supplier_name") or metadata.get("supplier") or "Distributor Invoice"
    gstin = metadata.get("gstin") or metadata.get("supplier_gstin") or "N/A"
    invoice_no = metadata.get("invoice_number") or metadata.get("invoice_no") or "N/A"
    invoice_date = metadata.get("invoice_date") or metadata.get("date") or "N/A"

    meta_rows = [
        ("Supplier Name:", str(supplier_name), "Invoice No:", str(invoice_no)),
        ("Supplier GSTIN:", str(gstin), "Invoice Date:", str(invoice_date)),
    ]

    for r_idx, (k1, v1, k2, v2) in enumerate(meta_rows, start=2):
        ws.row_dimensions[r_idx].height = 18
        ws.cell(row=r_idx, column=1, value=k1).font = META_LABEL_FONT
        ws.cell(row=r_idx, column=2, value=v1).font = META_VALUE_FONT
        ws.cell(row=r_idx, column=4, value=k2).font = META_LABEL_FONT
        ws.cell(row=r_idx, column=5, value=v2).font = META_VALUE_FONT

    start_table_row = 5
    ws.row_dimensions[start_table_row - 1].height = 10  # Spacer

    # 3. Clean & Order DataFrame Columns
    clean_df = df.copy()
    # Retain only recognized columns or keep existing
    display_cols = [c for c in clean_df.columns if c in COLUMN_DISPLAY_NAMES]
    if not display_cols:
        display_cols = list(clean_df.columns)

    # 4. Write Table Headers
    ws.row_dimensions[start_table_row].height = 24
    for c_idx, col_name in enumerate(display_cols, start=1):
        cell = ws.cell(row=start_table_row, column=c_idx)
        cell.value = COLUMN_DISPLAY_NAMES.get(col_name, col_name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER

    # 5. Write Data Rows
    current_row = start_table_row + 1
    for r_idx, (_, row_data) in enumerate(clean_df.iterrows(), start=current_row):
        ws.row_dimensions[r_idx].height = 20
        is_even = (r_idx % 2 == 0)
        
        for c_idx, col_name in enumerate(display_cols, start=1):
            cell = ws.cell(row=r_idx, column=c_idx)
            val = row_data.get(col_name, None)

            # Type conversion and formatting
            if col_name in CURRENCY_COLUMNS:
                try:
                    num_val = float(val) if pd.notna(val) else 0.0
                    cell.value = num_val
                    cell.number_format = '"₹"#,##0.00'
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                except (ValueError, TypeError):
                    cell.value = str(val or "")
                    cell.alignment = Alignment(horizontal="left", vertical="center")
            elif col_name in PERCENT_COLUMNS:
                try:
                    num_val = float(val) if pd.notna(val) else 0.0
                    cell.value = num_val
                    cell.number_format = '0.00"%"'
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                except (ValueError, TypeError):
                    cell.value = str(val or "")
                    cell.alignment = Alignment(horizontal="center", vertical="center")
            elif col_name in INT_COLUMNS:
                try:
                    num_val = float(val) if pd.notna(val) else 0.0
                    cell.value = int(num_val) if num_val.is_integer() else num_val
                    cell.number_format = '#,##0' if num_val.is_integer() else '0.###'
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                except (ValueError, TypeError):
                    cell.value = str(val or "")
                    cell.alignment = Alignment(horizontal="right", vertical="center")
            else:
                cell.value = str(val) if pd.notna(val) else ""
                align_h = "center" if col_name in CENTER_COLUMNS else "left"
                cell.alignment = Alignment(horizontal=align_h, vertical="center")

            cell.font = ROW_FONT
            cell.border = THIN_BORDER
            if is_even:
                cell.fill = ZEBRA_FILL
        
        current_row = r_idx

    # 6. Summary / Total Row with Live Excel Formulas
    total_row = current_row + 1
    ws.row_dimensions[total_row].height = 24
    
    first_data_row = start_table_row + 1
    last_data_row = current_row

    for c_idx, col_name in enumerate(display_cols, start=1):
        cell = ws.cell(row=total_row, column=c_idx)
        cell.font = TOTAL_FONT
        cell.fill = TOTAL_FILL
        cell.border = TOTAL_BORDER

        col_letter = get_column_letter(c_idx)
        if col_name in ["itemName", "company"]:
            if c_idx == 1:
                cell.value = "TOTALS / SUMMARY"
                cell.alignment = Alignment(horizontal="left", vertical="center")
        elif col_name in ["quantity", "freeQuantity"]:
            cell.value = f"=SUM({col_letter}{first_data_row}:{col_letter}{last_data_row})"
            cell.number_format = '#,##0'
            cell.alignment = Alignment(horizontal="right", vertical="center")
        elif col_name in ["taxableAmount", "discountAmount", "gstAmount", "amount", "netAmount"]:
            cell.value = f"=SUM({col_letter}{first_data_row}:{col_letter}{last_data_row})"
            cell.number_format = '"₹"#,##0.00'
            cell.alignment = Alignment(horizontal="right", vertical="center")
        else:
            cell.value = ""

    # 7. Auto-fit column widths
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            # Skip title merged banner in width calculation
            if cell.row == 1:
                continue
            val_str = str(cell.value or "")
            if len(val_str) > max_len:
                max_len = len(val_str)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    # Save to buffer
    buf = io.BytesIO()
    wb.save(buf)
    excel_bytes = buf.getvalue()

    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_bytes(excel_bytes)

    return excel_bytes


def export_to_canonical_json(
    items: list,
    metadata: Optional[Dict[str, Any]] = None,
    returns: Optional[list] = None,
) -> Dict[str, Any]:
    """
    Generates an ERP-compatible, cloud-database sync payload formatted for
    pharmacy retail stock list updating and purchase ledger ingestion.
    """
    if metadata is None:
        metadata = {}

    stock_items = []
    total_billed_qty = 0.0
    total_free_qty = 0.0
    total_gross = 0.0
    total_taxable = 0.0
    total_net = 0.0

    for it in (items or []):
        qty = float(it.get("quantity") or 0.0)
        free_qty = float(it.get("freeQuantity") or 0.0)
        rate = float(it.get("rate") or 0.0)
        amount = float(it.get("amount") or 0.0)
        disc_pct = float(it.get("discountPercent") or 0.0)
        taxable = float(it.get("taxableAmount") or (amount * (1.0 - (disc_pct / 100.0))))
        net = float(it.get("netAmount") or taxable)

        total_billed_qty += qty
        total_free_qty += free_qty
        total_gross += amount
        total_taxable += taxable
        total_net += net

        stock_items.append({
            "product_name": it.get("itemName") or it.get("product_name") or "",
            "pack": it.get("pack") or "",
            "batch_no": it.get("batchNo") or "",
            "expiry_date": it.get("expiryDate") or "",
            "hsn_code": it.get("hsnCode") or "",
            "billed_quantity": qty,
            "free_quantity": free_qty,
            "total_received_stock": qty + free_qty,
            "mrp": float(it.get("mrp") or 0.0),
            "ptr_rate": rate,
            "discount_percent": disc_pct,
            "taxable_amount": round(taxable, 2),
            "gst_percent": float(it.get("gstPercent") or 0.0),
            "cgst_percent": float(it.get("cgstPercent") or 0.0),
            "sgst_percent": float(it.get("sgstPercent") or 0.0),
            "line_gross_amount": round(amount, 2),
            "line_net_amount": round(net, 2),
            "accounting_status": it.get("_accounting_proof", {}).get("accounting_status", "VALID"),
            "accounting_confidence": it.get("_accounting_proof", {}).get("accounting_confidence", 1.0),
        })

    payload = {
        "supplier": {
            "name": metadata.get("supplier_name") or metadata.get("supplier") or "UNKNOWN",
            "gstin": metadata.get("gstin") or metadata.get("supplier_gstin") or "",
            "dl_no": metadata.get("dl_no") or "",
        },
        "invoice": {
            "invoice_no": metadata.get("invoice_number") or metadata.get("invoice_no") or "",
            "invoice_date": metadata.get("invoice_date") or metadata.get("date") or "",
            "total_items_count": len(stock_items),
            "total_billed_qty": total_billed_qty,
            "total_free_qty": total_free_qty,
            "total_gross_amount": round(total_gross, 2),
            "total_taxable_amount": round(total_taxable, 2),
            "total_net_amount": round(total_net, 2),
        },
        "stock_update_items": stock_items,
        "returns_adjusted": returns or [],
    }

    return payload


def export_to_marg_csv(
    df: pd.DataFrame,
    metadata: Optional[Dict[str, Any]] = None,
    output_path: Optional[Union[str, Path]] = None,
) -> str:
    """
    Generates Marg ERP 9+ compatible purchase import CSV format.
    Marg is used by over 70% of Indian retail pharmacy stores.
    """
    if metadata is None:
        metadata = {}

    marg_rows = []
    for _, row in df.iterrows():
        item_name = str(row.get("itemName") or "").strip()
        if not item_name:
            continue

        pack = str(row.get("pack") or "").strip()
        batch_no = str(row.get("batchNo") or "").strip()
        exp_date = str(row.get("expiryDate") or "").strip()
        hsn = str(row.get("hsnCode") or "").strip()

        try:
            qty = float(row.get("quantity") or 0.0)
            qty_val = int(qty) if qty.is_integer() else qty
        except (ValueError, TypeError):
            qty_val = 0

        try:
            free_qty = float(row.get("freeQuantity") or 0.0)
            free_val = int(free_qty) if free_qty.is_integer() else free_qty
        except (ValueError, TypeError):
            free_val = 0

        try:
            rate = float(row.get("rate") or 0.0)
        except (ValueError, TypeError):
            rate = 0.0

        try:
            mrp = float(row.get("mrp") or 0.0)
        except (ValueError, TypeError):
            mrp = 0.0

        try:
            disc = float(row.get("discountPercent") or 0.0)
        except (ValueError, TypeError):
            disc = 0.0

        try:
            gst = float(row.get("gstPercent") or 0.0)
        except (ValueError, TypeError):
            gst = 0.0

        try:
            amount = float(row.get("amount") or (qty_val * rate))
        except (ValueError, TypeError):
            amount = 0.0

        try:
            net = float(row.get("netAmount") or (amount * (1.0 - disc / 100.0) * (1.0 + gst / 100.0)))
        except (ValueError, TypeError):
            net = amount

        marg_rows.append({
            "ITEM_NAME": item_name,
            "PACKING": pack,
            "BATCH_NO": batch_no,
            "EXPIRY": exp_date,
            "HSN_CODE": hsn,
            "QTY": qty_val,
            "FREE_QTY": free_val,
            "PURCHASE_RATE": round(rate, 2),
            "MRP": round(mrp, 2),
            "DISC_PER": round(disc, 2),
            "GST_PER": round(gst, 2),
            "GROSS_AMOUNT": round(amount, 2),
            "NET_AMOUNT": round(net, 2),
        })

    marg_df = pd.DataFrame(marg_rows)
    csv_str = marg_df.to_csv(index=False)

    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(csv_str, encoding="utf-8")

    return csv_str


def export_to_tally_xml(
    df: pd.DataFrame,
    metadata: Optional[Dict[str, Any]] = None,
    output_path: Optional[Union[str, Path]] = None,
) -> str:
    """
    Generates standard TallyPrime / Tally.ERP 9 XML Purchase Voucher format with
    inventory item allocations, batch allocations, and CGST/SGST/IGST tax ledgers.
    """
    if metadata is None:
        metadata = {}

    supplier_name = metadata.get("supplier_name") or metadata.get("supplier") or "Sundry Creditors"
    invoice_no = metadata.get("invoice_number") or metadata.get("invoice_no") or "INV-PURCHASE"
    raw_date = metadata.get("invoice_date") or metadata.get("date") or ""

    # Format date as YYYYMMDD for Tally
    tally_date = "20260401"
    if raw_date:
        clean_d = raw_date.replace("-", "").replace("/", "").strip()
        if len(clean_d) == 8 and clean_d.isdigit():
            # If DDMMYYYY convert to YYYYMMDD
            if int(clean_d[:2]) <= 31 and int(clean_d[2:4]) <= 12:
                tally_date = clean_d[4:] + clean_d[2:4] + clean_d[:2]
            else:
                tally_date = clean_d

    inv_entries_xml = []
    total_taxable = 0.0
    total_cgst = 0.0
    total_sgst = 0.0
    total_igst = 0.0
    total_net = 0.0

    for _, row in df.iterrows():
        item_name = str(row.get("itemName") or "").strip()
        if not item_name:
            continue

        batch_no = str(row.get("batchNo") or "PRIMARY").strip()
        exp_date = str(row.get("expiryDate") or "").strip()

        try:
            qty = float(row.get("quantity") or 0.0)
            free_qty = float(row.get("freeQuantity") or 0.0)
        except (ValueError, TypeError):
            qty, free_qty = 0.0, 0.0

        actual_qty = qty + free_qty
        billed_qty = qty

        try:
            rate = float(row.get("rate") or 0.0)
        except (ValueError, TypeError):
            rate = 0.0

        try:
            amount = float(row.get("amount") or (billed_qty * rate))
        except (ValueError, TypeError):
            amount = 0.0

        try:
            disc = float(row.get("discountPercent") or 0.0)
        except (ValueError, TypeError):
            disc = 0.0

        taxable = float(row.get("taxableAmount") or (amount * (1.0 - disc / 100.0)))

        try:
            gst_pct = float(row.get("gstPercent") or 0.0)
            cgst_pct = float(row.get("cgstPercent") or (gst_pct / 2.0))
            sgst_pct = float(row.get("sgstPercent") or (gst_pct / 2.0))
        except (ValueError, TypeError):
            gst_pct, cgst_pct, sgst_pct = 0.0, 0.0, 0.0

        cgst_amt = round(taxable * (cgst_pct / 100.0), 2)
        sgst_amt = round(taxable * (sgst_pct / 100.0), 2)
        net_amt = round(taxable + cgst_amt + sgst_amt, 2)

        total_taxable += taxable
        total_cgst += cgst_amt
        total_sgst += sgst_amt
        total_net += net_amt

        inv_entry = f"""            <ALLINVENTORYENTRIES.LIST>
              <STOCKITEMNAME>{item_name}</STOCKITEMNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <RATE>{rate:.2f}/Nos</RATE>
              <AMOUNT>-{taxable:.2f}</AMOUNT>
              <ACTUALQTY> {actual_qty:.0f} Nos</ACTUALQTY>
              <BILLEDQTY> {billed_qty:.0f} Nos</BILLEDQTY>
              <BATCHALLOCATIONS.LIST>
                <GODOWNNAME>Main Location</GODOWNNAME>
                <BATCHNAME>{batch_no}</BATCHNAME>
                <EXPIRYDATE>{exp_date}</EXPIRYDATE>
                <AMOUNT>-{taxable:.2f}</AMOUNT>
                <ACTUALQTY> {actual_qty:.0f} Nos</ACTUALQTY>
                <BILLEDQTY> {billed_qty:.0f} Nos</BILLEDQTY>
              </BATCHALLOCATIONS.LIST>
            </ALLINVENTORYENTRIES.LIST>"""
        inv_entries_xml.append(inv_entry)

    inv_block = "\n".join(inv_entries_xml)

    # Tax Ledgers
    tax_ledgers = []
    if total_cgst > 0:
        tax_ledgers.append(f"""            <LEDGERENTRIES.LIST>
              <LEDGERNAME>Input CGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>-{total_cgst:.2f}</AMOUNT>
            </LEDGERENTRIES.LIST>""")
    if total_sgst > 0:
        tax_ledgers.append(f"""            <LEDGERENTRIES.LIST>
              <LEDGERNAME>Input SGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>-{total_sgst:.2f}</AMOUNT>
            </LEDGERENTRIES.LIST>""")
    if total_igst > 0:
        tax_ledgers.append(f"""            <LEDGERENTRIES.LIST>
              <LEDGERNAME>Input IGST</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>-{total_igst:.2f}</AMOUNT>
            </LEDGERENTRIES.LIST>""")

    tax_block = "\n".join(tax_ledgers)

    xml_content = f"""<ENVELOPE>
  <HEADER>
    <TALLYREQUEST>Import Data</TALLYREQUEST>
  </HEADER>
  <BODY>
    <IMPORTDATA>
      <REQUESTDESC>
        <REPORTNAME>Vouchers</REPORTNAME>
        <STATICVARIABLES>
          <SVCURRENTCOMPANY>MediAstra Pharmacy</SVCURRENTCOMPANY>
        </STATICVARIABLES>
      </REQUESTDESC>
      <REQUESTDATA>
        <TALLYMESSAGE xmlns:UDF="TallyUDF">
          <VOUCHER VCHTYPE="Purchase" ACTION="Create">
            <DATE>{tally_date}</DATE>
            <VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME>
            <VOUCHERNUMBER>{invoice_no}</VOUCHERNUMBER>
            <REFERENCE>{invoice_no}</REFERENCE>
            <PARTYLEDGERNAME>{supplier_name}</PARTYLEDGERNAME>
            <PARTYNAME>{supplier_name}</PARTYNAME>
            <PERSISTEDVIEW>Invoice Mode</PERSISTEDVIEW>
{inv_block}
            <LEDGERENTRIES.LIST>
              <LEDGERNAME>Purchase Account</LEDGERNAME>
              <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
              <AMOUNT>-{total_taxable:.2f}</AMOUNT>
            </LEDGERENTRIES.LIST>
{tax_block}
            <LEDGERENTRIES.LIST>
              <LEDGERNAME>{supplier_name}</LEDGERNAME>
              <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
              <AMOUNT>{total_net:.2f}</AMOUNT>
            </LEDGERENTRIES.LIST>
          </VOUCHER>
        </TALLYMESSAGE>
      </REQUESTDATA>
    </IMPORTDATA>
  </BODY>
</ENVELOPE>"""

    if output_path:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(xml_content, encoding="utf-8")

    return xml_content


def export_to_busy_vyapar_excel(
    df: pd.DataFrame,
    metadata: Optional[Dict[str, Any]] = None,
    output_path: Optional[Union[str, Path]] = None,
) -> bytes:
    """
    Generates a spreadsheet formatted for Busy Accounting and Vyapar item/purchase import.
    """
    if metadata is None:
        metadata = {}

    rows = []
    for _, r in df.iterrows():
        item_name = str(r.get("itemName") or "").strip()
        if not item_name:
            continue

        try:
            qty = float(r.get("quantity") or 0.0)
            free = float(r.get("freeQuantity") or 0.0)
            rate = float(r.get("rate") or 0.0)
            mrp = float(r.get("mrp") or 0.0)
            disc = float(r.get("discountPercent") or 0.0)
            gst = float(r.get("gstPercent") or 0.0)
            amount = float(r.get("amount") or (qty * rate))
            net = float(r.get("netAmount") or (amount * (1.0 - disc / 100.0) * (1.0 + gst / 100.0)))
        except (ValueError, TypeError):
            qty, free, rate, mrp, disc, gst, amount, net = 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

        rows.append({
            "Item Name": item_name,
            "HSN/SAC": str(r.get("hsnCode") or ""),
            "Unit": str(r.get("pack") or "NOS"),
            "Batch No": str(r.get("batchNo") or ""),
            "Expiry Date": str(r.get("expiryDate") or ""),
            "Billed Qty": qty,
            "Free Qty": free,
            "Purchase Price": rate,
            "MRP": mrp,
            "Discount %": disc,
            "Tax Rate %": gst,
            "Taxable Value": round(amount * (1.0 - disc / 100.0), 2),
            "Total Amount": round(net, 2),
        })

    busy_df = pd.DataFrame(rows)
    return export_to_formatted_excel(busy_df, metadata=metadata, output_path=output_path)

