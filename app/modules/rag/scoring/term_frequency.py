from collections import Counter
import re
import math
import logging

logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[a-z0-9]+")

_term_freq_cache = {}

async def get_kb_doc_frequency(kb_id: str, db) -> dict:
    """
    Returns {stemmed_token: number_of_chunks_containing_it} for a KB.
    Cached.
    """
    kb_id_str = str(kb_id)
    if kb_id_str in _term_freq_cache:
        return _term_freq_cache[kb_id_str]

    try:
        from app.modules.knowledge_bases.models import DocumentChunk
        from sqlalchemy import select
        from uuid import UUID
        
        try:
            kb_uuid = UUID(kb_id_str)
        except ValueError:
            kb_uuid = kb_id_str

        stmt = select(DocumentChunk.text).where(DocumentChunk.kb_id == kb_uuid)
        result = await db.execute(stmt)
        
        doc_freq = Counter()
        total_chunks = 0
        for text_val in result.scalars():
            total_chunks += 1
            if text_val:
                tokens = set(TOKEN_RE.findall(text_val.lower()))
                doc_freq.update(tokens)

        result_dict = {"_total_chunks": total_chunks, **doc_freq}
        _term_freq_cache[kb_id_str] = result_dict
        return result_dict
    except Exception as e:
        logger.warning(f"Failed to fetch doc frequency for kb_id={kb_id}: {e}")
        return {"_total_chunks": 1}

def invalidate_kb_doc_frequency(kb_id: str):
    """
    Cache invalidation hook. Call this when a KB is re-ingested or deleted.
    """
    _term_freq_cache.pop(str(kb_id), None)

def idf_discount(term: str, doc_freq: dict, floor: float = 0.15) -> float:
    """
    Returns a multiplier in (floor, 1.0].
    """
    total = doc_freq.get("_total_chunks", 1)
    df = doc_freq.get(term, 0)
    if df == 0:
        return 1.0

    idf = math.log((total + 1) / (df + 1))
    max_idf = math.log(total + 1)
    normalized = idf / max_idf if max_idf > 0 else 1.0

    return max(floor, normalized)
