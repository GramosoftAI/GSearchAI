"""Smoke test for Phase 2 Step 9: Seed Examples & Query Memory

Tests:
1. sqlglot parsing: SELECT-only validation, destructive query rejection, table/column verification, and LIMIT injection.
2. run_seed_query_memory pipeline with customer DB read-only execution.
3. QueryMemoryRepository persistence with provenance='seed', referenced_items, and embedding.
4. Suggested questions UI helper.
"""

import uuid
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.modules.database_knowledgebase.knowledge.jobs.seed_query_memory import (
    parse_and_validate_sql,
    run_seed_query_memory,
    get_suggested_questions,
)
from app.modules.database_knowledgebase.knowledge.adapters.phase1_adapter import (
    TableView,
    ColumnView,
    SchemaView,
)


def test_sqlglot_parse_and_validate():
    valid_tables = {"orders", "customers"}
    valid_cols = {
        "orders": {"id", "total_amount", "customer_id"},
        "customers": {"id", "name"},
    }

    # 1. Valid SELECT query missing LIMIT
    sql = "SELECT id, total_amount FROM orders WHERE total_amount > 100"
    is_valid, modified_sql, ref_items, err = parse_and_validate_sql(sql, valid_tables, valid_cols)
    assert is_valid is True
    assert "LIMIT 100" in modified_sql
    assert "table:orders" in ref_items
    assert err is None

    # 2. Reject DDL / DML
    bad_sql = "DELETE FROM orders WHERE id = 1"
    is_valid, _, _, err = parse_and_validate_sql(bad_sql, valid_tables, valid_cols)
    assert is_valid is False
    assert "Only SELECT" in err

    # 3. Reject unknown table
    bad_table_sql = "SELECT * FROM secret_passwords"
    is_valid, _, _, err = parse_and_validate_sql(bad_table_sql, valid_tables, valid_cols)
    assert is_valid is False
    assert "Unknown table" in err


@pytest.mark.asyncio
async def test_seed_query_memory_smoke():
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    schema_version = "v_test_qm_1"

    # Mock Schema
    tables = {
        "orders": TableView(
            schema_name="public",
            table_name="orders",
            table_type="BASE TABLE",
            columns={
                "id": ColumnView("id", "integer", "integer", False, True, False),
                "total_amount": ColumnView("total_amount", "numeric", "numeric", False, False, False),
            },
            primary_key_columns=["id"],
            foreign_keys=[],
        )
    }
    mock_schema = SchemaView(
        database_name="test_db",
        database_type="postgresql",
        schema_version=schema_version,
        tables=tables,
    )

    mock_adapter = MagicMock()
    mock_adapter.get_schema_by_version = AsyncMock(return_value=mock_schema)
    mock_adapter.get_current_schema = AsyncMock(return_value=mock_schema)

    # Mock customer db execution
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[{"id": 1, "total_amount": 50.0}])
    mock_adapter.open_readonly_connection.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_adapter.open_readonly_connection.return_value.__aexit__ = AsyncMock(return_value=None)

    # Mock LLM generating candidate pairs
    mock_llm = MagicMock()
    sample_pairs = {
        "pairs": [
            {
                "question": "What is the highest order total?",
                "sql": "SELECT id, total_amount FROM orders ORDER BY total_amount DESC LIMIT 1",
                "category": "aggregate",
                "tables_referenced": ["orders"],
            }
        ]
    }
    mock_llm.generate = AsyncMock(return_value=json.dumps(sample_pairs))

    # Mock QueryMemoryRepository
    upserted_memories = []
    mock_query_repo = MagicMock()
    mock_query_repo.db = MagicMock()
    mock_query_repo.db.commit = AsyncMock()

    async def mock_upsert_qm(**kwargs):
        upserted_memories.append(kwargs)
        return kwargs

    mock_query_repo.upsert_item = AsyncMock()
    mock_query_repo.upsert_query_memory = AsyncMock(side_effect=mock_upsert_qm)
    mock_query_repo.list_suggested_questions = AsyncMock(return_value=[
        {"question": "What is the highest order total?", "sql": "SELECT ..."}
    ])

    mock_item_repo = MagicMock()

    res = await run_seed_query_memory(
        tenant_id=tenant_id,
        kb_id=kb_id,
        schema_version=schema_version,
        adapter=mock_adapter,
        item_repo=mock_item_repo,
        query_repo=mock_query_repo,
        llm_client=mock_llm,
        target_pair_count=1,
    )

    assert res["generated"] == 1
    assert res["verified"] == 1
    assert len(upserted_memories) == 1

    qm = upserted_memories[0]
    assert qm["status"] == "verified"
    assert qm["execution_stats"]["provenance"] == "seed"
    assert "table:orders" in qm["referenced_items"]

    # Test suggested questions UI helper
    suggested = await get_suggested_questions(tenant_id, kb_id, mock_query_repo)
    assert len(suggested) == 1
    assert suggested[0]["question"] == "What is the highest order total?"
