"""
Prompt 21A: Unit & Regression Tests for Generic Table Header Band Detection & Metadata Isolation.

Tests:
A. PHUB metadata above table
B. Metadata containing numbers
C. Header immediately after metadata
D. Multi-line header
E. Header with missing fields
F. Different column counts
G. Different vertical positions
H. Existing invoices regression
"""
import os, sys, glob, pytest
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
import pdfplumber
from extractor import (
    extract_page_words,
    detect_coordinate_header_row,
    reconstruct_header_tokens,
    match_column_name,
    extract_pdf_table,
)


def test_synthetic_a_phub_metadata_above_table():
    """Test A: Invoice metadata directly above table header row is excluded."""
    words = [
        # Metadata line at y=100
        {"text": "Ph:", "x0": 10.0, "x1": 30.0, "top": 98.0, "bottom": 108.0},
        {"text": "9885473474/6281903272,", "x0": 35.0, "x1": 150.0, "top": 98.0, "bottom": 108.0},
        {"text": "IRNNo:", "x0": 200.0, "x1": 240.0, "top": 98.0, "bottom": 108.0},
        {"text": "Page", "x0": 400.0, "x1": 430.0, "top": 98.0, "bottom": 108.0},
        {"text": "No:", "x0": 435.0, "x1": 455.0, "top": 98.0, "bottom": 108.0},
        {"text": "1", "x0": 460.0, "x1": 468.0, "top": 98.0, "bottom": 108.0},
        {"text": "/", "x0": 470.0, "x1": 475.0, "top": 98.0, "bottom": 108.0},
        {"text": "1", "x0": 477.0, "x1": 485.0, "top": 98.0, "bottom": 108.0},
        {"text": "RemBy:", "x0": 550.0, "x1": 590.0, "top": 98.0, "bottom": 108.0},
        {"text": "VINAY", "x0": 595.0, "x1": 630.0, "top": 98.0, "bottom": 108.0},

        # Header line at y=112
        {"text": "MFGBy", "x0": 10.0, "x1": 45.0, "top": 110.0, "bottom": 120.0},
        {"text": "HSNCode", "x0": 50.0, "x1": 95.0, "top": 110.0, "bottom": 120.0},
        {"text": "QTY", "x0": 105.0, "x1": 125.0, "top": 110.0, "bottom": 120.0},
        {"text": "FREE", "x0": 135.0, "x1": 160.0, "top": 110.0, "bottom": 120.0},
        {"text": "PACK", "x0": 170.0, "x1": 195.0, "top": 110.0, "bottom": 120.0},
        {"text": "PRODUCTNAME", "x0": 205.0, "x1": 290.0, "top": 110.0, "bottom": 120.0},
        {"text": "M.R.P", "x0": 400.0, "x1": 435.0, "top": 110.0, "bottom": 120.0},
        {"text": "BATCH", "x0": 450.0, "x1": 485.0, "top": 110.0, "bottom": 120.0},
        {"text": "NO.", "x0": 488.0, "x1": 505.0, "top": 110.0, "bottom": 120.0},
        {"text": "E.X.P", "x0": 520.0, "x1": 545.0, "top": 110.0, "bottom": 120.0},
        {"text": "P.T.R", "x0": 560.0, "x1": 585.0, "top": 110.0, "bottom": 120.0},
        {"text": "RATE", "x0": 600.0, "x1": 630.0, "top": 110.0, "bottom": 120.0},
        {"text": "AMOUNT", "x0": 645.0, "x1": 690.0, "top": 110.0, "bottom": 120.0},
        {"text": "Disc", "x0": 700.0, "x1": 725.0, "top": 110.0, "bottom": 120.0},
        {"text": "GST", "x0": 735.0, "x1": 755.0, "top": 110.0, "bottom": 120.0},

        # Data row 1 at y=125
        {"text": "ABT-AH", "x0": 10.0, "x1": 45.0, "top": 122.0, "bottom": 130.0},
        {"text": "30049099", "x0": 50.0, "x1": 95.0, "top": 122.0, "bottom": 130.0},
        {"text": "5", "x0": 105.0, "x1": 115.0, "top": 122.0, "bottom": 130.0},
        {"text": "1", "x0": 135.0, "x1": 145.0, "top": 122.0, "bottom": 130.0},
        {"text": "15", "x0": 170.0, "x1": 185.0, "top": 122.0, "bottom": 130.0},
        {"text": "TELPRES 40", "x0": 205.0, "x1": 270.0, "top": 122.0, "bottom": 130.0},
        {"text": "108.31", "x0": 400.0, "x1": 435.0, "top": 122.0, "bottom": 130.0},
        {"text": "TEB25004", "x0": 450.0, "x1": 495.0, "top": 122.0, "bottom": 130.0},
        {"text": "05/27", "x0": 520.0, "x1": 545.0, "top": 122.0, "bottom": 130.0},
        {"text": "82.52", "x0": 560.0, "x1": 585.0, "top": 122.0, "bottom": 130.0},
        {"text": "74.27", "x0": 600.0, "x1": 630.0, "top": 122.0, "bottom": 130.0},
        {"text": "371.35", "x0": 645.0, "x1": 680.0, "top": 122.0, "bottom": 130.0},
        {"text": "-1.50", "x0": 700.0, "x1": 725.0, "top": 122.0, "bottom": 130.0},
        {"text": "5", "x0": 735.0, "x1": 745.0, "top": 122.0, "bottom": 130.0},
    ]
    for w in words:
        w["center_x"] = (w["x0"] + w["x1"]) / 2.0
        w["center_y"] = (w["top"] + w["bottom"]) / 2.0

    htokens, htop, hbot, conf = detect_coordinate_header_row(words, 800.0)
    assert htokens is not None
    assert htop >= 109.0, f"Header top should be >= 109, got {htop} (metadata included!)"
    header_texts = [ht["text"] for ht in htokens]
    
    # Metadata terms must not contaminate headers
    for h in header_texts:
        assert "VINAY" not in h
        assert "9885473474" not in h
        assert "RemBy" not in h
        assert "Page" not in h
        assert "IRNNo" not in h

    # Key headers must be present and isolated
    assert any("RATE" in h for h in header_texts)
    assert any("P.T.R" in h or "PTR" in h for h in header_texts)
    assert any("M.R.P" in h or "MRP" in h for h in header_texts)


