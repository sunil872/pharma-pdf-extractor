import sys, os
sys.path.insert(0, r"c:\Users\sunil\pharma-pdf-extractor")
import re
import numpy as np

def test_subcolumn_logic():
    print("Testing logical subcolumn reconstruction logic...")
    
    # Test Case A: PACK QTY FREE text
    header = "PACK QTY FREE"
    rows = [
        ["120TAB 1.00 0.00"],
        ["120TAB 9.00 0.00"],
        ["1*4 3.00 0.00"],
        ["10'S 6.00 0.00"],
    ]
    tokens = header.split()
    assert len(tokens) == 3
    print("Case A header tokens:", tokens)

if __name__ == "__main__":
    test_subcolumn_logic()
