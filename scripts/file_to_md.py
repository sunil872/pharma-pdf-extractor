#!/usr/bin/env python3
"""
Universal File to Markdown (file_to_md.py)
-----------------------------------------
Converts any file format (PDF, Excel, CSV, DOCX, JSON, XML, Images, Logs, Code)
into compact, token-optimized Markdown (.md).

Designed to minimize LLM token consumption when uploading documents and data files into chat.

Usage:
    python scripts/file_to_md.py <path_to_file> [--output <path.md>] [--max-rows <n>] [--summary]
"""

import sys
import os
import io
import re
import json
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Any

def estimate_tokens(text: str) -> int:
    """Rough estimate of token count (~4 characters per token)."""
    return max(1, len(text) // 4)

def clean_markdown_text(text: str) -> str:
    """Strip redundant whitespace, empty lines, and noisy characters to save tokens."""
    if not text:
        return ""
    # Normalize line breaks
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Replace 3 or more consecutive newlines with 2
    text = re.sub(r'\n{3,}', '\n\n', text)
    # Strip trailing whitespace on each line
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()

def format_table_as_markdown(headers: List[str], rows: List[List[Any]], max_rows: Optional[int] = None) -> str:
    """Convert tabular headers and rows into clean, token-efficient Markdown tables."""
    if not headers and not rows:
        return ""
    
    clean_headers = [str(h).strip().replace("\n", " ").replace("|", "\\|") if h is not None else "" for h in headers]
    if not clean_headers and rows:
        clean_headers = [f"Col_{i+1}" for i in range(len(rows[0]))]

    # Check if rows exceed max_rows
    total_rows = len(rows)
    displayed_rows = rows
    truncated = False
    if max_rows and len(rows) > max_rows:
        displayed_rows = rows[:max_rows]
        truncated = True

    md_lines = []
    # Header row
    md_lines.append("| " + " | ".join(clean_headers) + " |")
    md_lines.append("| " + " | ".join(["---"] * len(clean_headers)) + " |")

    # Data rows
    for r in displayed_rows:
        # Pad or trim row to match header length
        row_cells = []
        for i in range(len(clean_headers)):
            val = r[i] if i < len(r) else ""
            cell_str = str(val).strip().replace("\n", " ").replace("|", "\\|") if val is not None else ""
            row_cells.append(cell_str)
        md_lines.append("| " + " | ".join(row_cells) + " |")

    if truncated:
        md_lines.append(f"\n*(Truncated: Showing {max_rows} of {total_rows} rows to optimize context tokens)*")

    return "\n".join(md_lines)

# ==================== FORMAT HANDLERS ====================

def convert_pdf_to_md(file_path: Path, max_rows: Optional[int] = None) -> str:
    """Extract text and tables from PDF files into Markdown."""
    try:
        import pdfplumber
    except ImportError:
        return f"# Error\n`pdfplumber` is not installed. Please install with `pip install pdfplumber`."

    md_output = [f"# PDF Document: {file_path.name}\n"]
    
    with pdfplumber.open(file_path) as pdf:
        md_output.append(f"**Total Pages:** {len(pdf.pages)}\n")
        
        for idx, page in enumerate(pdf.pages, start=1):
            md_output.append(f"## Page {idx}")
            
            # Extract tables first
            tables = page.extract_tables()
            if tables:
                for t_idx, table in enumerate(tables, start=1):
                    if not table or len(table) < 1:
                        continue
                    headers = table[0]
                    data_rows = table[1:]
                    md_output.append(f"\n### Table {t_idx} (Page {idx})")
                    md_output.append(format_table_as_markdown(headers, data_rows, max_rows=max_rows))
            
            # Extract raw text (filter out text already in tables if possible or clean it)
            raw_text = page.extract_text()
            if raw_text:
                cleaned = clean_markdown_text(raw_text)
                if cleaned:
                    md_output.append("\n### Page Text Content\n")
                    md_output.append(cleaned)
            
            md_output.append("\n---\n")

    return "\n".join(md_output)

def convert_excel_to_md(file_path: Path, max_rows: int = 50) -> str:
    """Extract all sheets from Excel (.xlsx, .xls) into clean Markdown tables."""
    try:
        import pandas as pd
    except ImportError:
        return f"# Error\n`pandas` is not installed. Please install with `pip install pandas openpyxl`."

    md_output = [f"# Excel Workbook: {file_path.name}\n"]
    
    excel_file = pd.ExcelFile(file_path)
    sheet_names = excel_file.sheet_names
    md_output.append(f"**Sheets ({len(sheet_names)}):** {', '.join(sheet_names)}\n")

    for sheet in sheet_names:
        df = pd.read_excel(excel_file, sheet_name=sheet)
        md_output.append(f"## Sheet: `{sheet}`")
        md_output.append(f"**Dimensions:** {df.shape[0]} rows × {df.shape[1]} columns\n")
        
        if df.empty:
            md_output.append("*(Empty Sheet)*\n")
            continue

        # Drop columns that are completely empty
        df = df.dropna(how='all', axis=1)
        # Drop rows that are completely empty
        df = df.dropna(how='all', axis=0)

        headers = [str(c) for c in df.columns]
        rows = df.values.tolist()
        md_output.append(format_table_as_markdown(headers, rows, max_rows=max_rows))
        md_output.append("\n---\n")

    return "\n".join(md_output)

def convert_csv_to_md(file_path: Path, max_rows: int = 60) -> str:
    """Extract CSV/TSV into clean Markdown tables with token limits."""
    try:
        import pandas as pd
        sep = '\t' if file_path.suffix.lower() == '.tsv' else ','
        df = pd.read_csv(file_path, sep=sep)
        
        md_output = [f"# CSV Data: {file_path.name}\n"]
        md_output.append(f"**Dimensions:** {df.shape[0]} rows × {df.shape[1]} columns\n")
        
        headers = [str(c) for c in df.columns]
        rows = df.values.tolist()
        md_output.append(format_table_as_markdown(headers, rows, max_rows=max_rows))
        return "\n".join(md_output)
    except Exception as e:
        # Fallback to standard reader
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        return f"# CSV File: {file_path.name}\n```csv\n" + "".join(lines[:max_rows]) + "\n```"

def convert_docx_to_md(file_path: Path) -> str:
    """Extract paragraphs and tables from Word DOCX documents."""
    try:
        import docx
    except ImportError:
        return f"# Error\n`python-docx` is not installed. Please install with `pip install python-docx`."

    doc = docx.Document(file_path)
    md_output = [f"# Document: {file_path.name}\n"]

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style_name = para.style.name.lower() if para.style else ""
        if 'heading 1' in style_name:
            md_output.append(f"\n# {text}\n")
        elif 'heading 2' in style_name:
            md_output.append(f"\n## {text}\n")
        elif 'heading 3' in style_name:
            md_output.append(f"\n### {text}\n")
        elif 'bullet' in style_name or 'list' in style_name:
            md_output.append(f"- {text}")
        else:
            md_output.append(f"{text}\n")

    if doc.tables:
        md_output.append("\n## Tables in Document\n")
        for t_idx, table in enumerate(doc.tables, start=1):
            rows_data = []
            for row in table.rows:
                rows_data.append([cell.text.strip() for cell in row.cells])
            if rows_data:
                headers = rows_data[0]
                body = rows_data[1:]
                md_output.append(f"\n### Table {t_idx}")
                md_output.append(format_table_as_markdown(headers, body))

    return "\n".join(md_output)

def convert_json_to_md(file_path: Path, max_depth: int = 4) -> str:
    """Convert JSON files into structured, token-efficient Markdown."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            data = json.load(f)
    except Exception as e:
        return f"# Error reading JSON: {file_path.name}\n```\n{e}\n```"

    md_output = [f"# JSON Structure: {file_path.name}\n"]

    if isinstance(data, list):
        md_output.append(f"**Root Type:** Array with {len(data)} items\n")
        # If it's a list of uniform dicts, format as a table!
        if len(data) > 0 and isinstance(data[0], dict) and len(data[0]) <= 15:
            headers = list(data[0].keys())
            rows = [[item.get(h, "") for h in headers] for item in data if isinstance(item, dict)]
            md_output.append(format_table_as_markdown(headers, rows, max_rows=50))
            return "\n".join(md_output)
    elif isinstance(data, dict):
        md_output.append(f"**Root Keys ({len(data)}):** `{', '.join(list(data.keys())[:20])}`\n")

    # Pretty-print compact JSON
    compact_json = json.dumps(data, indent=2)
    # Truncate if gigantic
    if len(compact_json) > 12000:
        compact_json = compact_json[:12000] + "\n... [Remaining JSON truncated for token economy]"

    md_output.append("```json\n" + compact_json + "\n```")
    return "\n".join(md_output)

def convert_text_to_md(file_path: Path) -> str:
    """Read plain text, code, log, or config files and wrap cleanly."""
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    ext = file_path.suffix.lower().lstrip('.')
    lang_map = {
        'py': 'python', 'js': 'javascript', 'ts': 'typescript',
        'html': 'html', 'css': 'css', 'sql': 'sql', 'sh': 'bash',
        'ps1': 'powershell', 'yml': 'yaml', 'yaml': 'yaml', 'md': 'markdown'
    }
    lang = lang_map.get(ext, ext or 'text')
    cleaned = clean_markdown_text(content)

    return f"# File: {file_path.name}\n```{lang}\n{cleaned}\n```"

def convert_image_to_md(file_path: Path) -> str:
    """Extract OCR text from images if pytesseract is available."""
    try:
        from PIL import Image
        import pytesseract
        
        img = Image.open(file_path)
        ocr_text = pytesseract.image_to_string(img).strip()
        
        md_output = [f"# Image OCR Extract: {file_path.name}\n"]
        md_output.append(f"**Dimensions:** {img.width}x{img.height}px | **Mode:** {img.mode}\n")
        if ocr_text:
            md_output.append("## Extracted OCR Text\n")
            md_output.append(clean_markdown_text(ocr_text))
        else:
            md_output.append("*(No readable text detected via OCR)*")
        return "\n".join(md_output)
    except Exception as e:
        return f"# Image File: {file_path.name}\n*(OCR extraction unavailable: {e})*"

# ==================== MAIN ROUTER ====================

def convert_file_to_md(file_path_str: str, max_rows: int = 50) -> str:
    """Convert any supported file format into optimized Markdown."""
    path = Path(file_path_str)
    if not path.exists():
        return f"Error: File not found at `{file_path_str}`"

    ext = path.suffix.lower()

    if ext == '.pdf':
        return convert_pdf_to_md(path, max_rows=max_rows)
    elif ext in ['.xlsx', '.xls', '.xlsm']:
        return convert_excel_to_md(path, max_rows=max_rows)
    elif ext in ['.csv', '.tsv']:
        return convert_csv_to_md(path, max_rows=max_rows)
    elif ext in ['.docx']:
        return convert_docx_to_md(path)
    elif ext in ['.json', '.jsonl']:
        return convert_json_to_md(path)
    elif ext in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
        return convert_image_to_md(path)
    else:
        return convert_text_to_md(path)

def main():
    parser = argparse.ArgumentParser(description="Convert any file format to token-optimized Markdown for LLM chats.")
    parser.add_argument("file_path", help="Path to input file (PDF, XLSX, CSV, JSON, DOCX, TXT, etc.)")
    parser.add_argument("-o", "--output", help="Optional output .md file path. If omitted, prints to stdout.")
    parser.add_argument("-m", "--max-rows", type=int, default=50, help="Max rows for tables (default: 50)")
    parser.add_argument("-s", "--stats", action="store_true", help="Print token reduction statistics")

    args = parser.parse_args()

    input_path = Path(args.file_path)
    raw_size = input_path.stat().st_size if input_path.exists() else 0

    markdown_result = convert_file_to_md(args.file_path, max_rows=args.max_rows)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(markdown_result, encoding='utf-8')
        print(f"Successfully converted '{input_path.name}' -> '{out_path}'")
    else:
        print(markdown_result)

    if args.stats:
        est_tokens = estimate_tokens(markdown_result)
        print(f"\n--- Statistics ---", file=sys.stderr)
        print(f"Original File Size: {raw_size:,} bytes", file=sys.stderr)
        print(f"Markdown Output Size: {len(markdown_result):,} characters", file=sys.stderr)
        print(f"Estimated Token Cost: ~{est_tokens:,} tokens", file=sys.stderr)

if __name__ == "__main__":
    main()
