import asyncio
import os
import sys
import uuid
import pytest
from unittest.mock import patch, MagicMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import AsyncSessionLocal
from app.modules.rag.pipeline import RAGPipeline
from app.core.neo4j_repository import Neo4jRepository

TEST_TENANT_ID = str(uuid.uuid4())
TEST_AGENT_ID = str(uuid.uuid4())
TEST_KB_ID = str(uuid.uuid4())

@pytest.mark.asyncio
@patch('app.modules.rag.orchestrator.section_ranker.SectionRanker.rank_sections')
@patch('app.modules.rag.engines.vector_engine.VectorEngine.retrieve')
@patch('app.modules.rag.engines.vector_engine.VectorEngine.get_candidate_sections')
@patch('app.core.neo4j_repository.Neo4jRepository.execute_read')
async def test_section_fallback_logic(mock_execute_read, mock_get_candidates, mock_retrieve, mock_rank_sections):
    """
    Test that RAGPipeline triggers a full-KB fallback (empty target_sections)
    if the top SectionRanker score is < 2.0 OR the relative gap is < 30%.
    """
    # Setup standard dummy data to prevent downstream errors
    mock_get_candidates.return_value = [{"section_id": "Introduction", "title": "Introduction"}]
    mock_execute_read.return_value = []
    
    async with AsyncSessionLocal() as db_session:
        pipeline = RAGPipeline(tenant_id=TEST_TENANT_ID, db=db_session)
        pipeline.settings.use_triplet_extraction = False # Simplify

        # Test Case 1: High confidence score (no fallback)
        mock_rank_sections.return_value = [
            {"section_id": "Introduction", "rank_score": 5.0},
            {"section_id": "Conclusion", "rank_score": 2.0}
        ]
        
        await pipeline.query(query="test", kb_id=[TEST_KB_ID], agent_id=TEST_AGENT_ID)
        
        # Check what was passed to VectorEngine.retrieve
        task_passed = mock_retrieve.call_args[0][0]
        assert task_passed.target_section_ids == ["Introduction", "Conclusion"], "Should have targeted sections"
        
        # Test Case 2: Low absolute score (fallback)
        mock_rank_sections.return_value = [
            {"section_id": "Introduction", "rank_score": 1.5},
            {"section_id": "Conclusion", "rank_score": 1.0}
        ]
        
        await pipeline.query(query="test", kb_id=[TEST_KB_ID], agent_id=TEST_AGENT_ID)
        task_passed = mock_retrieve.call_args[0][0]
        assert task_passed.target_section_ids == [], "Should have fallen back due to low absolute score (< 2.0)"
        
        # Test Case 3: Small relative gap (fallback)
        mock_rank_sections.return_value = [
            {"section_id": "Introduction", "rank_score": 4.0},
            {"section_id": "Conclusion", "rank_score": 3.8} # Gap is 0.2, which is < 30% of 4.0 (1.2)
        ]
        
        await pipeline.query(query="test", kb_id=[TEST_KB_ID], agent_id=TEST_AGENT_ID)
        task_passed = mock_retrieve.call_args[0][0]
        assert task_passed.target_section_ids == [], "Should have fallen back due to small relative gap (< 30%)"

if __name__ == "__main__":
    asyncio.run(test_section_fallback_logic())
    print("Fallback logic tests passed!")
