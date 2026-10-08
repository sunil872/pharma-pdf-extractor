import pdfplumber

with pdfplumber.open('Sample Invoices/invoice (1).pdf') as pdf:
    p2 = pdf.pages[1]
    words = p2.extract_words()
    print('Words between y=100 and 160 on Page 2:')
    for w in sorted(words, key=lambda x: (x['top'], x['x0'])):
        if 100 <= w['top'] <= 160:
            print(f"top={w['top']:.2f}, bottom={w['bottom']:.2f}, x0={w['x0']:.2f}, x1={w['x1']:.2f}: {w['text']}")
