import re
import sys

def process(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # The new logic for _parse_html:
    new_parse_html = """    @staticmethod
    def _parse_html(html_content: str) -> List[Dict[str, Any]]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        
        for element in soup(["script", "style", "nav", "header", "footer"]):
            element.decompose()
            
        body = soup.body if soup.body else soup
        segments = []
        
        KNOWN_HEADERS = {
            "SUMMARY", "OBJECTIVE", "CAREER OBJECTIVE", "CAREER", "EDUCATION", 
            "EXPERIENCE", "WORK EXPERIENCE", "WORK HISTORY", "PROJECTS", "KEY PROJECTS",
            "PROJECT DETAILS", "SKILLS", "TECHNICAL SKILLS", "ADDITIONAL SKILLS", 
            "CERTIFICATIONS", "LANGUAGES", "AWARDS", "INTERESTS", "PUBLICATIONS", 
            "ABOUT ME", "CONTACT", "CONTACT INFO", "PERSONAL DETAILS", "DECLARATION",
            "ANALYSIS", "PROBABLE CAUSE", "PROBABLE CAUSE AND FINDINGS", 
            "FINDINGS", "HISTORY OF FLIGHT", "METEOROLOGICAL INFORMATION", 
            "AIRCRAFT INFORMATION", "WRECKAGE AND IMPACT INFORMATION",
            "MEDICAL AND PATHOLOGICAL INFORMATION", "TESTS AND RESEARCH",
            "ADDITIONAL INFORMATION", "FLIGHT RECORDERS", "SURVIVAL ASPECTS"
        }
        
        current_section = "Introduction"
        current_heading_level = 1
        
        def traverse(element):
            nonlocal current_section, current_heading_level
            
            from bs4 import NavigableString
            if isinstance(element, NavigableString):
                text = str(element).strip()
                if text:
                    segments.append({
                        "type": "text",
                        "text": text,
                        "section": current_section,
                        "heading_level": current_heading_level
                    })
                return
            
            if element.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                level = int(element.name[1])
                text = element.get_text().strip()
                if text:
                    if text.upper() in KNOWN_HEADERS:
                        current_section = text
                        current_heading_level = level
                        segments.append({
                            "type": "heading",
                            "text": text,
                            "level": level,
                            "section": current_section,
                            "heading_level": current_heading_level
                        })
                    else:
                        # Sub-item title using layout signal
                        segments.append({
                            "type": "project_heading",
                            "text": text,
                            "section": current_section,
                            "heading_level": level
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
                        
                    clean_text = re.sub(r'[*_:\\-\\s&/\\\\;]', '', text)
                    if len(text) <= 50 and text.upper().strip() in KNOWN_HEADERS:
                        current_section = text.strip()
                        current_heading_level = 2
                        segments.append({
                            "type": "heading",
                            "text": text.strip(),
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

            for child in getattr(element, "children", []):
                traverse(child)
                    
        traverse(body)
        return segments"""

    # We will replace from "@staticmethod\n    def _parse_html(html_content: str) -> List[Dict[str, Any]]:"
    # to "return segments" (the end of the _parse_html function)
    start_html = content.find("    @staticmethod\n    def _parse_html")
    end_html = content.find("        return segments", start_html) + len("        return segments")
    
    content = content[:start_html] + new_parse_html + content[end_html:]
    
    new_parse_markdown = """    @staticmethod
    def _parse_markdown(markdown_content: str) -> List[Dict[str, Any]]:
        segments = []
        current_section = "Introduction"
        current_heading_level = 1
        
        lines = markdown_content.split("\\n")
        
        KNOWN_HEADERS = {
            "SUMMARY", "OBJECTIVE", "CAREER OBJECTIVE", "CAREER", "EDUCATION", 
            "EXPERIENCE", "WORK EXPERIENCE", "WORK HISTORY", "PROJECTS", "KEY PROJECTS",
            "PROJECT DETAILS", "SKILLS", "TECHNICAL SKILLS", "ADDITIONAL SKILLS", 
            "CERTIFICATIONS", "LANGUAGES", "AWARDS", "INTERESTS", "PUBLICATIONS", 
            "ABOUT ME", "CONTACT", "CONTACT INFO", "PERSONAL DETAILS", "DECLARATION",
            "ANALYSIS", "PROBABLE CAUSE", "PROBABLE CAUSE AND FINDINGS", 
            "FINDINGS", "HISTORY OF FLIGHT", "METEOROLOGICAL INFORMATION", 
            "AIRCRAFT INFORMATION", "WRECKAGE AND IMPACT INFORMATION",
            "MEDICAL AND PATHOLOGICAL INFORMATION", "TESTS AND RESEARCH",
            "ADDITIONAL INFORMATION", "FLIGHT RECORDERS", "SURVIVAL ASPECTS"
        }
        
        in_table = False
        table_lines = []
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
                
            if "|" in stripped and stripped.startswith("|") and stripped.endswith("|"):
                in_table = True
                table_lines.append(line)
                continue
            else:
                if in_table:
                    segments.append({
                        "type": "table",
                        "text": "\\n".join(table_lines),
                        "section": current_section,
                        "heading_level": current_heading_level
                    })
                    in_table = False
                    table_lines = []
                    
            heading_match = re.match(r'^(#{1,6})\\s+(.*)', stripped)
            if heading_match:
                level = len(heading_match.group(1))
                text = heading_match.group(2).strip()
                if text.upper() in KNOWN_HEADERS:
                    current_section = text
                    current_heading_level = level
                    segments.append({
                        "type": "heading",
                        "text": text,
                        "level": level,
                        "section": current_section,
                        "heading_level": current_heading_level
                    })
                else:
                    segments.append({
                        "type": "project_heading",
                        "text": text,
                        "section": current_section,
                        "heading_level": level
                    })
                continue
                
            clean_line = re.sub(r'[*_:\\-\\s&/\\\\;]', '', stripped)
            raw_upper = re.sub(r'[*_]', '', stripped).strip().upper()
            if len(stripped) <= 50 and raw_upper in KNOWN_HEADERS:
                current_section = re.sub(r'[*_]', '', stripped).strip()
                current_heading_level = 2
                segments.append({
                    "type": "heading",
                    "text": current_section,
                    "level": 2,
                    "section": current_section,
                    "heading_level": current_heading_level
                })
                continue
                
            segments.append({
                "type": "text",
                "text": stripped,
                "section": current_section,
                "heading_level": current_heading_level
            })
            
        if in_table:
            segments.append({
                "type": "table",
                "text": "\\n".join(table_lines),
                "section": current_section,
                "heading_level": current_heading_level
            })
            
        return segments"""

    start_md = content.find("    @staticmethod\n    def _parse_markdown")
    end_md = content.find("        return segments", start_md) + len("        return segments")
    
    content = content[:start_md] + new_parse_markdown + content[end_md:]
    
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

process("c:/Users/hp/Desktop/GSOFT/RAG/GSearchAI/app/core/adaptive_chunker.py")
