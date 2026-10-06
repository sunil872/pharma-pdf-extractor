import sys, os
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
import unittest
from extractor import (
    detect_logical_subcolumns,
    split_text_multi_value_columns,
    infer_unresolved_column_semantics,
    parse_compound_qty,
    reconstruct_header_tokens,
    determine_column_boundaries,
    match_column_name,
)

class TestPrompt5SubColumnMatrix(unittest.TestCase):

    def test_case_a_pack_qty_free(self):
        """Case A: PACK QTY FREE -> pack, quantity, freeQuantity"""
        headers = ["PACK QTY FREE"]
        rows = [
            ["120TAB 1.00 0.00"],
            ["120TAB 9.00 0.00"],
            ["1*4 3.00 0.00"],
            ["10'S 6.00 0.00"],
        ]
        log_h, log_rows, diag = split_text_multi_value_columns(headers, rows)
        self.assertEqual(log_h, ["PACK", "QTY", "FREE"])
        self.assertEqual(log_rows[0], ["120TAB", "1.00", "0.00"])
        self.assertEqual(log_rows[2], ["1*4", "3.00", "0.00"])
        
        mapping = infer_unresolved_column_semantics(log_h, log_rows)
        self.assertEqual(mapping["PACK"]["mapped_to"], "pack")
        self.assertEqual(mapping["QTY"]["mapped_to"], "quantity")
        self.assertEqual(mapping["FREE"]["mapped_to"], "freeQuantity")

    def test_case_b_amount_gst(self):
        """Case B: AMOUNT GST -> amount, gstPercent"""
        headers = ["AMOUNT GST"]
        rows = [
            ["141.51 5%"],
            ["1281.87 5%"],
            ["422.34 5%"],
            ["1735.74 5%"],
        ]
        log_h, log_rows, diag = split_text_multi_value_columns(headers, rows)
        self.assertEqual(log_h, ["AMOUNT", "GST"])
        self.assertEqual(log_rows[0], ["141.51", "5%"])
        
        mapping = infer_unresolved_column_semantics(log_h, log_rows)
        self.assertEqual(mapping["AMOUNT"]["mapped_to"], "amount")
        self.assertEqual(mapping["GST"]["mapped_to"], "gstPercent")

    def test_case_c_qty_free(self):
        """Case C: QTY FREE -> quantity, freeQuantity"""
        headers = ["QTY FREE"]
        rows = [
            ["10 2"],
            ["20 0"],
            ["15 1"],
            ["5 0"],
        ]
        log_h, log_rows, diag = split_text_multi_value_columns(headers, rows)
        self.assertEqual(log_h, ["QTY", "FREE"])
        self.assertEqual(log_rows[0], ["10", "2"])
        
        mapping = infer_unresolved_column_semantics(log_h, log_rows)
        self.assertEqual(mapping["QTY"]["mapped_to"], "quantity")
        self.assertEqual(mapping["FREE"]["mapped_to"], "freeQuantity")

    def test_case_d_composite_qty_free(self):
        """Case D: composite Qty+Free expressions like 10+2, 2.500+.500"""
        billed, free = parse_compound_qty("10+2")
        self.assertEqual(billed, 10.0)
        self.assertEqual(free, 2.0)
        
        billed2, free2 = parse_compound_qty("2.500+.500")
        self.assertEqual(billed2, 2.5)
        self.assertEqual(free2, 0.5)

    def test_case_e_batch_expiry(self):
        """Case E: BATCH EXP -> batchNo, expiryDate"""
        headers = ["BATCH EXP"]
        rows = [
            ["306DB2518 11/27"],
            ["CCU26031 02/28"],
            ["GKH0248A 01/28"],
            ["PXD0005 12/27"],
        ]
        log_h, log_rows, diag = split_text_multi_value_columns(headers, rows)
        self.assertEqual(log_h, ["BATCH", "EXP"])
        self.assertEqual(log_rows[0], ["306DB2518", "11/27"])
        
        mapping = infer_unresolved_column_semantics(log_h, log_rows)
        self.assertEqual(mapping["BATCH"]["mapped_to"], "batchNo")
        self.assertEqual(mapping["EXP"]["mapped_to"], "expiryDate")

    def test_case_f_expiry_hsn(self):
        """Case F: EXP HSN -> expiryDate, hsnCode"""
        headers = ["EXP HSN"]
        rows = [
            ["11/27 30049099"],
            ["02/28 30049082"],
            ["01/28 30049081"],
            ["12/27 30049099"],
        ]
        log_h, log_rows, diag = split_text_multi_value_columns(headers, rows)
        self.assertEqual(log_h, ["EXP", "HSN"])
        self.assertEqual(log_rows[0], ["11/27", "30049099"])
        
        mapping = infer_unresolved_column_semantics(log_h, log_rows)
        self.assertEqual(mapping["EXP"]["mapped_to"], "expiryDate")
        self.assertEqual(mapping["HSN"]["mapped_to"], "hsnCode")

    def test_case_g_mrp_rate(self):
        """Case G: MRP RATE -> mrp, rate"""
        headers = ["MRP RATE"]
        rows = [
            ["159.00 121.14"],
            ["206.37 141.51"],
            ["421.88 289.29"],
            ["650.00 445.71"],
        ]
        log_h, log_rows, diag = split_text_multi_value_columns(headers, rows)
        self.assertEqual(log_h, ["MRP", "RATE"])
        self.assertEqual(log_rows[0], ["159.00", "121.14"])
        
        mapping = infer_unresolved_column_semantics(log_h, log_rows)
        self.assertEqual(mapping["MRP"]["mapped_to"], "mrp")
        self.assertEqual(mapping["RATE"]["mapped_to"], "rate")

    def test_case_h_cgst_sgst(self):
        """Case H: CGST SGST -> cgst, sgst"""
        headers = ["CGST SGST"]
        rows = [
            ["2.5 2.5"],
            ["6.0 6.0"],
            ["2.5 2.5"],
            ["9.0 9.0"],
        ]
        log_h, log_rows, diag = split_text_multi_value_columns(headers, rows)
        self.assertEqual(log_h, ["CGST", "SGST"])
        self.assertEqual(log_rows[0], ["2.5", "2.5"])
        
        mapping = infer_unresolved_column_semantics(log_h, log_rows)
        self.assertEqual(mapping["CGST"]["mapped_to"], "cgstPercent")
        self.assertEqual(mapping["SGST"]["mapped_to"], "sgstPercent")

    def test_case_i_ambiguous_multi_value_cell(self):
        """Case I: Ambiguous mixed cell with inconsistent values remains unresolved"""
        headers = ["UNKNOWN"]
        rows = [
            ["abc 123"],
            ["hello world extra"],
            ["foo"],
            ["99"],
        ]
        log_h, log_rows, diag = split_text_multi_value_columns(headers, rows)
        self.assertEqual(log_h, ["UNKNOWN"])
        mapping = infer_unresolved_column_semantics(log_h, log_rows)
        self.assertIn(mapping["UNKNOWN"]["status"], ("unresolved", "ambiguous"))
        self.assertIsNone(mapping["UNKNOWN"]["mapped_to"])

    def test_case_j_headerless_multi_value_cell_coordinate(self):
        """Case J: Headerless multi-value cell with stable coordinate clusters splits cleanly"""
        phys_cols = [{
            "index": 0,
            "header_raw": "Unnamed_Col_0",
            "header_text": "Unnamed_Col_0",
            "field": None,
            "x0": 100.0,
            "x1": 200.0,
            "center_x": 150.0,
        }]
        
        # 6 rows with distinct clusters at x=120 (Expiry date) and x=180 (HSN)
        row_groups = [
            [{"text": "11/27", "center_x": 120.0, "x0": 110.0, "x1": 130.0},
             {"text": "30049099", "center_x": 180.0, "x0": 170.0, "x1": 190.0}],
            [{"text": "02/28", "center_x": 121.0, "x0": 111.0, "x1": 131.0},
             {"text": "30049082", "center_x": 179.0, "x0": 169.0, "x1": 189.0}],
            [{"text": "01/28", "center_x": 119.5, "x0": 109.5, "x1": 129.5},
             {"text": "30049081", "center_x": 180.5, "x0": 170.5, "x1": 190.5}],
            [{"text": "12/27", "center_x": 120.2, "x0": 110.2, "x1": 130.2},
             {"text": "30049099", "center_x": 181.0, "x0": 171.0, "x1": 191.0}],
            [{"text": "08/28", "center_x": 120.0, "x0": 110.0, "x1": 130.0},
             {"text": "30049099", "center_x": 180.0, "x0": 170.0, "x1": 190.0}],
        ]
        
        log_cols, diag = detect_logical_subcolumns(phys_cols, row_groups)
        self.assertEqual(len(log_cols), 2)
        self.assertEqual(log_cols[0]["status"], "split")
        self.assertEqual(log_cols[1]["status"], "split")
        self.assertEqual(log_cols[0]["provenance"], "split_from_physical_column")
        self.assertEqual(log_cols[1]["provenance"], "split_from_physical_column")

    def test_case_k_hsn_arbitrary_positions(self):
        """Case K: HSN correctly mapped at first, middle, or last physical position"""
        # First position
        h1 = ["Unnamed_Col_0", "Item", "Qty", "Rate"]
        r1 = [["30049099", "PARACETAMOL 650", "10", "15.00"], ["30049082", "AZITHROMYCIN 500", "5", "45.00"]]
        m1 = infer_unresolved_column_semantics(h1, r1)
        self.assertEqual(m1["Unnamed_Col_0"]["mapped_to"], "hsnCode")

        # Last position
        h2 = ["Item", "Qty", "Rate", "Unnamed_Col_3"]
        r2 = [["PARACETAMOL 650", "10", "15.00", "30049099"], ["AZITHROMYCIN 500", "5", "45.00", "30049082"]]
        m2 = infer_unresolved_column_semantics(h2, r2)
        self.assertEqual(m2["Unnamed_Col_3"]["mapped_to"], "hsnCode")

    def test_case_l_8digit_non_hsn_identifier(self):
        """Case L: 8-digit numeric barcode/serial column must not automatically become HSN when not pharma chapter"""
        headers = ["Unnamed_Col_0", "Item", "Qty"]
        # Serial numbers outside Indian Pharma HSN chapter 3004/3003/3002/3006
        rows = [["87654321", "Item A", "10"], ["98765432", "Item B", "20"]]
        mapping = infer_unresolved_column_semantics(headers, rows)
        self.assertNotEqual(mapping["Unnamed_Col_0"]["mapped_to"], "hsnCode")


if __name__ == "__main__":
    unittest.main(verbosity=2)
