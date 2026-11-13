from app.core.adaptive_chunker import PDFStructureParser
from app.modules.rag.file_router.adapters import parse_pdf_structure

def run_table_bug_fixture():
    print("--- 1. Table Bug Fixture (Markdown) ---")
    md_text = """# Heading 1
Some introductory text.

| Col A | Col B |
|---|---|
| Data 1 | Data 2 |

This is some prose immediately after the table.
It should not be lost.
"""
    print("RAW MARKDOWN:")
    print(repr(md_text))
    
    print("\n--- PDFStructureParser OUTPUT ---")
    blocks = PDFStructureParser.parse(md_text)
    for i, b in enumerate(blocks):
        print(f"Block {i}: Type={b.get('type')}, Heading={b.get('heading')}")
        print(f"  Text: {repr(b.get('text'))}")
        
    print("\n--- ADAPTER OUTPUT ---")
    sections = parse_pdf_structure(blocks)
    for i, s in enumerate(sections):
        print(f"Section {i}: Kind={s.get('kind')}, Title={s.get('title')}")
        print(f"  Text: {repr(s.get('text'))}")
        
    print("\n--- 2. Table Bug Fixture (HTML) ---")
    html_text = """<h1>Heading 1</h1>
<p>Some introductory text.</p>
<table>
<tr><td>Col A</td><td>Col B</td></tr>
<tr><td>Data 1</td><td>Data 2</td></tr>
</table>
<p>This is some prose immediately after the table.</p>
<p>It should not be lost.</p>
"""
    print("RAW HTML:")
    print(repr(html_text))
    
    print("\n--- PDFStructureParser OUTPUT (HTML) ---")
    html_blocks = PDFStructureParser.parse(html_text)
    for i, b in enumerate(html_blocks):
        print(f"Block {i}: Type={b.get('type')}, Heading={b.get('heading')}")
        print(f"  Text: {repr(b.get('text'))}")

if __name__ == "__main__":
    run_table_bug_fixture()
