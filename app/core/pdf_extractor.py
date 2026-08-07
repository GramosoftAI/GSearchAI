# -*- coding: utf-8 -*-
"""PDF Extraction Service  Gdocz SDK (Primary) + pdfplumber (Fallback)

ARCHITECTURE:
    Primary:  Gdocz SDK  Converts PDF to clean markdown via cloud API
    Fallback: pdfplumber + AI-OCR  Local extraction with Vision LLM for scans

STRATEGY:
    1. Try Gdocz SDK first (best quality, handles complex PDFs + scans)
    2. If Gdocz fails (API down, quota exceeded), fall back to pdfplumber
    3. Clean the raw markdown into GraphRAG-friendly plain text
    4. Return clean text ready for chunking + embedding

MARKDOWN CLEANING:
    The raw markdown from Gdocz contains formatting artifacts that are
    noise for embedding models. We clean:
    - Headers (## Title  Title)
    - Bold/Italic (**text**, *text*  text)
    - Links ([text](url)  text)
    - Images (![alt](url)  removed)
    - Tables (| col |  flattened to sentences)
    - Code blocks (```code```  code)
    - HTML tags (<tag>  removed)
    - Excessive whitespace normalized

NON-BREAKING:
    This module is imported ONLY by the agent/KB routes that handle PDF ingestion.
    No existing modules are modified. The extraction function returns plain text
    which plugs directly into the existing ingest_document() pipeline.
"""

import logging
import re
import io
import asyncio
import tempfile
import os
from typing import Optional

from .config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_DOCLING_CONVERTER = None
import threading

_DOCLING_INIT_LOCK = threading.Lock()

def get_docling_converter():
    global _DOCLING_CONVERTER
    if _DOCLING_CONVERTER is None:
        with _DOCLING_INIT_LOCK:
            if _DOCLING_CONVERTER is None:
                try:
                    import time
                    t0 = time.perf_counter()
                    logger.info(" [Timing] Initializing Docling DocumentConverter (Singleton)...")
                    from docling.document_converter import DocumentConverter, PdfFormatOption
                    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableStructureOptions
                    from docling.datamodel.base_models import InputFormat
                    pipeline_options = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
                    _DOCLING_CONVERTER = DocumentConverter(allowed_formats=[InputFormat.PDF], format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)})
                    t1 = time.perf_counter()
                    logger.info(f" [Timing] Docling DocumentConverter initialized in {t1 - t0:.2f}s")
                except ImportError:
                    pass
    return _DOCLING_CONVERTER


class ExtractedText(str):
    def __new__(cls, clean_text: str, raw_content: str = None, is_html: bool = False, is_markdown: bool = False, extraction_method: str = "gdocz", extraction_incomplete: bool = False, failed_pages: list = None):
        obj = super().__new__(cls, clean_text)
        obj.raw_content = raw_content if raw_content is not None else clean_text
        obj.raw_html = obj.raw_content  # backward compatibility
        obj.is_html = is_html
        obj.is_markdown = is_markdown
        obj.extraction_method = extraction_method
        obj.extraction_incomplete = extraction_incomplete
        obj.failed_pages = failed_pages or []
        return obj


