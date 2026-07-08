import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch

from app.core.adaptive_chunker import (
    AdaptiveChunker,
    TableChunker,
    FAQChunker,
    SemanticChunker,
    ExcelChunker,
    URLChunker,
    PDFChunker
)

@pytest.mark.asyncio
async def test_table_chunker():
    table_text = (
        "| Name | Age | Job |\n"
        "|---|---|---|\n"
        "| Alice | 30 | Engineer |\n"
        "| Bob | 25 | Designer |"
    )
    chunks = TableChunker.chunk(table_text, max_chunk_size=100)
    assert len(chunks) > 0
    assert "Alice" in chunks[0]

def test_faq_chunker():
    text = (
        "Q: What is RAG?\n"
        "A: Retrieval-Augmented Generation.\n"
        "Q: What is Neo4j?\n"
        "A: A graph database."
    )
    chunks = FAQChunker.detect_and_chunk(text)
    assert len(chunks) == 2
    assert "RAG" in chunks[0]
    assert "Neo4j" in chunks[1]

@pytest.mark.asyncio
@patch("app.core.embeddings.EmbeddingGenerator.generate_embeddings_batch")
async def test_semantic_chunker(mock_emb_batch):
    # Mock embeddings for 3 micro-chunks: M1 & M2 are similar (vector [1, 0, ...]), M3 is different (vector [0, ..., 1])
    mock_emb_batch.return_value = [
        [1.0] + [0.0] * 1023,
        [1.0] + [0.0] * 1023,
        [0.0] * 1023 + [1.0]
    ]
    
    text = "Paragraph one is here.\n\nParagraph two is similar.\n\nParagraph three is completely different."
    # Use max_chunk_size = 100 so micro-chunk target size is 50 chars, generating 3 micro-chunks
    chunks = await SemanticChunker.chunk(text, max_chunk_size=100, threshold=0.75)
    # M1 (Paragraph 1) and M2 (Paragraph 2) should group together (identical vectors), M3 split
    assert len(chunks) == 2
    assert "Paragraph one" in chunks[0]
    assert "Paragraph two" in chunks[0]
    assert "Paragraph three" in chunks[1]

def test_excel_chunker():
    data = {
        "Department": ["IT", "IT", "HR", "HR", "Sales"],
        "Name": ["Alice", "Bob", "Charlie", "David", "Eve"],
        "Salary": [100, 110, 80, 90, 120]
    }
    df = pd.DataFrame(data)
    chunks = ExcelChunker.chunk(df, sheet_name="Employees", max_chunk_size=1000)
    
    assert len(chunks) > 0
    assert chunks[0]["chunk_type"] == "group"
    assert chunks[0]["sheet"] == "Employees"
    assert "group" in chunks[0]["metadata"]
    assert "rows" in chunks[0]["metadata"]

@pytest.mark.asyncio
@patch("app.core.embeddings.EmbeddingGenerator.generate_embeddings_batch")
async def test_url_chunker(mock_emb_batch):
    mock_emb_batch.return_value = [[0.1]*1024] * 10
    
    html = (
        "<html><body>"
        "<nav>Nav stuff</nav>"
        "<h1>Getting Started</h1>"
        "<p>This is a documentation paragraph.</p>"
        "<h2>Endpoint</h2>"
        "<pre>GET /api/v1/users</pre>"
        "</body></html>"
    )
    chunks = await URLChunker.chunk(html, max_chunk_size=500)
    assert len(chunks) > 0
    assert "Getting Started" in [c.get("section") for c in chunks]

@pytest.mark.asyncio
@patch("app.core.embeddings.EmbeddingGenerator.generate_embeddings_batch")
async def test_adaptive_chunker_router(mock_emb_batch):
    mock_emb_batch.return_value = [[0.1]*1024] * 10
    
    text_content = "This is a simple text file content. Section 1 is here."
    chunks = await AdaptiveChunker.chunk(text_content, source_type="pdf")
    assert len(chunks) > 0
    assert chunks[0]["source_type"] == "pdf"


