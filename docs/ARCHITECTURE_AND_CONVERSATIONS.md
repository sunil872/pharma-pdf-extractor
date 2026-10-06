# MediAstra: Architecture, Technical Decisions & Conversation Log

---

## 1. Domain Deep Dive & Business Context

### 🏥 The Retail Pharmacy Reality
In India and global pharmaceutical retail markets, independent retail pharmacies and hospital dispensaries purchase inventory from 15–40 authorized pharmaceutical distributors (e.g., Abbott, Cipla, Sun Pharma, Zydus, Alkem, Micro Labs, Mankind, Mankind, Torrent, etc.).

Each distributor uses disparate billing software (e.g., Marg ERP 9+, Busy, TallyPrime, custom legacy DOS software). Consequently, distributor purchase invoices feature wildly different layouts:
- Some place **Batch** before **Expiry**, others place **Expiry** first.
- Some print **Pack Size** embedded inside the **Item Name** (e.g., `THYRONORM 100MG 100S`).
- Some print compound quantities like `10+2` (10 billed, 2 free scheme units).
- Some invoices merge columns (column bleeding) where `MRP` and `Rate` share a single table cell coordinate.
- Some invoices split GST into separate CGST/SGST columns, while others show a single GST% rate.

### 💰 Business Impact
1. **Time Saved**: An average pharmacy owner spends **90–150 minutes every single night** manually typing invoice line items into their store software. MediAstra reduces this to **under 30 seconds per invoice**.
2. **Error Prevention**: Manual entry errors in medicine batch or expiry dates can cause drug recalls or regulatory penalties from Drug Inspectors.
3. **Financial Protection**: Precise extraction ensures full claim of GST Input Tax Credit (ITC) on GSTR-2B.

---

## 2. Technical System Architecture

```
                                  ┌─────────────────────────────┐
                                  │   Supplier PDF Invoices     │
                                  │ (Born-digital / Scan / etc) │
                                  └──────────────┬──────────────┘
                                                 │
                                                 ▼
                                  ┌─────────────────────────────┐
                                  │   extractor.py Pipeline     │
                                  │ - pdfplumber Coordinates    │
                                  │ - Fuzzy Aliases (rapidfuzz) │
                                  │ - Column Bleeding Repair    │
                                  │ - Compound Quantity Unpack  │
                                  │ - Row Accounting & Tax Math │
                                  └──────────────┬──────────────┘
                                                 │
                                 ┌───────────────┴──────────────┐
                                 │                              │
                                 ▼                              ▼
                 ┌──────────────────────────────┐ ┌──────────────────────────────┐
                 │ Layout Profile Memory Engine │ │  Streamlit Review UI         │
                 │ (SQLite DB / Profiles JSON)  │ │  (app.py - Human in loop)    │
                 └──────────────┬───────────────┘ └──────────────┬───────────────┘
                                │                                │
                                └────────────────┬───────────────┘
                                                 │
                                                 ▼
                                  ┌─────────────────────────────┐
                                  │ Output / Export Adapters    │
                                  │ - Structured CSV / Excel    │
                                  │ - SQLite Database Record    │
                                  │ - Marg / Tally / ERP Sync   │
                                  └─────────────────────────────┘
```

---

## 3. Detailed Component Breakdown

### A. `extractor.py` - Core Processing Logic
- **`ALIAS_DICT`**: Extensive fuzzy mapping dictionary mapping diverse distributor column names (e.g., `Particulars`, `Item Description`, `Product Name` -> `itemName`; `PTR`, `Unit Rate`, `Basic Rate` -> `rate`; `Exp`, `Expiry`, `D.O.E` -> `expiryDate`).
- **`extract_pdf_table()`**: Primary extraction function utilizing `pdfplumber` bounding boxes with dynamic table boundary detection.
- **`fix_column_bleeding()`**: Heuristic parser detecting merged cells and splitting them using regex (e.g. splitting decimal numbers or alphanumeric batch codes).
- **`parse_compound_qty()`**: Decomposes scheme strings like `"10+2"`, `"50+5"`, or `"10*10"` into explicit `quantity` and `freeQuantity`.
- **`compute_row_accounting()`**: Reconciles `Amount`, `Discount Amount`, `Taxable Amount`, `GST Amount`, and `Net Amount`.
- **`load_supplier_profiles()` & `update_supplier_profile_memory()`**: Dynamic memory layer keyed by distributor GSTIN.

### B. `app.py` - Streamlit Web Application
- Provides an intuitive web UI for pharmacy operators.
- Renders side-by-side interactive document inspection: raw PDF viewer on the left, extracted table with editable dropdown mappings on the right.
- Visual alerts (green = confident match, yellow = review required, red = accounting mismatch).
- One-click commit: when a user fixes a column mapping, the system saves the layout profile to memory for future invoices from that supplier.

### C. `storage/` - Persistence Service
- **`database.py`**: SQLite database initialization, transaction management, WAL mode.
- **`models.py`**: Pydantic and dataclass models for Supplier Profiles, Layout Signatures, Invoices, and Line Items.
- **`repositories.py`**: Repository layer for querying, creating, and updating supplier profile memory and extracted documents.

### D. `batch_processor.py` - Batch Engine & Benchmarks
- Processes entire folders of PDF invoices asynchronously.
- Aggregates document success rates, field extraction accuracy, and performance timings.

### E. `scripts/file_to_md.py` & `.agents/skills/file-to-md/` - Token Reduction Utility
- Converts PDF invoices, Excel spreadsheets, CSVs, DOCX, and JSON into compact, token-dense Markdown tables.
- Reduces LLM token usage by up to 85% during chat-based file inspection and debugging.

---

## 4. Chronological Conversation & Decision Log

| Milestone / Decision | Context & Rationale | Outcome |
|---|---|---|
| **Initial Extractor Design** | Built foundational table extractor using `pdfplumber` and `rapidfuzz`. | Solved basic digital PDF extraction for single-table invoices. |
| **Handling Supplier Variability** | Distributor invoices presented 50+ variations in column names. | Created `ALIAS_DICT` and header priority scoring. |
| **Column Bleeding Challenge** | Adjacent columns (e.g., MRP + Rate, Batch + Expiry) often merged in PDF coordinates. | Implemented `fix_column_bleeding()` regex decomposition. |
| **Pharma Schemes & Compound Qty** | Distributors frequently offer free goods (e.g., `10+2` scheme). Standard parsers failed or dropped free stock. | Created `parse_compound_qty()` to separate billed vs free stock. |
| **Layout Profile Memory** | Users did not want to re-map columns every day for the same distributor. | Implemented layout profile persistence keyed by GSTIN. |
| **Storage Architecture** | Upgraded from raw JSON to transactional SQLite database (`storage/`). | Enhanced concurrency, reliability, and auditability. |
| **Cross-IDE Continuity & Token Economy** | Standardized rules in `.agents/` and created `file_to_md.py` to save tokens. | Instant project orientation for any AI agent across IDEs. |

---

## 5. Benchmark & Quality Metrics

- **Sample Invoices Evaluated**: 9 diverse distributor layouts (`Sample Invoices/`).
- **Field Extraction Target**:
  - `itemName`, `batchNo`, `expiryDate`: **> 99% accuracy**
  - `quantity`, `rate`, `mrp`, `netAmount`: **100% mathematical consistency**
  - `hsnCode`, `gstPercent`: **> 98% accuracy**