class PDFExtractor:
    """
    PDF content extraction with dual-layer strategy:
    1. Gdocz SDK (primary)  Cloud-based, high-quality PDF  Markdown
    2. pdfplumber (fallback)  Local extraction with AI-OCR for scans

    Usage:
        text = await PDFExtractor.extract(pdf_bytes, filename="doc.pdf")
    """

    @staticmethod
    async def extract_tables_to_json(pdf_bytes: bytes) -> list:
        """
        Extract structured tables from PDF using pdfplumber into JSONB friendly format.
        Returns a list of dicts:
        [{
            "page_number": 1,
            "table_index": 0,
            "row_index": 0,
            "row_data": {"Part Number": "123", "Price": "5000"}
        }]
        """
        import pdfplumber
        import io
        
        extracted_tables = []
        try:
            # Run blocking pdfplumber open and extraction in a thread pool
            def _extract() -> list:
                results = []
                with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                    for page_idx, page in enumerate(pdf.pages):
                        tables = page.extract_tables()
                        for table_idx, table in enumerate(tables):
                            if not table or len(table) < 2:
                                continue
                                
                            # Extract headers
                            headers = table[0]
                            headers = [str(h).strip().replace('\n', ' ') if h else f"col_{i}" for i, h in enumerate(headers)]
                            
                            # Ensure unique headers if there are duplicates
                            unique_headers = []
                            for i, h in enumerate(headers):
                                if h in unique_headers:
                                    unique_headers.append(f"{h}_{i}")
                                else:
                                    unique_headers.append(h)
                            headers = unique_headers

                            # Extract rows
                            for row_idx, row in enumerate(table[1:]):
                                row_data = {}
                                has_data = False
                                for i, cell in enumerate(row):
                                    if i < len(headers):
                                        col_name = headers[i]
                                        cell_val = str(cell).strip().replace('\n', ' ') if cell else ""
                                        row_data[col_name] = cell_val
                                        if cell_val:
                                            has_data = True
                                
                                # Only append if the row has actual data
                                if has_data:
                                    results.append({
                                        "page_number": page_idx + 1,
                                        "table_index": table_idx,
                                        "row_index": row_idx,
                                        "row_data": row_data
                                    })
                return results

            loop = asyncio.get_event_loop()
            extracted_tables = await loop.run_in_executor(None, _extract)
            logger.info(f" Extracted {len(extracted_tables)} structured table rows from PDF")
            
        except Exception as e:
            logger.error(f" Failed to extract tables: {e}", exc_info=True)
            
        return extracted_tables

    @staticmethod
    async def extract(
        pdf_bytes: bytes,
        filename: str = "document.pdf",
        tenant_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> ExtractedText:
        """
        Extract text from PDF bytes using the best available method.

        FLOW:
        1. Try Gdocz SDK (cloud API, handles complex/scanned PDFs)
        2. If Gdocz fails  fall back to pdfplumber + AI-OCR
        3. Clean raw output into GraphRAG-friendly text
        4. Return cleaned text ready for chunking

        Args:
            pdf_bytes: Raw PDF file content
            filename: Original filename (for logging)
            tenant_id: For billing/tracking
            agent_id: For billing/tracking

        Returns:
            ExtractedText: Subclass of str containing cleaned text, with .raw_html, .raw_content, .is_html and .is_markdown properties.

        Raises:
            ValueError: If no text could be extracted from the PDF
        """
        logger.info(f" PDF Extraction starting: {filename} ({len(pdf_bytes)} bytes)")

        extracted_text = ""

        # ============= PRIMARY: GDOCZ SDK =============
        if settings.gdocz_api_key:
            try:
                raw_markdown = await PDFExtractor._extract_gdocz(
                    pdf_bytes, filename
                )
                if raw_markdown and raw_markdown.strip():
                    logger.info(
                        f" Gdocz extraction success: {filename} "
                        f"({len(raw_markdown)} chars raw markdown)"
                    )
                    # Clean page markers if present
                    raw_markdown_clean = re.sub(r"<---- Page \d+ ---->\r?\n?", "", raw_markdown)
                    
                    # LLM-based Markdown repair
                    try:
                        raw_markdown_clean = await PDFExtractor._repair_markdown_with_llm(raw_markdown_clean)
                    except Exception as llm_err:
                        logger.warning(f"LLM Markdown repair failed, using raw Markdown: {llm_err}")
                        
                    # Clean markdown for RAG
                    cleaned = PDFExtractor._clean_markdown_for_rag(raw_markdown_clean)
                    logger.info(
                        f" Cleaned for RAG: {len(cleaned)} chars "
                        f"(from {len(raw_markdown_clean)} raw)"
                    )
                    return ExtractedText(cleaned, raw_markdown_clean, is_markdown=True, extraction_method="gdocz")
                else:
                    # logger.warning(
                    #     f" Gdocz returned empty result for {filename}. "
                    #     f"Falling back to pdfplumber."
                    # )
                    raise ValueError(f"Gdocz returned empty result for {filename}.")
            except Exception as e:
                logger.error(f" Gdocz extraction failed for {filename}: {e}")
                # logger.warning(
                #     f" Gdocz extraction failed for {filename}: {e}. "
                #     f"Falling back to pdfplumber."
                # )
                raise ValueError(f"Could not extract text from PDF: {filename} using Gdocz SDK: {e}")
        else:
            # logger.info(
            #     " GDOCZ_API_KEY not configured. Using pdfplumber directly."
            # )
            raise ValueError(
                f"Could not extract text from PDF: {filename}. "
                f"GDOCZ_API_KEY is not configured and fallback extractors are disabled."
            )

        # ============= FALLBACK: PDFPLUMBER + AI-OCR =============
        # fallback_error = None
        # if settings.enable_pdf_fallback:
        #     try:
        #         extracted_text = await PDFExtractor._extract_pdfplumber(
        #             pdf_bytes, filename, tenant_id, agent_id
        #         )
        #         if extracted_text and extracted_text.strip():
        #             logger.info(
        #                 f" pdfplumber extraction success: {filename} "
        #                 f"({len(extracted_text)} chars)"
        #             )
        #             # LLM-based reconstruction of raw text to clean semantic Markdown
        #             try:
        #                 reconstructed_markdown = await PDFExtractor._reconstruct_text_to_markdown_with_llm(extracted_text)
        #                 cleaned = PDFExtractor._clean_markdown_for_rag(reconstructed_markdown)
        #                 logger.info("Successfully reconstructed pdfplumber plain text to Markdown via LLM")
        #                 return ExtractedText(cleaned, reconstructed_markdown, is_markdown=True, extraction_method="pdfplumber")
        #             except Exception as llm_err:
        #                 logger.warning(f"LLM text reconstruction to Markdown failed: {llm_err}. Returning raw plain text.")
        #             
        #             return ExtractedText(extracted_text, extracted_text, is_markdown=False, extraction_method="pdfplumber")
        #         else:
        #             fallback_error = "PDF contains no extractable text (likely a scanned image). OCR is required but Gdocz failed."
        #             logger.warning(f" pdfplumber extracted empty text for {filename}.")
        #     except Exception as e:
        #         fallback_error = f"pdfplumber exception: {str(e)}"
        #         logger.error(f" pdfplumber also failed for {filename}: {e}")
        # else:
        #     fallback_error = "PDF fallback is disabled by configuration settings."
        #     logger.info(fallback_error)
        # 
        # # ============= BOTH FAILED =============
        # raise ValueError(
        #     f"Could not extract text from PDF: {filename}. "
        #     f"Gdocz SDK failed. Fallback error: {fallback_error}"
        # )

    # ========================================================================
    # PRIMARY: GDOCZ SDK
    # ========================================================================

    @staticmethod
    async def _extract_gdocz(pdf_bytes: bytes, filename: str) -> str:
        """
        Extract PDF content using Gdocz OCR server via gdocz_sdk.
        """
        def _sync_gdocz_convert(pdf_data: bytes, fname: str, api_key: str) -> str:
            import os
            import time
            import tempfile
            import uuid
            from gdocz_sdk import GdoczaiClient, ConvertOptions
            
            # Write bytes to temporary file for the SDK
            temp_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}_{fname}")
            with open(temp_path, "wb") as f:
                f.write(pdf_data)
                
            try:
                client = GdoczaiClient(api_key=api_key)
                options = ConvertOptions(mode="accurate")
                
                max_retries = 2
                last_err = None
                result = None
                
                for attempt in range(max_retries):
                    start_t = time.time()
                    try:
                        logger.info(f"Calling Gdocz SDK convert (attempt {attempt + 1}/{max_retries})")
                        result = client.convert(temp_path, options=options)
                        break
                    except Exception as e:
                        last_err = e
                        elapsed = time.time() - start_t
                        logger.warning(f"Gdocz attempt {attempt + 1} failed after {elapsed:.2f}s: {e}")
                        if attempt < max_retries - 1:
                            time.sleep(2 ** attempt)
                else:
                    if last_err is not None:
                        raise last_err
                    raise RuntimeError("Failed to extract PDF using Gdocz SDK (retries exceeded)")
                    
                # Handle either dict or object response from SDK
                if isinstance(result, dict):
                    raw_markdown = result.get("markdown", "")
                    images = result.get("images") or result.get("image_map") or {}
                else:
                    raw_markdown = getattr(result, "markdown", "")
                    images = getattr(result, "images", None) or getattr(result, "image_map", None) or {}
                
                # Post-process to embed base64 images if any exist
                if images:
                    logger.info(f"Embedding {len(images)} base64 images into HTML/markdown content")
                    for img_name, img_base64 in images.items():
                        if not img_base64:
                            continue
                        if not img_base64.startswith("data:image/"):
                            ext = os.path.splitext(img_name.lower())[1]
                            mime = "image/jpeg"
                            if ext == ".png": mime = "image/png"
                            elif ext == ".gif": mime = "image/gif"
                            elif ext == ".webp": mime = "image/webp"
                            img_base64 = f"data:{mime};base64,{img_base64}"
                        
                        raw_markdown = raw_markdown.replace(f'src="{img_name}"', f'src="{img_base64}"')
                        raw_markdown = raw_markdown.replace(f"src='{img_name}'", f"src='{img_base64}'")
                        raw_markdown = raw_markdown.replace(f'src={img_name}', f'src="{img_base64}"')
                        raw_markdown = raw_markdown.replace(f"({img_name})", f"({img_base64})")
                
                return raw_markdown
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        loop = asyncio.get_event_loop()
        try:
            raw_markdown = await asyncio.wait_for(
                loop.run_in_executor(
                    None, _sync_gdocz_convert, pdf_bytes, filename, settings.gdocz_api_key
                ),
                timeout=60.0  # Strict 60s timeout to prevent 13+ min hangs!
            )
        except asyncio.TimeoutError:
            logger.warning(f"Gdocz SDK timed out after 60 seconds for {filename}")
            raise RuntimeError("Gdocz extraction timed out")

        return raw_markdown

    # ========================================================================
    # FALLBACK: PDFPLUMBER + AI-OCR
    # ========================================================================

    @staticmethod
    def _is_monetary(text: str) -> bool:
        if not text:
            return False
        text = str(text).strip()
        if any(c in text for c in "$\u20ac\u00a3\u00a5\u20b9"):
            return True
        import re
        if re.search(r'\.\d{2}\b', text):
            return True
        return False

    @staticmethod
    def validate_table_arithmetic(table) -> bool:
        """Hybrid heuristic: check for Total/Subtotal/Tax keywords, else generic validation."""
        if not table or len(table) < 3:
            return True  # Too small to validate
        
        def parse_num(val):
            if not val: return None
            s = str(val).replace(',', '').strip()
            s = s.replace('$', '').replace('\u20ac', '').replace('\u00a3', '')
            try: return float(s)
            except ValueError: return None
        
        # Look for subtotal, tax, total keywords
        subtotal_row, tax_row, total_row = None, None, None
        for i, row in enumerate(table[-5:]):  # Usually at the bottom
            i = len(table) - 5 + i if len(table) > 5 else i
            row_text = " ".join([str(c).lower() for c in row if c]).strip()
            if "subtotal" in row_text or "sub-total" in row_text: subtotal_row = i
            elif "tax" in row_text or "vat" in row_text or "gst" in row_text: tax_row = i
            elif "total" in row_text and "subtotal" not in row_text: total_row = i

        num_cols = len(table[0])
        
        # If we have keyword rows, do anchored validation
        if total_row is not None and (subtotal_row is not None or tax_row is not None):
            for col_idx in range(num_cols):
                # Only check columns that contain monetary patterns in the total row
                tot_str = table[total_row][col_idx] if total_row is not None and col_idx < len(table[total_row]) else ""
                if not PDFExtractor._is_monetary(tot_str):
                    continue

                sub_val = parse_num(table[subtotal_row][col_idx]) if subtotal_row is not None and col_idx < len(table[subtotal_row]) else 0.0
                tax_val = parse_num(table[tax_row][col_idx]) if tax_row is not None and col_idx < len(table[tax_row]) else 0.0
                tot_val = parse_num(tot_str)
                
                if tot_val is not None and (sub_val or tax_val):
                    calc_tot = (sub_val or 0.0) + (tax_val or 0.0)
                    if abs(calc_tot - tot_val) > 0.05:
                        return False
            return True

        if total_row is not None:
            # Only line items and a total
            for col_idx in range(num_cols):
                tot_str = table[total_row][col_idx] if col_idx < len(table[total_row]) else ""
                if not PDFExtractor._is_monetary(tot_str):
                    continue
                    
                numbers = []
                for i in range(total_row):
                    if col_idx < len(table[i]):
                        numbers.append(parse_num(table[i][col_idx]))
                valid_nums = [v for v in numbers if v is not None]
                tot_val = parse_num(tot_str)
                
                if tot_val is not None and len(valid_nums) > 0:
                    if abs(sum(valid_nums) - tot_val) > 0.05:
                        return False
            return True
            
        # Generic fallback
        for col_idx in range(num_cols):
                
            col_vals = []
            for row in table:
                if col_idx < len(row):
                    col_vals.append(parse_num(row[col_idx]))
                else:
                    col_vals.append(None)
            
            numbers = [v for v in col_vals if v is not None]
            if len(numbers) > 2 and col_vals[-1] is not None:
                last_val_str = table[-1][col_idx] if col_idx < len(table[-1]) else ""
                if PDFExtractor._is_monetary(last_val_str):
                    if abs(sum(numbers[:-1]) - col_vals[-1]) > 0.01:
                        return False
        return True

    @staticmethod
    def tables_look_well_formed(tables) -> bool:
        if not tables:
            return True
        for table in tables:
            if len(table) < 2:
                continue
            col_counts = [len(row) for row in table if row]
            if len(set(col_counts)) > 2:
                return False
            empty_cells = sum(1 for row in table for cell in row if not cell or str(cell).strip() == "")
            total_cells = sum(len(row) for row in table)
            if total_cells > 0 and (empty_cells / total_cells) > 0.5:
                return False
            if not PDFExtractor.validate_table_arithmetic(table):
                return False
        return True

    @staticmethod
    async def _extract_pdfplumber(
        pdf_bytes: bytes,
        filename: str,
        tenant_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> str:
        """
        Fallback extraction using pdfplumber + Docling (Dynamic Duo).
        Routes clean digital pages to pdfplumber, and scanned/complex pages to Docling.
        """
        def _sync_extract() -> str:
            import time
            start_time_total = time.perf_counter()
            try:
                import pdfplumber
            except ImportError:
                raise ImportError("pdfplumber is not installed. Run: pip install pdfplumber")

            import pypdfium2 as pdfium
            import tempfile
            import os
            import uuid

            def table_to_markdown(table) -> str:
                if not table: return ""
                md = ""
                for i, row in enumerate(table):
                    clean_row = [str(cell).replace('\n', ' ').replace('|', '\\|') if cell else "" for cell in row]
                    md += "| " + " | ".join(clean_row) + " |\n"
                    if i == 0:
                        md += "| " + " | ".join(["---"] * len(clean_row)) + " |\n"
                return md + "\n"

            docling_pages = []
            page_contents = {}
            total_pages = 0

            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                total_pages = len(pdf.pages)
                for page_idx, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    
                    if len(text.strip()) < 20:
                        logger.info(f"Empty/scanned page {page.page_number} in {filename}. Routing to Docling.")
                        docling_pages.append(page_idx)
                        continue

                    tables = page.extract_tables()
                    if tables and not PDFExtractor.tables_look_well_formed(tables):
                        logger.info(f"Complex/borderless tables on page {page.page_number} in {filename}. Routing to Docling.")
                        docling_pages.append(page_idx)
                        continue

                    logger.info(f"Clean digital page {page.page_number} in {filename}. Using pdfplumber.")
                    page_text = text + "\n\n"
                    if tables:
                        for table in tables:
                            page_text += table_to_markdown(table)
                    page_contents[page_idx] = page_text

            time_after_pdfplumber = time.perf_counter()
            logger.info(f" [Timing] pdfplumber pass completed in {time_after_pdfplumber - start_time_total:.2f}s for {total_pages} pages")

            failed_pages = []
            if docling_pages:
                converter = get_docling_converter()
                if converter is None:
                    logger.error("Docling not installed. Cannot process scanned pages.")
                    for p in docling_pages:
                        page_contents[p] = ""
                        failed_pages.append(p)
                else:
                    pdf_doc = pdfium.PdfDocument(pdf_bytes)
                    new_pdf = pdfium.PdfDocument.new()
                    new_pdf.import_pages(pdf_doc, docling_pages)
                    
                    temp_path = os.path.join(tempfile.gettempdir(), f"batch_docling_{uuid.uuid4()}_{filename}")
                    new_pdf.save(temp_path)
                    
                    try:
                        logger.info(f"Running Docling for {len(docling_pages)} escalated pages...")
                        t0_docling = time.perf_counter()
                        res = converter.convert(temp_path)
                        t1_docling = time.perf_counter()
                        logger.info(f" [Timing] Docling .convert() finished in {t1_docling - t0_docling:.2f}s")
                        
                        # Docling pages are 1-indexed. We map them back exactly to their original page_idx.
                        for docling_page_idx, original_page_idx in enumerate(docling_pages):
                            doc_page_no = docling_page_idx + 1
                            try:
                                docling_md = res.document.export_to_markdown(page_no=doc_page_no)
                                page_contents[original_page_idx] = docling_md + "\n\n"
                            except Exception as e:
                                logger.error(f"Failed to export page {doc_page_no} (original page {original_page_idx+1}) to markdown: {e}")
                                page_contents[original_page_idx] = ""
                                failed_pages.append(original_page_idx)
                    except Exception as e:
                        logger.error(f"Docling batch extraction failed: {e}", exc_info=True)
                        for p in docling_pages:
                            page_contents[p] = ""
                            failed_pages.append(p)
                    finally:
                        if os.path.exists(temp_path):
                            os.remove(temp_path)

            document_text = ""
            for i in range(total_pages):
                if i in page_contents:
                    document_text += page_contents[i]

            total_elapsed = time.perf_counter() - start_time_total
            logger.info(f" [Timing] Total fallback extraction (pdfplumber + Docling) completed in {total_elapsed:.2f}s for {filename}")

            return ExtractedText(
                clean_text=document_text, 
                raw_content=document_text, 
                is_markdown=True, 
                extraction_method="pdfplumber",
                extraction_incomplete=len(failed_pages) > 0, 
                failed_pages=failed_pages
            )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _sync_extract)

    # ========================================================================
    # MARKDOWN CLEANING (GraphRAG-Friendly)
    # ========================================================================

    @staticmethod
    def _get_adaptive_max_tokens(
        text: str,
        multiplier: int = 3,
        default_add: int = 1000,
        fallback_max: int = 4096
    ) -> int:
        """
        Dynamically calculate max_tokens based on text/segment length.
        Estimates expected output token size using actual token counts to prevent truncation while optimizing latency.
        """
        if not text:
            return 700
            
        try:
            import tiktoken
            encoding = tiktoken.get_encoding("cl100k_base")
            input_tokens = len(encoding.encode(text, disallowed_special=()))
        except Exception:
            input_tokens = len(text) // 4
            
        # Estimate expected output token length:
        # For reconstruction/repair, expected output is comparable to input size plus formatting.
        # Add a safe buffer of 400 tokens to ensure zero truncation.
        estimated_output_tokens = int(input_tokens * 1.1) + 400
        
        if input_tokens < 250:
            base_cap = 700
        elif input_tokens < 500:
            base_cap = 1000
        else:
            base_cap = min(fallback_max, input_tokens * multiplier + default_add)
            
        return max(base_cap, estimated_output_tokens)

    @staticmethod
    def _clean_markdown_for_rag(raw_markdown: str) -> str:
        """
        Clean raw markdown into GraphRAG-friendly plain text.

        WHAT WE KEEP:
        - All actual content text (sentences, paragraphs)
        - Header text (as plain text, preserving structure)
        - Table content (flattened to readable lines)
        - Code content (without backtick fences)
        - List items (as plain sentences)

        WHAT WE REMOVE:
        - Markdown formatting symbols (**, *, `, #)
        - Image references (![alt](url))
        - URL links (keep link text, remove URL)
        - HTML tags
        - Horizontal rules (---, ***)
        - Excessive whitespace / empty lines

        WHY: Embedding models (BAAI/bge-large) perform better on
        clean, natural language text without formatting noise.

        Args:
            raw_markdown: Raw markdown string from PDF extraction

        Returns:
            Cleaned plain text optimized for chunking + embedding
        """
        if not raw_markdown:
            return ""

        text = raw_markdown

        # ============= STEP 1: REMOVE IMAGES =============
        # ![alt text](url) or ![](url)
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)

        # ============= STEP 2: CONVERT LINKS TO TEXT =============
        # [link text](url)  link text
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

        # ============= STEP 3: REMOVE CODE FENCES =============
        # ```language\ncode\n```  code
        text = re.sub(r"```[\w]*\n?", "", text)

        # ============= STEP 4: REMOVE HTML TAGS =============
        # Convert block level tags to newlines to avoid merging text
        text = re.sub(r"</?(?:h[1-6]|p|div|tr|li|table|thead|tbody|ol|ul|br|section|article)[^>]*>", "\n", text)
        # Convert any other tags to empty string
        text = re.sub(r"<[^>]+>", "", text)

        # ============= STEP 5: CONVERT HEADERS TO PLAIN TEXT =============
        # ## Header  Header (keep the text, remove #)
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)

        # ============= STEP 6: REMOVE FORMATTING =============
        # Bold: **text** or __text__  text
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)

        # Italic: *text* or _text_  text
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", text)

        # Strikethrough: ~~text~~  text
        text = re.sub(r"~~([^~]+)~~", r"\1", text)

        # Inline code: `text`  text
        text = re.sub(r"`([^`]+)`", r"\1", text)

        # ============= STEP 7: REMOVE MARKDOWN TABLES =============
        # We now extract tables separately into structured rows. We do NOT want 
        # flattened tables polluting the unstructured semantic vector space.
        # Matches typical markdown tables like | Col1 | Col2 |
        text = re.sub(r"^(?:\|[^\n]+\|\r?\n)+", "", text, flags=re.MULTILINE)

        # ============= STEP 8: CLEAN LIST MARKERS =============
        # - item or * item or  item  item
        text = re.sub(r"^[\s]*[-*+]\s+", "", text, flags=re.MULTILINE)
        # 1. item  item (Only 1-2 digit numbers to avoid stripping years like 2023.)
        text = re.sub(r"^[\s]*\d{1,2}\.\s+", "", text, flags=re.MULTILINE)

        # ============= STEP 9: REMOVE HORIZONTAL RULES =============
        text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)

        # ============= STEP 10: NORMALIZE WHITESPACE =============
        # Replace multiple blank lines with single blank line
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Remove leading/trailing whitespace per line
        lines = [line.strip() for line in text.splitlines()]

        # Remove completely empty lines at start/end
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()

        # Rejoin with clean line breaks
        text = "\n".join(lines)

        # Final trim
        text = text.strip()

        logger.debug(
            f"Markdown cleaned: {len(raw_markdown)} chars  {len(text)} chars "
            f"(removed {len(raw_markdown) - len(text)} chars of formatting)"
        )

        return text

    @staticmethod
    async def extract_structured_entities(text: str) -> dict:
        """
        Phase 4: Universal Entity Extraction.
        LLM identifies candidate entities, system extracts exact source spans.
        """
        from .llm.deepinfra_llm import DeepInfraLLMClient
        import json
        from .entity_registry import ENTITY_TYPES, resolve_entity_type
        
        try:
            client = DeepInfraLLMClient()
            
            prompt = f"""
            Identify ALL business identifiers, codes, references, numbers, and key-value pairs in the text.
            Do not restrict yourself to a predefined list. Extract any field that looks like a business identifier (e.g. E-Way Bill, Registration No, Chassis Number, Policy Number, Claim Number, Dispatch Number, Batch Number, GSTIN, PAN, VIN, Invoice Number, etc.).
            Also extract standard contact info like ADDRESS, EMAIL, PHONE.
            Sections include: Place of Delivery, Billing Address, Shipping Address, Customer Details.
            
            Return exactly in JSON format. DO NOT use <think> blocks or reasoning. Output ONLY the JSON object immediately:
            {{
                "identifiers": [
                    {{"type": "E-WAY_BILL_NUMBER", "candidate_value": "123456789012", "confidence": 0.99}},
                    {{"type": "REGISTRATION_NO", "candidate_value": "TN06AD4950", "confidence": 0.98}},
                    {{"type": "GSTIN", "candidate_value": "33AAACS8779D1Z7", "confidence": 0.99}}
                ],
                "sections": [
                    {{"name": "Place of Delivery", "content": {{"address": "...", "gstin": "..."}}, "confidence": 0.95}}
                ]
            }}
            
            TEXT: {text}
            """
            
            response = await client.generate(
                prompt=prompt,
                system_prompt="You are an extraction system.",
                temperature=0.0,
                max_tokens=1000
            )
            print(f"RAW LLM RESPONSE: {response}")
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if not json_match:
                return {"identifiers": [], "sections": []}
                
            data = json.loads(json_match.group(0))
            
            results = {"identifiers": [], "sections": []}
            
            # System extracts exact spans for identifiers to avoid hallucination
            for ident in data.get("identifiers", []):
                cand = str(ident.get("candidate_value", ""))
                raw_type = ident.get("type", "")
                if cand and raw_type:
                    # Dynamically accept any entity type returned by the LLM
                    # Normalize to uppercase with underscores
                    canonical_type = str(raw_type).strip().upper().replace(' ', '_')
                    # Find exact span in original text
                    idx = text.find(cand)
                    if idx != -1:
                        results["identifiers"].append({
                            "type": canonical_type,
                            "value": text[idx:idx+len(cand)],
                            "start_offset": idx,
                            "end_offset": idx+len(cand),
                            "source_text": text[max(0, idx-20):min(len(text), idx+len(cand)+20)],
                            "confidence": float(ident.get("confidence", 1.0))
                        })
            
            for sec in data.get("sections", []):
                if isinstance(sec.get("content"), dict):
                    results["sections"].append({
                        "name": sec.get("name", ""),
                        "content": sec.get("content", {})
                    })
                
            return results
        except Exception as e:
            logger.error(f"Structured extraction failed: {e}")
            # Print raw response for debugging
            try:
                print(f"RAW LLM RESPONSE: {response}")
            except:
                pass
            return {"identifiers": [], "sections": []}

    @staticmethod
    def _split_into_segments(text: str, max_segment_chars: int = 8000) -> list[str]:
        if not text:
            return []
        segments = []
        current_segment = []
        current_length = 0
        for line in text.split("\n"):
            current_segment.append(line)
            current_length += len(line) + 1
            if current_length >= max_segment_chars:
                segments.append("\n".join(current_segment))
                current_segment = []
                current_length = 0
        if current_segment:
            segments.append("\n".join(current_segment))
        return segments

    @staticmethod
    async def _repair_segment(segment: str, idx: int, total: int, system_prompt: str) -> str:
        if not segment.strip():
            return segment
        from .llm.deepinfra_llm import DeepInfraLLMClient
        llm_client = DeepInfraLLMClient()
        user_prompt = (
            f"Here is segment {idx + 1} of {total} of the raw Markdown content to repair:\n\n"
            f"{segment}"
        )
        try:
            max_tokens = PDFExtractor._get_adaptive_max_tokens(segment, 3, 1000, 4096)
            res = await llm_client.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.0,
                max_tokens=max_tokens
            )
            res = res.strip()
            if res.startswith("```"):
                res = re.sub(r"^```(?:markdown)?\r?\n", "", res)
                res = re.sub(r"\r?\n```$", "", res)
                res = res.strip()
            return res if res else segment
        except Exception as e:
            logger.error(f"Failed to repair Markdown segment {idx+1}/{total}: {e}")
            return segment

    @staticmethod
    async def _reconstruct_segment(segment: str, idx: int, total: int, system_prompt: str) -> str:
        if not segment.strip():
            return segment
        from .llm.deepinfra_llm import DeepInfraLLMClient
        llm_client = DeepInfraLLMClient()
        user_prompt = (
            f"Here is segment {idx + 1} of {total} of the raw text to reconstruct into structured Markdown:\n\n"
            f"{segment}"
        )
        try:
            max_tokens = PDFExtractor._get_adaptive_max_tokens(segment, 4, 1000, 4096)
            res = await llm_client.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.0,
                max_tokens=max_tokens
            )
            res = res.strip()
            if res.startswith("```"):
                res = re.sub(r"^```(?:markdown)?\r?\n", "", res)
                res = re.sub(r"\r?\n```$", "", res)
                res = res.strip()
            return res if res else segment
        except Exception as e:
            logger.error(f"Failed to reconstruct text segment {idx+1}/{total}: {e}")
            return segment

    @staticmethod
    async def _repair_markdown_with_llm(markdown_content: str) -> str:
        """
        Use the LLM (Qwen/GPT) to post-process and repair the Gdocz raw Markdown:
        - Fix broken tables, headers, lists
        - Restore decimal quantities (e.g., preserving dots in quantities/prices)
        - Merge split words (e.g., "Maintenanc e" -> "Maintenance")
        - Keep all values/text unchanged (do not summarize or omit data)
        - Return valid Markdown only
        """
        if not markdown_content or not markdown_content.strip():
            return markdown_content

        # Placeholder strategy for base64 images to save tokens and prevent corruption
        image_placeholders = {}
        placeholder_md = markdown_content
        
        # Match base64 data URIs
        data_uri_pattern = re.compile(r'(data:image/[^\s"\'>\)]+)')
        matches = data_uri_pattern.findall(markdown_content)
        
        for idx, base64_str in enumerate(matches):
            placeholder = f"__IMG_BASE64_PLACEHOLDER_{idx}__"
            image_placeholders[placeholder] = base64_str
            placeholder_md = placeholder_md.replace(base64_str, placeholder)

        system_prompt = (
            "You are an expert document reconstruction and Markdown repair assistant. "
            "Your task is to take a raw, imperfectly extracted Markdown document and return a cleaned, "
            "semantically correct, and structurally valid Markdown version.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Fix broken Markdown table structures. Ensure tables have proper pipes, headers, and separator rows (e.g., |---|---).\n"
            "2. Merge separated table headers and data if they were split.\n"
            "3. Restore decimal quantities (e.g., if a quantity or rate lost its dot and became 9000 instead of 9.000, correct it based on the context).\n"
            "4. Merge split words (e.g., merge 'Maintenanc e' into 'Maintenance', 'elnvoice' to 'eInvoice').\n"
            "5. Keep all document values, numbers, names, and text content completely unchanged. Do not summarize or omit any information.\n"
            "6. DO NOT modify, remove, or corrupt any image placeholders like __IMG_BASE64_PLACEHOLDER_0__. Keep them exactly in their original positions/tags.\n"
            "7. Return ONLY the valid Markdown. Do not include markdown code fences (like ```markdown), do not write any introductory or concluding text."
        )

        try:
            logger.info("Starting LLM-based Markdown repair in parallel segments...")
            segments = PDFExtractor._split_into_segments(placeholder_md, max_segment_chars=6000)
            logger.info(f"Split Markdown into {len(segments)} segments.")
            
            repaired_segments = []
            batch_size = 5
            for i in range(0, len(segments), batch_size):
                batch_segs = segments[i:i+batch_size]
                batch_tasks = [
                    PDFExtractor._repair_segment(batch_segs[j], i+j, len(segments), system_prompt)
                    for j in range(len(batch_segs))
                ]
                batch_res = await asyncio.gather(*batch_tasks)
                repaired_segments.extend(batch_res)
                
            repaired_md = "\n\n".join(repaired_segments)
            repaired_md = repaired_md.strip()

            if repaired_md:
                logger.info(f"LLM Markdown repair success: original length {len(markdown_content)} -> repaired length {len(repaired_md)}")
                
                # Restore original base64 images
                for placeholder, base64_str in image_placeholders.items():
                    repaired_md = repaired_md.replace(placeholder, base64_str)
                    
                return repaired_md
        except Exception as e:
            logger.error(f"Failed to repair Markdown with LLM: {e}")
            
        return markdown_content

    @staticmethod
    async def _reconstruct_text_to_markdown_with_llm(raw_text: str) -> str:
        """
        Use the LLM (Qwen/GPT) to reconstruct messy, layout-scrambled plain text
        from pdfplumber/OCR into clean, semantic, and well-structured Markdown.
        """
        if not raw_text or not raw_text.strip():
            return raw_text

        system_prompt = (
            "You are an expert document reconstruction assistant. Your task is to take messy, "
            "scrambled plain text extracted from a PDF (where tables, columns, and sections are interleaved "
            "or flattened) and reconstruct it into clean, well-formatted, and semantically correct Markdown.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Identify and reconstruct tables. Group headers and data rows correctly in standard Markdown table format (e.g., | Col1 | Col2 |\n|---|---|\n| Val1 | Val2 |).\n"
            "2. Preserve decimal quantities. Ensure quantities, rates, and values do not lose their decimal points (e.g., '9.000' should remain '9.000' or '9.0').\n"
            "3. Merge split words (e.g., 'Maintenanc e' -> 'Maintenance', 'elnvoice' -> 'eInvoice').\n"
            "4. Retain all original information, including names, dates, amounts, invoice numbers, and line items. Do not omit, summarize, or truncate any data.\n"
            "5. Reconstruct the document hierarchy logically using Markdown syntax: headings (#, ##, ###), lists, etc.\n"
            "6. Return ONLY the valid Markdown. Do not include markdown code fences (like ```markdown), do not write any introductory or concluding text."
        )

        try:
            logger.info("Starting LLM-based text to Markdown reconstruction in parallel segments...")
            segments = PDFExtractor._split_into_segments(raw_text, max_segment_chars=6000)
            logger.info(f"Split text into {len(segments)} segments.")
            
            reconstructed_segments = []
            batch_size = 5
            for i in range(0, len(segments), batch_size):
                batch_segs = segments[i:i+batch_size]
                batch_tasks = [
                    PDFExtractor._reconstruct_segment(batch_segs[j], i+j, len(segments), system_prompt)
                    for j in range(len(batch_segs))
                ]
                batch_res = await asyncio.gather(*batch_tasks)
                reconstructed_segments.extend(batch_res)
                
            reconstructed_md = "\n\n".join(reconstructed_segments)
            reconstructed_md = reconstructed_md.strip()

            if reconstructed_md:
                logger.info(f"LLM text reconstruction success: original length {len(raw_text)} -> markdown length {len(reconstructed_md)}")
                return reconstructed_md
        except Exception as e:
            logger.error(f"Failed to reconstruct text with LLM: {e}")
            
        return raw_text

    @staticmethod
    async def _repair_html_with_llm(html_content: str) -> str:
        """
        Use the LLM (Qwen/GPT) to post-process and repair the Gdocz raw HTML:
        - Fix broken tables and merge header/rows
        - Restore decimal quantities (e.g., preserving dots in quantities/prices)
        - Merge split words (e.g., "Maintenanc e" -> "Maintenance")
        - Keep all values/text unchanged (do not summarize or omit data)
        - Return valid HTML only
        """
        if not html_content or not html_content.strip():
            return html_content

        # Placeholder strategy for base64 images to save tokens and prevent corruption
        image_placeholders = {}
        placeholder_html = html_content
        
        # Match base64 data URIs
        data_uri_pattern = re.compile(r'(data:image/[^\s"\'>\)]+)')
        matches = data_uri_pattern.findall(html_content)
        
        for idx, base64_str in enumerate(matches):
            placeholder = f"__IMG_BASE64_PLACEHOLDER_{idx}__"
            image_placeholders[placeholder] = base64_str
            placeholder_html = placeholder_html.replace(base64_str, placeholder)

        from .llm.deepinfra_llm import DeepInfraLLMClient
        
        system_prompt = (
            "You are an expert document reconstruction and HTML repair assistant. "
            "Your task is to take a raw, imperfectly extracted HTML document and return a cleaned, "
            "semantically correct, and structurally valid HTML version.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Fix broken table structures. Ensure tables have proper thead/tbody/tr/td/th structure.\n"
            "2. Merge separated table headers and data if they were split into separate tables.\n"
            "3. Restore decimal quantities (e.g., if a quantity or rate lost its dot and became 9000 instead of 9.000, correct it based on the invoice context).\n"
            "4. Merge split words (e.g., merge 'Maintenanc e' into 'Maintenance', 'elnvoice' to 'eInvoice').\n"
            "5. Keep all document values, numbers, names, and text content completely unchanged. Do not summarize or omit any information.\n"
            "6. DO NOT modify, remove, or corruption any image placeholders like __IMG_BASE64_PLACEHOLDER_0__. Keep them exactly in their original tags and positions.\n"
            "7. Return ONLY the valid HTML. Do not include markdown code fences (like ```html), do not write any introductory or concluding text."
        )

        user_prompt = (
            "Here is the raw HTML content to repair:\n\n"
            f"{placeholder_html}"
        )

        try:
            logger.info("Starting LLM-based HTML repair...")
            llm_client = DeepInfraLLMClient()
            # Set a high token limit since the HTML can be large
            max_tokens = PDFExtractor._get_adaptive_max_tokens(placeholder_html, 3, 2000, 16384)
            repaired_html = await llm_client.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.0,
                max_tokens=max_tokens
            )
            repaired_html = repaired_html.strip()
            
            # Remove markdown fences if the LLM outputted them despite instructions
            if repaired_html.startswith("```"):
                # Strip leading ```html or ```
                repaired_html = re.sub(r"^```(?:html)?\r?\n", "", repaired_html)
                repaired_html = re.sub(r"\r?\n```$", "", repaired_html)
                repaired_html = repaired_html.strip()

            if repaired_html:
                logger.info(f"LLM HTML repair success: original length {len(html_content)} -> repaired length {len(repaired_html)}")
                
                # Restore original base64 images
                for placeholder, base64_str in image_placeholders.items():
                    repaired_html = repaired_html.replace(placeholder, base64_str)
                    
                return repaired_html
        except Exception as e:
            logger.error(f"Failed to repair HTML with LLM: {e}")
            
        return html_content

    @staticmethod
    async def _reconstruct_text_to_html_with_llm(raw_text: str) -> str:
        """
        Use the LLM (Qwen/GPT) to reconstruct messy, layout-scrambled plain text
        from pdfplumber/OCR into clean, semantic, and well-structured HTML.
        """
        if not raw_text or not raw_text.strip():
            return raw_text

        from .llm.deepinfra_llm import DeepInfraLLMClient
        
        system_prompt = (
            "You are an expert document reconstruction assistant. Your task is to take messy, "
            "scrambled plain text extracted from a PDF (where tables, columns, and sections are interleaved "
            "or flattened) and reconstruct it into clean, well-formatted, and semantically correct HTML.\n\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. Identify and reconstruct tables. Group headers and data rows correctly. Look for numeric sequences "
            "that represent rows (e.g. quantities, prices, taxes) and align them with descriptions and codes.\n"
            "2. Preserve decimal quantities. Ensure quantities, rates, and values do not lose their decimal points "
            "(e.g., '9.000' should remain '9.000' or '9.0', do not convert it to '9000').\n"
            "3. Merge split words (e.g., 'Maintenanc e' -> 'Maintenance', 'elnvoice' -> 'eInvoice').\n"
            "4. Retain all original information, including names, dates, amounts, invoice numbers, and line items. "
            "Do not omit, summarize, or truncate any data.\n"
            "5. Reconstruct the document hierarchy logically using semantic HTML tags: <h1>, <h2>, <h3>, <p>, <table>, <tr>, <th>, <td>.\n"
            "6. Return ONLY the valid HTML. Do not include markdown code fences (like ```html), do not write any introductory or concluding text."
        )

        user_prompt = (
            "Here is the raw text to reconstruct into structured HTML:\n\n"
            f"{raw_text}"
        )

        try:
            logger.info("Starting LLM-based text to HTML reconstruction...")
            llm_client = DeepInfraLLMClient()
            max_tokens = PDFExtractor._get_adaptive_max_tokens(raw_text, 4, 2000, 16384)
            reconstructed_html = await llm_client.generate(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.0,
                max_tokens=max_tokens
            )
            reconstructed_html = reconstructed_html.strip()
            
            # Remove markdown code fences if outputted
            if reconstructed_html.startswith("```"):
                reconstructed_html = re.sub(r"^```(?:html)?\r?\n", "", reconstructed_html)
                reconstructed_html = re.sub(r"\r?\n```$", "", reconstructed_html)
                reconstructed_html = reconstructed_html.strip()

            if reconstructed_html:
                logger.info(f"LLM text reconstruction success: original length {len(raw_text)} -> html length {len(reconstructed_html)}")
                return reconstructed_html
        except Exception as e:
            logger.error(f"Failed to reconstruct text with LLM: {e}")
            
        return raw_text
