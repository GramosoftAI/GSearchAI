import logging
import io
import re
from typing import List
import docx
from docx.oxml.ns import qn
from app.core.pdf_extractor import ExtractedText

logger = logging.getLogger(__name__)

class DocxExtractor:
    """
    Native DOCX extraction bypassing LibreOffice to preserve paragraph order and structure.
    Reads XML directly via python-docx.
    """
    
    @staticmethod
    def _extract_checkbox_state(element) -> List[str]:
        """
        Extract checked/unchecked state from Word checkboxes (w:sdt and legacy w:checkBox).
        Returns a list of '[x]' or '[ ]' strings found in the element.
        """
        results = []
        try:
            # Modern Content Controls (w:sdt)
            sdt_checks = element._element.findall('.//' + qn('w14:checkbox'))
            for cb in sdt_checks:
                checked = cb.find(qn('w14:checked'))
                is_checked = False
                if checked is not None:
                    val = checked.get(qn('w14:val'))
                    if val in ['1', 'true', 'True']:
                        is_checked = True
                results.append("[x]" if is_checked else "[ ]")
                
            # Legacy Form Fields (w:ffData > w:checkBox)
            ff_checks = element._element.findall('.//' + qn('w:checkBox'))
            for cb in ff_checks:
                checked = cb.find(qn('w:checked'))
                is_checked = False
                if checked is not None:
                    val = checked.get(qn('w:val'))
                    if val in ['1', 'true', 'True']:
                        is_checked = True
                results.append("[x]" if is_checked else "[ ]")
        except Exception as e:
            logger.debug(f"Failed to parse checkboxes in element: {e}")
            
        return results

    @staticmethod
    def _process_paragraph(p) -> str:
        """Convert a paragraph to Markdown, including headings, styling, and checkboxes."""
        text = p.text.strip()
        if not text:
            return ""
            
        # Extract true checkboxes if any
        cbs = DocxExtractor._extract_checkbox_state(p)
        if cbs:
            text = " ".join(cbs) + " " + text
            
        # Handle headings
        style_name = p.style.name if p.style else ""
        if style_name.startswith('Heading'):
            try:
                level = int(style_name.replace('Heading ', ''))
                level = min(level, 6)
                return f"{'#' * level} {text}"
            except ValueError:
                pass
                
        # Handle lists
        if style_name.startswith('List'):
            return f"- {text}"
            
        return text

    @staticmethod
    def _process_table(table) -> str:
        """Convert a python-docx table to Markdown format."""
        if not table.rows:
            return ""
            
        md = []
        for i, row in enumerate(table.rows):
            row_data = []
            for cell in row.cells:
                cell_text = cell.text.replace('\n', ' ').replace('|', '\\|').strip()
                cbs = DocxExtractor._extract_checkbox_state(cell)
                if cbs:
                    cell_text = " ".join(cbs) + " " + cell_text
                row_data.append(cell_text)
                
            md.append("| " + " | ".join(row_data) + " |")
            
            # Add separator after header
            if i == 0:
                md.append("| " + " | ".join(["---"] * len(row_data)) + " |")
                
        return "\n".join(md)

    @staticmethod
    async def extract(file_bytes: bytes, filename: str) -> ExtractedText:
        """
        Extract structured markdown natively from DOCX bytes.
        Returns an ExtractedText object.
        """
        logger.info(f" Starting native DOCX extraction for {filename}")
        try:
            doc = docx.Document(io.BytesIO(file_bytes))
            
            elements_md = []
            
            # python-docx doesn't guarantee element order between paragraphs and tables.
            # We iterate through the XML body to preserve true document order.
            for element in doc.element.body:
                if element.tag.endswith('p'):
                    # Paragraph
                    for p in doc.paragraphs:
                        if p._element == element:
                            md_text = DocxExtractor._process_paragraph(p)
                            if md_text:
                                elements_md.append(md_text)
                            break
                elif element.tag.endswith('tbl'):
                    # Table
                    for t in doc.tables:
                        if t._element == element:
                            md_table = DocxExtractor._process_table(t)
                            if md_table:
                                elements_md.append(md_table)
                            break
                            
            raw_markdown = "\n\n".join(elements_md)
            
            # Simple structure confidence check to skip LLM repair if high confidence
            high_confidence = False
            if len(doc.paragraphs) > 0 and raw_markdown.strip():
                high_confidence = True
                
            logger.info(f" Successfully extracted {len(raw_markdown)} chars from DOCX natively. High confidence: {high_confidence}")
            
            return ExtractedText(
                clean_text=raw_markdown,
                raw_content=raw_markdown,
                is_markdown=True,
                extraction_method="docx_native",
                extraction_incomplete=False
            )
        except Exception as e:
            logger.error(f" Native DOCX extraction failed: {e}")
            raise ValueError(f"Native DOCX extraction failed: {e}")
