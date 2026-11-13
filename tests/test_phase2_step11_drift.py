"""Smoke test for Phase 2 Step 11: Schema Drift & Dependent Invalidation

Tests:
1. Schema diff events: TABLE_ADDED, TABLE_DROPPED, COLUMN_ADDED, COLUMN_MODIFIED, COLUMN_DROPPED.
2. Invalidation: dropped/modified objects mark dependent relationships, metrics, glossary stale (or conflict if admin-locked).
3. Deprecation of query memory records referencing affected objects.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.modules.database_knowledgebase.knowledge.drift.schema_drift import (
    compute_schema_diff,
    invalidate_dependents_on_drift,
    DriftEventType,
)
from app.modules.database_knowledgebase.knowledge.adapters.phase1_adapter import (
    SchemaView,
    TableView,
    ColumnView,
)
from app.modules.database_knowledgebase.knowledge.models.knowledge_items import (
    KB2KnowledgeItem,
    KB2QueryMemory,
)


def test_schema_diff_events():
    # Old schema: users, orders (id, total_amount, old_col)
    old_schema = SchemaView(
        database_name="db",
        database_type="postgresql",
        schema_version="v1",
        tables={
            "users": TableView("public", "users", "BASE TABLE", {"id": ColumnView("id", "int", "int", False, True, False)}, ["id"], []),
            "orders": TableView(
                "public", "orders", "BASE TABLE",
                {
                    "id": ColumnView("id", "int", "int", False, True, False),
                    "total_amount": ColumnView("total_amount", "int", "int", False, False, False),
                    "old_col": ColumnView("old_col", "text", "text", True, False, False),
                },
                ["id"], [],
            ),
        },
    )

    # New schema: users dropped, orders modified (old_col dropped, total_amount changed to numeric), payments added
    new_schema = SchemaView(
        database_name="db",
        database_type="postgresql",
        schema_version="v2",
        tables={
            "orders": TableView(
                "public", "orders", "BASE TABLE",
                {
                    "id": ColumnView("id", "int", "int", False, True, False),
                    "total_amount": ColumnView("total_amount", "numeric", "numeric", False, False, False),  # modified
                    "new_col": ColumnView("new_col", "varchar", "varchar", True, False, False),  # added
                },
                ["id"], [],
            ),
            "payments": TableView("public", "payments", "BASE TABLE", {"id": ColumnView("id", "int", "int", False, True, False)}, ["id"], []),  # added
        },
    )

    diff = compute_schema_diff(old_schema, new_schema)
    assert diff.has_changes is True
    assert "payments" in diff.added_tables
    assert "users" in diff.dropped_tables
    assert "orders" in diff.modified_tables

    event_types = {e.event_type for e in diff.events}
    assert DriftEventType.TABLE_ADDED in event_types
    assert DriftEventType.TABLE_DROPPED in event_types
    assert DriftEventType.COLUMN_ADDED in event_types
    assert DriftEventType.COLUMN_MODIFIED in event_types
    assert DriftEventType.COLUMN_DROPPED in event_types


@pytest.mark.asyncio
async def test_drift_dependent_invalidation_smoke():
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    # Create dummy diff: table 'users' dropped, 'orders.old_col' dropped
    old_s = SchemaView("db", "postgresql", "v1", {
        "users": TableView("public", "users", "BASE TABLE", {}, [], []),
        "orders": TableView("public", "orders", "BASE TABLE", {"old_col": ColumnView("old_col", "text", "text", True, False, False)}, [], []),
    })
    new_s = SchemaView("db", "postgresql", "v2", {
        "orders": TableView("public", "orders", "BASE TABLE", {}, [], []),
    })
    diff = compute_schema_diff(old_s, new_s)

    # Items depending on users or orders.old_col
    rel_unlocked = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="relationship",
        item_key="rel:orders.user_id->users.id",
        status="confirmed",
        is_locked_by_admin=False,
        payload={"child_table": "orders", "parent_table": "users", "child_columns": ["user_id"], "parent_columns": ["id"]},
    )
    metric_locked = KB2KnowledgeItem(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        item_type="metric",
        item_key="metric:old_metric",
        status="confirmed",
        is_locked_by_admin=True,  # locked -> conflict
        payload={"depends_on": ["public.orders.old_col"]},
    )
    qm_verified = KB2QueryMemory(
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        schema_version="v1",
        natural_query="Select users",
        normalized_query="select users",
        compiled_sql="SELECT * FROM users",
        plan_ir={},
        execution_stats={},
        status="verified",
        referenced_items=["table:users"],
    )

    mock_session = MagicMock()
    mock_session.commit = AsyncMock()

    mock_scalars_ki = MagicMock()
    mock_scalars_ki.all.return_value = [rel_unlocked, metric_locked]
    mock_scalars_qm = MagicMock()
    mock_scalars_qm.all.return_value = [qm_verified]

    async def mock_exec(stmt):
        stmt_s = str(stmt).lower()
        res = MagicMock()
        if "kb2_query_memory" in stmt_s:
            res.scalars.return_value = mock_scalars_qm
        else:
            res.scalars.return_value = mock_scalars_ki
        return res

    mock_session.execute = AsyncMock(side_effect=mock_exec)

    summary = await invalidate_dependents_on_drift(tenant_id, kb_id, diff, mock_session)

    assert summary["stale_items"] == 1
    assert summary["conflict_items"] == 1
    assert summary["deprecated_queries"] == 1

    assert rel_unlocked.status == "stale"
    assert metric_locked.status == "conflict"
    assert qm_verified.status == "deprecated"
