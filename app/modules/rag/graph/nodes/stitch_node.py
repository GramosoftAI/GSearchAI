import logging
from sqlalchemy.future import select
from app.modules.rag.graph.state import GraphState
from app.core.config import get_settings
from app.core.database import get_db_with_tenant
from app.modules.knowledge_bases.models import DocumentChunk

logger = logging.getLogger(__name__)

async def stitch_node(state: GraphState) -> GraphState:
    """
    For the highest-confidence reranked chunks, pull in adjacent
    chunk_index neighbors from the same kb_id so a key-value pair 
    or fact split across a chunk boundary isn't lost.
    """
    reranked_chunks = state.get("reranked_chunks", [])
    if not reranked_chunks:
        return {}

    tenant_id = state["tenant_id"]
    settings = get_settings()
    window = getattr(settings, "stitch_window", 1)
    max_expanded = 3

    if window <= 0:
        return {}

    seen_ids = {str(c.id) for c in reranked_chunks if hasattr(c, "id")}
    expanded = []

    # Only stitch neighbors for the top few chunks
    candidates = sorted(reranked_chunks, key=lambda c: getattr(c, "reranker_score", None) or getattr(c, "final_relevance_score", 0.0) or 0.0, reverse=True)[:max_expanded]

    try:
        async with get_db_with_tenant(tenant_id) as db:
            for chunk in candidates:
                if not hasattr(chunk, "chunk_index") or not hasattr(chunk, "kb_id"):
                    continue
                    
                chunk_index = chunk.chunk_index
                if chunk_index is None:
                    continue

                neighbor_indices = [
                    chunk_index + i
                    for i in range(-window, window + 1)
                    if i != 0
                ]
                
                if not neighbor_indices:
                    continue

                rows = await db.execute(
                    select(DocumentChunk).where(
                        DocumentChunk.kb_id == chunk.kb_id,
                        DocumentChunk.tenant_id == tenant_id,
                        DocumentChunk.chunk_index.in_(neighbor_indices),
                    )
                )
                
                for neighbor in rows.scalars():
                    if str(neighbor.id) not in seen_ids:
                        neighbor.is_stitched_neighbor = True
                        neighbor.reason = "STITCHED_NEIGHBOR"
                        # Inherit score with a slight discount
                        base_score = getattr(chunk, "reranker_score", 0.0)
                        neighbor.reranker_score = base_score * 0.9
                        seen_ids.add(str(neighbor.id))
                        expanded.append(neighbor)
                        
        if expanded:
            logger.info(f"[STITCH] Added {len(expanded)} neighbor chunks for {len(candidates)} candidates")
            return {"reranked_chunks": reranked_chunks + expanded}
            
    except Exception as e:
        logger.error(f"[STITCH_NODE] Failed to stitch neighbors: {e}", exc_info=True)
        
    return {}
