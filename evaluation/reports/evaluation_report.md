# MediAstra Pharma PDF Extractor — Real-World Evaluation & Error Analysis Report

**Generated at**: `2026-09-16T06:19:10Z`  
**Total Documents Evaluated**: `9`  
**Total Duration**: `60.86 s` (avg `6762.3 ms/doc`)

## 1. Dataset Summary

| Category | Document Count | AUTO_ACCEPT | REVIEW_REQUIRED | UNRESOLVED | FAILED |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **GOLDEN** | 9 | 2 | 5 | 2 | 0 |
| **GOLDEN_V1** | 0 | 0 | 0 | 0 | 0 |
| **REAL** | 0 | 0 | 0 | 0 | 0 |
| **SYNTHETIC** | 0 | 0 | 0 | 0 | 0 |
| **EDGE_CASE** | 0 | 0 | 0 | 0 | 0 |
| **OTHER** | 0 | 0 | 0 | 0 | 0 |


## 2. Supplier & Layout Diversity

- **Unique Verified Suppliers**: `9`
- **Unique Verified GSTINs**: `8`
- **Unique Layout Profiles**: `1`
- **Avg Layouts per Supplier**: `1.00`

## 3. Field-Level Performance

| Canonical Field | Ground Truth | Extracted | Exact Match | Norm/Tol Match | Precision | Recall | F1 Score |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |


## 4. Row-Level Performance

- **Expected Benchmark Rows**: `148`
- **Extracted Rows**: `151`
- **Correctly Reconstructed Rows**: `147`
- **Missing Rows**: `1` | **Extra Rows**: `4`
- **Duplicate Rows**: `0` | **Split Rows**: `0` | **Merged Rows**: `0`
- **Overall Row Accuracy**: **`97.4%`**

## 5. Semantic Mapping Confusion Matrix

| Expected Canonical Field | Predicted Field | Frequency | Status |
| :--- | :--- | :--- | :--- |
| `itemName` | `itemName` | 2 | ✅ Match |
| `pack` | `pack` | 10 | ✅ Match |
| `company` | `company` | 2 | ✅ Match |
| `expiryDate` | `expiryDate` | 9 | ✅ Match |
| `mrp` | `mrp` | 9 | ✅ Match |
| `rate` | `rate` | 10 | ✅ Match |
| `quantity` | `quantity` | 8 | ✅ Match |
| `freeQuantity` | `freeQuantity` | 6 | ✅ Match |
| `discountPercent` | `discountPercent` | 8 | ✅ Match |
| `amount` | `amount` | 7 | ✅ Match |
| `gstPercent` | `gstPercent` | 6 | ✅ Match |
| `hsnCode` | `hsnCode` | 8 | ✅ Match |
| `batchNo` | `batchNo` | 8 | ✅ Match |
| `sgstPercent` | `sgstPercent` | 2 | ✅ Match |
| `taxableAmount` | `taxableAmount` | 2 | ✅ Match |
| `netAmount` | `netAmount` | 3 | ✅ Match |
| `cgstPercent` | `cgstPercent` | 1 | ✅ Match |


## 6. Confidence Calibration Analysis

| Confidence Range | Documents | Fully Correct | Incorrect | Review Reqd | Unresolved | Empirical Accuracy |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `0-50` | 2 | 1 | 1 | 0 | 2 | **50.0%** |
| `50-60` | 0 | 0 | 0 | 0 | 0 | **0.0%** |
| `60-70` | 2 | 2 | 0 | 2 | 0 | **100.0%** |
| `70-80` | 1 | 0 | 1 | 1 | 0 | **0.0%** |
| `80-90` | 0 | 0 | 0 | 0 | 0 | **0.0%** |
| `90-95` | 1 | 1 | 0 | 1 | 0 | **100.0%** |
| `95-100` | 3 | 2 | 1 | 1 | 0 | **66.7%** |


## 7. AUTO_ACCEPT Safety Analysis

- **Total AUTO_ACCEPT Invoices**: `2`
- **Fully Verified Correct**: `2`
- **With Field Errors**: `0`
- **With Row Errors**: `0`
- **AUTO_ACCEPT Precision**: **`100.0%`**
- **AUTO_ACCEPT Error Rate**: **`0.0%`**

## 8. REVIEW_REQUIRED & UNRESOLVED Analysis

### REVIEW_REQUIRED (`5` documents)

- No explicit validation warnings logged.


### UNRESOLVED (`2` documents)

- Root Cause: `LOGICAL_SUBCOLUMN_SPLIT` (1 documents)
- Root Cause: `UNKNOWN` (1 documents)


## 9. Root-Cause Pipeline Distribution

| Pipeline Stage Root Cause | Detected Error Occurrences | Percentage |
| :--- | :--- | :--- |
| `TRUE_COLUMN_BOUNDARY_ERROR` | 16 | 100.0% |


## 10. Recommended Engineering Priorities (Evidence-Backed)

1. **Continuous Pipeline Validation**: Maintain current coordinate and sub-column reconstruction routines.
