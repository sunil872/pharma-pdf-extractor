"""Re-author ONLY INVOICE_7GU0X28XM.PDF field GT from visible PDF text. No extractor use."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "Sample Invoices"
MANIFEST = ROOT / "evaluation" / "field_ground_truth_manifest.json"
CHANGELOG = ROOT / "scratch" / "_final_7gu0_gt_changelog.json"

EXPECTED_SHA = "c26b45256359ae1674a2c8b1010fe545da32d142b305944de57e2f04a8625b1e"

# Values transcribed from pdfplumber extract_text of the hashed PDF (not extractor output).
# Columns: S QTY FREE MFR BOXS PRODUCT PACK [PTR OLD] Batch EXP MRP RATE SCH AMOUNT GST HSN
# FREE '-' => 0.0. RATE taken from RATE column (PTR OCR noise ignored). Pack from PACK token.
NEW_ROWS = [
    {
        "row_index": 0,
        "page": 1,
        "raw_row_text": "1 9 1 LUPI 1.000 GLUCONORM G1 FORTE TAB 15 167.85 235.00 UA02711 10/26 220.31 167.85 10.0 1510.65 5.00 30049099",
        "cells": {
            "itemName": {"value": "GLUCONORM G1 FORTE TAB", "state": "KNOWN"},
            "pack": {"value": "15", "state": "KNOWN"},
            "batchNo": {"value": "UA02711", "state": "KNOWN"},
            "expiryDate": {"value": "10/26", "state": "KNOWN"},
            "quantity": {"value": 9.0, "state": "KNOWN"},
            "freeQuantity": {"value": 1.0, "state": "KNOWN"},
            "discountPercent": {"value": 10.0, "state": "KNOWN"},
            "rate": {"value": 167.85, "state": "KNOWN"},
            "mrp": {"value": 220.31, "state": "KNOWN"},
            "hsnCode": {"value": "30049099", "state": "KNOWN"},
            "amount": {"value": 1510.65, "state": "KNOWN"},
            "gstPercent": {"value": 5.0, "state": "KNOWN"},
            "company": {"value": "LUPI", "state": "KNOWN"},
        },
    },
    {
        "row_index": 1,
        "page": 1,
        "raw_row_text": "2 5 - LUPI 0.500 GLUCONORM PG 2 TAB 15 275.32 385.45 AGNT25009 4/27 361.36 275.32 13.0 1376.60 5.00 30045039",
        "cells": {
            "itemName": {"value": "GLUCONORM PG 2 TAB", "state": "KNOWN"},
            "pack": {"value": "15", "state": "KNOWN"},
            "batchNo": {"value": "AGNT25009", "state": "KNOWN"},
            "expiryDate": {"value": "4/27", "state": "KNOWN"},
            "quantity": {"value": 5.0, "state": "KNOWN"},
            "freeQuantity": {"value": 0.0, "state": "KNOWN"},
            "discountPercent": {"value": 13.0, "state": "KNOWN"},
            "rate": {"value": 275.32, "state": "KNOWN"},
            "mrp": {"value": 361.36, "state": "KNOWN"},
            "hsnCode": {"value": "30045039", "state": "KNOWN"},
            "amount": {"value": 1376.60, "state": "KNOWN"},
            "gstPercent": {"value": 5.0, "state": "KNOWN"},
            "company": {"value": "LUPI", "state": "KNOWN"},
        },
    },
    {
        "row_index": 2,
        "page": 1,
        "raw_row_text": "3 10 - LUPI 1.000 TONACT 20 TAB 15 153.32 214.65 UB02155 7/27 201.20 153.32 14.0 1533.20 5.00 30049079",
        "cells": {
            "itemName": {"value": "TONACT 20 TAB", "state": "KNOWN"},
            "pack": {"value": "15", "state": "KNOWN"},
            "batchNo": {"value": "UB02155", "state": "KNOWN"},
            "expiryDate": {"value": "7/27", "state": "KNOWN"},
            "quantity": {"value": 10.0, "state": "KNOWN"},
            "freeQuantity": {"value": 0.0, "state": "KNOWN"},
            "discountPercent": {"value": 14.0, "state": "KNOWN"},
            "rate": {"value": 153.32, "state": "KNOWN"},
            "mrp": {"value": 201.20, "state": "KNOWN"},
            "hsnCode": {"value": "30049079", "state": "KNOWN"},
            "amount": {"value": 1533.20, "state": "KNOWN"},
            "gstPercent": {"value": 5.0, "state": "KNOWN"},
            "company": {"value": "LUPI", "state": "KNOWN"},
        },
    },
    {
        "row_index": 3,
        "page": 1,
        "raw_row_text": "4 5 1 MED 0.600 BILAHIST 20 TAB 10 103.62 132.00 HBH121 1/28 136.00 103.62 12.0 518.10 5.00 30049099",
        "cells": {
            "itemName": {"value": "BILAHIST 20 TAB", "state": "KNOWN"},
            "pack": {"value": "10", "state": "KNOWN"},
            "batchNo": {"value": "HBH121", "state": "KNOWN"},
            "expiryDate": {"value": "1/28", "state": "KNOWN"},
            "quantity": {"value": 5.0, "state": "KNOWN"},
            "freeQuantity": {"value": 1.0, "state": "KNOWN"},
            "discountPercent": {"value": 12.0, "state": "KNOWN"},
            "rate": {"value": 103.62, "state": "KNOWN"},
            "mrp": {"value": 136.00, "state": "KNOWN"},
            "hsnCode": {"value": "30049099", "state": "KNOWN"},
            "amount": {"value": 518.10, "state": "KNOWN"},
            "gstPercent": {"value": 5.0, "state": "KNOWN"},
            "company": {"value": "MED", "state": "KNOWN"},
        },
    },
    {
        "row_index": 4,
        "page": 1,
        "raw_row_text": "5 30 - MERC 3.000 CONCOR AM 5 TAB 10 100.91 141.27 M22EF25043 11/27 132.44 100.91 10.0 3027.30 5.00 300490",
        "cells": {
            "itemName": {"value": "CONCOR AM 5 TAB", "state": "KNOWN"},
            "pack": {"value": "10", "state": "KNOWN"},
            "batchNo": {"value": "M22EF25043", "state": "KNOWN"},
            "expiryDate": {"value": "11/27", "state": "KNOWN"},
            "quantity": {"value": 30.0, "state": "KNOWN"},
            "freeQuantity": {"value": 0.0, "state": "KNOWN"},
            "discountPercent": {"value": 10.0, "state": "KNOWN"},
            "rate": {"value": 100.91, "state": "KNOWN"},
            "mrp": {"value": 132.44, "state": "KNOWN"},
            "hsnCode": {"value": "300490", "state": "KNOWN"},
            "amount": {"value": 3027.30, "state": "KNOWN"},
            "gstPercent": {"value": 5.0, "state": "KNOWN"},
            "company": {"value": "MERC", "state": "KNOWN"},
        },
    },
    {
        "row_index": 5,
        "page": 1,
        "raw_row_text": "6 25 - MICR 1.000 AMLONG 2.5 TAB 15 21.83 30.07 AMTS0008 9/28 28.65 21.83 14.0 545.75 5.00 30049082",
        "cells": {
            "itemName": {"value": "AMLONG 2.5 TAB", "state": "KNOWN"},
            "pack": {"value": "15", "state": "KNOWN"},
            "batchNo": {"value": "AMTS0008", "state": "KNOWN"},
            "expiryDate": {"value": "9/28", "state": "KNOWN"},
            "quantity": {"value": 25.0, "state": "KNOWN"},
            "freeQuantity": {"value": 0.0, "state": "KNOWN"},
            "discountPercent": {"value": 14.0, "state": "KNOWN"},
            "rate": {"value": 21.83, "state": "KNOWN"},
            "mrp": {"value": 28.65, "state": "KNOWN"},
            "hsnCode": {"value": "30049082", "state": "KNOWN"},
            "amount": {"value": 545.75, "state": "KNOWN"},
            "gstPercent": {"value": 5.0, "state": "KNOWN"},
            "company": {"value": "MICR", "state": "KNOWN"},
        },
    },
    {
        "row_index": 6,
        "page": 1,
        "raw_row_text": "7 1 - OMNI 1.000 OMNIMOIST LOTION 200MIL 403.41 499.00 BSC51543 10/28 595.00 403.41 12.0 403.41 18.00 21069099",
        "cells": {
            "itemName": {"value": "OMNIMOIST LOTION", "state": "KNOWN"},
            "pack": {"value": "200MIL", "state": "KNOWN"},
            "batchNo": {"value": "BSC51543", "state": "KNOWN"},
            "expiryDate": {"value": "10/28", "state": "KNOWN"},
            "quantity": {"value": 1.0, "state": "KNOWN"},
            "freeQuantity": {"value": 0.0, "state": "KNOWN"},
            "discountPercent": {"value": 12.0, "state": "KNOWN"},
            "rate": {"value": 403.41, "state": "KNOWN"},
            "mrp": {"value": 595.00, "state": "KNOWN"},
            "hsnCode": {"value": "21069099", "state": "KNOWN"},
            "amount": {"value": 403.41, "state": "KNOWN"},
            "gstPercent": {"value": 18.0, "state": "KNOWN"},
            "company": {"value": "OMNI", "state": "KNOWN"},
        },
    },
    {
        "row_index": 7,
        "page": 1,
        "raw_row_text": "8 5 - SAMA 0.500 ANOBLISS CREAM 30GM 117.04 163.87 B282602 12/27 153.62 117.04 10.0 585.20 5.00 30049072",
        "cells": {
            "itemName": {"value": "ANOBLISS CREAM", "state": "KNOWN"},
            "pack": {"value": "30GM", "state": "KNOWN"},
            "batchNo": {"value": "B282602", "state": "KNOWN"},
            "expiryDate": {"value": "12/27", "state": "KNOWN"},
            "quantity": {"value": 5.0, "state": "KNOWN"},
            "freeQuantity": {"value": 0.0, "state": "KNOWN"},
            "discountPercent": {"value": 10.0, "state": "KNOWN"},
            "rate": {"value": 117.04, "state": "KNOWN"},
            "mrp": {"value": 153.62, "state": "KNOWN"},
            "hsnCode": {"value": "30049072", "state": "KNOWN"},
            "amount": {"value": 585.20, "state": "KNOWN"},
            "gstPercent": {"value": 5.0, "state": "KNOWN"},
            "company": {"value": "SAMA", "state": "KNOWN"},
        },
    },
    {
        "row_index": 8,
        "page": 1,
        "raw_row_text": "9 10 - SUN 1.000 URSOCOL 300 TABS E15 528.00 575.00 GTG3930A 11/27 693.00 528.00 10.0 5280.00 5.00 30049036",
        "cells": {
            "itemName": {"value": "URSOCOL 300 TABS", "state": "KNOWN"},
            "pack": {"value": "E15", "state": "KNOWN"},
            "batchNo": {"value": "GTG3930A", "state": "KNOWN"},
            "expiryDate": {"value": "11/27", "state": "KNOWN"},
            "quantity": {"value": 10.0, "state": "KNOWN"},
            "freeQuantity": {"value": 0.0, "state": "KNOWN"},
            "discountPercent": {"value": 10.0, "state": "KNOWN"},
            "rate": {"value": 528.00, "state": "KNOWN"},
            "mrp": {"value": 693.00, "state": "KNOWN"},
            "hsnCode": {"value": "30049036", "state": "KNOWN"},
            "amount": {"value": 5280.00, "state": "KNOWN"},
            "gstPercent": {"value": 5.0, "state": "KNOWN"},
            "company": {"value": "SUN", "state": "KNOWN"},
        },
    },
    {
        "row_index": 9,
        "page": 1,
        "raw_row_text": "10 10 - TORR 1.000 PREGEB NT TAB M10 195.92 249.45 GCEF0004 9/27 257.15 195.92 10.0 1959.20 5.00 30049099",
        "cells": {
            "itemName": {"value": "PREGEB NT TAB", "state": "KNOWN"},
            "pack": {"value": "M10", "state": "KNOWN"},
            "batchNo": {"value": "GCEF0004", "state": "KNOWN"},
            "expiryDate": {"value": "9/27", "state": "KNOWN"},
            "quantity": {"value": 10.0, "state": "KNOWN"},
            "freeQuantity": {"value": 0.0, "state": "KNOWN"},
            "discountPercent": {"value": 10.0, "state": "KNOWN"},
            "rate": {"value": 195.92, "state": "KNOWN"},
            "mrp": {"value": 257.15, "state": "KNOWN"},
            "hsnCode": {"value": "30049099", "state": "KNOWN"},
            "amount": {"value": 1959.20, "state": "KNOWN"},
            "gstPercent": {"value": 5.0, "state": "KNOWN"},
            "company": {"value": "TORR", "state": "KNOWN"},
        },
    },
    {
        "row_index": 10,
        "page": 1,
        "raw_row_text": "11 2.50 0.50 YASH 0.300 SUNKROMA ADVANCED SUNSCREEN 50GM 467.82 241.78 B1040105 6/27 690.00 467.82 12.0 1169.55 18.00 21069099",
        "cells": {
            "itemName": {"value": "SUNKROMA ADVANCED SUNSCREEN", "state": "KNOWN"},
            "pack": {"value": "50GM", "state": "KNOWN"},
            "batchNo": {"value": "B1040105", "state": "KNOWN"},
            "expiryDate": {"value": "6/27", "state": "KNOWN"},
            "quantity": {"value": 2.5, "state": "KNOWN"},
            "freeQuantity": {"value": 0.5, "state": "KNOWN"},
            "discountPercent": {"value": 12.0, "state": "KNOWN"},
            "rate": {"value": 467.82, "state": "KNOWN"},
            "mrp": {"value": 690.00, "state": "KNOWN"},
            "hsnCode": {"value": "21069099", "state": "KNOWN"},
            "amount": {"value": 1169.55, "state": "KNOWN"},
            "gstPercent": {"value": 18.0, "state": "KNOWN"},
            "company": {"value": "YASH", "state": "KNOWN"},
        },
    },
]


def cell_val(cells, field):
    c = cells.get(field) or {}
    return c.get("value")


def main():
    pdf = SAMPLES / "INVOICE_7GU0X28XM.PDF"
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert sha == EXPECTED_SHA, f"SHA mismatch {sha}"

    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    docs = data["documents"]
    idx = next(i for i, d in enumerate(docs) if d["filename"] == "INVOICE_7GU0X28XM.PDF")
    old_doc = docs[idx]
    assert old_doc["sha256"] == EXPECTED_SHA

    changes = []
    for old_row, new_row in zip(old_doc["rows"], NEW_ROWS):
        for field in sorted(set(old_row["cells"]) | set(new_row["cells"])):
            ov = cell_val(old_row["cells"], field)
            nv = cell_val(new_row["cells"], field)
            if ov != nv:
                changes.append(
                    {
                        "row_index": new_row["row_index"],
                        "field": field,
                        "old": ov,
                        "new": nv,
                        "evidence": new_row["raw_row_text"],
                    }
                )

    new_doc = dict(old_doc)
    new_doc["rows"] = NEW_ROWS
    # Preserve presence matrix / formula / ids; note re-author source
    new_doc["gt_reauthor_note"] = (
        "Prompt FINAL: re-authored from hashed PDF text evidence; "
        "replaced Digene/Thyronorm/Senquel rows that did not appear in this PDF."
    )

    # Integrity: other docs untouched by identity
    other_before = [json.dumps(d, sort_keys=True) for i, d in enumerate(docs) if i != idx]
    docs[idx] = new_doc
    other_after = [json.dumps(d, sort_keys=True) for i, d in enumerate(docs) if i != idx]
    assert other_before == other_after

    data["documents"] = docs
    MANIFEST.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    CHANGELOG.write_text(json.dumps({"sha256": sha, "change_count": len(changes), "changes": changes}, indent=2), encoding="utf-8")
    print(f"Updated 7GU0 GT: {len(changes)} cell changes. Changelog -> {CHANGELOG}")


if __name__ == "__main__":
    main()
