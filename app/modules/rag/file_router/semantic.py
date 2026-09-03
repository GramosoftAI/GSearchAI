import logging
from typing import List, Dict, Any
from .schema import FileMatch
from app.core.embeddings import EmbeddingGenerator

logger = logging.getLogger(__name__)

def match_by_summary_embedding(query_embedding: List[float], kb_metadata: Dict[str, Any], candidate_kb_ids: List[str]) -> List[FileMatch]:
    matches = []
    
    for kb_id in candidate_kb_ids:
        meta = kb_metadata.get(kb_id, {})
        summary_emb = meta.get("summary_embedding")
        name = meta.get("name", "Unknown")
        
        if summary_emb is None:
            logger.warning(f"[FileRouter] Skipping KB {kb_id} ({name}) in semantic matching: summary_embedding is NULL.")
            continue
            
        try:
            score = EmbeddingGenerator.cosine_similarity(query_embedding, summary_emb)
            matches.append(
                FileMatch(
                    kb_id=kb_id,
                    name=name,
                    match_type="semantic",
                    score=score,
                    matched_on="summary_embedding"
                )
            )
        except Exception as e:
            logger.error(f"[FileRouter] Error calculating similarity for KB {kb_id}: {e}")
            continue
            
    matches.sort(key=lambda x: x.score, reverse=True)
    return matches
