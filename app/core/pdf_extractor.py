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


class ExtractedText(str):
    def __new__(cls, clean_text: str, raw_html: str, is_html: bool = False):
        obj = super().__new__(cls, clean_text)
        obj.raw_html = raw_html
        obj.is_html = is_html
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
            ExtractedText: Subclass of str containing cleaned text, with .raw_html and .is_html properties.

        Raises:
            ValueError: If no text could be extracted from the PDF
        """
        logger.info(f" PDF Extraction starting: {filename} ({len(pdf_bytes)} bytes)")

        extracted_text = ""

        # ============= PRIMARY: GDOCZ SDK =============
        if settings.gdocz_api_key:
            try:
                raw_html = await PDFExtractor._extract_gdocz(
                    pdf_bytes, filename
                )
                if raw_html and raw_html.strip():
                    logger.info(
                        f" Gdocz extraction success: {filename} "
                        f"({len(raw_html)} chars raw HTML/markdown)"
                    )
                    # Clean page markers if present in HTML
                    raw_html_clean = re.sub(r"<---- Page \d+ ---->\r?\n?", "", raw_html)
                    
                    # LLM-based HTML repair
                    try:
                        raw_html_clean = await PDFExtractor._repair_html_with_llm(raw_html_clean)
                    except Exception as llm_err:
                        logger.warning(f"LLM HTML repair failed, using raw HTML: {llm_err}")
                        
                    # Clean markdown / HTML for RAG
                    cleaned = PDFExtractor._clean_markdown_for_rag(raw_html_clean)
                    logger.info(
                        f" Cleaned for RAG: {len(cleaned)} chars "
                        f"(from {len(raw_html_clean)} raw)"
                    )
                    return ExtractedText(cleaned, raw_html_clean, is_html=True)
                else:
                    logger.warning(
                        f" Gdocz returned empty result for {filename}. "
                        f"Falling back to pdfplumber."
                    )
            except Exception as e:
                logger.warning(
                    f" Gdocz extraction failed for {filename}: {e}. "
                    f"Falling back to pdfplumber."
                )
        else:
            logger.info(
                " GDOCZ_API_KEY not configured. Using pdfplumber directly."
            )

        # ============= FALLBACK: PDFPLUMBER + AI-OCR =============
        try:
            extracted_text = await PDFExtractor._extract_pdfplumber(
                pdf_bytes, filename, tenant_id, agent_id
            )
            if extracted_text and extracted_text.strip():
                logger.info(
                    f" pdfplumber extraction success: {filename} "
                    f"({len(extracted_text)} chars)"
                )
                # LLM-based reconstruction of raw text to clean semantic HTML
                try:
                    reconstructed_html = await PDFExtractor._reconstruct_text_to_html_with_llm(extracted_text)
                    cleaned = PDFExtractor._clean_markdown_for_rag(reconstructed_html)
                    logger.info("Successfully reconstructed pdfplumber plain text to HTML via LLM")
                    return ExtractedText(cleaned, reconstructed_html, is_html=True)
                except Exception as llm_err:
                    logger.warning(f"LLM text reconstruction to HTML failed: {llm_err}. Returning raw plain text.")
                
                return ExtractedText(extracted_text, extracted_text, is_html=False)
        except Exception as e:
            logger.error(f" pdfplumber also failed for {filename}: {e}")

        # ============= BOTH FAILED =============
        raise ValueError(
            f"Could not extract text from PDF: {filename}. "
            f"Both Gdocz SDK and pdfplumber failed."
        )

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
                options = ConvertOptions(mode="chandra")
                
                max_retries = 3
                last_err = None
                result = None
                
                for attempt in range(max_retries):
                    try:
                        logger.info(f"Calling Gdocz SDK convert (attempt {attempt + 1}/{max_retries})")
                        result = client.convert(temp_path, options=options)
                        break
                    except Exception as e:
                        last_err = e
                        logger.warning(f"Gdocz attempt {attempt + 1} failed: {e}")
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
        raw_markdown = await loop.run_in_executor(
            None, _sync_gdocz_convert, pdf_bytes, filename, settings.gdocz_api_key
        )

        return raw_markdown

    # ========================================================================
    # FALLBACK: PDFPLUMBER + AI-OCR
    # ========================================================================

    @staticmethod
    async def _extract_pdfplumber(
        pdf_bytes: bytes,
        filename: str,
        tenant_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> str:
        """
        Fallback extraction using pdfplumber with AI-OCR for scanned pages.

        Args:
            pdf_bytes: Raw PDF bytes
            filename: Original filename
            tenant_id: For AI-OCR billing
            agent_id: For AI-OCR billing

        Returns:
            Extracted text string
        """
        try:
            import pdfplumber
        except ImportError:
            raise ImportError(
                "pdfplumber is not installed. "
                "Run: pip install pdfplumber"
            )

        document_text = ""

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    document_text += text + "\n\n"
                else:
                    # OCR FALLBACK: Page is likely a scan/image
                    logger.info(
                        f" Empty page {page.page_number} in {filename}. "
                        f"Attempting AI-OCR..."
                    )
                    try:
                        from .llm.deepinfra_llm import get_llm_client

                        img = page.to_image(resolution=300).original
                        img_byte_arr = io.BytesIO()
                        img.save(img_byte_arr, format="JPEG")
                        img_bytes = img_byte_arr.getvalue()

                        llm = await get_llm_client()
                        ocr_text = await llm.vision_ocr(
                            img_bytes,
                            tenant_id=tenant_id,
                            agent_id=agent_id,
                        )

                        if ocr_text:
                            document_text += (
                                f"[OCR Page {page.page_number}]:\n"
                                f"{ocr_text}\n\n"
                            )
                            logger.info(
                                f" AI-OCR success for page {page.page_number}"
                            )
                    except Exception as ocr_err:
                        logger.error(
                            f" AI-OCR failed for page {page.page_number}: {ocr_err}"
                        )
                        # Continue  other pages may have text

        return document_text

    # ========================================================================
    # MARKDOWN CLEANING (GraphRAG-Friendly)
    # ========================================================================

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
            max_tokens = min(16384, len(placeholder_html) * 3 + 2000)
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
            max_tokens = min(16384, len(raw_text) * 4 + 2000)
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
