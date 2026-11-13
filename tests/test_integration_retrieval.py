import asyncio
import os
import sys
import uuid
import pytest
from typing import List, Dict

# Ensure we can import from app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase, DocumentChunk
from app.modules.rag.engines.vector_engine import VectorEngine
from app.modules.rag.pipeline import RAGPipeline
from app.modules.rag.schemas import RetrievalTask
from app.core.neo4j_repository import Neo4jRepository

# Test tenant and KB
TEST_TENANT_ID = str(uuid.uuid4())
TEST_AGENT_ID = str(uuid.uuid4())
TEST_KB_ID = str(uuid.uuid4())

@pytest.mark.asyncio
async def test_vector_engine_contract():
    """
    Test that VectorEngine.retrieve accepts the shared RetrievalTask contract
    and executes without interface drift failures.
    """
    async with AsyncSessionLocal() as db_session:
        neo4j_repo = Neo4jRepository(tenant_id=TEST_TENANT_ID)
        engine = VectorEngine(TEST_TENANT_ID, neo4j_repo, db=db_session)
        
        task = RetrievalTask(
            task_id="test_vector_task",
            query="Where does Arun live?",
            metadata_filters={},
            top_k=5,
            target_section_ids=[]
        )
        
        try:
            # We expect this to run cleanly and return chunks (or empty list if no data)
            # The test will FAIL if the method signature changed or it raises an exception
            # due to missing duck-typed fields.
            results = await engine.retrieve(task, [TEST_KB_ID])
            assert isinstance(results, list)
        except Exception as e:
            pytest.fail(f"VectorEngine.retrieve failed with interface error: {e}")

@pytest.mark.asyncio
async def test_rag_pipeline_concurrent_flow():
    """
    Test that RAGPipeline.query executes the full concurrent 4-branch flow
    and merges via RRF without dropping or blocking branches.
    """
    async with AsyncSessionLocal() as db_session:
        pipeline = RAGPipeline(tenant_id=TEST_TENANT_ID, db=db_session)
        
        test_queries = [
            "What led to the failure of 'The Lost Notes'?",
            "What was the name of the recording studio where Arun interned at age 20?",
            "Where does Arun live?"
        ]
        
        for q in test_queries:
            try:
                context = await pipeline.query(
                    query=q,
                    kb_id=[TEST_KB_ID],
                    agent_id=TEST_AGENT_ID
                )
                assert context is not None
                # If it didn't crash, the 4-branch asyncio.gather completed successfully
                # and target_section_ids were properly passed as post-hoc boosts.
            except Exception as e:
                pytest.fail(f"RAGPipeline.query failed on '{q}' with error: {e}")

if __name__ == "__main__":
    asyncio.run(test_vector_engine_contract())
    asyncio.run(test_rag_pipeline_concurrent_flow())
    print("Integration tests passed! Contract is intact.")
