import re
import os
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

STOP_WORDS = {
    'the', 'a', 'an', 'and', 'or', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from',
    'is', 'was', 'were', 'are', 'it', 'this', 'that', 'these', 'those', 'be', 'been', 'has', 'have',
    'had', 'do', 'does', 'did', 'but', 'if', 'as', 'what', 'which', 'who', 'when', 'where', 'why', 'how',
    'so', 'than', 'then', 'too', 'very', 'can', 'will', 'just', 'should', 'now'
}


def clean_display_name(raw_source: str, url: str = "", chunk_id: str = "") -> str:
    """Extracts a clean, human-readable document or source name."""
    if url and url.startswith("http"):
        return url
    if raw_source:
        name = os.path.basename(str(raw_source))
        if name.startswith("PDF: "):
            name = name[5:]
        elif name.startswith("Spreadsheet: "):
            name = name[13:]
        return name
    return f"Document Chunk {chunk_id[:8]}" if chunk_id else "Reference Source"


def extract_citation_evidence(
    chunk_text: str,
    answer: str = "",
    query: str = "",
    chunk_index: int = 0,
    default_page: int = 1
) -> Dict[str, Any]:
    """
    Identifies precise context-level traceability for a chunk:
    1. Paragraph: identifies the specific paragraph containing the supporting evidence.
    2. Lines: pinpoints the exact 1-based start line and end line.
    3. Text: extracts the exact supporting sentence/phrase/words.
    """
    if not chunk_text or not chunk_text.strip():
        return {
            "paragraph": 1,
            "paragraph_number": 1,
            "para_in_chunk": 1,
            "line_start": 1,
            "line_end": 1,
            "supporting_text": "",
            "snippet": "",
        }

    lines = chunk_text.splitlines()
    raw_paras = [p.strip() for p in re.split(r'\n\s*\n', chunk_text) if p.strip()]
    if not raw_paras:
        raw_paras = [chunk_text.strip()]

    # Extract tokens including numbers, symbols, and alphanumeric identifiers
    combined_query_answer = f"{query} {answer}".strip()
    raw_tokens = re.findall(r'\b[a-zA-Z0-9_-]{2,}\b', combined_query_answer)
    token_set = {w.lower() for w in raw_tokens if w.lower() not in STOP_WORDS}

    # 1. Paragraph Identification
    best_p_idx = 0
    best_p_score = -1
    for p_idx, p in enumerate(raw_paras):
        # Strip header markers before calculating lexical overlap
        p_clean = re.sub(r'^(Topic|Section|Source File|Document [^:]+):[^\n]*\n?', '', p, flags=re.MULTILINE).strip()
        p_tokens = {w.lower() for w in re.findall(r'\b[a-zA-Z0-9_-]{2,}\b', p_clean) if w.lower() not in STOP_WORDS}
        score = len(p_tokens.intersection(token_set))
        if score > best_p_score:
            best_p_score = score
            best_p_idx = p_idx

    chosen_para = raw_paras[best_p_idx]

    # 2. Text / Sentence / Passage Identification within chosen paragraph
    is_structured = any(':' in l for l in chosen_para.splitlines()) or '|' in chosen_para
    if is_structured and chosen_para.count('.') <= 2:
        units = [l.strip() for l in chosen_para.splitlines() if l.strip()]
    else:
        units = [s.strip() for s in re.split(r'(?<=[.!?])\s+', chosen_para) if len(s.strip()) > 8]
        if not units:
            units = [chosen_para]

    unit_scores = []
    for u in units:
        u_clean = re.sub(r'^(Topic|Section|Source File|Document [^:]+):[^\n]*\n?', '', u, flags=re.MULTILINE).strip()
        u_tokens = {w.lower() for w in re.findall(r'\b[a-zA-Z0-9_-]{2,}\b', u_clean) if w.lower() not in STOP_WORDS}
        score = len(u_tokens.intersection(token_set))
        unit_scores.append((u, score, u_clean))

    max_score = max((s for _, s, _ in unit_scores), default=0)

    if max_score > 0:
        threshold = max(1, int(max_score * 0.4))
        matching_indices = [idx for idx, (_, s, _) in enumerate(unit_scores) if s >= threshold]
        min_idx = min(matching_indices)
        max_idx = max(matching_indices)
        if max_idx - min_idx <= 4:
            selected_units = [unit_scores[i][0] for i in range(min_idx, max_idx + 1)]
        else:
            selected_units = [unit_scores[i][0] for i in matching_indices]
        clean_supporting_text = " ".join(selected_units).strip()
    else:
        clean_supporting_text = units[0].strip()

    # Clean individual snippet phrases (e.g. strip 'Field: ')
    supporting_snippets = []
    for u in units:
        clean_val = re.sub(r'^[A-Za-z0-9 _-]+:\s*', '', u).strip()
        if len(clean_val) >= 4 and clean_val != "...":
            supporting_snippets.append(clean_val)

    # 3. Line Number Pinpointing (1-based index)
    search_terms = [w for w in re.findall(r'\b[a-zA-Z0-9_-]{3,}\b', clean_supporting_text)[:6]]
    line_start = 1
    for l_idx, line in enumerate(lines):
        line_lower = line.strip().lower()
        if any(term.lower() in line_lower for term in search_terms):
            line_start = l_idx + 1
            break

    sent_lines_count = max(1, len(clean_supporting_text.splitlines()))
    line_end = min(len(lines), line_start + sent_lines_count - 1)
    if line_end < line_start:
        line_end = line_start

    # Global paragraph calculation across document chunks
    global_para_num = (chunk_index * 2) + best_p_idx + 1

    return {
        "paragraph": global_para_num,
        "paragraph_number": global_para_num,
        "para_in_chunk": best_p_idx + 1,
        "line_start": line_start,
        "line_end": line_end,
        "supporting_text": clean_supporting_text,
        "supporting_snippets": supporting_snippets,
        "snippet": clean_supporting_text[:300],
    }