def test_pdf_structure_parser_html():
    from app.core.adaptive_chunker import PDFStructureParser
    
    html = (
        "<html><body>"
        "<h1>Main Title</h1>"
        "<p>Paragraph 1</p>"
        "<table><tr><td>Cell 1</td></tr></table>"
        "<h2>Subsection</h2>"
        "<p>Paragraph 2</p>"
        "</body></html>"
    )
    segments = PDFStructureParser.parse(html)
    assert len(segments) == 5
    assert segments[0]["type"] == "heading"
    assert segments[0]["text"] == "Main Title"
    assert segments[1]["type"] == "text"
    assert segments[1]["text"] == "Paragraph 1"
    assert segments[2]["type"] == "table"
    assert "Cell 1" in segments[2]["text"]
    assert segments[3]["type"] == "heading"
    assert segments[3]["text"] == "Subsection"
    assert segments[4]["type"] == "text"
    assert segments[4]["text"] == "Paragraph 2"


def test_pdf_structure_parser_markdown():
    from app.core.adaptive_chunker import PDFStructureParser
    
    markdown = (
        "# Main Title\n"
        "Paragraph 1\n\n"
        "| Col 1 |\n"
        "|---|\n"
        "| Cell 1 |\n\n"
        "## Subsection\n"
        "Paragraph 2"
    )
    segments = PDFStructureParser.parse(markdown)
    assert len(segments) == 5
    assert segments[0]["type"] == "heading"
    assert segments[0]["text"] == "Main Title"
    assert segments[1]["type"] == "text"
    assert segments[1]["text"] == "Paragraph 1"
    assert segments[2]["type"] == "table"
    assert "Cell 1" in segments[2]["text"]
    assert segments[3]["type"] == "heading"
    assert segments[3]["text"] == "Subsection"
    assert segments[4]["type"] == "text"
    assert segments[4]["text"] == "Paragraph 2"


@pytest.mark.asyncio
@patch("app.core.embeddings.EmbeddingGenerator.generate_embeddings_batch")
async def test_pdf_chunker_accessibility_example(mock_emb_batch):
    from app.core.adaptive_chunker import PDFChunker
    mock_emb_batch.return_value = [[0.1]*1024] * 10
    
    html = (
        "<html><body>"
        "<h1>Table Examples</h1>"
        "<p>This document contains various table examples for testing accessibility.</p>"
        "<h2>Example 1</h2>"
        "<p>Here is the course information table:</p>"
        "<table id='course-info'>"
        "  <tr><th>Course</th><th>Instructor</th></tr>"
        "  <tr><td>RAG Architecture</td><td>Dr. Smith</td></tr>"
        "</table>"
        "<h2>Example 2</h2>"
        "<p>Here is the grading scale table:</p>"
        "<table id='grading-scale'>"
        "  <tr><th>Grade</th><th>Percentage</th></tr>"
        "  <tr><td>A</td><td>90-100</td></tr>"
        "</table>"
        "<h2>Example 3</h2>"
        "<p>Below is the reading assignments table:</p>"
        "<table id='reading-assignments'>"
        "  <tr><th>Week</th><th>Reading</th></tr>"
        "  <tr><td>Week 1</td><td>Chapter 1</td></tr>"
        "</table>"
        "<h2>Example 4</h2>"
        "<p>Finally, we have table color info.</p>"
        "<h3>Table Color</h3>"
        "<p>Make sure text has proper contrast ratios.</p>"
        "</body></html>"
    )
    
    # Simulate an ExtractedText object with raw_html attribute
    from app.core.pdf_extractor import ExtractedText
    extracted = ExtractedText("Table Examples...", html, is_html=True)
    
    chunks = await AdaptiveChunker.chunk(extracted, source_type="pdf")
    
    # We expect chunks for sections and tables
    # Check that we have multiple chunks and verify metadata
    assert len(chunks) >= 9
    
    # Check chunk types and metadata keys
    for c in chunks:
        assert "source_type" in c
        assert "chunk_type" in c
        assert "section" in c
        assert "position" in c
        # metadata requirements
        assert "source_type" in c["metadata"]
        assert "chunk_type" in c["metadata"]
        assert "section" in c["metadata"]
        assert "heading_level" in c["metadata"]
        assert "position" in c["metadata"]
        
    chunk_sections = [c["section"] for c in chunks]
    chunk_types = [c["chunk_type"] for c in chunks]
    
    assert "Table Examples" in chunk_sections
    assert "Example 1" in chunk_sections
    assert "Example 2" in chunk_sections
    assert "Example 3" in chunk_sections
    assert "Example 4" in chunk_sections
    assert "Table Color" in chunk_sections
    assert "table" in chunk_types


