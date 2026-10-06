# 🏥 MediAstra — Pharma Purchase Invoice Extraction Engine

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B.svg)](https://streamlit.io)
[![RapidOCR](https://img.shields.io/badge/OCR-RapidOCR%20ONNX-green.svg)](https://github.com/RapidAI/RapidOCR)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**MediAstra** is an intelligent, high-accuracy extraction engine engineered specifically for pharmaceutical distributor purchase invoices (born-digital PDFs, scanned documents, and bill photos).

It automates the tedious 2–4 hours of manual night-time invoice data entry performed by retail medical stores, hospital pharmacies, and pharma ERP operators—extracting medicine names, batches, expiry dates, HSN codes, MRP, rates, promotional schemes (`10+2`), and GST tax slabs with 99%+ accuracy and strict accounting validation.

---

## 📑 Table of Contents

- [Key Features](#-key-features)
- [System Architecture](#-system-architecture)
- [Supported Invoice Types](#-supported-invoice-types)
- [Quick Start](#-quick-start)
- [Component Overview](#-component-overview)
- [Extraction Pipeline & Heuristics](#-extraction-pipeline--heuristics)
- [Streamlit UI Walkthrough](#-streamlit-ui-walkthrough)
- [Batch Processing & Benchmarks](#-batch-processing--benchmarks)
- [Repository Structure](#-repository-structure)
- [Roadmap & Implementation Plan](#-roadmap--implementation-plan)

---

## ⚡ Key Features

1. **Dual Extraction Engine (Digital + Scanned OCR)**:
   - **Born-Digital PDFs**: Precise coordinate table parsing using `pdfplumber` with word clustering and dynamic boundary detection.
   - **Scanned Invoices & Photos**: 100% offline, zero-API-cost OCR using `RapidOCR` (ONNX Runtime) + `OpenCV` image preprocessing (CLAHE, deskewing, binarization).

2. **Pharma-Specific Intelligence**:
   - **Fuzzy Header Matching**: Auto-maps 50+ distributor header aliases (`Item Description`, `Particulars`, `PTR`, `D.O.E.`, `HSN`, `Batch No.`).
   - **Column Bleeding De-duplication**: Decomposes merged PDF coordinates (e.g., `MRP Rate` or `Batch Expiry` joined together).
   - **Compound Scheme Unpacker**: Splits schemes like `10+2`, `50+5`, or `10*10` into explicit billed quantity vs free promotional stock.
   - **Closed-Form Mathematical Solver**: Automatically repairs broken or misread digits using accounting invariance (`Net = (Qty * Rate - Disc) + GST`).

3. **Layout Profile Memory**:
   - Remembers user corrections keyed by Supplier GSTIN.
   - Supports transactional SQLite persistence (`mediastra.db`) and dual JSON sync (`supplier_profiles.json`, `templates.json`).

4. **Enterprise Formatted Excel Export (`export_engine.py`)**:
   - Generates beautifully styled `.xlsx` sheets with pharmacy headers, currency number formatting (`₹#,##0.00`), zebra striping, and live `=SUM()` formulas.

5. **Human-in-the-Loop Streamlit UI**:
   - Side-by-side interactive PDF/image inspection with editable column remapping and 1-click profile commitment.

---

## 🏛️ System Architecture

```
                                  ┌─────────────────────────────┐
                                  │   Supplier PDF / Images     │
                                  │ (Born-digital / Scanned / JPG)│
                                  └──────────────┬──────────────┘
                                                 │
                                                 ▼
                                  ┌─────────────────────────────┐
                                  │   Document Router           │
                                  │ - Digital -> pdfplumber     │
                                  │ - Scanned -> RapidOCR+CV    │
                                  └──────────────┬──────────────┘
                                                 │
                                                 ▼
                                  ┌─────────────────────────────┐
                                  │   Heuristic & Math Pipeline │
                                  │ - Fuzzy Aliases (rapidfuzz) │
                                  │ - Column Bleeding Repair    │
                                  │ - Compound Quantity Unpack  │
                                  │ - Closed-Form Math Solver   │
                                  └──────────────┬──────────────┘
                                                 │
                                  ┌──────────────┴──────────────┐
                                  ▼                             ▼
                  ┌──────────────────────────────┐ ┌──────────────────────────────┐
                  │ Layout Profile Memory Engine │ │  Streamlit Review UI         │
                  │ (SQLite DB / Profiles JSON)  │ │  (Interactive Column Mapper) │
                  └──────────────┬───────────────┘ └──────────────┬───────────────┘
                                 │                                │
                                 └────────────────┬───────────────┘
                                                  │
                                                  ▼
                                   ┌─────────────────────────────┐
                                   │ Export & Integration Layer  │
                                   │ - Formatted Excel (.xlsx)   │
                                   │ - Clean CSV / JSON          │
                                   │ - SQLite Ingestion          │
                                   └─────────────────────────────┘
```

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.11+
- Virtual environment (recommended)

### 2. Installation

```bash
# Clone the repository
git clone https://github.com/sunil872/pharma-pdf-extractor.git
cd pharma-pdf-extractor

# Create & activate virtual environment
python -m venv .venv
# On Windows PowerShell:
.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Run the Streamlit Application

```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

### 4. Run Batch Processing / Benchmark

```bash
# Process all sample invoices in batch mode
python batch_processor.py "Sample Invoices"
```

---

## 🧩 Component Overview

| Module | File | Description |
|---|---|---|
| **Core Extractor** | [`extractor.py`](file:///extractor.py) | Table coordinate extraction, fuzzy aliases, boundary alignment, row accounting solver, profile lookup. |
| **Local OCR Engine** | [`ocr_engine.py`](file:///ocr_engine.py) | 100% offline OCR with RapidOCR + OpenCV preprocessing for scanned bills and mobile images. |
| **Excel Exporter** | [`export_engine.py`](file:///export_engine.py) | Formatted `.xlsx` exporter with pharmacy theme, currency masks, and live Excel calculation formulas. |
| **Streamlit Web UI** | [`app.py`](file:///app.py) | Interactive purchase import workspace, live PDF viewer, column remapping, batch execution UI. |
| **Batch Processor** | [`batch_processor.py`](file:///batch_processor.py) | Bulk ingestion engine for processing directories of invoices with failure isolation and metrics reporting. |
| **Storage & Persistence** | [`storage/`](file:///storage/) | SQLite database layer (`database.py`, `models.py`, `repositories.py`) with JSON profile sync. |
| **Evaluation Suite** | [`evaluation/`](file:///evaluation/) | Precision benchmark harness comparing extraction results against golden ground truth datasets. |
| **Token Reduction Tool** | [`scripts/file_to_md.py`](file:///scripts/file_to_md.py) | Universal document-to-markdown converter to minimize LLM token usage during inspections. |

---

## 🔬 Extraction Pipeline & Heuristics

1. **Header Identification**:
   - `rapidfuzz.fuzz.token_sort_ratio` matches header tokens against canonical fields (`itemName`, `batchNo`, `expiryDate`, `quantity`, `freeQuantity`, `mrp`, `rate`, `discountPercent`, `hsnCode`, `gstPercent`, `netAmount`).
2. **Column Bleeding Splitter**:
   - Separates merged text in overlapping bounding boxes using regex pattern matchers for alphanumeric tokens and decimal amounts.
3. **Compound Quantity Resolution**:
   - Handles patterns such as `"10+2"` -> `quantity=10, freeQuantity=2`, `"10*10"` -> `quantity=100`, `"2 BOX"` -> `quantity=2, unit="BOX"`.
4. **Closed-Form Accounting Solver**:
   $$\text{Amount} = \text{Quantity} \times \text{Rate}$$
   $$\text{Taxable} = \text{Amount} - \left(\text{Amount} \times \frac{\text{Disc\%}}{100}\right)$$
   $$\text{GST Amount} = \text{Taxable} \times \frac{\text{GST\%}}{100}$$
   $$\text{Net Amount} = \text{Taxable} + \text{GST Amount}$$
   If OCR misreads a single digit (e.g. `'8'` as `'3'`), the solver reconciles the row mathematically.

---

## 📊 Formats Supported

- **Digital PDFs**: Born-digital PDF invoices generated from Marg ERP, Busy, Tally, Vyapar, MedPlus, etc.
- **Scanned PDFs & Photos**: Multi-page scanned bills, PNG, JPEG, TIFF images.
- **Exports**:
  - **Formatted Excel (`.xlsx`)**: Ready for accountant review with formulas and styling.
  - **Standard CSV**: Ready for ERP import (Marg, Tally, Vyapar).
  - **Structured JSON**: Ready for REST APIs and cloud synchronization.
  - **SQLite Database**: Native transaction history stored locally.

---

## 📜 License

This project is licensed under the MIT License — see the LICENSE file for details.
