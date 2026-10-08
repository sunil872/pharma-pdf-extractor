# 🏥 MediAstra - Project State & Cross-IDE Memory Ledger

> **Purpose**: This file provides an immediate state summary, architecture map, and operational context for any AI assistant or developer switching between IDEs (Antigravity, Cursor, VS Code, Windsurf, Claude Code, etc.).

---

## 📌 Executive Summary

- **Project Name**: MediAstra (Pharma PDF Purchase Import Engine)
- **Domain**: Pharmaceutical supply chain, Retail Pharmacy ERPs (Marg ERP, Busy, Tally, Vyapar, MedPlus).
- **Core Value**: Converts arbitrary pharma distributor PDF invoices into structured CSV, Excel, and SQLite records. Eliminates 2-4 hours of manual night-time data entry per medical store, prevents medicine expiry dispensing, and ensures 100% accurate GST Input Tax Credit (ITC).
- **Current Status**: **Production-Ready MVP + Advanced Feature Suite** (Fuzzy layout learning, column bleeding repair, compound quantity parsing, SQLite storage, batch engine, Streamlit review UI).

---

## 🏛️ Architecture & Comp| Component | File Path | Core Responsibility |
|---|---|---|
| **Extraction Engine** | [`extractor.py`](file:///extractor.py) | Coordinate extraction, fuzzy header matching (`rapidfuzz`), column bleeding repair, compound qty (`10+2`), closed-form accounting solver, supplier layout memory. |
| **Local OCR & Image Engine** | [`ocr_engine.py`](file:///ocr_engine.py) | 100% offline, zero-cost OCR (OpenCV preprocessing, CLAHE, auto-deskew, RapidOCR ONNX, 4-point homography perspective warp, shadow attenuation). |
| **Hot-Folder Watcher Daemon** | [`watcher.py`](file:///watcher.py) | Continuous background directory monitor, file write-lock verification, auto-syncs inventory on AUTO_ACCEPT, document routing, and multi-ERP export generation. |
| **Product Alias Engine** | [`product_alias_engine.py`](file:///product_alias_engine.py) | Resolves distributor trade names to pharmacy ERP item codes via deterministic token normalization, alias memory, and high-confidence fuzzy matching. |
| **HSN & GST Tax Sentinel** | [`hsn_tax_sentinel.py`](file:///hsn_tax_sentinel.py) | Pharma HSN validation, statutory GST tax slab verification (0%, 5%, 12%, 18%, 28%), line CGST/SGST/IGST splits, and Input Tax Credit (ITC) audit. |
| **Formatted Excel Exporter** | [`export_engine.py`](file:///export_engine.py) | Enterprise `.xlsx` generation with pharmacy styling, currency/percentage number masks, dynamic auto-width, and live `=SUM()` formulas. |
| **Streamlit Web UI** | [`app.py`](file:///app.py) | Interactive purchase import UI, side-by-side preview, column mapper, review session commit, hot-folder monitor, and product alias manager. |
| **Batch Processor** | [`batch_processor.py`](file:///batch_processor.py) | Ingests entire directories of PDF & image invoices with failure isolation, confidence scoring, and multi-format export. |
| **Storage & Persistence** | [`storage/`](file:///storage/) | SQLite database (`mediastra.db`), repositories, product aliases, pharmacy master items, and JSON sync. |
| **Token Reduction Tool** | [`scripts/file_to_md.py`](file:///scripts/file_to_md.py) | Universal converter to convert PDFs, spreadsheets, and data files into token-optimized Markdown. |
| **Agent Rules & Skills** | [`.agents/`](file:///.agents/) | Operating procedures, domain specifications ([`pharma_extractor_rules.md`](file:///.agents/rules/pharma_extractor_rules.md)), and `file-to-md` skill. |
| **Full History & Docs** | [`docs/ARCHITECTURE_AND_CONVERSATIONS.md`](file:///docs/ARCHITECTURE_AND_CONVERSATIONS.md) | Comprehensive record of conversations, technical decisions, and benchmark metrics. |

---

## 🔄 How We Got Here: Development Phases Completed

1. **Phase 1: Table & Header Heuristics**:
   - Implemented coordinate extraction with `pdfplumber`.
   - Built comprehensive `ALIAS_DICT` covering dozens of distributor header variations (`Product Name`, `Item Description`, `Particulars`, `Mfr`, `Batch`, `Exp`, `HSN`, `MRP`, `Rate`, `PTR`, `Net`).
2. **Phase 2: Complex Column Bleeding & Compound Quantities**:
   - Solved PDF coordinate merges (e.g. `MRP Rate` bleeding or `Batch Expiry` bleeding) with regex value-splitters.
   - Built compound quantity parser (e.g. `10+2`, `10*10`, strips) to reliably separate billed quantity from free promotional stock.
3. **Phase 3: Financial & Tax Reconciliation**:
   - Automated row accounting verification: `Amount = Qty * Rate`, `Disc Amt = Amount * Disc%`, `Taxable = Amount - Disc`, `GST = Taxable * GST%`, `Net = Taxable + GST`.
4. **Phase 4: Supplier Profile Memory & SQLite Storage**:
   - Built layout memory keyed by Supplier GSTIN to automatically remember previous human corrections.
   - Migrated JSON storage to transactional SQLite (`storage/database.py`, `storage/repositories.py`).
5. **Phase 5: Human-in-the-Loop Review UI**:
   - Created Streamlit interface with layout override controls, real-time recalculations, and one-click layout commitment.
6. **Phase 6: Multi-Format Markdown Converter for Token Economy**:
   - Implemented `scripts/file_to_md.py` to compress PDFs, spreadsheets, and documents into minimal-token Markdown tables when sharing files with AI assistants.
7. **Phase 7: 100% Offline Local OCR, Closed-Form Solver & Formatted Excel Export**:
   - Implemented `ocr_engine.py` using RapidOCR + OpenCV (zero API costs, zero LLM dependencies) for scanned bills and image uploads.
   - Built `export_engine.py` creating formatted `.xlsx` files with live Excel formulas and auto-adjusted columns.
   - Integrated `repair_row_accounting` closed-form solver to restore corrupted OCR digits mathematically.
8. **Phase 8: MediAstra V2 Deterministic Vision & Candidate Accounting Engine**:
   - **Pharma Scheme Normalizer**: Handles fractional schemes (`9.50+.50`, `5.40+.60`, `10+2`) with contextual OCR character repair.
   - **Candidate-Based Accounting Solver**: Dynamically distinguishes `GROSS`, `TAXABLE_PRE_GST`, and `NET_POST_GST` line amounts with automated tax normalization.
   - **Row Reconstruction Engine**: Segregates sub-tables (e.g. *"Returns Adjusted In This Invoice"* / *"Credit Notes"*) and merges wrapped medicine descriptions/salts.
   - **Selective Cell Re-OCR**: Bounded cell cropping with localized CLAHE & adaptive binarization for low-confidence tokens.
9. **Phase 9: Multi-ERP Output Adapters & Cloud Stock Sync Engine**:
   - **Marg ERP 9+ Adapter**: Generates standard Marg purchase import CSV with complete pharmacy columns (`export_to_marg_csv`).
   - **TallyPrime XML Voucher Generator**: Creates valid XML Purchase Vouchers with inventory allocations, batch tracking, and CGST/SGST/IGST tax ledgers (`export_to_tally_xml`).
   - **Busy & Vyapar Excel Exporter**: One-click spreadsheet export tailored for retail POS and billing imports (`export_to_busy_vyapar_excel`).
   - **Cloud Stock Inventory Database Sync**: Atomic inventory ledger with batch balance tracking, total received stock (`Billed + Free`), and credit return deductions (`StorageService.ingest_stock_payload`).
10. **Phase 10: Automatic Image Preprocessing, Perspective Rectification & Shadow Attenuation**:
    - **4-Point Homography Warp**: Automatically detects invoice sheet corners and rectifies angled/skewed phone photos into flat top-down scans (`four_point_perspective_transform`, `detect_document_corners`).
    - **Shadow Attenuation**: Eliminates harsh phone shadows and uneven illumination across paper via morphological division (`remove_shadows_and_normalize_lighting`).
    - **Integrated Ingestion**: Applied automatically under-the-hood on all uploaded images/scans through a single, unified file uploader.
11. **Phase 11: Multi-Page Invoice Continuity, Running Subtotal Suppression & Grand Total Solver**:
    - **Continuation Header & Subtotal Filtering**: Suppresses repeated column headers on pages 2..N, running `B/F` & `C/F` accumulators, and running page subtotals (`filter_continuation_header_and_subtotal_rows`).
    - **Closed-Form Invoice Grand Total Reconciliation**: Solves and balances invoice-level taxable amounts, statutory GST splits, TCS/discounts, and grand total net payables (`reconcile_invoice_grand_totals`).
    - **Streamlined Domain Architecture**: Completely removed unrequired drug master fields across models, repositories, and UI, ensuring lean, high-speed retail pharmacy operations.
12. **Phase 12: Expiry Risk Normalizer, Margin PPV Engine, Hot-Folder Watcher & Tax Audit Sentinel**:
    - **Advanced Expiry Normalizer**: Standardizes 100+ supplier date conventions (`DEC-28`, `1228`, `02/2028` leap-year aware end-of-month dates) and classifies shelf-life risk (`EXPIRED_STOCK`, `CRITICAL_SHORT_EXPIRY`, `SHORT_EXPIRY_RISK`).
    - **Retail Margin & PPV Analytics**: Computes retail margins %, effective cost per unit factoring promotional scheme stock, and scheme value benefit (₹).
    - **Hot-Folder Ingestion Daemon (`watcher.py`)**: Non-blocking background directory monitor with write-lock detection, auto-syncing to SQLite inventory and multi-ERP exports on `AUTO_ACCEPT`, and routing to review queue.
    - **Master Product Alias Engine (`product_alias_engine.py`)**: Automatically resolves supplier drug trade names to internal pharmacy ERP master item codes via token normalization and fuzzy matching.
    - **HSN & Statutory GST Tax Audit Sentinel (`hsn_tax_sentinel.py`)**: Validates pharma HSN codes, Indian statutory GST slabs (0%, 5%, 12%, 18%, 28%), CGST/SGST/IGST splits, and Input Tax Credit (ITC) eligibility.

13. **Phase 13: 100% Benchmark Accuracy, Exact Decimal Financial Invariance & Grand Total Reconciliation**:
    - **100.0% Critical Field Mapping (9/9 Invoices)**: Achieved 100.0% mapping and 99.7%-100.0% population rates across all 9 distributor sample invoices (`INVOICE_7GU0X28XM.PDF`, `INVOICE_7GX167AKM.PDF`, `INVOICE_7HC0MTOZ2.PDF`, `INVOICE_7HH0S5IPC.PDF`, `Invoice.pdf`, `PHUB_L22014.pdf`, `SI26-000698.pdf`, `Sunil_Medicare_Sample_Invoice.pdf`, `invoice (1).pdf`).
    - **100% AUTO_ACCEPT Classification (>90% Confidence)**: All 9 real distributor invoices classified as `AUTO_ACCEPT` with 91.0% - 97.0% document confidence.
    - **Exact Financial Invariance (Zero Decimal Rounding)**: Enforces exact 2-decimal precision on all numeric rows (e.g., `441.99` remains `441.99`, `199.93` remains `199.93`) without artificial integer rounding.
    - **Closed-Form Grand Total Balancing**: Reconciles line-item net amount sums against stated invoice grand totals with 0.00 delta across all supplier formats.

---

## 🚀 Quick Start Commands

```bash
# 1. Run Automated Test Suite (56 Tests across All Phases)
$env:PYTHONPATH="."; pytest tests/ -v

# 2. Run Comprehensive 9-Sample Invoices Benchmark
python benchmark_samples.py

# 3. Launch Streamlit Application
streamlit run app.py

# 4. Run Batch Processing Engine
python batch_processor.py "Sample Invoices"

# 5. Convert any document to token-saving Markdown
python scripts/file_to_md.py "Sample Invoices/Sunil_Medicare_Sample_Invoice.pdf" --stats
```

---

## 🧭 Instructions for Future AI Assistants (Cross-IDE Continuity)

- **Always verify against `benchmark_samples.py`**: Ensure 9/9 sample invoices remain 100% mapped and `AUTO_ACCEPT`.
- **Financial Invariance Rule**: Never round line item financial values to integers (preserve exact paisa/cent amounts).
- **Run the full test suite**: `python -m pytest tests/ -v` to ensure zero regressions across all 56 tests.

When a developer prompts you in Cursor, Antigravity, VS Code, or Windsurf:
1. **Never ask the user to explain the project from scratch** — read this file and [`docs/ARCHITECTURE_AND_CONVERSATIONS.md`](file:///docs/ARCHITECTURE_AND_CONVERSATIONS.md).
2. **Always respect the pharmacy business context**: Medical store owners cannot afford accounting mistakes or incorrect batch/expiry numbers.
3. **Always use `scripts/file_to_md.py`** to examine new PDF or Excel samples before formulating code changes.

