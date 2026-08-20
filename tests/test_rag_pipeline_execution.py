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

    db_mock = AsyncMock()
    mock_res = MagicMock()
    mock_res.all.return_value = []
    mock_res.fetchall.return_value = []
    db_mock.execute.return_value = mock_res
    pipeline = RAGPipeline("12345678-1234-5678-1234-567812345678", db=db_mock)
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

    db_mock = AsyncMock()
    mock_res = MagicMock()
    mock_res.all.return_value = []
    mock_res.fetchall.return_value = []
    db_mock.execute.return_value = mock_res
    pipeline = RAGPipeline("12345678-1234-5678-1234-567812345678", db=db_mock)
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


# ============================================================
# VECTORENGINE CONTRACT REGRESSION TESTS
# These tests are fully deterministic and use only mocks.
# They cover the three bugs fixed in vector_engine.py:
#   1. pgvector branch must respect target_section_ids
#   2. empty target_section_ids must not trigger a full-KB scan
#   3. ontology_node must not be fabricated from task.target_section
# ============================================================

@pytest.mark.asyncio
async def test_vector_retrieval_respects_target_section_ids():
    import uuid
    from unittest.mock import AsyncMock, patch, MagicMock
    from app.modules.rag.engines.vector_engine import VectorEngine
    from app.modules.rag.orchestrator.planner import RetrievalTask
    from app.modules.rag.orchestrator.query_analyzer import QueryMetadata

    tenant_id = "12345678-1234-5678-1234-567812345678"
    kb_id = "aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb"
    section_id = str(uuid.uuid4())

    neo4j_mock = AsyncMock()
    db_mock = AsyncMock()

    mock_row = MagicMock()
    mock_row.id = uuid.uuid4()
    mock_row.text = "Thambi is the youngest sibling."
    mock_row.chunk_index = 5
    mock_row.kb_id = uuid.uuid4()
    mock_row.metadata_json = None
    mock_row.name = "doc.pdf"
    mock_row.s3_path = "s3://bucket/doc.pdf"
    mock_row.similarity = 0.91

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    db_mock.execute.return_value = mock_result

    engine = VectorEngine(tenant_id=tenant_id, neo4j_repo=neo4j_mock, db=db_mock)

    task = RetrievalTask(
        engine_name="vector",
        query="who is the thambi",
        metadata_filters=QueryMetadata(
            keywords=["thambi"],
            query_embedding=[0.1] * 10,
        ),
        task_id="fact_1_primary",
        target_section_ids=[section_id],
    )
    setattr(task, "top_k", 15)

    with patch("app.core.embeddings.EmbeddingGenerator.generate_embedding", new_callable=AsyncMock) as mock_gen:
        chunks = await engine.retrieve(task, [kb_id])

    mock_gen.assert_not_called()
    db_mock.execute.assert_called_once()
    assert len(chunks) == 1

@pytest.mark.asyncio
async def test_zero_target_sections_does_not_return_arbitrary_chunks():
    import uuid
    from unittest.mock import AsyncMock, MagicMock
    from app.modules.rag.engines.vector_engine import VectorEngine
    from app.modules.rag.orchestrator.planner import RetrievalTask
    from app.modules.rag.orchestrator.query_analyzer import QueryMetadata

    neo4j_mock = AsyncMock()
    db_mock = AsyncMock()

    mock_row = MagicMock()
    mock_row.id = uuid.uuid4()
    mock_row.text = "Muruganandam P is the CEO."
    mock_row.chunk_index = 2
    mock_row.kb_id = uuid.uuid4()
    mock_row.metadata_json = None
    mock_row.name = "doc.pdf"
    mock_row.s3_path = None
    mock_row.similarity = 0.9

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    db_mock.execute.return_value = mock_result

    engine = VectorEngine(tenant_id="12345678-1234-5678-1234-567812345678", neo4j_repo=neo4j_mock, db=db_mock)

    task = RetrievalTask(
        engine_name="vector",
        query="who is the thambi",
        metadata_filters=QueryMetadata(
            keywords=["thambi"],
            query_embedding=[0.1] * 10,
        ),
        task_id="fact_1_primary",  # Normal task
        target_section_ids=[],     # Empty means SectionRanker rejected all candidate sections
    )
    setattr(task, "top_k", 15)

    result = await engine.retrieve(task, ["aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb"])

    assert result == []
    db_mock.execute.assert_not_called()
    neo4j_mock.execute_read.assert_not_called()

