import pytest
from app.modules.rag.file_router.adapters import parse_gdocz_markdown, parse_pdf_structure

def test_markdown_heading_levels():
    md = "# Heading 1\nSome text.\n## Heading 2\nMore text.\n# Heading 3\nText 3"
    sections = parse_gdocz_markdown(md)
    assert len(sections) == 3
    assert sections[0]['title'] == 'Heading 1'
    assert sections[1]['title'] == 'Heading 1 > Heading 2'
    assert sections[2]['title'] == 'Heading 3'

def test_markdown_detection():
    # Table
    md_table = "Header A | Header B\n---|---\nRow 1 | Row 2"
    sec1 = parse_gdocz_markdown(md_table)
    assert sec1[0]['kind'] == 'table'
    
    # List
    md_list = "- Item 1\n- Item 2\n* Item 3"
    sec2 = parse_gdocz_markdown(md_list)
    assert sec2[0]['kind'] == 'list'

def test_table_then_prose_fixture():
    # PDFStructureParser output structure
    blocks = [
        {
            "type": "table",
            "heading": "Table 1",
            "text": "A | B\n1 | 2\nThis is prose after the table."
        }
    ]
    sections = parse_pdf_structure(blocks)
    assert len(sections) == 2
    assert sections[0]['kind'] == 'table'
    assert "A | B\n1 | 2" in sections[0]['text']
    assert sections[1]['kind'] == 'text'
    assert sections[1]['text'] == "This is prose after the table."
