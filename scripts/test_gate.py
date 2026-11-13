import asyncio
import logging
from app.modules.rag.pipeline import RAGPipeline
from uuid import UUID

# Setup logging to see the pipeline output
logging.basicConfig(level=logging.INFO)

async def test_gate():
    # Known KB IDs from the backfill output
    kb_ids = [
        "47452b97-fedf-416f-839e-e98ffbc10ec0", # rag_memory_test_corpus.pdf (has the backup coordinator)
        "1e0d79e5-03bb-4504-a805-362c74707ddf", # pricelist book feb 2026-36-40.pdf
        "d4e44a72-7439-4ed3-a956-5b35c20ef685"  # Big_Cats_Comprehensive_Compendium.pdf
    ]
    
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        pipeline = RAGPipeline(tenant_id="00000000-0000-0000-0000-000000000000", db=session)
        pipeline.session_id = str(UUID('00000000-0000-0000-0000-000000000000'))
        
        # TEST 1: The query that hallucinated before
        query1 = "who is the backup system coordinator?"
        print(f"\n\n===========================================")
        print(f"TEST 1: {query1}")
        print(f"===========================================\n")
        
        ctx1 = await pipeline.query(query1, agent_id=None, kb_id=kb_ids)
        print(f"\nRESULT 1: search_type = {ctx1.search_type}, chunks = {len(ctx1.chunks)}\n")
        
        
        # TEST 2: A query completely unrelated to the files
        query2 = "what is the recipe for making a traditional japanese ramen broth?"
        print(f"\n\n===========================================")
        print(f"TEST 2: {query2}")
        print(f"===========================================\n")
        
        ctx2 = await pipeline.query(query2, agent_id=None, kb_id=kb_ids)
        print(f"\nRESULT 2: search_type = {ctx2.search_type}, chunks = {len(ctx2.chunks)}\n")

if __name__ == "__main__":
    asyncio.run(test_gate())
