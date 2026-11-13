import pytest
import os
import tempfile
import shutil
from pathlib import Path
import zipfile
from unittest.mock import patch, AsyncMock

from app.modules.file_supporter import LibreOfficeConverter, prepare_for_pdf_pipeline, SUPPORTED_EXTENSIONS

def create_valid_dummy_docx(path: str):
    """Creates a minimal valid OOXML .docx file using stdlib zipfile."""
    content_types = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'
    rels = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    document = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hello World from DOCX</w:t></w:r></w:p></w:body></w:document>'
    
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('[Content_Types].xml', content_types)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('word/document.xml', document)

def is_soffice_available():
    return shutil.which("soffice") is not None

@pytest.fixture
def temp_workspace():
    workspace = tempfile.mkdtemp()
    yield workspace
    shutil.rmtree(workspace, ignore_errors=True)

@pytest.mark.asyncio
async def test_prepare_for_pdf_pipeline_with_mock(temp_workspace):
    """Tests the routing logic using a mock to ensure we don't depend on soffice being installed."""
    txt_path = Path(temp_workspace) / "test.txt"
    txt_path.write_text("Hello World from TXT")
    
    with patch("app.modules.file_supporter.converter.LibreOfficeConverter.convert_to_pdf", new_callable=AsyncMock) as mock_convert:
        mock_convert.return_value = str(Path(temp_workspace) / "test.pdf")
        
        pdf_path = await prepare_for_pdf_pipeline(str(txt_path), temp_workspace)
        
        assert pdf_path == str(Path(temp_workspace) / "test.pdf")
        mock_convert.assert_called_once_with(str(txt_path.absolute()), temp_workspace)

@pytest.mark.skipif(not is_soffice_available(), reason="soffice not installed on this system")
@pytest.mark.asyncio
async def test_libreoffice_converter_real_txt(temp_workspace):
    """Integration test that actually invokes LibreOffice for a .txt file."""
    txt_path = Path(temp_workspace) / "test.txt"
    txt_path.write_text("This is a real text file for conversion.")
    
    converter = LibreOfficeConverter()
    pdf_path = await converter.convert_to_pdf(str(txt_path), temp_workspace)
    
    assert os.path.exists(pdf_path)
    assert pdf_path.endswith(".pdf")
    
    # Check that PDF has some bytes
    assert os.path.getsize(pdf_path) > 0

@pytest.mark.skipif(not is_soffice_available(), reason="soffice not installed on this system")
@pytest.mark.asyncio
async def test_libreoffice_converter_real_docx(temp_workspace):
    """Integration test that actually invokes LibreOffice for a .docx file."""
    docx_path = Path(temp_workspace) / "test.docx"
    create_valid_dummy_docx(str(docx_path))
    
    converter = LibreOfficeConverter()
    pdf_path = await converter.convert_to_pdf(str(docx_path), temp_workspace)
    
    assert os.path.exists(pdf_path)
    assert pdf_path.endswith(".pdf")
    assert os.path.getsize(pdf_path) > 0
