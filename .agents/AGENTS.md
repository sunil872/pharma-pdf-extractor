# AGENTS.md - MediAstra Pharma PDF Purchase Extractor

This repository contains **MediAstra**, a specialized AI/ML and heuristic extraction engine for pharmaceutical distributor purchase invoices.

---

## 🎯 Project Mission & Context

### Why This Exists (Business & Medical Store Problem)
- **Client**: Medical Store Owners, Pharmacists, Hospital Pharmacies, and Pharma Retail ERP operators.
- **Problem**: Receiving 10–50 PDF invoices daily from dozens of distributors. Hand-keying batch numbers, expiry dates, HSN codes, MRP, PTR, schemes (`10+2`), and GST tax slabs into billing software takes 2–4 hours every night and causes fatal stock expiry dispensing and GST ITC mismatches.
- **Outcome**: 100% automated ingestion of pharma supplier PDFs into structured CSV, Excel, and database formats with 99%+ extraction accuracy and Human-in-the-Loop review.

---

## 🛠️ Technology Stack & Tools

- **Core Extraction**: Python 3.11+, `pdfplumber`, `rapidfuzz`, `pandas`, `pydantic`.
- **UI & Review Interface**: Streamlit (`app.py`) with custom CSS layout preview, interactive column mapper, and review validation.
- **Layout Memory**: Dual JSON/SQLite persistence (`storage/database.py`, `storage/repositories.py`, `supplier_profiles.json`) keyed by distributor GSTIN.
- **Batch Processing**: `batch_processor.py` for parallel/bulk directory ingestion and accuracy benchmarking.
- **Token-Saving Markdown Tool**: `scripts/file_to_md.py` & `.agents/skills/file-to-md/` for converting any incoming format to token-efficient Markdown.

---

## 📋 Operating Procedures for AI Agents

Whenever working in this repository:
1. **Understand the Domain**: Check [.agents/rules/pharma_extractor_rules.md](file:///.agents/rules/pharma_extractor_rules.md) for full field contracts, accounting formulas, and column bleeding rules.
2. **Review Historical State**: Check [PROJECT_STATE.md](file:///PROJECT_STATE.md) and [docs/ARCHITECTURE_AND_CONVERSATIONS.md](file:///docs/ARCHITECTURE_AND_CONVERSATIONS.md) to understand current implementation progress before proposing code changes.
3. **Save Token Budget**: Convert any input sample files to Markdown using `scripts/file_to_md.py <path>` before discussing in chat context.
4. **Preserve Accounting Invariance**: Validate row-level mathematics (`Amount = Qty * Rate`, `Taxable = Amount - Discount`, `Net = Taxable + GST`) on any parser changes.
5. **Run Tests & Benchmarks**: Always verify against `Sample Invoices/` after modifying `extractor.py` or `batch_processor.py`.