def enrich_chunk_citations(
    chunks: List[Any],
    answer: str = "",
    query: str = ""
) -> List[Dict[str, Any]]:
    """
    Transforms retrieved chunks into rich context-level citation objects with:
    - paragraph
    - lines (line_start, line_end)
    - text (supporting_text, snippet, full chunk text)
    - metadata (page, section, score, source name, kb_id)
    """
    results: List[Dict[str, Any]] = []
    seen_chunk_ids = set()

    for idx, c in enumerate(chunks or []):
        chunk_id = str(getattr(c, "chunk_id", f"chunk_{idx}"))
        if chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(chunk_id)

        prov = getattr(c, "provenance_metadata", {}) or {}
        raw_source = (
            getattr(c, "source", "")
            or prov.get("source", "")
            or getattr(c, "metadata", {}).get("source", "")
            or ""
        )
        url = (
            prov.get("url", "")
            or prov.get("source_url", "")
            or getattr(c, "metadata", {}).get("url", "")
            or getattr(c, "metadata", {}).get("source_url", "")
            or ""
        )
        c_kb_id = str(getattr(c, "kb_id", "") or prov.get("kb_id", ""))

        clean_name = clean_display_name(raw_source, url, chunk_id)
        if getattr(c, "is_stitched_neighbor", False):
            clean_name = f"{clean_name} (Neighbor Context)"

        chunk_text = getattr(c, "text", "") or ""
        c_pos = getattr(c, "position", 0) or idx
        page_num = (
            prov.get("page_number")
            or prov.get("page")
            or getattr(c, "page", None)
            or 1
        )
        section_name = (
            getattr(c, "section", "")
            or prov.get("section", "")
            or prov.get("project_name", "")
            or ""
        )

        evidence = extract_citation_evidence(
            chunk_text=chunk_text,
            answer=answer,
            query=query,
            chunk_index=int(c_pos),
            default_page=int(page_num) if isinstance(page_num, int) else 1
        )

        score_val = round(
            float(
                getattr(c, "final_relevance_score", 0.0)
                or getattr(c, "hybrid_score", 0.0)
                or 0.0
            ),
            3
        )

        results.append({
            "id": chunk_id,
            "chunk_id": chunk_id,
            "source": clean_name,
            "name": clean_name,
            "kb_id": c_kb_id,
            "score": score_val,
            "position": c_pos,
            "section": section_name,
            "page": int(page_num) if isinstance(page_num, (int, str)) and str(page_num).isdigit() else 1,
            "paragraph": evidence["paragraph"],
            "paragraph_number": evidence["paragraph_number"],
            "line_start": evidence["line_start"],
            "line_end": evidence["line_end"],
            "supporting_text": evidence["supporting_text"],
            "supporting_snippets": evidence.get("supporting_snippets", []),
            "snippet": evidence["snippet"],
            "text": chunk_text,
            "s3_path": getattr(c, "s3_path", None) or prov.get("s3_path"),
            "content_type": getattr(c, "content_type", "original"),
            "reason": getattr(c, "reason", "RELEVANT_CONTEXT")
        })

    return results
