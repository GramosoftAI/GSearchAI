"""
Adaptive Chunking Engine for Enterprise RAG.
Intelligently chooses and routes to specialized chunkers based on document type and structure.
Supports: PDF, Word Documents, Plain Text, Excel, CSV, URLs/Web Pages, and Semantic/Table chunking.
"""

import re
import logging
from typing import List, Dict, Any, Optional
import pandas as pd

logger = logging.getLogger(__name__)

def html_table_to_markdown(table_tag) -> str:
    """Helper to convert BeautifulSoup HTML table tag to a Markdown table."""
    rows = []
    for tr in table_tag.find_all("tr"):
        cols = [td.get_text().strip() for td in tr.find_all(["td", "th"])]
        if cols:
            rows.append("| " + " | ".join(cols) + " |")
    if not rows:
        return ""
    # Add header separator
    header_sep = "| " + " | ".join(["---"] * len(table_tag.find_all("tr")[0].find_all(["td", "th"]))) + " |"
    rows.insert(1, header_sep)
    return "\n".join(rows)


class TableChunker:
    """
    Markdown Table Chunker.
    Keeps small tables together, repeats headers when splitting large tables,
    preserves column names and row relationships.
    """
    @staticmethod
    def chunk(table_text: str, max_chunk_size: int = 2500) -> List[str]:
        if len(table_text) <= max_chunk_size:
            return [table_text]
            
        rows = table_text.split('\n')
        # Extract header (usually first 2 rows: header + separator)
        if len(rows) > 2 and '---' in rows[1]:
            header = rows[0] + '\n' + rows[1]
            data_rows = rows[2:]
        else:
            # No clear separator, just use first row as header
            header = rows[0]
            data_rows = rows[1:]
            
        chunks = []
        current_chunk = header
        
        for row in data_rows:
            if not row.strip():
                continue
            test_chunk = current_chunk + '\n' + row
            if len(test_chunk) <= max_chunk_size:
                current_chunk = test_chunk
            else:
                if current_chunk != header:
                    chunks.append(current_chunk)
                new_chunk = header + '\n' + row
                while len(new_chunk) > max_chunk_size:
                    chunks.append(new_chunk[:max_chunk_size])
                    new_chunk = header + '\n' + new_chunk[max_chunk_size:]
                current_chunk = new_chunk
                
        if current_chunk and current_chunk != header:
            chunks.append(current_chunk)
            
        return chunks


class FAQChunker:
    """
    Detects Q&A pairs (e.g. Q: ... A: ...) and returns them as individual chunks.
    """
    @staticmethod
    def detect_and_chunk(text: str) -> List[str]:
        # Detect patterns: Q: ... A: ..., Question: ... Answer: ...
        faq_pattern = re.compile(
            r'(?:^|\n)(?:Q|q|Question|question|QUESTION):\s*(.*?)\n\s*(?:A|a|Answer|answer|ANSWER):\s*(.*?)(?=\n(?:Q|q|Question|question|QUESTION):|$)',
            re.DOTALL | re.IGNORECASE
        )
        matches = faq_pattern.findall(text)
        chunks = []
        for q, a in matches:
            chunks.append(f"Question: {q.strip()}\nAnswer: {a.strip()}")
        return chunks