@pytest.mark.asyncio
@patch("app.core.embeddings.EmbeddingGenerator.generate_embeddings_batch")
async def test_semantic_chunker_single_newline_fallback(mock_emb_batch):
    # Mock embeddings returning standard vector dimensions
    mock_emb_batch.return_value = [[0.1]*1024] * 20
    
    # 3000 chars text separated ONLY by single newlines
    lines = [f"This is sentence line {i} that contains some words to build up character count." for i in range(40)]
    single_newline_text = "\n".join(lines)
    assert len(single_newline_text) > 3000
    
    # Chunk with max_chunk_size = 1000
    chunks = await SemanticChunker.chunk(single_newline_text, max_chunk_size=1000)
    
    # Should successfully split the text into multiple chunks
    assert len(chunks) > 1
@pytest.mark.asyncio
@patch("app.core.embeddings.EmbeddingGenerator.generate_embeddings_batch")
async def test_pdf_adaptive_chunking_resume(mock_emb_batch):
    mock_emb_batch.return_value = [[0.1]*1024] * 20
    
    resume_text = (
        "S. SRI VISHNU\n"
        "Alandur, Chennai | +91 7904677821 | ssrivishnu002@gmail.com\n\n"
        "CAREER OBJECTIVE\n"
        "Highly motivated Full-Stack Developer and Cloud Data Engineer graduate with a B.C.A (Hons) degree.\n\n"
        "EDUCATION\n"
        "B.C.A, Vels University - 2023\n"
        "HSC, Holy Angels School - 2019\n"
        "SSLC, Holy Angels School - 2017\n\n"
        "TECHNICAL SKILLS\n"
        "Programming: Python, JavaScript\n"
        "Database: SQL\n\n"
        "PROJECTS\n"
        "ATM System (Python, OOP, SQLite)\n"
        "Developed a terminal-based ATM simulation using Python and OOP concepts.\n"
        "Responsive Login Form with Dynamic Validation (HTML, CSS, JavaScript)\n"
        "Built a custom login form with validation for name, email, and password.\n"
        "ETL Pipeline using PySpark & AWS\n"
        "Built scalable ETL processes to extract data from S3.\n\n"
        "CERTIFICATIONS\n"
        "AWS Data Engineer Certification\n\n"
        "LANGUAGES\n"
        "English, Tamil"
    )
    
    chunks = await AdaptiveChunker.chunk(resume_text, source_type="pdf")
    
    assert len(chunks) >= 8
    
    project_chunks = [c for c in chunks if c["chunk_type"] == "project"]
    assert len(project_chunks) == 3
    
    project_names = [c["metadata"].get("project_name") for c in project_chunks]
    assert "ATM System (Python, OOP, SQLite)" in project_names
    assert "Responsive Login Form with Dynamic Validation (HTML, CSS, JavaScript)" in project_names
    assert "ETL Pipeline using PySpark & AWS" in project_names
    
    for c in chunks:
        assert "chunk_type" in c
        assert "section" in c
        assert "position" in c
        assert "metadata" in c
        assert "source_type" in c["metadata"]
        assert "chunk_type" in c["metadata"]
        assert "section" in c["metadata"]
        assert "position" in c["metadata"]


def test_structured_chunker():
    from app.core.structured_chunker import StructuredChunker, StructuredRecord
    
    records = [
        StructuredRecord(
            document_type="spreadsheet",
            source_file="employees.csv",
            group_name="Sheet1",
            row_index=2,
            columns=["Employee ID", "First Name", "Job Title", "Salary"],
            values={
                "Employee ID": "EMP1004",
                "First Name": "Joseph",
                "Job Title": "Software Engineer",
                "Salary": "63032"
            }
        )
    ]
    
    chunks = StructuredChunker.chunk(records)
    
    # We expect 2 chunks: 1 atomic row-level chunk and 1 consolidated chunk
    assert len(chunks) == 2
    
    atomic_chunk = next(c for c in chunks if c.metadata["chunk_type"] == "atomic")
    assert atomic_chunk.metadata["table_id"] == "Sheet1"
    assert atomic_chunk.metadata["row_label"] == "EMP1004"
    assert "[Sheet1]" in atomic_chunk.text
    assert "Employee ID: EMP1004" in atomic_chunk.text
    assert "First Name: Joseph" in atomic_chunk.text
    assert "Job Title: Software Engineer" in atomic_chunk.text
    assert "Salary: 63032" in atomic_chunk.text




