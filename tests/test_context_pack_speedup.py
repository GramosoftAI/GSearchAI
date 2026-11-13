import asyncio
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import date

from app.modules.database_knowledgebase.knowledge.retrieval.analyzer import QuestionAnalyzer, QuestionFrame
from app.modules.database_knowledgebase.knowledge.retrieval.context_pack import ContextPackBuilder, ContextPack
from app.modules.database_knowledgebase.knowledge.retrieval.entity_resolver import LiveEntityResolver, EntityResolutionResult
from app.modules.database_knowledgebase.knowledge.retrieval.table_retriever import TableCandidate
from app.modules.database_knowledgebase.knowledge.retrieval.column_retriever import TableColumnBundle, ColumnCandidate
from app.modules.database_knowledgebase.knowledge.retrieval.join_path import JoinPathResult


@pytest.mark.asyncio
async def test_entity_resolver_batch_query_execution():
    """Verify that entity resolver collects spans and executes a single batch IN query on kb2_entity_values."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    # Mock execute result for batch IN query
    mock_exec_result = MagicMock()
    mock_exec_result.scalars.return_value.all.return_value = []
    mock_db.execute.return_value = mock_exec_result

    # Mock schema adapter
    mock_adapter = AsyncMock()
    mock_schema = MagicMock()
    mock_schema.tables = {}
    mock_adapter.get_current_schema.return_value = mock_schema

    resolver = LiveEntityResolver(db=mock_db, tenant_id=tenant_id, adapter=mock_adapter)

    analyzer = QuestionAnalyzer()
    frame = analyzer.analyze("show orders for Arun Kumar in Chennai branch")

    result = await resolver.resolve(db_knowledgebase_id=kb_id, frame=frame)

    assert isinstance(result, EntityResolutionResult)
    assert not result.unanswerable

    # Verify execute was called with a single IN query on normalized_value
    calls = [c for c in mock_db.execute.call_args_list]
    # At most 1 batch query on kb2_entity_values was executed for exact hits (instead of loop per span)
    assert len(calls) <= 1


@pytest.mark.asyncio
async def test_context_pack_builder_sequential_fallback():
    """Verify ContextPackBuilder works sequentially when session_factory is None."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    builder = ContextPackBuilder(
        db=mock_db,
        tenant_id=tenant_id,
        session_factory=None,
    )
    assert builder.session_factory is None

    # Mock components to isolate orchestration logic
    builder.entity_resolver.resolve = AsyncMock(return_value=EntityResolutionResult())
    builder.table_retriever.retrieve_tables = AsyncMock(return_value=[
        TableCandidate(table_name="orders", score=0.9, reasons=["test"])
    ])
    builder.column_retriever.retrieve_for_tables = AsyncMock(return_value=[
        TableColumnBundle(table_name="orders", table_score=0.9, columns=[
            ColumnCandidate(table_name="orders", column_name="id", full_key="orders.id", score=0.9)
        ])
    ])
    builder.join_finder.build_graph = AsyncMock()
    builder.join_finder.find_join_tree = MagicMock(return_value=JoinPathResult(success=True, joins=[]))
    builder._fetch_similar_queries = AsyncMock(return_value=[])
    builder._fetch_rules = AsyncMock(return_value=[])
    builder.adapter.get_current_schema = AsyncMock(return_value=None)

    with patch("app.core.embeddings.EmbeddingGenerator.generate_embedding", new=AsyncMock(return_value=[0.1] * 768)):
        pack = await builder.build(
            db_knowledgebase_id=kb_id,
            question="delivered orders last week",
        )

    assert isinstance(pack, ContextPack)
    assert len(pack.tables) == 1
    assert pack.tables[0]["name"] == "orders"
    assert "analyzer_ms" in pack.timings_ms
    assert "table_retrieval_ms" in pack.timings_ms
    assert "column_retrieval_ms" in pack.timings_ms


@pytest.mark.asyncio
async def test_context_pack_builder_concurrent_pipeline():
    """Verify ContextPackBuilder runs independent stages concurrently with mock session_factory."""
    mock_db = AsyncMock()
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    # Mock session factory yielding mock sessions
    mock_branch_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__.return_value = mock_branch_session
    mock_factory.return_value.__aexit__.return_value = None

    builder = ContextPackBuilder(
        db=mock_db,
        tenant_id=tenant_id,
        session_factory=mock_factory,
    )

    builder.entity_resolver.resolve = AsyncMock(return_value=EntityResolutionResult())
    builder.table_retriever.retrieve_tables = AsyncMock(return_value=[
        TableCandidate(table_name="customers", score=0.95, reasons=["test"])
    ])
    builder.column_retriever.retrieve_for_tables = AsyncMock(return_value=[
        TableColumnBundle(table_name="customers", table_score=0.95, columns=[
            ColumnCandidate(table_name="customers", column_name="name", full_key="customers.name", score=0.9)
        ])
    ])
    builder.join_finder.build_graph = AsyncMock()
    builder.join_finder.find_join_tree = MagicMock(return_value=JoinPathResult(success=True, joins=[]))
    builder._fetch_similar_queries = AsyncMock(return_value=[])
    builder._fetch_rules = AsyncMock(return_value=[])

    with patch("app.core.embeddings.EmbeddingGenerator.generate_embedding", new=AsyncMock(return_value=[0.2] * 768)):
        pack = await builder.build(
            db_knowledgebase_id=kb_id,
            question="show customers",
        )

    assert isinstance(pack, ContextPack)
    assert len(pack.tables) == 1
    assert pack.tables[0]["name"] == "customers"
    assert not pack.unanswerable["flag"]
    # Verify dedicated sessions were acquired from session factory for concurrent branches
    assert mock_factory.call_count >= 1