def test_synthetic_b_metadata_containing_numbers():
    """Test B: Metadata lines with GSTIN, phone, and invoice numbers are excluded."""
    words = [
        # Metadata lines
        {"text": "GSTIN:", "x0": 10.0, "x1": 50.0, "top": 50.0, "bottom": 60.0},
        {"text": "36AAZFP3596K1Z5", "x0": 55.0, "x1": 150.0, "top": 50.0, "bottom": 60.0},
        {"text": "InvNo:", "x0": 200.0, "x1": 240.0, "top": 50.0, "bottom": 60.0},
        {"text": "L22014", "x0": 245.0, "x1": 280.0, "top": 50.0, "bottom": 60.0},
        {"text": "Date:", "x0": 320.0, "x1": 350.0, "top": 50.0, "bottom": 60.0},
        {"text": "02-06-2026", "x0": 355.0, "x1": 420.0, "top": 50.0, "bottom": 60.0},

        # Header line
        {"text": "Item Name", "x0": 10.0, "x1": 100.0, "top": 80.0, "bottom": 90.0},
        {"text": "Pack", "x0": 110.0, "x1": 140.0, "top": 80.0, "bottom": 90.0},
        {"text": "Batch", "x0": 150.0, "x1": 190.0, "top": 80.0, "bottom": 90.0},
        {"text": "Exp", "x0": 200.0, "x1": 230.0, "top": 80.0, "bottom": 90.0},
        {"text": "Qty", "x0": 240.0, "x1": 260.0, "top": 80.0, "bottom": 90.0},
        {"text": "Free", "x0": 270.0, "x1": 290.0, "top": 80.0, "bottom": 90.0},
        {"text": "MRP", "x0": 300.0, "x1": 330.0, "top": 80.0, "bottom": 90.0},
        {"text": "Rate", "x0": 340.0, "x1": 370.0, "top": 80.0, "bottom": 90.0},
        {"text": "Amount", "x0": 380.0, "x1": 420.0, "top": 80.0, "bottom": 90.0},

        # Data row
        {"text": "PARACETAMOL", "x0": 10.0, "x1": 100.0, "top": 95.0, "bottom": 105.0},
        {"text": "10T", "x0": 110.0, "x1": 130.0, "top": 95.0, "bottom": 105.0},
        {"text": "BAT123", "x0": 150.0, "x1": 190.0, "top": 95.0, "bottom": 105.0},
        {"text": "12/27", "x0": 200.0, "x1": 230.0, "top": 95.0, "bottom": 105.0},
        {"text": "10", "x0": 240.0, "x1": 250.0, "top": 95.0, "bottom": 105.0},
        {"text": "1", "x0": 270.0, "x1": 275.0, "top": 95.0, "bottom": 105.0},
        {"text": "50.00", "x0": 300.0, "x1": 330.0, "top": 95.0, "bottom": 105.0},
        {"text": "35.00", "x0": 340.0, "x1": 370.0, "top": 95.0, "bottom": 105.0},
        {"text": "350.00", "x0": 380.0, "x1": 420.0, "top": 95.0, "bottom": 105.0},
    ]
    for w in words:
        w["center_x"] = (w["x0"] + w["x1"]) / 2.0
        w["center_y"] = (w["top"] + w["bottom"]) / 2.0

    htokens, htop, hbot, conf = detect_coordinate_header_row(words, 600.0)
    assert htop >= 78.0, f"Header top should be >= 78.0, got {htop}"
    assert len(htokens) == 9


