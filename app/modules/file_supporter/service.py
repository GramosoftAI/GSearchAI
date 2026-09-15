from pathlib import Path
from .converter import LibreOfficeConverter, ConversionError

# Document formats that LibreOffice will convert to PDF
SUPPORTED_EXTENSIONS = (".doc", ".docx", ".txt", ".md")

# All extensions allowed by the ingest_file endpoint
ALLOWED_UPLOAD_EXTENSIONS = (".pdf", ".xlsx", ".xls", ".csv") + SUPPORTED_EXTENSIONS

async def prepare_for_pdf_pipeline(upload_path: str, workdir: str) -> str:
    """
    Prepares a document for the PDF ingestion pipeline.
    If it's already a PDF, it returns the path unchanged.
    If it's a supported document format, it converts it to PDF via LibreOffice.
    
    Args:
        upload_path: Absolute path to the uploaded file.
        workdir: Directory where the converted PDF should be saved.
        
    Returns:
        Absolute path to the PDF file.
        
    Raises:
        ConversionError: If the conversion fails or the file extension is unsupported.
    """
    upload_file = Path(upload_path)
    ext = upload_file.suffix.lower()
    
    if ext == ".pdf":
        return str(upload_file.absolute())
        
    if ext in SUPPORTED_EXTENSIONS:
        converter = LibreOfficeConverter()
        pdf_path = await converter.convert_to_pdf(str(upload_file.absolute()), workdir)
        return pdf_path
        
    raise ConversionError(f"Unsupported file extension for PDF pipeline: {ext}. "
                          f"Supported: .pdf, {', '.join(SUPPORTED_EXTENSIONS)}")
