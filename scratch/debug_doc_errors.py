import os
import sys
import json
import re

sys.path.insert(0, ".")

import extractor
from scratch.test_prompt19_engine import generic_global_semantic_assignment

extractor.infer_unresolved_column_semantics = generic_global_semantic_assignment

from evaluation.field_accuracy import evaluate_canonical_field_accuracy

res = evaluate_canonical_field_accuracy()
print("="*80)
print(f"OVERALL ACCURACY: {res.overall_field_accuracy}%")
print(f"CRITICAL ACCURACY: {res.overall_critical_field_accuracy}%")
print(f"FINANCIAL ACCURACY: {res.overall_financial_field_accuracy}%")
print(f"FULLY CORRECT ROWS: {res.fully_correct_rows}")
print(f"PARTIALLY CORRECT ROWS: {res.partially_correct_rows}")
print(f"CRITICAL ERROR ROWS: {res.critical_error_rows}")
print("="*80)

for doc in res.document_reports:
    print(f"Doc: {doc.filename:35s} | FieldAcc: {doc.overall_field_accuracy:6.2f}% | CritAcc: {doc.critical_field_accuracy:6.2f}% | FinAcc: {doc.financial_field_accuracy:6.2f}% | Dec: {doc.decision}")
    # Print mistakes
    for r_i, r_eval in enumerate(doc.row_evaluations):
        if r_eval.classification.value != "FULLY_CORRECT":
            mismatches = []
            for f, m in r_eval.field_results.items():
                if m.value in ("MISMATCH", "MISSING", "UNEXPECTED"):
                    mismatches.append(f"{f}:{m.value}")
            if mismatches:
                print(f"   Row {r_i+1} [{r_eval.classification.value}]: {', '.join(mismatches)}")
                if r_eval.detected_high_risk_errors:
                    print(f"      High Risk: {r_eval.detected_high_risk_errors}")
