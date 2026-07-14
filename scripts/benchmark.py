import asyncio
import logging
import sys
sys.path.insert(0, r"v:\graphmind")
from app.modules.rag.pipeline import RAGPipeline
from app.core.neo4j_repository import Neo4jRepository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_regression_suite():
    """
    Automated regression suite for the Enterprise Retrieval Orchestrator.
    Tests core query intents against the pipeline and asserts performance.
    """
    logger.info("Starting Enterprise Benchmark Regression Suite...")
    from app.core.database import get_db_public, AsyncSessionLocal
    
    tenant_id = "fd06d2c3-c7c8-4a6e-a155-40870a062310"
    repo = Neo4jRepository(tenant_id=tenant_id)
    
    db_session = AsyncSessionLocal()
    from sqlalchemy import text
    await db_session.execute(text("SELECT set_config('app.current_tenant', :tenant_id, false)"), {"tenant_id": tenant_id})
    pipeline = RAGPipeline(tenant_id=tenant_id, db=db_session)
    pipeline.neo4j_repo = repo
    kb_ids = ["c176dad2-e07f-49b1-972f-faa0cbebec44"]
    
    test_queries = [
        "What significant changes in accounting practices or accounting estimates occurred?",
        "What was the exact Gaming revenue and Professional Visualization revenue?",
        "How much stock was repurchased during the third quarter under the share repurchase program?"
    ]
    
    successes = 0
    
    for query in test_queries:
        logger.info(f"--- Running Query: {query} ---")
        try:
            # We skip generating the final LLM response to isolate Retrieval testing
            context = await pipeline.query(query=query, agent_id="benchmark", kb_id=kb_ids)
            
            logger.info(f"Retrieved {len(context.chunks)} chunks.")
            
            # Print sections to verify SectionRanker success
            sections_retrieved = set(c.section for c in context.chunks if getattr(c, "section", None))
            logger.info(f"Sections Retrieved: {sections_retrieved}")
            
            if context.triplet_context and "WARNING" in context.triplet_context:
                logger.warning("Conflict detected during benchmark.")
                
            # Assertions
            assert len(context.chunks) > 0, "Failed to retrieve evidence."
            assert context.total_tokens <= 8192, "Exceeded token budget."
            
            successes += 1
            logger.info("PASS")
            
        except AssertionError as e:
            logger.error(f"FAIL: {e}")
        except Exception as e:
            logger.error(f"ERROR: {e}")
            
    logger.info(f"Benchmark Complete. {successes}/{len(test_queries)} passed.")
    if successes < len(test_queries):
        logger.error("REGRESSION DETECTED. DO NOT DEPLOY.")
        
if __name__ == "__main__":
    asyncio.run(run_regression_suite())