@pytest.mark.asyncio
async def test_coverage_fallback_task_allowed_through_zero_section_guard():
    import uuid
    from unittest.mock import AsyncMock, MagicMock
    from app.modules.rag.engines.vector_engine import VectorEngine
    from app.modules.rag.orchestrator.planner import RetrievalTask
    from app.modules.rag.orchestrator.query_analyzer import QueryMetadata

    neo4j_mock = AsyncMock()
    db_mock = AsyncMock()

    mock_row = MagicMock()
    mock_row.id = uuid.uuid4()
    mock_row.text = "Some related content."
    mock_row.chunk_index = 1
    mock_row.kb_id = uuid.uuid4()
    mock_row.metadata_json = None
    mock_row.name = "file.pdf"
    mock_row.s3_path = None
    mock_row.similarity = 0.75

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    db_mock.execute.return_value = mock_result

    engine = VectorEngine(tenant_id="12345678-1234-5678-1234-567812345678", neo4j_repo=neo4j_mock, db=db_mock)

    task = RetrievalTask(
        engine_name="vector",
        query="who is the thambi",
        metadata_filters=QueryMetadata(
            keywords=["thambi"],
            query_embedding=[0.1] * 10,
        ),
        task_id="fallback_Character",  # coverage-validation fallback task
        target_section_ids=[],         # intentionally no section restriction
    )
    setattr(task, "top_k", 15)

    result = await engine.retrieve(task, ["aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb"])

    db_mock.execute.assert_called_once()
    assert len(result) == 1

@pytest.mark.asyncio
async def test_retrieved_chunk_does_not_fake_ontology_coverage():
    import uuid
    from unittest.mock import AsyncMock, MagicMock
    from app.modules.rag.engines.vector_engine import VectorEngine
    from app.modules.rag.orchestrator.planner import RetrievalTask
    from app.modules.rag.orchestrator.query_analyzer import QueryMetadata

    section_id = str(uuid.uuid4())
    neo4j_mock = AsyncMock()
    db_mock = AsyncMock()

    mock_row = MagicMock()
    mock_row.id = uuid.uuid4()
    mock_row.text = "Some content."
    mock_row.chunk_index = 4
    mock_row.kb_id = uuid.uuid4()
    mock_row.metadata_json = None
    mock_row.name = "resume.pdf"
    mock_row.s3_path = None
    mock_row.similarity = 0.85

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [mock_row]
    db_mock.execute.return_value = mock_result

    engine = VectorEngine(tenant_id="12345678-1234-5678-1234-567812345678", neo4j_repo=neo4j_mock, db=db_mock)

    task = RetrievalTask(
        engine_name="vector",
        query="who is the thambi",
        metadata_filters=QueryMetadata(
            keywords=["thambi"],
            query_embedding=[0.1] * 10,
        ),
        task_id="fact_1_primary",
        target_section="Character",       # requested scope
        target_section_ids=[section_id],  # valid sections
    )
    setattr(task, "top_k", 15)

    result = await engine.retrieve(task, ["aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb"])

    assert len(result) == 1
    assert result[0].ontology_node is None, "ontology_node must not be faked from task.target_section"

@pytest.mark.asyncio
async def test_no_false_coverage_for_unrelated_chunks():
    from app.modules.rag.pipeline import RetrievedChunk

    coverage_goals = {"Character"}

    chunks = [
        RetrievedChunk(
            chunk_id="c1",
            text="Muruganandam is the CEO.",
            kb_id="kb1",
            position=0,
            embedding_similarity=0.9,
            graph_score=0.0,
            hybrid_score=0.9,
            reason="VECTOR_SEARCH_HYBRID",
            ontology_node=None
        ),
        RetrievedChunk(
            chunk_id="c2",
            text="Gramosoft is a tech company.",
            kb_id="kb1",
            position=1,
            embedding_similarity=0.85,
            graph_score=0.0,
            hybrid_score=0.85,
            reason="VECTOR_SEARCH_HYBRID",
            ontology_node=None
        )
    ]

    retrieved_nodes = {c.ontology_node for c in chunks if getattr(c, "ontology_node", None)}
    missing_goals = coverage_goals - retrieved_nodes

    assert "Character" in missing_goals

