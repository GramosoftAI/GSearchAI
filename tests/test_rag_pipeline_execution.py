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

@pytest.mark.asyncio
async def test_fact_query_bypasses_router_call_1():
    from app.modules.rag.pipeline import RAGPipeline
    from app.modules.rag.orchestrator.query_analyzer import AnalysisResult, QueryIntent, QueryMetadata
    from app.modules.rag.pipeline import RAGContext, RetrievedChunk
    from app.modules.rag.query_router import RouteResult, SearchType

    pipeline = RAGPipeline("12345678-1234-5678-1234-567812345678", db=AsyncMock())
    pipeline.router.route_query = AsyncMock(return_value=RouteResult(intent=SearchType.CHUNK_SEARCH, confidence=1.0))

    analysis_res = AnalysisResult(
        intent=QueryIntent.FACT,
        metadata=QueryMetadata(keywords=["thambi"]),
        is_tabular=False,
        confidence=0.95,
        reasoning="Fact lookup"
    )

    with patch("app.modules.rag.orchestrator.query_analyzer.QueryAnalyzer.analyze_query", new_callable=AsyncMock) as mock_analyze, \
         patch("app.core.embeddings.EmbeddingGenerator.generate_embedding_with_usage", new_callable=AsyncMock) as mock_emb, \
         patch("app.modules.rag.engines.financial_engine.FinancialEngine.get_candidate_sections", new_callable=AsyncMock) as mock_cand, \
         patch("app.modules.rag.engines.financial_engine.FinancialEngine.retrieve", new_callable=AsyncMock) as mock_ret:

        mock_analyze.return_value = analysis_res
        mock_emb.return_value = ([0.1, 0.2, 0.3], 5)
        mock_cand.return_value = [{"section_id": "s1", "task_id": "fact_1_fallback"}]
        mock_ret.return_value = [
            RetrievedChunk(
                chunk_id="c1",
                text="Thambi is a younger brother.",
                kb_id="kb1",
                position=0,
                embedding_similarity=0.9,
                graph_score=0.9,
                hybrid_score=0.9,
                reason="FACT",
                source="doc1"
            )
        ]

        context = await pipeline.query(
            query="who is the thambi",
            agent_id="agent1",
            kb_id="kb1"
        )

        assert context is not None
        assert context.query == "who is the thambi"
        # Verify QueryRouter Call #1 was NOT invoked for FACT query
        pipeline.router.route_query.assert_not_called()
        # Verify QueryAnalyzer was invoked
        mock_analyze.assert_called_once_with("who is the thambi")

@pytest.mark.asyncio
async def test_table_query_triggers_table_analytics_without_router_call_1():
    from app.modules.rag.pipeline import RAGPipeline
    from app.modules.rag.orchestrator.query_analyzer import AnalysisResult, QueryIntent, QueryMetadata
    from app.modules.rag.query_router import RouteResult, SearchType

    pipeline = RAGPipeline("12345678-1234-5678-1234-567812345678", db=AsyncMock())
    pipeline.router.route_query = AsyncMock(return_value=RouteResult(intent=SearchType.CHUNK_SEARCH, confidence=1.0))
    pipeline._execute_table_analytics = AsyncMock(return_value="Average Salary: $100,000")

    analysis_res = AnalysisResult(
        intent=QueryIntent.CALCULATION,
        metadata=QueryMetadata(keywords=["average", "salary"]),
        is_tabular=True,
        confidence=0.95,
        reasoning="Table calculation"
    )

    with patch("app.modules.rag.orchestrator.query_analyzer.QueryAnalyzer.analyze_query", new_callable=AsyncMock) as mock_analyze, \
         patch("app.core.embeddings.EmbeddingGenerator.generate_embedding_with_usage", new_callable=AsyncMock) as mock_emb, \
         patch("app.modules.rag.engines.table_engine.TableEngine.get_candidate_sections", new_callable=AsyncMock) as mock_cand, \
         patch("app.modules.rag.engines.table_engine.TableEngine.retrieve", new_callable=AsyncMock) as mock_ret:

        mock_analyze.return_value = analysis_res
        mock_emb.return_value = ([0.1, 0.2, 0.3], 5)
        mock_cand.return_value = []
        mock_ret.return_value = []

        context = await pipeline.query(
            query="what is the average salary?",
            agent_id="agent1",
            kb_id="kb1"
        )

        # QueryRouter Call #1 was NOT invoked because is_tabular handled it
        # Only Call #2 fallback ran since candidate chunks was empty
        pipeline.router.route_query.assert_called_once_with("what is the average salary?", tenant_id="12345678-1234-5678-1234-567812345678")
        # _execute_table_analytics was called BEFORE AdaptivePlanner
        pipeline._execute_table_analytics.assert_called_with("what is the average salary?", ["kb1"])