class SemanticChunker:
    """
    Splits content into paragraphs, groups them into micro-chunks to reduce embedding costs,
    and then groups them based on cosine similarity of their embeddings.
    """
    @staticmethod
    async def chunk(text: str, max_chunk_size: int = 2500, threshold: float = 0.75) -> List[str]:
        from .structural_parser import RegionDetector, RegionType
        
        # 1. Parse into semantic regions
        regions = RegionDetector.detect_regions(text)
        
        final_paragraphs = []
        for region in regions:
            p = region["content"]
            if region["type"] == RegionType.TABLE:
                if len(p) > max_chunk_size:
                    table_chunks = TableChunker.chunk(p, max_chunk_size)
                    final_paragraphs.extend(table_chunks)
                else:
                    final_paragraphs.append(p)
            elif len(p) > max_chunk_size:
                sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', p) if s.strip()]
                for s in sentences:
                    if len(s) > max_chunk_size:
                        # Hard character-limit split if a sentence is massive
                        temp_s = s
                        while len(temp_s) > max_chunk_size:
                            final_paragraphs.append(temp_s[:max_chunk_size])
                            temp_s = temp_s[max_chunk_size:]
                        if temp_s:
                            final_paragraphs.append(temp_s)
                    else:
                        final_paragraphs.append(s)
            else:
                final_paragraphs.append(p)
                
        paragraphs = final_paragraphs
        if not paragraphs:
            return []
            
        # 2. Group adjacent paragraphs into micro-chunks to reduce embedding API calls
        micro_chunks = []
        current_micro = []
        current_len = 0
        target_micro_size = max_chunk_size // 2  # target around 1250 characters
        
        for p in paragraphs:
            if current_len + len(p) + 2 > target_micro_size and current_micro:
                micro_chunks.append("\n\n".join(current_micro))
                current_micro = [p]
                current_len = len(p)
            else:
                current_micro.append(p)
                current_len += len(p) + 2
                
        if current_micro:
            micro_chunks.append("\n\n".join(current_micro))
            
        # Cost Optimization: if only 1 micro-chunk and it is within limit, return immediately
        if len(micro_chunks) <= 1:
            # If the single micro-chunk exceeds max_chunk_size, we must split it by character limit as a final safety
            if micro_chunks and len(micro_chunks[0]) > max_chunk_size:
                chunks = []
                temp = micro_chunks[0]
                while len(temp) > max_chunk_size:
                    chunks.append(temp[:max_chunk_size])
                    temp = temp[max_chunk_size:]
                if temp:
                    chunks.append(temp)
                return chunks
            return micro_chunks
            
        # 3. Generate embeddings for micro-chunks
        from app.core.embeddings import EmbeddingGenerator
        embeddings = await EmbeddingGenerator.generate_embeddings_batch(micro_chunks)
        if len(embeddings) != len(micro_chunks):
            # Fallback if embeddings batch generation fails
            return micro_chunks
        
        # 4. Group adjacent micro-chunks by cosine similarity
        chunks = []
        current_chunk_micros = [micro_chunks[0]]
        current_emb = embeddings[0]
        chunk_emb_count = 1
        
        for i in range(1, len(micro_chunks)):
            sim = EmbeddingGenerator.cosine_similarity(current_emb, embeddings[i])
            
            # Check length of current chunk plus new micro-chunk
            current_len = sum(len(m) for m in current_chunk_micros) + len(micro_chunks[i]) + 2
            
            if sim < threshold or current_len > max_chunk_size:
                # Save previous chunk
                chunks.append("\n\n".join(current_chunk_micros))
                current_chunk_micros = [micro_chunks[i]]
                current_emb = embeddings[i]
                chunk_emb_count = 1
            else:
                # Rolling average of embedding to represent current chunk context
                current_emb = [
                    (current_emb[j] * chunk_emb_count + embeddings[i][j]) / (chunk_emb_count + 1)
                    for j in range(len(current_emb))
                ]
                current_chunk_micros.append(micro_chunks[i])
                chunk_emb_count += 1
                
        if current_chunk_micros:
            chunks.append("\n\n".join(current_chunk_micros))
            
        return chunks


def df_to_markdown(df: pd.DataFrame) -> str:
    """Custom helper to convert pandas DataFrame to Markdown table without tabulate dependency."""
    if df.empty:
        return ""
    headers = [str(col) for col in df.columns]
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for _, row in df.iterrows():
        vals = [str(val).replace('\n', ' ').replace('\r', '') if val is not None else "" for val in row]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)


