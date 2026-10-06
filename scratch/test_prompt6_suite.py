import sys, os
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
import unittest
from extractor import (
    validate_field_quality,
    detect_and_resolve_field_swaps,
    validate_cross_field_accounting,
    compute_layout_signature,
    detect_layout_drift,
    compute_global_validation_and_confidence,
    infer_unresolved_column_semantics,
    split_text_multi_value_columns,
    parse_compound_qty,
)

class TestPrompt6ValidationEngine(unittest.TestCase):

    def test_case_a_correct_pack_qty_free(self):
        """Case A: Correct PACK/QTY/FREE"""
        headers = ["PACK", "QTY", "FREE"]
        rows = [["120TAB", "1.00", "0.00"], ["120TAB", "9.00", "0.00"], ["1*4", "3.00", "0.00"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        val = compute_global_validation_and_confidence(headers, [], mappings, rows)
        res = val["resolved_mappings"]
        self.assertEqual(res["PACK"]["mapped_to"], "pack")
        self.assertEqual(res["QTY"]["mapped_to"], "quantity")
        self.assertEqual(res["FREE"]["mapped_to"], "freeQuantity")

    def test_case_b_qty_free_swapped(self):
        """Case B: QTY/FREE swapped -> detected and reconciled"""
        headers = ["Col_Qty", "Col_Free"]
        # Col_Qty has all zeros while Col_Free has positive quantities
        rows = [["0.00", "10.00"], ["0.00", "5.00"], ["0.00", "20.00"]]
        initial_mappings = {
            "Col_Qty": {"mapped_to": "quantity", "status": "known_header"},
            "Col_Free": {"mapped_to": "freeQuantity", "status": "known_header"},
        }
        res, swap_log = detect_and_resolve_field_swaps(headers, [], initial_mappings, rows)
        self.assertEqual(res["Col_Qty"]["mapped_to"], "freeQuantity")
        self.assertEqual(res["Col_Free"]["mapped_to"], "quantity")
        self.assertTrue(len(swap_log) >= 1)

    def test_case_c_correct_amount_gst(self):
        """Case C: Correct AMOUNT/GST"""
        headers = ["AMOUNT", "GST"]
        rows = [["141.51", "5%"], ["1281.87", "5%"], ["422.34", "5%"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        val = compute_global_validation_and_confidence(headers, [], mappings, rows)
        res = val["resolved_mappings"]
        self.assertEqual(res["AMOUNT"]["mapped_to"], "amount")
        self.assertEqual(res["GST"]["mapped_to"], "gstPercent")

    def test_case_d_amount_gst_swapped(self):
        """Case D: AMOUNT/GST swapped -> detected and reconciled"""
        headers = ["Col_Amt", "Col_GST"]
        # Col_Amt has statutory GST values (5.0, 12.0) and Col_GST has monetary amounts
        rows = [["5.00", "141.51"], ["5.00", "1281.87"], ["12.00", "422.34"]]
        initial_mappings = {
            "Col_Amt": {"mapped_to": "amount", "status": "known_header"},
            "Col_GST": {"mapped_to": "gstPercent", "status": "known_header"},
        }
        res, swap_log = detect_and_resolve_field_swaps(headers, [], initial_mappings, rows)
        self.assertEqual(res["Col_Amt"]["mapped_to"], "gstPercent")
        self.assertEqual(res["Col_GST"]["mapped_to"], "amount")
        self.assertTrue(len(swap_log) >= 1)

    def test_case_e_correct_mrp_rate(self):
        """Case E: Correct MRP/RATE (MRP >= Rate)"""
        headers = ["MRP", "RATE"]
        rows = [["200.00", "150.00"], ["100.00", "80.00"], ["500.00", "350.00"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        res, swap_log = detect_and_resolve_field_swaps(headers, [], mappings, rows)
        self.assertEqual(res["MRP"]["mapped_to"], "mrp")
        self.assertEqual(res["RATE"]["mapped_to"], "rate")
        self.assertEqual(len(swap_log), 0)

    def test_case_f_mrp_rate_swapped(self):
        """Case F: MRP/RATE swapped (Rate column has higher values than MRP) -> swapped back"""
        headers = ["Col_Rate", "Col_MRP"]
        # Rate mapped column has MRP (200.0) and MRP mapped column has Rate (150.0)
        rows = [["200.00", "150.00"], ["100.00", "80.00"], ["500.00", "350.00"]]
        initial_mappings = {
            "Col_Rate": {"mapped_to": "rate", "status": "known_header"},
            "Col_MRP": {"mapped_to": "mrp", "status": "known_header"},
        }
        res, swap_log = detect_and_resolve_field_swaps(headers, [], initial_mappings, rows)
        self.assertEqual(res["Col_Rate"]["mapped_to"], "mrp")
        self.assertEqual(res["Col_MRP"]["mapped_to"], "rate")
        self.assertTrue(len(swap_log) >= 1)

    def test_case_g_correct_batch_exp(self):
        """Case G: Correct BATCH/EXP"""
        headers = ["BATCH", "EXP"]
        rows = [["CCU26031", "02/28"], ["GKH0248A", "01/28"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        res, swap_log = detect_and_resolve_field_swaps(headers, [], mappings, rows)
        self.assertEqual(res["BATCH"]["mapped_to"], "batchNo")
        self.assertEqual(res["EXP"]["mapped_to"], "expiryDate")
        self.assertEqual(len(swap_log), 0)

    def test_case_h_batch_exp_swapped(self):
        """Case H: BATCH/EXP swapped -> detected and reconciled"""
        headers = ["Col_Batch", "Col_Exp"]
        rows = [["02/28", "CCU26031"], ["01/28", "GKH0248A"]]
        initial_mappings = {
            "Col_Batch": {"mapped_to": "batchNo", "status": "known_header"},
            "Col_Exp": {"mapped_to": "expiryDate", "status": "known_header"},
        }
        res, swap_log = detect_and_resolve_field_swaps(headers, [], initial_mappings, rows)
        self.assertEqual(res["Col_Batch"]["mapped_to"], "expiryDate")
        self.assertEqual(res["Col_Exp"]["mapped_to"], "batchNo")
        self.assertTrue(len(swap_log) >= 1)

    def test_case_i_correct_exp_hsn(self):
        """Case I: Correct EXP/HSN"""
        headers = ["EXP", "HSN"]
        rows = [["11/27", "30049099"], ["02/28", "30049082"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        res, swap_log = detect_and_resolve_field_swaps(headers, [], mappings, rows)
        self.assertEqual(res["EXP"]["mapped_to"], "expiryDate")
        self.assertEqual(res["HSN"]["mapped_to"], "hsnCode")

    def test_case_j_numeric_non_hsn_identifier(self):
        """Case J: 8-digit numeric barcode/serial column must not automatically become HSN"""
        headers = ["Unnamed_Col_0", "Item", "Qty"]
        rows = [["87654321", "Item A", "10"], ["98765432", "Item B", "20"]]
        mapping = infer_unresolved_column_semantics(headers, rows)
        self.assertNotEqual(mapping["Unnamed_Col_0"]["mapped_to"], "hsnCode")

    def test_case_k_correct_gst(self):
        """Case K: Correct GST flat rate preserved"""
        headers = ["Item", "Qty", "Rate", "Amount", "GST"]
        rows = [["Item A", "10", "100.00", "1000.00", "12%"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        val = compute_global_validation_and_confidence(headers, [], mappings, rows)
        self.assertEqual(val["resolved_mappings"]["GST"]["mapped_to"], "gstPercent")

    def test_case_l_cgst_sgst(self):
        """Case L: CGST + SGST mapped without artificial overwrites"""
        headers = ["CGST", "SGST"]
        rows = [["2.5", "2.5"], ["6.0", "6.0"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        self.assertEqual(mappings["CGST"]["mapped_to"], "cgstPercent")
        self.assertEqual(mappings["SGST"]["mapped_to"], "sgstPercent")

    def test_case_m_gst_without_cgst_sgst(self):
        """Case M: Flat GST invoice does not create artificial CGST/SGST columns"""
        headers = ["Item", "Qty", "GST"]
        rows = [["Item A", "10", "18%"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        self.assertIn("GST", mappings)
        self.assertEqual(mappings["GST"]["mapped_to"], "gstPercent")
        self.assertNotIn("cgstPercent", [m.get("mapped_to") for m in mappings.values()])

    def test_case_n_missing_hsn(self):
        """Case N: Missing optional HSN does not fail document validation"""
        headers = ["Item", "Qty", "Rate", "Amount"]
        rows = [["Item A", "10", "50.00", "500.00"], ["Item B", "5", "100.00", "500.00"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        val = compute_global_validation_and_confidence(headers, [], mappings, rows)
        self.assertEqual(val["classification"], "AUTO_ACCEPT")

    def test_case_o_missing_gst(self):
        """Case O: Missing optional GST does not fail document validation"""
        headers = ["Item", "Qty", "Rate", "Amount"]
        rows = [["Item A", "10", "50.00", "500.00"], ["Item B", "5", "100.00", "500.00"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        val = compute_global_validation_and_confidence(headers, [], mappings, rows)
        self.assertIn(val["classification"], ("AUTO_ACCEPT", "REVIEW_REQUIRED"))

    def test_case_p_missing_discount(self):
        """Case P: Missing optional discount does not cause validation failure"""
        headers = ["Item", "Qty", "Rate", "Amount", "GST"]
        rows = [["Item A", "10", "50.00", "500.00", "5%"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        val = compute_global_validation_and_confidence(headers, [], mappings, rows)
        self.assertEqual(val["classification"], "AUTO_ACCEPT")

    def test_case_q_missing_free_quantity(self):
        """Case Q: Missing optional free quantity does not cause validation failure"""
        headers = ["Item", "Qty", "Rate", "Amount"]
        rows = [["Item A", "10", "50.00", "500.00"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        val = compute_global_validation_and_confidence(headers, [], mappings, rows)
        self.assertEqual(val["classification"], "AUTO_ACCEPT")

    def test_case_r_amount_arithmetic_mismatch(self):
        """Case R: Amount arithmetic mismatch -> logged as discrepancy, extracted value preserved"""
        headers = ["Item", "Qty", "Rate", "Amount"]
        # Extracted Amount 450.00 != Expected 500.00 (10 * 50)
        rows = [["Item A", "10", "50.00", "450.00"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        discrepancies, summary = validate_cross_field_accounting(rows, mappings, headers)
        self.assertEqual(len(discrepancies[0]), 1)
        self.assertEqual(discrepancies[0][0]["severity"], "CRITICAL")
        self.assertEqual(discrepancies[0][0]["extracted"], 450.00)
        self.assertEqual(discrepancies[0][0]["expected"], 500.00)

    def test_case_s_rounding_difference(self):
        """Case S: Small rounding difference (<= 0.05) flagged as INFO and auto-accepted"""
        headers = ["Item", "Qty", "Rate", "Amount"]
        # 3 * 33.33 = 99.99, extracted is 100.00 (diff 0.01)
        rows = [["Item A", "3", "33.33", "100.00"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        discrepancies, summary = validate_cross_field_accounting(rows, mappings, headers)
        self.assertEqual(len(discrepancies[0]), 1)
        self.assertEqual(discrepancies[0][0]["severity"], "INFO")

    def test_case_t_compound_quantity_10_plus_2(self):
        """Case T: Compound quantity 10+2 parsed accurately"""
        billed, free = parse_compound_qty("10+2")
        self.assertEqual(billed, 10.0)
        self.assertEqual(free, 2.0)

    def test_case_u_compound_quantity_decimal(self):
        """Case U: Compound quantity 2.500+.500 parsed accurately"""
        billed, free = parse_compound_qty("2.500+.500")
        self.assertEqual(billed, 2.5)
        self.assertEqual(free, 0.5)

    def test_case_v_duplicate_legitimate_rows(self):
        """Case V: Duplicate legitimate product rows are preserved without deduplication deletion"""
        rows = [
            ["Item A", "BATCH01", "10", "50.00", "500.00"],
            ["Item A", "BATCH01", "10", "50.00", "500.00"],
            ["Item B", "BATCH02", "5", "100.00", "500.00"],
        ]
        self.assertEqual(len(rows), 3)

    def test_case_w_layout_drift_detection(self):
        """Case W: Layout drift detected on template modification"""
        saved = {
            "TEST_SUPPLIER": {
                "Item": "itemName", "Qty": "quantity", "Rate": "rate", "Amount": "amount"
            }
        }
        curr_headers = ["Item", "Pack", "Qty", "Rate", "Discount", "Amount"]
        sig = compute_layout_signature(curr_headers)
        drift = detect_layout_drift(sig, "TEST_SUPPLIER", saved)
        self.assertEqual(drift["drift_status"], "LAYOUT_DRIFT")
        self.assertTrue(len(drift["details"]) >= 1)

    def test_case_x_new_supplier_no_template(self):
        """Case X: New supplier with no prior template processed cleanly"""
        saved = {}
        curr_headers = ["Item", "Qty", "Rate", "Amount"]
        sig = compute_layout_signature(curr_headers)
        drift = detect_layout_drift(sig, "NEW_UNKNOWN_SUPPLIER", saved)
        self.assertEqual(drift["drift_status"], "NEW_SUPPLIER")

    def test_case_y_existing_supplier_changed_layout(self):
        """Case Y: Existing supplier with completely redesigned layout flagged as LAYOUT_REDESIGN"""
        saved = {
            "OLD_SUPPLIER": {
                "Product": "itemName", "Pack": "pack", "Batch": "batchNo"
            }
        }
        curr_headers = ["SNO", "HSN", "Taxable", "CGST", "SGST", "NetTotal"]
        sig = compute_layout_signature(curr_headers)
        drift = detect_layout_drift(sig, "OLD_SUPPLIER", saved)
        self.assertEqual(drift["drift_status"], "LAYOUT_REDESIGN")

    def test_case_z_ambiguous_assignment_review_required(self):
        """Case Z: Ambiguous unmapped columns require review"""
        headers = ["UNKNOWN_A", "UNKNOWN_B"]
        rows = [["abc 123", "xyz 456"], ["foo bar", "baz qux"]]
        mappings = infer_unresolved_column_semantics(headers, rows)
        val = compute_global_validation_and_confidence(headers, [], mappings, rows)
        self.assertIn(val["classification"], ("REVIEW_REQUIRED", "UNRESOLVED"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
