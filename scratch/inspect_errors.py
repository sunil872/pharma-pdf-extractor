import sys, os
sys.path.insert(0, os.path.abspath("."))
from evaluation.field_accuracy import evaluate_canonical_field_accuracy

def inspect_all_errors():
    res = evaluate_canonical_field_accuracy()
    print("=== EVALUATION RESULTS ===")
    print(f"Overall Accuracy: {res.overall_field_accuracy}% ({res.total_correct_cells}/{res.total_known_cells})")
    print(f"Critical Accuracy: {res.overall_critical_field_accuracy}%")
    print(f"Financial Accuracy: {res.overall_financial_field_accuracy}%")
    print("Root causes:", res.root_cause_distribution)
    
    for doc in res.document_reports:
        print(f"\n--- Document: {doc.filename} ({doc.supplier_name}) ---")
        print(f"  Rows: {doc.extracted_rows}/{doc.expected_rows}, Acc: {doc.overall_field_accuracy}%, Decision: {doc.decision}")
        mismatches = []
        for r_idx, r in enumerate(doc.row_evaluations):
            for fld, m_type in r.field_results.items():
                if m_type in ["MISMATCH", "MISSING", "UNEXPECTED"]:
                    mismatches.append((r.row_index, fld, m_type.value))
        print(f"  Mismatches ({len(mismatches)}):")
        for r_idx, fld, m_type_val in mismatches[:12]:
            print(f"    Row {r_idx} [{fld}]: {m_type_val}")

if __name__ == "__main__":
    inspect_all_errors()
