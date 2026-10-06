---
name: file-to-md
description: Convert any document, spreadsheet, or structured data format (PDF, XLSX, CSV, DOCX, JSON, XML, Images) into compact, token-optimized Markdown (.md) to minimize LLM token consumption in chats.
---

# File to Markdown Converter Skill (`file-to-md`)

This skill provides an automated workflow to convert arbitrary file formats into clean, dense, token-saving Markdown before analyzing or discussing them in chat sessions.

## Purpose & Token Efficiency Rationale
- **Direct PDF / Binary / Large Excel uploads** waste tens of thousands of LLM context tokens with repetitive formatting, styling tags, empty rows, and bloated whitespace.
- **Conversion to Markdown** condenses tabular structures into GitHub-style Markdown tables, extracts text hierarchies, and reduces token consumption by **60% - 85%**.

## How to Use

### 1. Command Line Execution
To convert any file in the workspace to Markdown:
```bash
# Print to stdout
python scripts/file_to_md.py path/to/document.pdf

# Save to a .md file
python scripts/file_to_md.py path/to/data.xlsx -o output_data.md

# Limit table rows for mega spreadsheets
python scripts/file_to_md.py path/to/large_sheet.csv -m 30

# View token reduction stats
python scripts/file_to_md.py path/to/document.pdf --stats
```

### 2. Supported Formats
- **PDF (`.pdf`)**: Extracts coordinate tables into clean Markdown tables + extracts textual header/footer metadata.
- **Excel (`.xlsx`, `.xls`)**: Iterates through all sheets, cleans empty cells/columns, and outputs markdown tables.
- **CSV / TSV (`.csv`, `.tsv`)**: Formats structured columns into compact GitHub markdown tables.
- **Word (`.docx`)**: Preserves headings, bullets, paragraphs, and embedded tables.
- **JSON / XML (`.json`, `.xml`)**: Formats into compact hierarchical code blocks or markdown tables (for lists of records).
- **Images (`.png`, `.jpg`, `.jpeg`)**: Performs OCR text extraction using Tesseract / PIL.
- **Code / Text / Logs (`.py`, `.log`, `.txt`, `.sql`)**: Cleans multi-line blank runs and wraps in syntax-highlighted fences.

## Best Practices for LLMs / Agents
- When the user uploads a document or refers to a new sample file, run `scripts/file_to_md.py <file>` to inspect the structured contents in minimal tokens.
- When outputting large tables in responses, truncate past 20-30 rows and indicate summary counts.
