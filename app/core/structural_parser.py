import re
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class RegionType:
    TEXT = "TEXT"
    TABLE = "TABLE"
    LIST = "LIST"
    HEADER = "HEADER"
    CODE = "CODE"
    FOOTER = "FOOTER"

class RegionDetector:
    """
    Parses Markdown/Text into semantic blocks (Regions).
    """
    @staticmethod
    def detect_regions(text: str) -> List[Dict[str, Any]]:
        regions = []
        # Fallback to single newline split if no double newlines and text is long
        paragraphs = [p.strip() for p in re.split(r'\n\n+', text) if p.strip()]
        if len(paragraphs) <= 1 and len(text) > 2500:
            paragraphs = [p.strip() for p in text.split('\n') if p.strip()]

        for p in paragraphs:
            # 1. Header Detection (Markdown #)
            if re.match(r'^#{1,6}\s+', p):
                level = len(re.match(r'^(#{1,6})', p).group(1))
                regions.append({"type": RegionType.HEADER, "level": level, "content": p})
                continue
                
            # 2. Table Detection
            if "|---" in p.replace(" ", "") and p.strip().startswith("|") and p.strip().endswith("|"):
                regions.append({"type": RegionType.TABLE, "content": p})
                continue
                
            # 3. List Detection (Markdown -, *, or 1.)
            if re.match(r'^(?:[\-\*]|\d+\.)\s+', p):
                regions.append({"type": RegionType.LIST, "content": p})
                continue
                
            # 4. Code Block Detection
            if p.startswith("```") and p.endswith("```"):
                regions.append({"type": RegionType.CODE, "content": p})
                continue
                
            # Fallback to Text
            regions.append({"type": RegionType.TEXT, "content": p})
            
        return regions

class HierarchyExtractor:
    """
    Builds a hierarchical tree from detected regions (e.g., Document -> H1 -> H2 -> Table).
    """
    @staticmethod
    def extract_hierarchy(regions: List[Dict[str, Any]], doc_id: str) -> Dict[str, Any]:
        root = {"id": doc_id, "type": "DOCUMENT", "title": "Document Root", "children": []}
        stack = [root]
        
        for idx, region in enumerate(regions):
            if region["type"] == RegionType.HEADER:
                level = region["level"]
                node = {
                    "id": f"{doc_id}_sec_{idx}", 
                    "type": "SECTION", 
                    "level": level, 
                    "title": region["content"].strip('#').strip(), 
                    "children": []
                }
                
                # Pop stack until we find a parent with a strictly smaller level (higher hierarchy)
                while len(stack) > 1 and stack[-1].get("level", 0) >= level:
                    stack.pop()
                    
                stack[-1]["children"].append(node)
                stack.append(node)
            else:
                # Attach content to current section
                node = {
                    "id": f"{doc_id}_content_{idx}",
                    "type": region["type"],
                    "content": region["content"]
                }
                stack[-1]["children"].append(node)
                
        return root
