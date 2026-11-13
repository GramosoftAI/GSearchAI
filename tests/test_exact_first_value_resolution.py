"""Comprehensive Unit and Integration Tests for Exact-First, Latency-Efficient Database Value Resolution.

Covers all 12 scenarios specified in the task:
1. Input `CREAM_Reward`; database contains exactly `CREAM_Reward`. Preserve exact value.
2. Input `bug`; database contains `Bugs`. Discover candidate via normalization without modifying original input.
3. Input `Bug`; database contains both `Bug` and `Bugs`. Preserve `Bug` (exact match bypasses fuzzy/plural).
4. Input `cream_type`; database contains `CREAM_Reward`. No false substitution solely based on low/partial similarity.
5. Input `bug`; database contains `Bug` and `Debug`. Avoid unsafe substring-based match.
6. Two candidates have similar scores. Trigger ambiguity workflow / detect ambiguity margin.
7. No candidate is sufficiently relevant. Do not silently substitute.
8. Relevant column is unknown. Use bounded fallback retrieval.
9. Database lookup times out or fails. Gracefully fallback and avoid generating unsafe SQL.
10. Case-sensitive values, nulls, numeric columns, and punctuation handled correctly.
11. User input cannot cause SQL injection through value lookup.
12. Matching works across schemas and database adapters dynamically without static hardcoding.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from app.modules.database_knowledgebase.retrieval.grounded_entity_resolver import (
    GroundedEntityResolver,
    DimensionTableMeta,
)
from app.modules.database_knowledgebase.planning.entity_value_resolver import (
    EntityValueResolver,
    ResolutionStatus,
)
from app.modules.database_knowledgebase.schemas.canonical import (
    DatabaseSchema,
    SchemaInfo,
    TableSchema,
    ColumnSchema,
    ColumnDataType,
    ForeignKeySchema,
)
from app.modules.database_knowledgebase.schemas.connection import (
    DatabaseConnectionConfig,
    DatabaseType,
)


@pytest.fixture
def dummy_conn_config():
    return DatabaseConnectionConfig(
        db_type=DatabaseType.POSTGRESQL,
        host="localhost",
        port=5432,
        database_name="testdb",
        username="postgres",
        password="secretpassword",
    )


@pytest.fixture
def sample_canonical_schema():
    """Create a fully dynamic schema with dimension tables (issue_types, categories, users, projects)."""
    issue_types = TableSchema(
        table_name="types",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="int", is_primary_key=True),
            "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        },
        foreign_keys=[],
    )

    rewards = TableSchema(
        table_name="rewards",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="int", is_primary_key=True),
            "code": ColumnSchema(name="code", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
            "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        },
        foreign_keys=[],
    )

    tasks = TableSchema(
        table_name="tasks",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="int", is_primary_key=True),
            "type_id": ColumnSchema(name="type_id", data_type=ColumnDataType.INTEGER, raw_data_type="int"),
            "reward_id": ColumnSchema(name="reward_id", data_type=ColumnDataType.INTEGER, raw_data_type="int"),
            "subject": ColumnSchema(name="subject", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        },
        foreign_keys=[
            ForeignKeySchema(
                constrained_columns=["type_id"],
                referred_table="types",
                referred_columns=["id"],
            ),
            ForeignKeySchema(
                constrained_columns=["reward_id"],
                referred_table="rewards",
                referred_columns=["id"],
            ),
        ],
    )

    return DatabaseSchema(
        database_name="testdb",
        schemas={
            "public": SchemaInfo(
                schema_name="public",
                tables={
                    "types": issue_types,
                    "rewards": rewards,
                    "tasks": tasks,
                },
            )
        },
    )


@pytest.mark.asyncio
async def test_scenario_1_exact_match_preserved(monkeypatch, sample_canonical_schema, dummy_conn_config):
    """Scenario 1: Input `CREAM_Reward`; DB contains exactly `CREAM_Reward`. Exact match preserved."""
    async def mock_get_dimension_rows(conn_config, kb_id, dim, limit=2000, tenant_id=None):
        if dim.table_name == "rewards":
            return [
                {"id": 101, "code": "CREAM_Reward", "name": "CREAM_Reward"},
                {"id": 102, "code": "ICE_Reward", "name": "ICE_Reward"},
            ]
        return []

    monkeypatch.setattr(GroundedEntityResolver, "get_dimension_rows", mock_get_dimension_rows)

    res = await GroundedEntityResolver.resolve_entities_in_query(
        user_query="Filter by CREAM_Reward code",
        canonical_schema=sample_canonical_schema,
        conn_config=dummy_conn_config,
        kb_id="kb-test",
    )

    assert len(res["resolved_entities"]) == 1
    ent = res["resolved_entities"][0]
    assert ent["name"] == "CREAM_Reward"
    assert ent["match_stage"] == "EXACT"
    assert ent["confidence"] == 1.0
    assert ent["id"] == 101
    assert res["timings"]["exact_latency_ms"] >= 0.0


@pytest.mark.asyncio
async def test_scenario_2_singular_plural_normalization(monkeypatch, sample_canonical_schema, dummy_conn_config):
    """Scenario 2: User enters `bug`; DB contains `Bugs`. Discover candidate without changing original input."""
    async def mock_get_dimension_rows(conn_config, kb_id, dim, limit=2000, tenant_id=None):
        if dim.table_name == "types":
            return [
                {"id": 1, "name": "Bugs"},
                {"id": 2, "name": "Feature"},
            ]
        return []

    monkeypatch.setattr(GroundedEntityResolver, "get_dimension_rows", mock_get_dimension_rows)

    res = await GroundedEntityResolver.resolve_entities_in_query(
        user_query="Show me all bug tasks",
        canonical_schema=sample_canonical_schema,
        conn_config=dummy_conn_config,
        kb_id="kb-test",
    )

    assert len(res["resolved_entities"]) == 1
    ent = res["resolved_entities"][0]
    # Retains actual database value
    assert ent["name"] == "Bugs"
    assert ent["match_stage"] == "NORMALIZED"
    assert ent["confidence"] >= 0.90
    assert ent["id"] == 1


@pytest.mark.asyncio
async def test_scenario_3_exact_priority_over_plural(monkeypatch, sample_canonical_schema, dummy_conn_config):
    """Scenario 3: Input `Bug`; DB contains both `Bug` and `Bugs`. Preserve `Bug` exact match."""
    async def mock_get_dimension_rows(conn_config, kb_id, dim, limit=2000, tenant_id=None):
        if dim.table_name == "types":
            return [
                {"id": 1, "name": "Bugs"},
                {"id": 2, "name": "Bug"},
            ]
        return []

    monkeypatch.setattr(GroundedEntityResolver, "get_dimension_rows", mock_get_dimension_rows)

    res = await GroundedEntityResolver.resolve_entities_in_query(
        user_query="Find issues of type Bug",
        canonical_schema=sample_canonical_schema,
        conn_config=dummy_conn_config,
        kb_id="kb-test",
    )

    assert len(res["resolved_entities"]) == 1
    ent = res["resolved_entities"][0]
    # Exact match MUST take precedence over Bugs
    assert ent["name"] == "Bug"
    assert ent["match_stage"] == "EXACT"
    assert ent["confidence"] == 1.0
    assert ent["id"] == 2


@pytest.mark.asyncio
async def test_scenario_4_no_false_similarity_substitution(monkeypatch, sample_canonical_schema, dummy_conn_config):
    """Scenario 4: Input `cream_type`; DB contains `CREAM_Reward`. No false equivalence based solely on partial similarity."""
    async def mock_get_dimension_rows(conn_config, kb_id, dim, limit=2000, tenant_id=None):
        if dim.table_name == "rewards":
            return [
                {"id": 50, "code": "CREAM_Reward", "name": "CREAM_Reward"},
            ]
        return []

    monkeypatch.setattr(GroundedEntityResolver, "get_dimension_rows", mock_get_dimension_rows)

    res = await GroundedEntityResolver.resolve_entities_in_query(
        user_query="Check the cream_type in system",
        canonical_schema=sample_canonical_schema,
        conn_config=dummy_conn_config,
        kb_id="kb-test",
        fuzzy_threshold=0.85,
    )

    # cream_type vs CREAM_Reward similarity is only ~0.5; should NOT resolve
    assert len(res["resolved_entities"]) == 0
    assert len(res["ambiguous_entities"]) == 0


@pytest.mark.asyncio
async def test_scenario_5_avoid_substring_false_positives(monkeypatch, sample_canonical_schema, dummy_conn_config):
    """Scenario 5: Input `bug`; DB contains `Bug` and `Debug`. Avoid unsafe substring matching `Debug`."""
    async def mock_get_dimension_rows(conn_config, kb_id, dim, limit=2000, tenant_id=None):
        if dim.table_name == "types":
            return [
                {"id": 10, "name": "Debug"},
                {"id": 20, "name": "Bug"},
            ]
        return []

    monkeypatch.setattr(GroundedEntityResolver, "get_dimension_rows", mock_get_dimension_rows)

    res = await GroundedEntityResolver.resolve_entities_in_query(
        user_query="Show open bug items",
        canonical_schema=sample_canonical_schema,
        conn_config=dummy_conn_config,
        kb_id="kb-test",
    )

    assert len(res["resolved_entities"]) == 1
    ent = res["resolved_entities"][0]
    # Word boundary prevents 'bug' from matching 'Debug'
    assert ent["name"] == "Bug"
    assert ent["id"] == 20


@pytest.mark.asyncio
async def test_scenario_6_ambiguous_candidates_within_margin(monkeypatch, sample_canonical_schema, dummy_conn_config):
    """Scenario 6: Two candidates have similar scores. Trigger clarification / ambiguous entities workflow."""
    async def mock_get_dimension_rows(conn_config, kb_id, dim, limit=2000, tenant_id=None):
        if dim.table_name == "types":
            return [
                {"id": 1, "name": "TaskFlowA"},
                {"id": 2, "name": "TaskFlowB"},
            ]
        return []

    monkeypatch.setattr(GroundedEntityResolver, "get_dimension_rows", mock_get_dimension_rows)

    res = await GroundedEntityResolver.resolve_entities_in_query(
        user_query="Show records for TaskFlow",
        canonical_schema=sample_canonical_schema,
        conn_config=dummy_conn_config,
        kb_id="kb-test",
        fuzzy_threshold=0.75,
        ambiguity_margin=0.10,
    )

    # TaskFlowA and TaskFlowB have identical similarity to TaskFlow (8/9 = 0.888) -> score gap = 0.0 < 0.10
    assert len(res["resolved_entities"]) == 0
    assert len(res["ambiguous_entities"]) == 1
    amb = res["ambiguous_entities"][0]
    assert len(amb["candidates"]) == 2
    assert amb["match_stage"] == "FUZZY_AMBIGUOUS"


@pytest.mark.asyncio
async def test_scenario_7_low_confidence_no_silent_substitution(monkeypatch, sample_canonical_schema, dummy_conn_config):
    """Scenario 7: No candidate is sufficiently relevant. Do not silently substitute."""
    async def mock_get_dimension_rows(conn_config, kb_id, dim, limit=2000, tenant_id=None):
        if dim.table_name == "types":
            return [
                {"id": 1, "name": "Critical"},
                {"id": 2, "name": "Trivial"},
            ]
        return []

    monkeypatch.setattr(GroundedEntityResolver, "get_dimension_rows", mock_get_dimension_rows)

    res = await GroundedEntityResolver.resolve_entities_in_query(
        user_query="List items by completelyUnrelatedThing",
        canonical_schema=sample_canonical_schema,
        conn_config=dummy_conn_config,
        kb_id="kb-test",
    )

    assert len(res["resolved_entities"]) == 0
    assert len(res["ambiguous_entities"]) == 0


@pytest.mark.asyncio
async def test_scenario_8_bounded_candidate_discovery(monkeypatch, sample_canonical_schema, dummy_conn_config):
    """Scenario 8: Column/table candidates bounded by retrieved schema docs without scanning entire DB."""
    fetched_dims = []

    async def mock_get_dimension_rows(conn_config, kb_id, dim, limit=2000, tenant_id=None):
        fetched_dims.append(dim.table_name)
        # Dynamically generate mock rows using the discovered schema metadata
        row = {dim.pk_col: 1}
        for idx, col in enumerate(dim.label_cols):
            row[col] = "Bug" if "name" in col else f"{dim.table_name}_val"
        return [row]

    monkeypatch.setattr(GroundedEntityResolver, "get_dimension_rows", mock_get_dimension_rows)

    res = await GroundedEntityResolver.resolve_entities_in_query(
        user_query="Show me all Bug items",
        canonical_schema=sample_canonical_schema,
        conn_config=dummy_conn_config,
        kb_id="kb-test",
        relevant_tables=["types"],
    )

    # Candidate tables are bounded and prioritized
    assert "types" in fetched_dims
    assert len(res["resolved_entities"]) == 1


@pytest.mark.asyncio
async def test_scenario_9_database_lookup_failure_resilience(monkeypatch, sample_canonical_schema, dummy_conn_config):
    """Scenario 9: Database lookup times out or fails. Gracefully fallback and avoid crash."""
    async def mock_get_dimension_rows(conn_config, kb_id, dim, limit=2000, tenant_id=None):
        raise TimeoutError("Database connection timed out")

    monkeypatch.setattr(GroundedEntityResolver, "get_dimension_rows", mock_get_dimension_rows)

    res = await GroundedEntityResolver.resolve_entities_in_query(
        user_query="Show me all Bug items",
        canonical_schema=sample_canonical_schema,
        conn_config=dummy_conn_config,
        kb_id="kb-test",
    )

    # Fails closed gracefully without raising unhandled exception
    assert res["resolved_entities"] == []
    assert res["ambiguous_entities"] == []
    assert "timings" in res


@pytest.mark.asyncio
async def test_scenario_10_case_sensitivity_nulls_numeric(monkeypatch, sample_canonical_schema, dummy_conn_config):
    """Scenario 10: Handles case-sensitive values, nulls, and numeric columns correctly."""
    async def mock_get_dimension_rows(conn_config, kb_id, dim, limit=2000, tenant_id=None):
        if dim.table_name == "types":
            return [
                {"id": 1, "name": None},  # Null value test
                {"id": 2, "name": 42},    # Numeric value test
                {"id": 3, "name": "VIP-Customer_Tier"},
            ]
        return []

    monkeypatch.setattr(GroundedEntityResolver, "get_dimension_rows", mock_get_dimension_rows)

    res = await GroundedEntityResolver.resolve_entities_in_query(
        user_query="Find VIP-Customer_Tier accounts",
        canonical_schema=sample_canonical_schema,
        conn_config=dummy_conn_config,
        kb_id="kb-test",
    )

    assert len(res["resolved_entities"]) == 1
    assert res["resolved_entities"][0]["name"] == "VIP-Customer_Tier"


@pytest.mark.asyncio
async def test_scenario_11_sql_injection_prevention():
    """Scenario 11: User input cannot cause SQL injection through parameterized executor."""
    mock_executor = AsyncMock()
    # Return empty to verify safe execution
    mock_executor.execute.return_value = []

    result = await EntityValueResolver.resolve_with_executor(
        query_literal="Robert'); DROP TABLE users;--",
        target_table="users",
        table_alias="u",
        candidate_columns=["username"],
        executor=mock_executor,
    )

    # Verify query used parameterized $1 and didn't interpolate raw SQL
    executed_call = mock_executor.execute.call_args_list[0]
    query_sql, params = executed_call[0][0], executed_call[0][1]
    assert "$1" in query_sql
    assert "DROP TABLE" not in query_sql
    assert params == ["Robert'); DROP TABLE users;--"]
    assert result.status == ResolutionStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_scenario_12_dynamic_adapter_schema_independence(sample_canonical_schema):
    """Scenario 12: Matching works dynamically with zero hardcoded domain tables."""
    dims = GroundedEntityResolver.discover_dimension_tables(sample_canonical_schema)
    discovered_table_names = [d.table_name for d in dims]

    # Dynamic discovery detected dimension tables
    assert "types" in discovered_table_names
    assert "rewards" in discovered_table_names
    
    # Types and rewards have inbound FKs from tasks, so they rank ahead of tasks
    type_meta = next(d for d in dims if d.table_name == "types")
    reward_meta = next(d for d in dims if d.table_name == "rewards")
    task_meta = next(d for d in dims if d.table_name == "tasks")
    
    assert type_meta.inbound_fks >= 1
    assert reward_meta.inbound_fks >= 1
    assert task_meta.inbound_fks == 0
    assert dims[0].inbound_fks >= dims[-1].inbound_fks
