# AGENTS.md - MediAstra Pharma PDF Purchase Extractor

This repository contains **MediAstra**, an AI/ML and heuristic extraction engine for pharmaceutical distributor purchase invoices.

---

## 🎯 Project Mission & Context

### Why This Exists (Medical Store Owner & Pharmacy Pain Point)
- **Client**: Medical Store Owners, Pharmacists, Hospital Pharmacies, and Pharma Retail ERP operators.
- **Problem**: Receiving 10–50 PDF invoices daily from dozens of distributors. Hand-keying batch numbers, expiry dates, HSN codes, MRP, PTR, schemes (`10+2`), and GST tax slabs into billing software takes 2–4 hours every night and causes stock expiry dispensing and GST ITC mismatches.
- **Outcome**: Automated ingestion of pharma supplier PDFs into structured CSV, Excel, and database formats with 99%+ extraction accuracy and Human-in-the-Loop review.

---

## 🛠️ Technology Stack & Key Files

- **`extractor.py`**: Core extraction engine (fuzzy headers, bleeding columns, compound quantities, row accounting, layout profiles).
- **`app.py`**: Streamlit UI with live PDF preview, column mapping overrides, review session commit, and profile memory management.
- **`batch_processor.py`**: Batch execution engine for multi-invoice ingestion and evaluation benchmarking.
- **`storage/`**: SQLite-backed enterprise storage service (`database.py`, `models.py`, `repositories.py`).
- **`scripts/file_to_md.py`**: Universal file-to-markdown converter to minimize LLM token usage.
- **`.agents/rules/pharma_extractor_rules.md`**: Complete domain engineering specifications.
- **`PROJECT_STATE.md`**: Current development status, roadmap, and cross-IDE continuity ledger.
- **`docs/ARCHITECTURE_AND_CONVERSATIONS.md`**: Complete conversation & implementation recap.

---

## 📋 Core Rules for AI Models

1. **Accounting Invariance**: Never alter invoice financial calculations without strict validation against `Amount = Qty * Rate`, `Taxable = Amount - Disc`, `Net = Taxable + GST`.
2. **Resilience over Fragility**: Ensure layout memory handles both known profiles and novel supplier formats gracefully with human review fallbacks.
3. **Token Economy**: Use `scripts/file_to_md.py` to inspect sample files in token-optimized Markdown.
