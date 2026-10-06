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
