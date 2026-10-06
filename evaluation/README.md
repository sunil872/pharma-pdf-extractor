# MediAstra Invoice Diversity Evaluation & Error Analysis Framework

This directory contains the independent evaluation system for the MediAstra Pharma PDF Import Engine (Prompt 12).

---

## 1. Directory Structure

```text
evaluation/
    ├── README.md               # Documentation & usage instructions
    ├── manifest.json           # Evaluation dataset manifest with SHA-256 and metadata
    ├── ground_truth.json       # Optional custom ground truth store
    ├── models.py               # Core dataclasses, enums, and metrics schemas
    ├── ground_truth.py         # Ground truth loader and verified reference data
    ├── evaluator.py            # Field, row, column, calibration, and safety analyzer
    ├── report_generator.py     # JSON and Markdown report producer
    ├── results/
    │   └── evaluation_results.json
    └── reports/
        └── evaluation_report.md
```

---

## 2. Dataset Categories

The evaluation framework strictly separates invoice sets into 4 distinct categories:

1. **`GOLDEN`**: The immutable 9 benchmark PDFs (`benchmark_manifest.json`) preserved for baseline regression.
2. **`REAL`**: Genuine supplier invoices provided from production environments.
3. **`SYNTHETIC`**: Programmatically generated or adapted stress invoices for boundary testing.
4. **`EDGE_CASE`**: Specifically curated invoices containing severe visual deformations or complex composite layouts.

---

## 3. Evaluation Metrics

### A. Field-Level Metrics
- **Exact Match**: Predicted raw string or number exactly equals ground truth.
- **Normalized Match**: Matches after whitespace collapsing, case folding, and date format alignment (`DD/MM/YY` -> `DD/MM/YYYY`).
- **Numeric Tolerance Match**: Per-field tolerance matching:
  - `quantity`, `freeQuantity`: $\pm 0.01$
  - `discountPercent`: $\pm 0.05\%$
  - `rate`, `mrp`: $\pm 0.05$ or $0.5\%$
  - `amount`, `taxableAmount`, `netAmount`: $\pm 0.10$ or $0.5\%$
  - `cgstPercent`, `sgstPercent`, `gstPercent`: $\pm 0.10\%$
- **Precision, Recall, F1**: Computed per canonical field.

### B. Row-Level Metrics
- **Expected vs Extracted Rows**
- **Matched Rows** (evaluated against product name / batch signatures)
- **Missing / Extra Rows**
- **Duplicate, Merged, and Split Row Detection**

### C. Column Mapping & Confusion Matrix
- Physical / logical column -> predicted canonical field vs expected canonical field.
- Mapping confusion matrix (e.g. `rate -> mrp`, `qty -> freeQty`).

### D. Root-Cause Pipeline Stage Taxonomy
Every detected extraction defect is classified into root causes:
- `HEADER_RECONSTRUCTION`
- `COLUMN_BOUNDARY`
- `LOGICAL_SUBCOLUMN_SPLIT`
- `SEMANTIC_MAPPING`
- `VALUE_NORMALIZATION`
- `ROW_RECONSTRUCTION`
- `SUPPLIER_IDENTITY`
- `LAYOUT_MATCHING`
- `ACCOUNTING_VALIDATION`
- `CONFIDENCE_DECISION`
- `PDF_EXTRACTION`
- `UNKNOWN`

---

## 4. Running the Evaluation

To run evaluation programmatically:

```python
from evaluation.evaluator import InvoiceEvaluator
from evaluation.report_generator import EvaluationReportGenerator

evaluator = InvoiceEvaluator()
results = evaluator.run_evaluation()

reporter = EvaluationReportGenerator()
json_path = reporter.save_json_results(results)
md_path = reporter.generate_markdown_report(results)
print(f"Results saved to {json_path} and {md_path}")
```
