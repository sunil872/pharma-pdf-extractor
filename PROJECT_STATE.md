# 🏥 MediAstra - Project State & Cross-IDE Memory Ledger

> **Purpose**: This file provides an immediate state summary, architecture map, and operational context for any AI assistant or developer switching between IDEs (Antigravity, Cursor, VS Code, Windsurf, Claude Code, etc.).

---

## 📌 Executive Summary

- **Project Name**: MediAstra (Pharma PDF Purchase Import Engine)
- **Domain**: Pharmaceutical supply chain, Retail Pharmacy ERPs (Marg ERP, Busy, Tally, Vyapar, MedPlus).
- **Core Value**: Converts arbitrary pharma distributor PDF invoices into structured CSV, Excel, and SQLite records. Eliminates 2-4 hours of manual night-time data entry per medical store, prevents medicine expiry dispensing, and ensures 100% accurate GST Input Tax Credit (ITC).
- **Current Status**: **Production-Ready MVP + Advanced Feature Suite** (Fuzzy layout learning, column bleeding repair, compound quantity parsing, SQLite storage, batch engine, Streamlit review UI).

---

## 🏛️ Architecture & Component Map

| Component | File Path | Core Responsibility |
|---|---|---|
| **Extraction Engine** | [`extractor.py`](file:///extractor.py) | Coordinate extraction, fuzzy header matching (`rapidfuzz`), column bleeding repair, compound qty (`10+2`), row accounting, supplier layout memory. |
| **Streamlit Web UI** | [`app.py`](file:///app.py) | Interactive purchase import UI, side-by-side PDF preview, column mapper, review session commit, batch runner. |
| **Batch Processor** | [`batch_processor.py`](file:///batch_processor.py) | Ingests entire directories of supplier invoices with failure isolation, confidence scoring, and multi-format export. |
| **Storage & Persistence** | [`storage/`](file:///storage/) | SQLite database (`mediastra.db`), repositories, and JSON sync (`supplier_profiles.json`, `templates.json`). |
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

---

## 🚀 Quick Start Commands

```bash
# 1. Launch Streamlit Application
streamlit run app.py

# 2. Run Batch Processing Benchmark
python batch_processor.py "Sample Invoices"

# 3. Convert any document to token-saving Markdown
python scripts/file_to_md.py "Sample Invoices/Sunil_Medicare_Sample_Invoice.pdf" --stats
```

---

## 🧭 Instructions for Future AI Assistants (Cross-IDE Continuity)

When a developer prompts you in Cursor, Antigravity, VS Code, or Windsurf:
1. **Never ask the user to explain the project from scratch** — read this file and [`docs/ARCHITECTURE_AND_CONVERSATIONS.md`](file:///docs/ARCHITECTURE_AND_CONVERSATIONS.md).
2. **Always respect the pharmacy business context**: Medical store owners cannot afford accounting mistakes or incorrect batch/expiry numbers.
3. **Always use `scripts/file_to_md.py`** to examine new PDF or Excel samples before formulating code changes.
