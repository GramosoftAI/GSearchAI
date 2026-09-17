import logging
import math
import asyncio
from app.modules.rag.graph.state import GraphState
from app.core.config import get_settings

logger = logging.getLogger(__name__)

async def rerank_node(state: GraphState) -> GraphState:
    """
    Executes DeepInfra LLM-based reranking on retrieved chunks.
    Implements dual-logic cutoffs (flat vs relative 15%).
    Explicitly bypasses all noise floors if graph_triplets are present.
    """
    chunks = state.get("retrieved_chunks", [])
    if not chunks:
        return {"reranked_chunks": []}

    query = state["query"]
    settings = get_settings()
    model_reranker = getattr(settings, "model_reranker", None)

    scored_chunks = []
    # If no reranker model configured, or chunks are already reranked by pipeline, pass through
    if not model_reranker or len(chunks) <= 1 or any(hasattr(c, "reranker_score") for c in chunks[:3]):
        # Just apply the noise filter thresholds on the existing scores
        scored_chunks = chunks
    else:
        try:
            from app.core.llm.deepinfra_llm import get_llm_client
            llm = await get_llm_client()

            doc_texts = [getattr(c, "text", "") for c in chunks]

            reranked_results = await asyncio.wait_for(
                llm.rerank_documents(
                    query=query,
                    documents=doc_texts,
                    top_n=min(len(doc_texts), 10),
                    model=model_reranker,
                    tenant_id=state["tenant_id"],
                    user_id=state.get("user_id")
                ),
                timeout=10.0
            )

            # Map reranker scores back onto chunk objects
            for rank, r in enumerate(reranked_results):
                orig_idx = r.get("original_index")
                if orig_idx is not None and orig_idx < len(chunks):
                    chunk = chunks[orig_idx]
                    raw_score = r.get("relevance_score", 0.0)
                    chunk.reranker_raw_score = float(raw_score) if isinstance(raw_score, (int, float)) else 0.0
                    if isinstance(raw_score, (int, float)):
                        if raw_score > 1.0 or raw_score < 0.0:
                            prob = 1.0 / (1.0 + math.exp(-max(-20.0, min(20.0, raw_score))))
                        else:
                            prob = raw_score
                    else:
                        prob = 0.95 - (rank * 0.01)

                    normalized_score = max(0.0, min(1.0, float(prob)))
                    chunk.reranker_score = normalized_score
                    chunk.final_relevance_score = normalized_score
                    chunk.reason = "LLM_RERANKED"
                    scored_chunks.append(chunk)

        except Exception as e:
            logger.error(f"[RERANK_NODE] Reranker failed: {e}")
            return {"reranked_chunks": chunks}

    if not scored_chunks:
        return {"reranked_chunks": chunks}

    # Graph Bypass Logic: if triplets exist, skip noise floors
    graph_triplets = state.get("graph_triplets", [])
    if len(graph_triplets) > 0:
        logger.info(f"Graph triplet bypass active ({len(graph_triplets)} triplets). Bypassing noise floors.")
        return {"reranked_chunks": scored_chunks}

    # Dual-logic cutoffs
    is_tabular = state.get("used_sql_fallback", False) or state.get("intent") in ["TABULAR_SQL", "DATA_AGGREGATION"]
    flat_cutoff = 0.01 if is_tabular else 0.02

    max_score = max((getattr(c, "reranker_score", 0) for c in scored_chunks), default=0)
    relative_cutoff = max_score * 0.05  # Lowered to 5% to keep more chunks (e.g. ones scoring 0.25 when top is 0.97)

    survived = []
    for c in scored_chunks:
        score = getattr(c, "reranker_score", 0)
        if score >= flat_cutoff and score >= relative_cutoff:
            survived.append(c)

    return {"reranked_chunks": survived if survived else scored_chunks}
