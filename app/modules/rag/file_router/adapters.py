import re
from typing import List, Dict, Any

def parse_gdocz_markdown(markdown_text: str) -> List[Dict[str, Any]]:
    """
    Adapter for Gdocz markdown.
    Splits by markdown headers and determines if a section is a table, list, or text.
    Maintains a heading hierarchy (H1 > H2 > H3).
    """
    lines = markdown_text.split('\n')
    sections = []
    
    # State tracking
    hierarchy = []  # List of tuples (level, title)
    curr_text = []
    
    def get_heading_path():
        if not hierarchy:
            return "Document Start"
        return " > ".join(t for lvl, t in hierarchy)
        
    for line in lines:
        header_match = re.match(r'^(#{1,6})\s+(.*)', line)
        if header_match:
            # Save existing section if any text exists
            if curr_text and "".join(curr_text).strip():
                sections.append({
                    "title": get_heading_path(), 
                    "text": "\n".join(curr_text).strip(), 
                    "kind": _detect_kind(curr_text)
                })
            
            level = len(header_match.group(1))
            title = header_match.group(2).strip()
            
            # Pop headings of equal or greater level
            while hierarchy and hierarchy[-1][0] >= level:
                hierarchy.pop()
                
            hierarchy.append((level, title))
            curr_text = []
        else:
            curr_text.append(line)
            
    if curr_text and "".join(curr_text).strip():
        sections.append({
            "title": get_heading_path(), 
            "text": "\n".join(curr_text).strip(), 
            "kind": _detect_kind(curr_text)
        })
        
    return _apply_table_prose_fixture(sections)

def parse_pdf_structure(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Adapter for PDFStructureParser output.
    Assumes blocks is a list of dicts with 'text', 'type', 'heading'.
    """
    sections = []
    for b in blocks:
        kind = "text"
        if b.get('type') == 'table':
            kind = "table"
        elif b.get('type') == 'list':
            kind = "list"
            
        sections.append({
            "title": b.get('heading', 'Unknown'),
            "text": b.get('text', ''),
            "kind": kind
        })
    return _apply_table_prose_fixture(sections)

def _detect_kind(lines: List[str]) -> str:
    text = "\n".join(lines).strip()
    if not text:
        return "text"
        
    # Table detection (markdown tables)
    if "|" in lines[0] and len([l for l in lines if "|" in l]) > len(lines) / 2:
        return "table"
        
    # List detection
    list_markers = [l for l in lines if re.match(r'^[\s]*([-*+]|[0-9]+\.)\s+', l)]
    if len(list_markers) > len(lines) / 2:
        return "list"
        
    return "text"

def _apply_table_prose_fixture(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Table-then-prose bug fixture (no LLM).
    Detects if a 'table' section contains prose at the end (lines without '|').
    Splits the prose into a separate 'text' section following the table.
    """
    fixed = []
    for sec in sections:
        if sec['kind'] == 'table':
            lines = sec['text'].split('\n')
            table_lines = []
            prose_lines = []
            in_prose = False
            
            for line in lines:
                if not in_prose:
                    if '|' in line or not line.strip():
                        table_lines.append(line)
                    else:
                        in_prose = True
                        prose_lines.append(line)
                else:
                    prose_lines.append(line)
                    
            if prose_lines:
                sec['text'] = "\n".join(table_lines).strip()
                fixed.append(sec)
                fixed.append({
                    "title": sec['title'],
                    "text": "\n".join(prose_lines).strip(),
                    "kind": "text"
                })
            else:
                fixed.append(sec)
        else:
            fixed.append(sec)
            
    return [s for s in fixed if s['text']]
