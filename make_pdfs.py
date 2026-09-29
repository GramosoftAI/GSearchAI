import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

os.makedirs('tests/data', exist_ok=True)

def create_mock_pdf(filename, title, num_pages):
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter
    for p in range(num_pages):
        c.setFont("Helvetica-Bold", 16)
        c.drawString(72, height - 72, f"{title} - Page {p+1}")
        c.setFont("Helvetica", 12)
        c.drawString(72, height - 100, f"This is mock content for {title}.")
        c.drawString(72, height - 120, "It contains some generic text that should be chunked by the V2 chunker.")
        c.drawString(72, height - 140, "Here is another sentence just to add some length.")
        # Add a mock table for testing structure parser
        if p == 0:
            c.drawString(72, height - 180, "Income | Expenses | Profit")
            c.drawString(72, height - 200, "1000   | 500      | 500")
            
        c.showPage()
    c.save()

create_mock_pdf('tests/data/apple.pdf', 'Apple 10-K', 10)
create_mock_pdf('tests/data/ntsb.pdf', 'NTSB Report', 8)
create_mock_pdf('tests/data/the-four-million-o-henry-1147.pdf', 'The Four Million', 12)
print("Created mock PDFs.")
