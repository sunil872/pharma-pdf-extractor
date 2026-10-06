# Pharma PDF Extractor: AI/ML Engineering & Domain Operating Rules

## 1. Domain Persona & Strategic Purpose (The "Why")

### Client Persona: Medical Store Owner & Pharmacy Billing Operator
- **Target Users**: Retail chemist shops, pharmacy chains, wholesale stockists, and hospital pharmacy billing desks.
- **The Core Problem**: Every day, a pharmacy receives 10 to 50 paper/PDF purchase invoices from diverse pharmaceutical distributors (e.g., Cipla, Sun Pharma, Abbott, Alkem, Micro Labs, Vardhman, local stockists).
- **The Cost of Manual Entry**:
  1. **Time Drain**: Staff spends 2 to 4 hours every evening hand-typing 50-200 line items per invoice into billing software (Marg ERP, Tally, Busy, Vyapar, Retailio).
  2. **Audit & Regulatory Penalties**: Typing errors in **Batch Numbers** or **Expiry Dates** lead to dispensing expired stock or severe penalties during Drug Inspector regulatory audits (Drugs & Cosmetics Act).
  3. **GST Input Tax Credit (ITC) Losses**: Misclassifying HSN codes or GST rates (0%, 5%, 12%, 18%) causes GSTR-2B reconciliation mismatches and locked working capital.
  4. **Margin Leakage**: Failing to capture distributor schemes, cash discounts, and compound quantities (`10+2` free goods) distorts the true purchase price (PTR/PTS).
- **The Solution**: **MediAstra Pharma PDF Purchase Import Engine** — an automated, resilient extraction and normalization pipeline that converts messy distributor PDF invoices into clean, validated CSV/XLSX/database records ready for 1-click ERP sync.

---

## 2. Product Scope & Capabilities (The "What")

### Standard Pharma Invoice Data Contract
Every extracted record must conform to the normalized schema:
- **Supplier Identification**: Distributor Name, GSTIN, DL Number, Invoice Number, Invoice Date.
- **Product Details**: Item / Drug Name, Manufacturer / Brand (`Mfr`), Pack Size (`10S`, `100ML`, `15's`).
- **Batch & Traceability**: Batch Number (`batchNo`), Expiry Date (`MM/YY` or `MM/YYYY` normalized).
- **Regulatory & Tax Codes**: HSN / SAC Code (4-8 digits), GST Slab (CGST % + SGST % or IGST %).
- **Stock Quantities**: Billed Quantity (`quantity`), Free / Scheme Quantity (`freeQuantity`), Compound Quantity (e.g., `10+2`).
- **Commercial Accounting**:
  - `mrp`: Maximum Retail Price printed on pack
  - `rate`: Price to Retailer (PTR / Unit Rate)
  - `discountPercent` / `discountAmount`: Trade discount given by distributor
  - `taxableAmount`: `(quantity * rate) - discountAmount`
  - `gstAmount`: `taxableAmount * (gstPercent / 100)`
  - `netAmount`: `taxableAmount + gstAmount`

---

## 3. Technical Pipeline Architecture (The "How")

```
[Distributor PDF Invoice]
         │
         ▼
[1. PDF Plumber / Coordinate Table Extraction]
         │
         ▼
[2. Fuzzy Header Matching & Alias Priority Scoring (rapidfuzz)]
         │
         ▼
[3. Column Bleeding Detection & Value Unpacking]
         │
         ▼
[4. Compound Quantity Parsing ('10+2' -> Qty: 10, Free: 2)]
         │
         ▼
[5. Row-Level Accounting & Tax Consistency Verification]
         │
         ▼
[6. Distributor Layout Profile Memory (SQLite / JSON)]
    ├── Match Existing Profile? ──> Apply Proven Coordinate Schema
    └── Novel Layout? ────────────> Infer & Propose for Review
         │
         ▼
[7. Streamlit Human-in-the-Loop Review UI]
         │
         ▼
[8. Normalized Export: SQLite Database, Excel (.xlsx), CSV, ERP Sync]
```

---

## 4. AI/ML Engineering Protocols & Coding Standards

1. **Deterministic Financial Math**:
   - Never hallucinate or heuristically guess financial values when mathematical constraints exist.
   - Always enforce: `Net = (Qty * Rate - Discount) + GST`.
2. **Column Bleeding Resilience**:
   - In noisy PDFs, PDFPlumber often merges adjacent columns (e.g. `MRP Rate` into `"150.00 110.00"` or `Batch Exp` into `"B2401 05/27"`).
   - Use `fix_column_bleeding()` with regex pattern splitters to safely decompose merged text.
3. **Layout Memory Preservation**:
   - Store learned distributor mappings in `supplier_profiles.json` and SQLite database keyed by distributor GSTIN / Name hash.
   - Boost layout confidence after human review confirmation.
4. **Safety & Fallbacks**:
   - If confidence falls below 85% or accounting reconciliation fails by > ₹1.00, flag the row with an amber alert for human confirmation in the Streamlit UI.
5. **Token Economy Discipline**:
   - When ingesting test documents or inspecting data structures, use `scripts/file_to_md.py` to compress tabular representations into Markdown tables to prevent context window bloat.