@pytest.mark.asyncio
async def test_legitimate_section_retrieval_still_works():
    import uuid
    from unittest.mock import AsyncMock, MagicMock
    from app.modules.rag.engines.vector_engine import VectorEngine
    from app.modules.rag.orchestrator.planner import RetrievalTask
    from app.modules.rag.orchestrator.query_analyzer import QueryMetadata

    section_id_1 = str(uuid.uuid4())
    section_id_2 = str(uuid.uuid4())
    neo4j_mock = AsyncMock()
    db_mock = AsyncMock()

    def make_row(text, score):
        row = MagicMock()
        row.id = uuid.uuid4()
        row.text = text
        row.chunk_index = 2
        row.kb_id = uuid.uuid4()
        row.metadata_json = None
        row.name = "kb.pdf"
        row.s3_path = "s3://bucket/kb.pdf"
        row.similarity = score
        return row

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [
        make_row("Revenue increased by 20%.", 0.92),
        make_row("Operating expenses declined.", 0.88),
    ]
    db_mock.execute.return_value = mock_result

    engine = VectorEngine(tenant_id="12345678-1234-5678-1234-567812345678", neo4j_repo=neo4j_mock, db=db_mock)

    task = RetrievalTask(
        engine_name="vector",
        query="what is the revenue?",
        metadata_filters=QueryMetadata(
            keywords=["revenue"],
            query_embedding=[0.2] * 10,
        ),
        task_id="fact_1_primary",
        target_section_ids=[section_id_1, section_id_2],
    )
    setattr(task, "top_k", 15)

    result = await engine.retrieve(task, ["aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb"])

    assert len(result) == 2

@pytest.mark.asyncio
async def test_thambi_query_regression():
    import uuid
    from unittest.mock import AsyncMock, MagicMock
    from app.modules.rag.engines.vector_engine import VectorEngine
    from app.modules.rag.orchestrator.planner import RetrievalTask
    from app.modules.rag.orchestrator.query_analyzer import QueryMetadata

    original_query = "who is the thambi"

    neo4j_mock = AsyncMock()
    db_mock = AsyncMock()

    unrelated_row = MagicMock()
    unrelated_row.id = uuid.uuid4()
    unrelated_row.text = "Muruganandam P is the CEO of Gramosoft."
    unrelated_row.chunk_index = 0
    unrelated_row.kb_id = uuid.uuid4()
    unrelated_row.metadata_json = None
    unrelated_row.name = "company_profile.pdf"
    unrelated_row.s3_path = None
    unrelated_row.similarity = 0.78

    mock_result = MagicMock()
    mock_result.fetchall.return_value = [unrelated_row]
    db_mock.execute.return_value = mock_result

    engine = VectorEngine(tenant_id="12345678-1234-5678-1234-567812345678", neo4j_repo=neo4j_mock, db=db_mock)

    task = RetrievalTask(
        engine_name="vector",
        query=original_query,
        metadata_filters=QueryMetadata(keywords=["thambi"]),
        task_id="fact_1_primary",
        target_section_ids=[], # No candidates matched "thambi"
    )
    setattr(task, "top_k", 15)

    result = await engine.retrieve(task, ["aaaabbbb-cccc-dddd-eeee-ffffaaaabbbb"])

    assert result == [], "Zero-section guard failed"
    assert task.query == original_query

    muruganandam_present = any("muruganandam" in (getattr(c, "text", "") or "").lower() for c in result)
    assert not muruganandam_present