def test_synthetic_c_header_immediately_after_metadata():
    """Test C: Header row starting just 2 points below metadata row."""
    words = [
        # Metadata at y=88-98
        {"text": "D.L", "x0": 10.0, "x1": 30.0, "top": 88.0, "bottom": 98.0},
        {"text": "No.:", "x0": 35.0, "x1": 60.0, "top": 88.0, "bottom": 98.0},
        {"text": "20&21:TG/24/04/2017-26136", "x0": 65.0, "x1": 200.0, "top": 88.0, "bottom": 98.0},
        {"text": "Sales", "x0": 250.0, "x1": 280.0, "top": 88.0, "bottom": 98.0},
        {"text": "Man", "x0": 285.0, "x1": 310.0, "top": 88.0, "bottom": 98.0},
        {"text": ":", "x0": 312.0, "x1": 316.0, "top": 88.0, "bottom": 98.0},
        {"text": "WHOLESALE", "x0": 320.0, "x1": 390.0, "top": 88.0, "bottom": 98.0},

        # Header at y=100-110 (only 2pt gap!)
        {"text": "P.T.R", "x0": 10.0, "x1": 40.0, "top": 100.0, "bottom": 110.0},
        {"text": "PRODUCTNAME", "x0": 50.0, "x1": 150.0, "top": 100.0, "bottom": 110.0},
        {"text": "PACK", "x0": 160.0, "x1": 190.0, "top": 100.0, "bottom": 110.0},
        {"text": "QTY", "x0": 200.0, "x1": 220.0, "top": 100.0, "bottom": 110.0},
        {"text": "FREE", "x0": 230.0, "x1": 250.0, "top": 100.0, "bottom": 110.0},
        {"text": "BATCH", "x0": 260.0, "x1": 290.0, "top": 100.0, "bottom": 110.0},
        {"text": "EXP", "x0": 300.0, "x1": 320.0, "top": 100.0, "bottom": 110.0},
        {"text": "MRP", "x0": 330.0, "x1": 350.0, "top": 100.0, "bottom": 110.0},
        {"text": "Rate", "x0": 360.0, "x1": 380.0, "top": 100.0, "bottom": 110.0},
        {"text": "AMOUNT", "x0": 390.0, "x1": 430.0, "top": 100.0, "bottom": 110.0},

        # Data row
        {"text": "157.23", "x0": 10.0, "x1": 40.0, "top": 115.0, "bottom": 125.0},
        {"text": "THYRONORM", "x0": 50.0, "x1": 120.0, "top": 115.0, "bottom": 125.0},
        {"text": "120TAB", "x0": 160.0, "x1": 190.0, "top": 115.0, "bottom": 125.0},
        {"text": "1.00", "x0": 200.0, "x1": 220.0, "top": 115.0, "bottom": 125.0},
        {"text": "0.00", "x0": 230.0, "x1": 250.0, "top": 115.0, "bottom": 125.0},
        {"text": "CCU26031", "x0": 260.0, "x1": 295.0, "top": 115.0, "bottom": 125.0},
        {"text": "2/28", "x0": 300.0, "x1": 320.0, "top": 115.0, "bottom": 125.0},
        {"text": "206.37", "x0": 330.0, "x1": 355.0, "top": 115.0, "bottom": 125.0},
        {"text": "141.51", "x0": 360.0, "x1": 385.0, "top": 115.0, "bottom": 125.0},
        {"text": "141.51", "x0": 390.0, "x1": 420.0, "top": 115.0, "bottom": 125.0},
    ]
    for w in words:
        w["center_x"] = (w["x0"] + w["x1"]) / 2.0
        w["center_y"] = (w["top"] + w["bottom"]) / 2.0

    htokens, htop, hbot, conf = detect_coordinate_header_row(words, 600.0)
    assert htop >= 99.0, f"Expected header top >= 99.0, got {htop}"
    texts = [ht["text"] for ht in htokens]
    assert "D.L P.T.R" not in texts
    assert "WHOLESALE AMOUNT" not in texts


