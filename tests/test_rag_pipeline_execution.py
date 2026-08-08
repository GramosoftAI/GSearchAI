import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from app.core.llm.deepinfra_llm import DeepInfraLLMClient
from app.modules.rag.orchestrator.query_analyzer import QueryAnalyzer, QueryMetadata
from app.modules.rag.engines.vector_engine import VectorEngine
from app.modules.rag.orchestrator.planner import RetrievalTask

@pytest.mark.asyncio
async def test_deepinfra_cloud_model_kwarg():
    client = DeepInfraLLMClient()
    client.deepinfra_api_key = "test_key"
    client.model_answer = "default-model"
    
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"choices": [{"message": {"content": "test answer"}}]}
        mock_post.return_value = mock_response
        
        # Test default
        await client.generate_cloud("hello")
        payload = mock_post.call_args[1]["json"]
        assert payload["model"] == "default-model"
        
        # Test override
        await client.generate_cloud("hello", model="custom-router-model")
        payload = mock_post.call_args[1]["json"]
        assert payload["model"] == "custom-router-model"

@pytest.mark.asyncio
async def test_query_analyzer_embedding():
    analyzer = QueryAnalyzer()
    with patch.object(analyzer.llm_client, "generate_cloud", return_value='{"intent": "FACT", "primary_topic": "test"}'):
        res = await analyzer.analyze_query("hello")
        assert res.intent.value == "FACT"
        assert res.metadata.query_embedding is None
        
        # Manually assign embedding (simulating pipeline.py)
        res.metadata.query_embedding = [0.1, 0.2, 0.3]
        assert res.metadata.query_embedding == [0.1, 0.2, 0.3]

@pytest.mark.asyncio
async def test_vector_engine_reuses_embedding():
    neo4j_mock = AsyncMock()
    engine = VectorEngine(neo4j_mock, "tenant1")
    
    task = RetrievalTask(
        engine_name="vector",
        query="hello",
        metadata_filters=QueryMetadata(query_embedding=[0.1, 0.2, 0.3]),
        task_id="t1"
    )
    
    with patch("app.core.embeddings.EmbeddingGenerator.generate_embedding") as mock_gen:
        neo4j_mock.execute_read.return_value = []
        await engine.retrieve(task, ["kb1"])
        
        # Ensure generate_embedding was NOT called because it reused task.metadata_filters.query_embedding
        mock_gen.assert_not_called()
