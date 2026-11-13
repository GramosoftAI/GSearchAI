"""Smoke test for Phase 2 Step 5: Relationship Finder and RelationshipGraph

Tests:
1. Declared foreign keys detected with status='confirmed', confidence=1.0.
2. Inferred foreign keys detected via naming pattern and type compatibility.
3. Sensitive columns are skipped from relationship inference.
4. RelationshipGraph loads items and computes join path using weighted BFS.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.modules.database_knowledgebase.knowledge.adapters.phase1_adapter import (
    ColumnView,
    FKView,
    TableView,
    SchemaView,
)
from app.modules.database_knowledgebase.knowledge.jobs.relationships import (
    run_stage_relationships,
    _singularize,
    _types_compatible,
    _check_name_match,
)
from app.modules.database_knowledgebase.knowledge.graph.relationship_graph import (
    RelationshipGraph,
)


def test_singularize_and_name_match():
    assert _singularize("customers") == "customer"
    assert _singularize("categories") == "category"
    assert _singularize("orders") == "order"

    assert _types_compatible("integer", "bigint") is True
    assert _types_compatible("varchar(255)", "text") is True
    assert _types_compatible("uuid", "text") is True

    matched, score, reason = _check_name_match("customer_id", "customers", "id")
    assert matched is True
    assert score >= 0.35

    matched, _, _ = _check_name_match("fk_department", "departments", "dept_id")
    assert matched is True


@pytest.mark.asyncio
async def test_relationship_stage_and_graph_smoke():
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    schema_version = "v_test_rel_1"

    # Mock Schema with customers, orders, order_items
    tables = {
        "customers": TableView(
            schema_name="public",
            table_name="customers",
            table_type="BASE TABLE",
            columns={
                "id": ColumnView("id", "integer", "integer", False, True, False),
                "name": ColumnView("name", "varchar", "varchar", False, False, False),
            },
            primary_key_columns=["id"],
            foreign_keys=[],
        ),
        "orders": TableView(
            schema_name="public",
            table_name="orders",
            table_type="BASE TABLE",
            columns={
                "id": ColumnView("id", "integer", "integer", False, True, False),
                # Declared FK to customers
                "customer_id": ColumnView("customer_id", "integer", "integer", False, False, True),
            },
            primary_key_columns=["id"],
            foreign_keys=[
                FKView(
                    name="fk_orders_customer",
                    constrained_columns=["customer_id"],
                    referred_schema="public",
                    referred_table="customers",
                    referred_columns=["id"],
                )
            ],
        ),
        "order_items": TableView(
            schema_name="public",
            table_name="order_items",
            table_type="BASE TABLE",
            columns={
                "id": ColumnView("id", "integer", "integer", False, True, False),
                # Inferred FK candidate to orders
                "order_id": ColumnView("order_id", "integer", "integer", False, False, False),
                "card_number": ColumnView("card_number", "varchar", "varchar", True, False, False),
            },
            primary_key_columns=["id"],
            foreign_keys=[],
        ),
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

    # Mock readonly connection for value overlap
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[{"val": 1}])
    mock_adapter.open_readonly_connection.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_adapter.open_readonly_connection.return_value.__aexit__ = AsyncMock(return_value=None)

    upserted_items = []
    mock_item_repo = MagicMock()
    mock_item_repo.db = MagicMock()
    mock_item_repo.db.commit = AsyncMock()

    async def mock_upsert(**kwargs):
        upserted_items.append(kwargs)
        return kwargs

    mock_item_repo.upsert_item = AsyncMock(side_effect=mock_upsert)

    # Run relationships stage
    res = await run_stage_relationships(
        tenant_id=tenant_id,
        kb_id=kb_id,
        schema_version=schema_version,
        adapter=mock_adapter,
        item_repo=mock_item_repo,
    )

    assert res["declared_relationships"] == 1
    assert res["inferred_relationships"] >= 1

    # Check that declared FK is confirmed and conf 1.0
    declared_ki = next(i for i in upserted_items if i["source"] == "declared")
    assert declared_ki["status"] == "confirmed"
    assert declared_ki["confidence"] == 1.0
    assert "orders.customer_id->public.customers.id" in declared_ki["item_key"]

    # Check that inferred FK is draft
    inferred_ki = next(i for i in upserted_items if i["source"] == "inferred")
    assert inferred_ki["status"] == "draft"
    assert "order_items.order_id->public.orders.id" in inferred_ki["item_key"]

    # Check that sensitive card_number was NOT inferred
    assert not any("card_number" in i["item_key"] for i in upserted_items)

    # 4. RelationshipGraph join path finding
    graph = RelationshipGraph.from_knowledge_items(upserted_items)
    path = graph.find_join_path(["order_items", "customers"])
    assert path is not None
    assert len(path) == 2  # order_items -> orders -> customers
    tables_in_path = {edge.source_table for edge in path} | {edge.target_table for edge in path}
    assert "order_items" in tables_in_path
    assert "orders" in tables_in_path
    assert "customers" in tables_in_path