def test_synthetic_d_multiline_header():
    """Test D: Genuine multi-line header is merged properly."""
    words = [
        # Top tier of header (y=100)
        {"text": "PRODUCT", "x0": 10.0, "x1": 60.0, "top": 100.0, "bottom": 108.0},
        {"text": "BATCH", "x0": 100.0, "x1": 135.0, "top": 100.0, "bottom": 108.0},
        {"text": "EXP", "x0": 150.0, "x1": 170.0, "top": 100.0, "bottom": 108.0},
        {"text": "TAXABLE", "x0": 200.0, "x1": 245.0, "top": 100.0, "bottom": 108.0},
        {"text": "GST", "x0": 260.0, "x1": 280.0, "top": 100.0, "bottom": 108.0},
        {"text": "NET", "x0": 310.0, "x1": 330.0, "top": 100.0, "bottom": 108.0},

        # Bottom tier of header (y=110)
        {"text": "NAME", "x0": 10.0, "x1": 40.0, "top": 110.0, "bottom": 118.0},
        {"text": "NO.", "x0": 100.0, "x1": 120.0, "top": 110.0, "bottom": 118.0},
        {"text": "DATE", "x0": 150.0, "x1": 175.0, "top": 110.0, "bottom": 118.0},
        {"text": "VALUE", "x0": 200.0, "x1": 235.0, "top": 110.0, "bottom": 118.0},
        {"text": "%", "x0": 260.0, "x1": 270.0, "top": 110.0, "bottom": 118.0},
        {"text": "AMOUNT", "x0": 310.0, "x1": 355.0, "top": 110.0, "bottom": 118.0},

        # Data row (y=125)
        {"text": "AMCLAV 625", "x0": 10.0, "x1": 70.0, "top": 125.0, "bottom": 135.0},
        {"text": "BT99", "x0": 100.0, "x1": 125.0, "top": 125.0, "bottom": 135.0},
        {"text": "09/27", "x0": 150.0, "x1": 175.0, "top": 125.0, "bottom": 135.0},
        {"text": "500.00", "x0": 200.0, "x1": 240.0, "top": 125.0, "bottom": 135.0},
        {"text": "12", "x0": 260.0, "x1": 270.0, "top": 125.0, "bottom": 135.0},
        {"text": "560.00", "x0": 310.0, "x1": 350.0, "top": 125.0, "bottom": 135.0},
    ]
    for w in words:
        w["center_x"] = (w["x0"] + w["x1"]) / 2.0
        w["center_y"] = (w["top"] + w["bottom"]) / 2.0

    htokens, htop, hbot, conf = detect_coordinate_header_row(words, 600.0)
    assert htop <= 101.0, f"Expected multi-line header top <= 101, got {htop}"
    assert hbot >= 117.0, f"Expected multi-line header bot >= 117, got {hbot}"
    texts = [ht["text"] for ht in htokens]
    assert any("PRODUCT" in h and "NAME" in h for h in texts)
    assert any("BATCH" in h and "NO" in h for h in texts)


def test_synthetic_e_header_with_missing_fields():
    """Test E: Minimal table header with only 4 columns."""
    words = [
        {"text": "Item", "x0": 10.0, "x1": 40.0, "top": 100.0, "bottom": 110.0},
        {"text": "Qty", "x0": 100.0, "x1": 120.0, "top": 100.0, "bottom": 110.0},
        {"text": "Rate", "x0": 150.0, "x1": 180.0, "top": 100.0, "bottom": 110.0},
        {"text": "Amount", "x0": 220.0, "x1": 260.0, "top": 100.0, "bottom": 110.0},

        {"text": "MEDICINE A", "x0": 10.0, "x1": 80.0, "top": 120.0, "bottom": 130.0},
        {"text": "5", "x0": 100.0, "x1": 110.0, "top": 120.0, "bottom": 130.0},
        {"text": "100.00", "x0": 150.0, "x1": 185.0, "top": 120.0, "bottom": 130.0},
        {"text": "500.00", "x0": 220.0, "x1": 255.0, "top": 120.0, "bottom": 130.0},
    ]
    for w in words:
        w["center_x"] = (w["x0"] + w["x1"]) / 2.0
        w["center_y"] = (w["top"] + w["bottom"]) / 2.0

    htokens, htop, hbot, conf = detect_coordinate_header_row(words, 600.0)
    assert htokens is not None
    assert len(htokens) == 4


