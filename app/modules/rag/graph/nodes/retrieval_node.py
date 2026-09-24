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

            # --- ENUMERATION BYPASS ---
            intent = state.get("intent")
            analysis = state.get("analysis_object")
            target_chunk_type = None
            if analysis and hasattr(analysis, "metadata") and hasattr(analysis.metadata, "target_chunk_type"):
                target_chunk_type = analysis.metadata.target_chunk_type
                
            if intent == "ENUMERATION" and target_chunk_type:
                from app.modules.knowledge_bases.models import DocumentChunk
                from sqlalchemy import select
                from app.modules.rag.pipeline import RetrievedChunk
                import uuid
                
                logger.info(f"Bypassing vector retrieval for ENUMERATION intent, fetching chunk_type: {target_chunk_type}")
                
                # Fetch chunks for this tenant/kb that match the chunk_type
                stmt = select(DocumentChunk).where(
                    DocumentChunk.tenant_id == (uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id)
                )
                
                if resolved_kb_ids:
                    stmt = stmt.where(DocumentChunk.kb_id.in_([uuid.UUID(k) for k in resolved_kb_ids]))
                    
                stmt = stmt.where(DocumentChunk.metadata_json['chunk_type'].astext == target_chunk_type)
                
                result = await db.execute(stmt)
                db_chunks = result.scalars().all()
                
                chunks = []
                for db_chunk in db_chunks:
                    chunks.append(RetrievedChunk(
                        chunk_id=str(db_chunk.id),
                        text=db_chunk.text,
                        kb_id=str(db_chunk.kb_id),
                        position=db_chunk.chunk_index,
                        embedding_similarity=1.0,
                        graph_score=0.0,
                        hybrid_score=1.0,
                        exact_score=1.0,
                        final_relevance_score=1.0,
                        provenance_metadata=db_chunk.metadata_json
                    ))
                    
                logger.info(f"ENUMERATION fetch returned {len(chunks)} chunks.")
                
                return {
                    "retrieved_chunks": chunks,
                    "graph_triplets": []
                }
            # --- END BYPASS ---

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

