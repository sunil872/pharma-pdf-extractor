import os
import sys
import json
import re
from rapidfuzz import fuzz, process

sys.path.insert(0, ".")

from extractor import (
    ALIAS_DICT, clean_text, normalize_split_header_text, is_serial_number_header,
    _to_float, parse_compound_qty, GST_STANDARD_RATES, PHARMA_ITEM_WORDS, PACK_PATTERN,
    extract_page_words, detect_coordinate_header_row, determine_column_boundaries,
    detect_logical_subcolumns, assign_tokens_to_columns, _merge_continuation_rows,
    _is_genuine_product_row, _is_footer_row, _is_letterhead_row, standardize_date,
    profile_column, check_arithmetic_relationship, ensure_named_headers, extract_pdf_table
)

from evaluation.field_ground_truth import CANONICAL_FIELDS, CRITICAL_FIELDS, FINANCIAL_FIELDS
from evaluation.field_accuracy import evaluate_canonical_field_accuracy

def run_test():
    print("Testing evaluate_canonical_field_accuracy...")
    res = evaluate_canonical_field_accuracy()
    print(f"Overall Accuracy: {res.overall_field_accuracy}%")
    print(f"Critical Accuracy: {res.overall_critical_field_accuracy}%")
    print(f"Financial Accuracy: {res.overall_financial_field_accuracy}%")
    print(f"Fully Correct Rows: {res.fully_correct_rows}")
    print(f"Critical Error Rows: {res.critical_error_rows}")
    for doc in res.document_reports:
        print(f"  Doc: {doc.filename} | Acc: {doc.field_accuracy}% | Crit: {doc.critical_field_accuracy}% | Dec: {doc.decision}")

if __name__ == "__main__":
    run_test()
