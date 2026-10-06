import json
from extractor import extract_pdf_table

files = [
    'Sample Invoices/INVOICE_7GU0X28XM.PDF',
    'Sample Invoices/Invoice.pdf',
    'Sample Invoices/Sunil_Medicare_Sample_Invoice.pdf'
]

for f in files:
    print('='*60)
    print('FILE:', f)
    meta, hdrs, col_map, rows = extract_pdf_table(f)
    print('Headers:', hdrs)
    print('Mappings:')
    for h in hdrs:
        info = col_map.get(h, {})
        mapped = info.get("mapped_to") if isinstance(info, dict) else info
        status = info.get("status") if isinstance(info, dict) else ""
        conf = info.get("confidence") if isinstance(info, dict) else ""
        source = info.get("source") if isinstance(info, dict) else ""
        ev = info.get("evidence") if isinstance(info, dict) else []
        print(f'  {h} -> {mapped} (status={status}, conf={conf}, source={source}, ev={ev[:2]})')
    print('Row count:', len(rows))
    if rows:
        print('Sample Row 0:', rows[0])