def test_synthetic_f_different_column_counts():
    """Test F: Wide table with 18 distinct columns."""
    col_names = ["S.No", "Mfr", "Product Name", "Pack", "Batch", "Exp", "HSN", "MRP", "PTR", "PTS", "Rate", "Qty", "Free", "Disc%", "Taxable", "GST%", "GST Amt", "Net Amt"]
    words = []
    x = 10.0
    for name in col_names:
        w_len = len(name) * 5.0
        words.append({"text": name, "x0": x, "x1": x + w_len, "top": 100.0, "bottom": 110.0})
        x += w_len + 10.0

    # Add 1 data row
    x = 10.0
    for i, name in enumerate(col_names):
        w_len = len(name) * 5.0
        words.append({"text": f"val_{i}", "x0": x, "x1": x + w_len, "top": 120.0, "bottom": 130.0})
        x += w_len + 10.0

    for w in words:
        w["center_x"] = (w["x0"] + w["x1"]) / 2.0
        w["center_y"] = (w["top"] + w["bottom"]) / 2.0

    htokens, htop, hbot, conf = detect_coordinate_header_row(words, 600.0)
    assert htokens is not None
    assert len(htokens) >= 16


def test_synthetic_g_different_vertical_positions():
    """Test G: Table header located at lower page position (y=350)."""
    words = [
        {"text": "Product", "x0": 10.0, "x1": 60.0, "top": 350.0, "bottom": 360.0},
        {"text": "Batch", "x0": 100.0, "x1": 130.0, "top": 350.0, "bottom": 360.0},
        {"text": "Expiry", "x0": 160.0, "x1": 195.0, "top": 350.0, "bottom": 360.0},
        {"text": "MRP", "x0": 220.0, "x1": 250.0, "top": 350.0, "bottom": 360.0},
        {"text": "Rate", "x0": 280.0, "x1": 310.0, "top": 350.0, "bottom": 360.0},
        {"text": "Qty", "x0": 340.0, "x1": 360.0, "top": 350.0, "bottom": 360.0},
        {"text": "Amount", "x0": 390.0, "x1": 430.0, "top": 350.0, "bottom": 360.0},

        {"text": "AMLO 5MG", "x0": 10.0, "x1": 70.0, "top": 370.0, "bottom": 380.0},
        {"text": "B123", "x0": 100.0, "x1": 125.0, "top": 370.0, "bottom": 380.0},
        {"text": "05/27", "x0": 160.0, "x1": 190.0, "top": 370.0, "bottom": 380.0},
        {"text": "45.00", "x0": 220.0, "x1": 250.0, "top": 370.0, "bottom": 380.0},
        {"text": "30.00", "x0": 280.0, "x1": 310.0, "top": 370.0, "bottom": 380.0},
        {"text": "10", "x0": 340.0, "x1": 355.0, "top": 370.0, "bottom": 380.0},
        {"text": "300.00", "x0": 390.0, "x1": 425.0, "top": 370.0, "bottom": 380.0},
    ]
    for w in words:
        w["center_x"] = (w["x0"] + w["x1"]) / 2.0
        w["center_y"] = (w["top"] + w["bottom"]) / 2.0

    htokens, htop, hbot, conf = detect_coordinate_header_row(words, 800.0)
    assert htokens is not None
    assert htop >= 348.0 and hbot <= 362.0


def test_h_existing_invoices_regression():
    """Test H: All existing sample invoices maintain valid header detection and row extraction."""
    samples = sorted(glob.glob("Sample Invoices/*.[pP][dD][fF]"))
    assert len(samples) >= 9
    for s in samples:
        bname = os.path.basename(s)
        with pdfplumber.open(s) as pdf:
            p0 = pdf.pages[0]
            words = extract_page_words(p0)
            htokens, htop, hbot, conf = detect_coordinate_header_row(words, float(p0.height))
            assert htokens is not None, f"Failed to detect headers on {bname}"
            assert len(htokens) >= 5, f"Too few headers ({len(htokens)}) on {bname}"
            assert conf >= 0.5, f"Low confidence ({conf}) on {bname}"

            # Verify no obvious invoice metadata contaminated the headers
            for ht in htokens:
                text = ht["text"]
                assert not any(meta in text.lower() for meta in ["gstin:", "d.l.no:", "pan:", "email:", "phone:"]), \
                    f"Metadata found in header token '{text}' on {bname}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