class ExcelChunker:
    """
    Intelligently chunks Excel sheets by grouping columns (cardinality-based)
    or row count with repeated headers.
    """
    @staticmethod
    def chunk(df: pd.DataFrame, sheet_name: str = "Sheet1", max_chunk_size: int = 2500) -> List[Dict[str, Any]]:
        df = df.dropna(how="all")
        if df.empty:
            return []
            
        # Detect grouping columns dynamically (reasonable cardinality: 2 to 20 unique values)
        group_col = None
        
        for col in df.columns:
            col_lower = str(col).lower().strip()
            # Skip ID, Index, Key or Float columns
            if any(term in col_lower for term in ["id", "index", "key"]):
                continue
            if pd.api.types.is_float_dtype(df[col]):
                continue
                
            cardinality = df[col].nunique()
            if 2 <= cardinality <= 20 and cardinality < len(df) * 0.7:
                group_col = col
                break
                    
        chunks = []
        
        if group_col:
            # Group rows by that column
            grouped = df.groupby(group_col)
            position = 0
            for name, group_df in grouped:
                # Convert group to Markdown table
                table_text = df_to_markdown(group_df)
                
                # Split table if too large using TableChunker
                sub_chunks = TableChunker.chunk(table_text, max_chunk_size=max_chunk_size)
                row_start = group_df.index[0]
                
                for sc in sub_chunks:
                    chunks.append({
                        "chunk_text": sc,
                        "chunk_type": "group",
                        "source_type": "excel",
                        "position": position,
                        "section": f"Group: {group_col} = {name}",
                        "sheet": sheet_name,
                        "metadata": {
                            "group": f"{group_col}={name}",
                            "row_start": int(row_start),
                            "group_value": str(name),
                            "group_column": str(group_col),
                            "rows": group_df.to_dict(orient="records")
                        }
                    })
                    position += 1
        else:
            # Chunk by row count (fallback)
            # Estimate how many rows can fit in a chunk based on average row string length
            avg_row_len = df.astype(str).apply(lambda x: x.str.len()).sum(axis=1).mean()
            if pd.isna(avg_row_len) or avg_row_len <= 0:
                avg_row_len = 100
            
            rows_per_chunk = max(1, int((max_chunk_size - 500) // avg_row_len))
            rows_per_chunk = min(50, max(5, rows_per_chunk))
            
            position = 0
            for i in range(0, len(df), rows_per_chunk):
                chunk_df = df.iloc[i : i + rows_per_chunk]
                table_text = df_to_markdown(chunk_df)
                sub_chunks = TableChunker.chunk(table_text, max_chunk_size=max_chunk_size)
                
                for sc in sub_chunks:
                    chunks.append({
                        "chunk_text": sc,
                        "chunk_type": "rows",
                        "source_type": "excel",
                        "position": position,
                        "section": f"Rows {i} to {i + len(chunk_df)}",
                        "sheet": sheet_name,
                        "metadata": {
                            "group": None,
                            "row_start": i,
                            "rows": chunk_df.to_dict(orient="records")
                        }
                    })
                    position += 1
                    
        return chunks


class CSVChunker:
    """
    Chunks CSV inputs similarly to Excel sheets.
    """
    @staticmethod
    def chunk(df: pd.DataFrame, max_chunk_size: int = 2500) -> List[Dict[str, Any]]:
        chunks = ExcelChunker.chunk(df, sheet_name="Sheet1", max_chunk_size=max_chunk_size)
        for c in chunks:
            c["source_type"] = "csv"
        return chunks


class URLChunker:
    """
    Chunks HTML content by cleaning up scripts/styles/ads,
    extracting headings and tables, and applying hierarchical heading-based chunking.
    """
    @staticmethod
    async def chunk(html_content: str, max_chunk_size: int = 2500) -> List[Dict[str, Any]]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Preprocessing: Remove clutter
        for element in soup(["script", "style", "nav", "header", "footer", "aside", "form", "iframe"]):
            element.decompose()
            
        for element in soup.find_all(attrs={"class": re.compile(r"ad-|banner|promo|popup", re.I)}):
            element.decompose()
        for element in soup.find_all(attrs={"id": re.compile(r"ad-|banner|promo|popup", re.I)}):
            element.decompose()
            
        # Prune DOM to main content container if available to speed up traversal on large sites
        main_content = None
        for selector in ["main", "article", "#content", ".content", "#main", ".main", '[role="main"]']:
            found = soup.select_one(selector)
            if found:
                main_content = found
                break
                
        body = main_content if main_content else (soup.body if soup.body else soup)
        
        # Traverse DOM and split content by headings
        sections = []
        current_heading = "Introduction"
        current_content = []
        
        for element in body.find_all(True):
            if element.name in ["h1", "h2", "h3", "h4"]:
                # Save previous section
                content_text = "".join(current_content).strip()
                if content_text:
                    sections.append((current_heading, content_text))
                current_heading = element.get_text().strip()
                current_content = []
            elif element.name == "table":
                markdown_table = html_table_to_markdown(element)
                if markdown_table:
                    current_content.append("\n\n" + markdown_table + "\n\n")
            elif element.name in ["p", "li", "pre", "code"]:
                has_child_blocks = element.find(["p", "li", "table", "pre", "code"])
                if not has_child_blocks:
                    text = element.get_text().strip()
                    if text:
                        current_content.append(text + "\n\n")
                        
        content_text = "".join(current_content).strip()
        if content_text:
            sections.append((current_heading, content_text))
            
        if not sections:
            clean_text = body.get_text("\n").strip()
            sections = [("Main Content", clean_text)]
            
        # Detect FAQ page structure
        total_text = "\n".join(c for _, c in sections)
        faq_chunks = FAQChunker.detect_and_chunk(total_text)
        if faq_chunks and len(faq_chunks) > len(total_text) // 5000:
            chunks = []
            for idx, fc in enumerate(faq_chunks):
                chunks.append({
                    "chunk_text": fc,
                    "chunk_type": "faq",
                    "source_type": "url",
                    "position": idx,
                    "section": "FAQ",
                    "sheet": None,
                    "metadata": {}
                })
            return chunks

        chunks = []
        position = 0
        for heading, content in sections:
            chunk_type = "section"
            if any(method in content for method in ["POST /", "GET /", "PUT /", "DELETE /", "PATCH /"]):
                chunk_type = "api_doc"
            elif any(kw in heading.lower() for kw in ["faq", "q&a", "question"]):
                chunk_type = "faq"
                
            table_pattern = re.compile(r'((?:^\|.*?\|[ \t]*(?:\n|$))+)', re.MULTILINE)
            tables = table_pattern.findall(content)
            
            if tables:
                last_idx = 0
                for match in table_pattern.finditer(content):
                    pre_text = content[last_idx:match.start()].strip()
                    if pre_text:
                        if len(pre_text) <= max_chunk_size:
                            chunks.append({
                                "chunk_text": pre_text,
                                "chunk_type": chunk_type,
                                "source_type": "url",
                                "position": position,
                                "section": heading,
                                "sheet": None,
                                "metadata": {}
                            })
                            position += 1
                        else:
                            semantic_subchunks = await SemanticChunker.chunk(pre_text, max_chunk_size=max_chunk_size)
                            for sc in semantic_subchunks:
                                chunks.append({
                                    "chunk_text": sc,
                                    "chunk_type": "semantic",
                                    "source_type": "url",
                                    "position": position,
                                    "section": heading,
                                    "sheet": None,
                                    "metadata": {}
                                })
                                position += 1
                    
                    table_chunks = TableChunker.chunk(match.group(0).strip(), max_chunk_size=max_chunk_size)
                    for tc in table_chunks:
                        chunks.append({
                            "chunk_text": tc,
                            "chunk_type": "table",
                            "source_type": "url",
                            "position": position,
                            "section": heading,
                            "sheet": None,
                            "metadata": {}
                        })
                        position += 1
                    last_idx = match.end()
                
                post_text = content[last_idx:].strip()
                if post_text:
                    if len(post_text) <= max_chunk_size:
                        chunks.append({
                            "chunk_text": post_text,
                            "chunk_type": chunk_type,
                            "source_type": "url",
                            "position": position,
                            "section": heading,
                            "sheet": None,
                            "metadata": {}
                        })
                        position += 1
                    else:
                        semantic_subchunks = await SemanticChunker.chunk(post_text, max_chunk_size=max_chunk_size)
                        for sc in semantic_subchunks:
                            chunks.append({
                                "chunk_text": sc,
                                "chunk_type": "semantic",
                                "source_type": "url",
                                "position": position,
                                "section": heading,
                                "sheet": None,
                                "metadata": {}
                            })
                            position += 1
            else:
                if len(content) <= max_chunk_size:
                    chunks.append({
                        "chunk_text": content,
                        "chunk_type": chunk_type,
                        "source_type": "url",
                        "position": position,
                        "section": heading,
                        "sheet": None,
                        "metadata": {}
                    })
                    position += 1
                else:
                    semantic_subchunks = await SemanticChunker.chunk(content, max_chunk_size=max_chunk_size)
                    for sc in semantic_subchunks:
                        chunks.append({
                            "chunk_text": sc,
                            "chunk_type": "semantic",
                            "source_type": "url",
                            "position": position,
                            "section": heading,
                            "sheet": None,
                            "metadata": {}
                        })
                        position += 1
                        
        return chunks


class PDFStructureParser:
    """
    Parses HTML or Markdown text into structured segments.
    Each segment is a dict containing:
    - type: "heading", "table", "text"
    - text: content of the segment
    - section: current section heading
    - heading_level: heading level (1-6) or None
    """
    @staticmethod
    def parse(raw_content: str) -> List[Dict[str, Any]]:
        if not raw_content:
            return []
            
        # Detect HTML
        is_html = False
        if any(tag in raw_content.lower() for tag in ["<html", "<body", "<p>", "<table", "</div>", "</span>", "</h1>"]):
            is_html = True
            
        if is_html:
            return PDFStructureParser._parse_html(raw_content)
        else:
            return PDFStructureParser._parse_markdown(raw_content)

    @staticmethod
    def _parse_html(html_content: str) -> List[Dict[str, Any]]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Preprocessing: Remove scripts, styles
        for element in soup(["script", "style", "nav", "header", "footer"]):
            element.decompose()
            
        body = soup.body if soup.body else soup
        
        segments = []
        current_section = "Introduction"
        current_heading_level = 1
        
        def traverse(element):
            nonlocal current_section, current_heading_level
            
            if element.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                level = int(element.name[1])
                text = element.get_text().strip()
                if text:
                    # Check if it should be a project heading
                    is_project = False
                    if current_section.upper() in ["PROJECTS", "PROJECT DETAILS", "WORK EXPERIENCE", "EXPERIENCE"]:
                        if 5 <= len(text) <= 75 and not text.endswith((".", ",", ";", "?", "!")):
                            common_keywords = {
                                "SUMMARY", "OBJECTIVE", "CAREER OBJECTIVE", "CAREER", "EDUCATION", 
                                "EXPERIENCE", "WORK EXPERIENCE", "WORK HISTORY", "PROJECTS", 
                                "PROJECT DETAILS", "SKILLS", "TECHNICAL SKILLS", "ADDITIONAL SKILLS", 
                                "CERTIFICATIONS", "LANGUAGES", "AWARDS", "INTERESTS", "PUBLICATIONS", 
                                "ABOUT ME", "CONTACT", "CONTACT INFO", "PERSONAL DETAILS", "DECLARATION"
                            }
                            is_all_caps = text.isupper() and any(c.isalpha() for c in text)
                            if text.upper() not in common_keywords and not (is_all_caps and len(text.split()) == 1):
                                has_tech_parentheses = bool(re.search(r'\([^)]+(?:python|javascript|html|css|sql|c\+\+|java|aws|react|vue|angular|django|flask|sqlite|postgres)[^)]*\)', text, re.IGNORECASE))
                                has_using_tech = bool(re.search(r'\busing\s+[\w\s\&]+', text, re.IGNORECASE))
                                words = text.split()
                                is_title_case = all(w[0].isupper() or w[0] in "(&" for w in words if w and w[0].isalpha())
                                
                                if has_tech_parentheses or has_using_tech or (is_title_case and len(words) <= 6):
                                    is_project = True
                                
                    if is_project:
                        segments.append({
                            "type": "project_heading",
                            "text": text,
                            "section": current_section,
                            "heading_level": level
                        })
                    else:
                        current_section = text
                        current_heading_level = level
                        segments.append({
                            "type": "heading",
                            "text": text,
                            "level": level,
                            "section": current_section,
                            "heading_level": current_heading_level
                        })
                return
                
            if element.name == "table":
                table_html = str(element)
                segments.append({
                    "type": "table",
                    "text": table_html,
                    "section": current_section,
                    "heading_level": current_heading_level
                })
                return
                
            if element.name in ["p", "pre", "blockquote", "ul", "ol"]:
                text = element.get_text().strip()
                if text:
                    parent = element.parent
                    while parent is not None:
                        if parent.name in ["p", "pre", "blockquote", "ul", "ol", "table", "h1", "h2", "h3", "h4", "h5", "h6"]:
                            return
                        parent = parent.parent
                        
                    # 1. Project heading detection heuristic:
                    is_project = False
                    if current_section.upper() in ["PROJECTS", "PROJECT DETAILS", "WORK EXPERIENCE", "EXPERIENCE"]:
                        if 5 <= len(text) <= 75 and not text.endswith((".", ",", ";", "?", "!")):
                            common_keywords = {
                                "SUMMARY", "OBJECTIVE", "CAREER OBJECTIVE", "CAREER", "EDUCATION", 
                                "EXPERIENCE", "WORK EXPERIENCE", "WORK HISTORY", "PROJECTS", 
                                "PROJECT DETAILS", "SKILLS", "TECHNICAL SKILLS", "ADDITIONAL SKILLS", 
                                "CERTIFICATIONS", "LANGUAGES", "AWARDS", "INTERESTS", "PUBLICATIONS", 
                                "ABOUT ME", "CONTACT", "CONTACT INFO", "PERSONAL DETAILS", "DECLARATION"
                            }
                            is_all_caps = text.isupper() and any(c.isalpha() for c in text)
                            if text.upper() not in common_keywords and not (is_all_caps and len(text.split()) == 1):
                                has_tech_parentheses = bool(re.search(r'\([^)]+(?:python|javascript|html|css|sql|c\+\+|java|aws|react|vue|angular|django|flask|sqlite|postgres)[^)]*\)', text, re.IGNORECASE))
                                has_using_tech = bool(re.search(r'\busing\s+[\w\s\&]+', text, re.IGNORECASE))
                                words = text.split()
                                is_title_case = all(w[0].isupper() or w[0] in "(&" for w in words if w and w[0].isalpha())
                                
                                if has_tech_parentheses or has_using_tech or (is_title_case and len(words) <= 6):
                                    is_project = True
                                
                    if is_project:
                        segments.append({
                            "type": "project_heading",
                            "text": text,
                            "section": current_section,
                            "heading_level": current_heading_level + 1
                        })
                        return

                    # 2. Plain text heading detection heuristic inside <p>:
                    is_h = False
                    if element.name == "p" and len(text) <= 50 and not text.endswith((".", ",", "?", "!")):
                        clean_h = re.sub(r'[:\-\s\&\/\\]', '', text)
                        if clean_h.isalnum():
                            has_alpha = any(c.isalpha() for c in text)
                            is_all_caps = has_alpha and text.isupper()
                            
                            common_keywords = {
                                "SUMMARY", "OBJECTIVE", "CAREER OBJECTIVE", "CAREER", "EDUCATION", 
                                "EXPERIENCE", "WORK EXPERIENCE", "WORK HISTORY", "PROJECTS", 
                                "PROJECT DETAILS", "SKILLS", "TECHNICAL SKILLS", "ADDITIONAL SKILLS", 
                                "CERTIFICATIONS", "LANGUAGES", "AWARDS", "INTERESTS", "PUBLICATIONS", 
                                "ABOUT ME", "CONTACT", "CONTACT INFO", "PERSONAL DETAILS", "DECLARATION"
                            }
                            if is_all_caps or text.upper() in common_keywords:
                                is_h = True
                                
                    if is_h:
                        current_section = text
                        current_heading_level = 2
                        segments.append({
                            "type": "heading",
                            "text": text,
                            "level": 2,
                            "section": current_section,
                            "heading_level": current_heading_level
                        })
                        return
                        
                    segments.append({
                        "type": "text",
                        "text": text,
                        "section": current_section,
                        "heading_level": current_heading_level
                    })
                return

            for child in element.children:
                if child.name is not None:
                    traverse(child)
                    
        traverse(body)
        return segments

    @staticmethod
    def _parse_markdown(markdown_content: str) -> List[Dict[str, Any]]:
        lines = markdown_content.split("\n")
        segments = []
        current_section = "Introduction"
        current_heading_level = 1
        
        in_table = False
        table_lines = []
        text_lines = []
        
        def flush_text():
            nonlocal text_lines
            txt = "\n".join(text_lines).strip()
            if txt:
                segments.append({
                    "type": "text",
                    "text": txt,
                    "section": current_section,
                    "heading_level": current_heading_level
                })
            text_lines = []
            
        def flush_table():
            nonlocal table_lines, in_table
            if table_lines:
                tbl = "\n".join(table_lines).strip()
                segments.append({
                    "type": "table",
                    "text": tbl,
                    "section": current_section,
                    "heading_level": current_heading_level
                })
            table_lines = []
            in_table = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
                
            heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
            
            is_heuristic_heading = False
            heading_text = ""
            level = 2
            
            if not heading_match:
                # 1. FAQ/Question headings: ends with '?' and starts with common question words or is short
                if 5 <= len(stripped) <= 80 and stripped.endswith("?") and any(stripped.lower().startswith(w) for w in ["what", "how", "why", "who", "when", "where", "can", "is", "are", "do", "does", "did"]):
                    is_heuristic_heading = True
                    heading_text = stripped
                    level = 3
                
                # 2. Numbered headings (e.g. 1. Introduction, 2.1 Technical Specs, 3.2.1 Deep Dive)
                # We look for: (digits and dots) + space + Title Case or UPPERCASE words
                elif 3 <= len(stripped) <= 60 and re.match(r"^\d+(?:\.\d+)*\.?\s+[A-Z][a-zA-Z\s\&\-\/]*$", stripped):
                    is_heuristic_heading = True
                    heading_text = stripped
                    level = 2
                    
                # 3. Resume headings / UPPERCASE headings
                # Must consist of alphabetic words, spaces, and optionally separators like &, /, -, :
                # Must be entirely uppercase (at least 3 characters) or match common section keywords
                else:
                    clean_h = re.sub(r'[:\-\s\&\/\\]', '', stripped)
                    if 3 <= len(stripped) <= 60 and clean_h.isalnum() and not stripped.endswith((".", ",", "?", "!")):
                        has_alpha = any(c.isalpha() for c in stripped)
                        is_all_caps = has_alpha and stripped.isupper()
                        
                        common_keywords = {
                            "SUMMARY", "OBJECTIVE", "CAREER OBJECTIVE", "CAREER", "EDUCATION", 
                            "EXPERIENCE", "WORK EXPERIENCE", "WORK HISTORY", "PROJECTS", 
                            "PROJECT DETAILS", "SKILLS", "TECHNICAL SKILLS", "ADDITIONAL SKILLS", 
                            "CERTIFICATIONS", "LANGUAGES", "AWARDS", "INTERESTS", "PUBLICATIONS", 
                            "ABOUT ME", "CONTACT", "CONTACT INFO", "PERSONAL DETAILS", "DECLARATION"
                        }
                        
                        if is_all_caps or stripped.upper() in common_keywords:
                            is_heuristic_heading = True
                            heading_text = stripped
                            level = 2
                            
            # 4. Project heading check
            is_project = False
            if not heading_match and not is_heuristic_heading:
                if current_section.upper() in ["PROJECTS", "PROJECT DETAILS", "WORK EXPERIENCE", "EXPERIENCE"]:
                    if 5 <= len(stripped) <= 75 and not stripped.endswith((".", ",", ";", "?", "!")):
                        # Check for tech stack in parentheses or using keyword
                        has_tech_parentheses = bool(re.search(r'\([^)]+(?:python|javascript|html|css|sql|c\+\+|java|aws|react|vue|angular|django|flask|sqlite|postgres)[^)]*\)', stripped, re.IGNORECASE))
                        has_using_tech = bool(re.search(r'\busing\s+[\w\s\&]+', stripped, re.IGNORECASE))
                        # Or it consists of Title Case words
                        words = stripped.split()
                        is_title_case = all(w[0].isupper() or w[0] in "(&" for w in words if w and w[0].isalpha())
                        
                        if has_tech_parentheses or has_using_tech or (is_title_case and len(words) <= 6):
                            is_project = True

            if heading_match or is_heuristic_heading:
                flush_text()
                flush_table()
                if heading_match:
                    hashes, text = heading_match.groups()
                    level = len(hashes)
                    heading_text = text
                
                current_section = heading_text
                current_heading_level = level
                segments.append({
                    "type": "heading",
                    "text": heading_text,
                    "level": level,
                    "section": current_section,
                    "heading_level": current_heading_level
                })
                continue
                
            if is_project:
                flush_text()
                flush_table()
                segments.append({
                    "type": "project_heading",
                    "text": stripped,
                    "section": current_section,
                    "heading_level": current_heading_level + 1
                })
                continue
                
            if stripped.startswith("|") and stripped.endswith("|"):
                if not in_table:
                    flush_text()
                    in_table = True
                table_lines.append(line)
            else:
                if in_table:
                    flush_table()
                text_lines.append(line)
                
        flush_text()
        flush_table()
        return segments


class PDFChunker:
    """
    Chunks PDF, DOCX, and plain text files using structured parser.
    Detects headings, sections, FAQ patterns, and tables.
    If a section exceeds the maximum size, applies SemanticChunker to divide it.
    """
    @staticmethod
    async def chunk(structure_or_text: Any, max_chunk_size: int = 2500) -> List[Dict[str, Any]]:
        # 1. Parse into structure if string is passed
        if isinstance(structure_or_text, str):
            structure = PDFStructureParser.parse(structure_or_text)
        else:
            structure = structure_or_text
            
        if not structure:
            return []
            
        # 2. Reconstruct text to check for FAQ patterns
        text_elements = []
        for seg in structure:
            if seg["type"] in ["text", "heading"]:
                text_elements.append(seg["text"])
        total_text = "\n\n".join(text_elements)
        
        faq_chunks = FAQChunker.detect_and_chunk(total_text)
        if faq_chunks and len(faq_chunks) > len(total_text) // 5000:
            chunks = []
            for idx, fc in enumerate(faq_chunks):
                chunks.append({
                    "chunk_text": fc,
                    "chunk_type": "faq",
                    "source_type": "pdf",
                    "position": idx,
                    "section": "FAQ",
                    "sheet": None,
                    "metadata": {
                        "source_type": "pdf",
                        "chunk_type": "faq",
                        "section": "FAQ",
                        "heading_level": None,
                        "position": idx
                    }
                })
            return chunks
            
        # 3. Group segments by section or process tables sequentially
        sections = []
        current_section_name = "Introduction"
        current_heading_level = 1
        current_project_name = None
        current_section_texts = []
        current_section_type = "section"
        
        for seg in structure:
            if seg["type"] == "table":
                # Flush current section text
                if current_section_texts:
                    sections.append({
                        "name": current_section_name,
                        "project_name": current_project_name,
                        "level": current_heading_level,
                        "text": "\n\n".join(current_section_texts),
                        "type": current_section_type
                    })
                    current_section_texts = []
                
                # Add table segment directly
                sections.append({
                    "name": seg["section"],
                    "project_name": None,
                    "level": seg["heading_level"],
                    "text": seg["text"],
                    "type": "table"
                })
            elif seg["type"] == "heading":
                # Flush current section text
                if current_section_texts:
                    sections.append({
                        "name": current_section_name,
                        "project_name": current_project_name,
                        "level": current_heading_level,
                        "text": "\n\n".join(current_section_texts),
                        "type": current_section_type
                    })
                    current_section_texts = []
                current_section_name = seg["section"]
                current_heading_level = seg["heading_level"]
                current_project_name = None
                current_section_type = "section"
            elif seg["type"] == "project_heading":
                # Flush current section text
                if current_section_texts:
                    sections.append({
                        "name": current_section_name,
                        "project_name": current_project_name,
                        "level": current_heading_level,
                        "text": "\n\n".join(current_section_texts),
                        "type": current_section_type
                    })
                    current_section_texts = []
                current_project_name = seg["text"]
                current_section_type = "project"
            elif seg["type"] == "text":
                current_section_texts.append(seg["text"])
                
        # Flush final section text
        if current_section_texts:
            sections.append({
                "name": current_section_name,
                "project_name": current_project_name,
                "level": current_heading_level,
                "text": "\n\n".join(current_section_texts),
                "type": current_section_type
            })
            
        # 4. Generate chunks from sections/tables
        chunks = []
        position = 0
        
        current_combined_text = ""
        current_combined_metadata = None
        
        def flush_accumulator():
            nonlocal current_combined_text, current_combined_metadata, chunks, position
            if current_combined_text:
                current_combined_metadata["position"] = position
                chunks.append({
                    "chunk_text": current_combined_text.strip(),
                    "chunk_type": current_combined_metadata["chunk_type"],
                    "source_type": "pdf",
                    "position": position,
                    "section": current_combined_metadata["section"],
                    "sheet": None,
                    "metadata": current_combined_metadata
                })
                position += 1
                current_combined_text = ""
                current_combined_metadata = None

        for sec in sections:
            sec_name = sec["name"]
            sec_project = sec.get("project_name")
            sec_level = sec["level"]
            sec_text = sec["text"]
            sec_type = sec.get("type", "section")
            
            # Format chunk text with metadata prefixes for enhanced retrieval
            if sec_type == "project":
                chunk_text = f"Section: {sec_name}\nProject: {sec_project}\n\n{sec_text}"
                chunk_type_val = "project"
            elif sec_type == "table":
                chunk_text = f"Section: {sec_name}\nTable:\n\n{sec_text}" if sec_name and sec_name != "Introduction" else sec_text
                chunk_type_val = "table"
            else:
                chunk_text = f"Section: {sec_name}\n\n{sec_text}" if sec_name and sec_name != "Introduction" else sec_text
                chunk_type_val = "section"
                
            # If it's a FAQ section (the faq_chunks check was not matched, or this is individual questions)
            if sec_name and sec_name.strip().endswith("?") and chunk_type_val == "section":
                chunk_type_val = "faq"
                
            # If the single section is already huge, flush accumulator and semantically chunk it
            if len(sec_text) > max_chunk_size:
                flush_accumulator()
                # Semantic chunking ONLY inside large sections
                semantic_subchunks = await SemanticChunker.chunk(sec_text, max_chunk_size=max_chunk_size)
                for sc in semantic_subchunks:
                    prefix = f"Section: {sec_name} (continued)\n\n"
                    if sec_type == "project":
                        prefix = f"Section: {sec_name}\nProject: {sec_project} (continued)\n\n"
                        
                    chunks.append({
                        "chunk_text": f"{prefix}{sc}",
                        "chunk_type": chunk_type_val,
                        "source_type": "pdf",
                        "position": position,
                        "section": sec_name,
                        "sheet": None,
                        "metadata": {
                            "source_type": "pdf",
                            "chunk_type": chunk_type_val,
                            "section": sec_name,
                            "project_name": sec_project,
                            "heading_level": sec_level,
                            "position": position
                        }
                    })
                    position += 1
            else:
                # Accumulate small sections
                if len(current_combined_text) + len(chunk_text) > max_chunk_size and current_combined_text:
                    flush_accumulator()
                    
                if not current_combined_metadata:
                    current_combined_metadata = {
                        "source_type": "pdf",
                        "chunk_type": chunk_type_val,
                        "section": sec_name,
                        "project_name": sec_project,
                        "heading_level": sec_level
                    }
                
                current_combined_text += chunk_text + "\n\n"

        # Flush any remaining text in accumulator
        flush_accumulator()

        return chunks


class AdaptiveChunker:
    """
    Intelligently routes inputs to specialized chunkers based on document types.
    """
    @staticmethod
    async def chunk(content: Any, source_type: str, metadata: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        source_type = source_type.lower().strip()
        max_chunk_size = 4000  # Increased default chunk size
        
        # Adaptive chunk sizing based on text density
        if isinstance(content, str):
            lines = content.split('\n')
            if lines:
                avg_words_per_line = sum(len(line.split()) for line in lines) / len(lines)
                if avg_words_per_line > 12:
                    max_chunk_size = 6000  # Dense text: use larger chunks to reduce LLM calls
                elif avg_words_per_line < 5:
                    max_chunk_size = 2500  # Sparse text (TOC, lists): smaller chunks
                    
        if source_type in ["excel", "xlsx", "xls"]:
            if isinstance(content, pd.DataFrame):
                sheet_name = (metadata or {}).get("sheet_name", "Sheet1")
                return ExcelChunker.chunk(content, sheet_name=sheet_name, max_chunk_size=max_chunk_size)
            else:
                all_chunks = []
                if isinstance(content, dict):
                    for s_name, s_df in content.items():
                         all_chunks.extend(ExcelChunker.chunk(s_df, sheet_name=s_name, max_chunk_size=max_chunk_size))
                return all_chunks
                
        elif source_type == "csv":
            if isinstance(content, pd.DataFrame):
                return CSVChunker.chunk(content, max_chunk_size=max_chunk_size)
            return []
            
        elif source_type == "url":
            return await URLChunker.chunk(str(content), max_chunk_size=max_chunk_size)
            
        elif source_type in ["pdf", "docx", "txt", "text"]:
            if source_type == "pdf":
                raw_html = getattr(content, "raw_html", str(content))
                structure = PDFStructureParser.parse(raw_html)
                return await PDFChunker.chunk(structure, max_chunk_size=max_chunk_size)
            else:
                return await PDFChunker.chunk(str(content), max_chunk_size=max_chunk_size)
            
        else:
            fallback_subchunks = await SemanticChunker.chunk(str(content), max_chunk_size=max_chunk_size)
            chunks = []
            for idx, sc in enumerate(fallback_subchunks):
                chunks.append({
                    "chunk_text": sc,
                    "chunk_type": "generic",
                    "source_type": source_type,
                    "position": idx,
                    "section": None,
                    "sheet": None,
                    "metadata": {}
                })
            return chunks

