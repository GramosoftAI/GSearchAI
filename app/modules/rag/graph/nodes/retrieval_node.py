import asyncio
import logging
from app.modules.rag.graph.state import GraphState
from app.modules.rag.pipeline import RAGPipeline
from app.core.embeddings import EmbeddingGenerator

logger = logging.getLogger(__name__)

async def retrieval_node(state: GraphState) -> GraphState:
    """
    Executes Vector, Graph, and RRF retrieval.
    Deduplicates Triplets and sets the graph_triplets bypass flag.
    """
    # Only run retrieval if it's not a tabular query (tabular routing handles unstructured fallback if needed)
    if state.get("intent") in ["TABULAR_SQL", "DATA_AGGREGATION", "CALCULATION"]:
        return {}

    from app.core.database import get_db_with_tenant
    
    tenant_id = state["tenant_id"]
    query = state["query"]
    

    try:
        async with get_db_with_tenant(tenant_id) as db:
            pipeline = RAGPipeline(tenant_id, db=db)
            
            # Extract the resolved doc_kbs (unstructured) from state, falling back to raw kb_ids if none found
            doc_kbs = state.get("doc_kbs")
            if doc_kbs is not None:
                resolved_kb_ids = [str(kb.id) for kb in doc_kbs]
                if not resolved_kb_ids:
                    return {
                        "retrieved_chunks": [],
                        "graph_triplets": []
                    }
            else:
                resolved_kb_ids = state.get("kb_ids", [])

            # We fetch the embedding from the cache (primed in init_node)
            query_embedding = await EmbeddingGenerator.generate_embedding_with_usage(query, is_query=True)

            # We leverage the existing _retrieve_and_rank method from pipeline but split it logically.
            res = await pipeline.query(
                query=query,
                agent_id=state["agent_id"],
                kb_id=resolved_kb_ids,
                user_id=state.get("user_id"),
                session_id=state.get("session_id"),
                top_k=state.get("top_k", 20),
                max_depth=state.get("max_depth", 2),
                analysis=state.get("analysis_object"),
                query_embedding_tuple=state.get("query_embedding_tuple") or query_embedding
            )
            
            chunks = getattr(res, "chunks", [])
            
            # Triplet Deduplication & Bypass Flag (The Phase 1 Fix)
            raw_triplets = getattr(res, "graph_triplets", [])
            seen_triplets = set()
            deduped_triplets = []
            for t in raw_triplets:
                sig = f"{t.get('source')}--{t.get('relationship')}--{t.get('target')}"
                if sig not in seen_triplets:
                    seen_triplets.add(sig)
                    deduped_triplets.append(t)
                    
            return {
                "retrieved_chunks": chunks,
                "graph_triplets": deduped_triplets
            }
            
    except Exception as e:
        logger.error(f"Retrieval node failed: {e}")
        return {
            "error": str(e),
            "retrieved_chunks": [],
            "graph_triplets": []
        }

