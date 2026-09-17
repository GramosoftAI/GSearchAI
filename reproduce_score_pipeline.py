import asyncio
import os
import sys
from uuid import UUID

from app.core.database import AsyncSessionLocal
from app.modules.rag.service import RAGService
from app.modules.rag.pipeline import RAGPipeline
from app.core.config import get_settings

async def reproduce_scores():
    tenant_id = "b91f23d9-7127-420d-acc9-fc420b46bf9e"
    agent_id = "88c3d480-2624-4f0c-9462-10ef0e70bf63"
    # Testing with Big Cats Compendium KB
    kb_id = "1d76cbe7-3f2b-41b5-bc71-805806720940"
    
    test_queries = [
        "What are the physical characteristics and hunting behaviors of big cats?",
        "How do tigers differ from lions in their social structure?",
        "What is the conservation status of leopards?",
    ]
    
    async with AsyncSessionLocal() as db:
        rag_service = RAGService(db=db, tenant_id=tenant_id)
        
        for q in test_queries:
            print(f"\n=======================================================")
            print(f"QUERY: {q}")
            print(f"=======================================================")
            
            context = await rag_service.pipeline.query(
                query=q,
                agent_id=agent_id,
                kb_id=kb_id,
                top_k=15
            )
            
            print(f"Retrieved chunks before service filter: {len(context.chunks) if context and context.chunks else 0}")
            if context and context.chunks:
                for idx, c in enumerate(context.chunks):
                    print(f"  [{idx+1}] chunk_id={c.chunk_id[:8]}.. sim={c.embedding_similarity:.4f} hybrid_score={c.hybrid_score:.4f} reason={c.reason} src={c.source}")
            
            dropped = rag_service._filter_relevant_chunks(context)
            print(f"Filter dropped: {dropped}")
            print(f"Retrieved chunks AFTER service filter: {len(context.chunks) if context and context.chunks else 0}")
            if context and context.chunks:
                for idx, c in enumerate(context.chunks):
                    print(f"  [SURVIVED {idx+1}] chunk_id={c.chunk_id[:8]}.. hybrid_score={c.hybrid_score:.4f}")

if __name__ == "__main__":
    asyncio.run(reproduce_scores())