@pytest.mark.asyncio
async def test_structured_query_fallback():
    from app.modules.rag.pipeline import RAGPipeline
    from app.modules.rag.orchestrator.query_analyzer import AnalysisResult, QueryIntent, QueryMetadata
    from app.modules.rag.pipeline import RAGContext, RetrievedChunk
    from unittest.mock import AsyncMock, patch, MagicMock

@pytest.mark.asyncio
async def test_structured_query_fallback():
    from app.modules.rag.pipeline import RAGPipeline
    from app.modules.rag.orchestrator.query_analyzer import AnalysisResult, QueryIntent, QueryMetadata
    from app.modules.rag.pipeline import RAGContext, RetrievedChunk
    from unittest.mock import AsyncMock, patch, MagicMock

    db_mock = AsyncMock()
    mock_res = MagicMock()
    mock_res.all.return_value = []
    db_mock.execute.return_value = mock_res
    pipeline = RAGPipeline("12345678-1234-5678-1234-567812345678", db=db_mock)

    # Mock analyze_query to return two structured queries
    analysis_res = AnalysisResult(
        intent=QueryIntent.SUMMARY,
        metadata=QueryMetadata(
            keywords=["gramosoft"],
            structured_queries=["Explain the services provided by Gramosoft.", "What services does Gramosoft offer?"]
        ),
        is_tabular=False,
        confidence=0.9,
        reasoning="Test rephrasing fallback"
    )

    # Let's count how many times retrieve is called to ensure fallback works.
    retrievals_called = []

    async def mock_retrieve_func(task, kb_ids):
        retrievals_called.append(task.query)
        if task.query == "Explain the services provided by Gramosoft.":
            # First structured query returns empty list (fails to retrieve)
            return []
        else:
            # Second structured query succeeds
            return [
                RetrievedChunk(
                    chunk_id="c1",
                    text="Gramosoft provides custom software development services.",
                    kb_id="kb1",
                    position=0,
                    embedding_similarity=0.95,
                    graph_score=0.0,
                    hybrid_score=0.0,
                    ontology_node="Services"
                )
            ]

    with patch("app.modules.rag.orchestrator.query_analyzer.QueryAnalyzer.analyze_query", new_callable=AsyncMock) as mock_analyze, \
         patch("app.core.embeddings.EmbeddingGenerator.generate_embedding_with_usage", new_callable=AsyncMock) as mock_emb, \
         patch("app.modules.rag.engines.vector_engine.VectorEngine.get_candidate_sections", new_callable=AsyncMock) as mock_cand, \
         patch("app.modules.rag.engines.vector_engine.VectorEngine.retrieve", side_effect=mock_retrieve_func) as mock_ret:

        mock_analyze.return_value = analysis_res
        mock_emb.return_value = ([0.1] * 1536, 5)
        # Match candidate section search
        mock_cand.return_value = [{"section_id": "s1", "task_id": "test_task"}]

        # Create a mock planner that plans a VectorEngine task
        from app.modules.rag.orchestrator.planner import RetrievalPlan, RetrievalTask
        mock_plan = RetrievalPlan(
            tasks=[
                RetrievalTask(
                    engine_name="vector",
                    query="Explain the services provided by Gramosoft.",
                    metadata_filters=analysis_res.metadata,
                    task_id="t1"
                )
            ],
            aggregator_strategy="rank",
            coverage_goals=["Services"]
        )
        
        with patch("app.modules.rag.orchestrator.planner.AdaptivePlanner.create_plan", new_callable=AsyncMock) as mock_create_plan:
            mock_create_plan.return_value = mock_plan

            res = await pipeline.query(
                query="explain the gramosoft services",
                agent_id="agent1",
                kb_id="kb1"
            )

            # Assertions
            assert isinstance(res, RAGContext)
            # The query attribute in RAGContext should be the original user query!
            assert res.query == "explain the gramosoft services"
            assert len(res.chunks) == 1
            assert res.chunks[0].text == "Gramosoft provides custom software development services."
            # Verify retrieval was called for both structured queries sequentially
            assert "Explain the services provided by Gramosoft." in retrievals_called
            assert "What services does Gramosoft offer?" in retrievals_called
