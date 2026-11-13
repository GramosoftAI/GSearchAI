import pytest
import uuid
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.database_knowledgebase.knowledge.retrieval.entity_resolver import (
    extract_candidate_spans,
    resolve_entities,
    resolve_entities_live,
    _get_label_columns_from_knowledge,
    LiveEntityResolver,
    GENERIC_STOP_WORDS,
)
from app.modules.database_knowledgebase.knowledge.retrieval.analyzer import QuestionAnalyzer
from app.modules.database_knowledgebase.planning.planner import QueryPlanner
from app.modules.database_knowledgebase.retrieval.retriever import SchemaRetrievalResult
from app.modules.database_knowledgebase.schemas.canonical import (
    DatabaseSchema,
    TableSchema,
    ColumnSchema,
    ColumnDataType,
    RelationshipSchema,
    RelationshipType,
)


KB_ID = uuid.UUID("c0f9fbc6-fdb1-49a1-bfe8-9b2aed3b25ae")
TENANT_ID = uuid.UUID("2b41fa8c-9c12-491d-8199-a75292e683ec")


def test_spans_order_and_exclusions():
    """Spans for the query put 'arun' among the first spans and exclude 'assign'."""
    exclusion_set = {"projects", "what", "are", "the"}
    query = "what are the projects assigned to arun"
    spans = extract_candidate_spans(query, exclusion_set)

    # 'arun' must be in spans and among the first spans
    assert "arun" in spans
    assert spans.index("arun") == 0 or spans[0] == "arun"
    # 'assign' and 'assigned' must be completely excluded
    assert "assign" not in spans
    assert "assigned" not in spans
    assert "assign to arun" not in spans


@pytest.mark.asyncio
async def test_exact_query_timeout_handling():
    """Timeout in the exact query -> warning logged, rollback called, trigram still runs."""
    mock_session = AsyncMock()
    mock_session.rollback = AsyncMock()

    # Make target_session.execute raise asyncio.TimeoutError on exact query, then succeed on trigram
    trigram_result = MagicMock()
    trigram_result.fetchall.return_value = [
        ("users", "login", "Arun S", "arun s", 0.85)
    ]

    call_count = 0
    async def side_effect_execute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise asyncio.TimeoutError()
        return trigram_result

    mock_session.execute = AsyncMock(side_effect=side_effect_execute)

    with patch("app.modules.database_knowledgebase.knowledge.retrieval.entity_resolver.build_kb_exclusion_set", new_callable=AsyncMock) as mock_ex, \
         patch("app.modules.database_knowledgebase.knowledge.retrieval.entity_resolver.get_kb_table_kinds", new_callable=AsyncMock) as mock_kinds:
        mock_ex.return_value = {"projects"}
        mock_kinds.return_value = {"users": "entity"}

        res = await resolve_entities(
            question="projects assigned to arun",
            kb_id=KB_ID,
            session=mock_session,
            tenant_id=TENANT_ID,
            timeout_ms=100,
        )

        # Rollback was called on exact query timeout
        assert mock_session.rollback.called
        # Trigram query still ran and returned matches
        assert len(res.resolved_entities) > 0
        assert res.resolved_entities[0].table_name == "users"


@pytest.mark.asyncio
async def test_column_selection_priorities_and_enum_exclusion():
    """Column selection includes users.login/firstname/lastname, excludes enum-role columns."""
    mock_session = AsyncMock()

    # Mock knowledge items query result
    # (item_key, payload, is_sensitive)
    mock_items = [
        (
            "col_1",
            {"column_name": "status", "table_name": "users", "role": "enum", "is_primary_key": False},
            False,
        ),
        (
            "col_2",
            {"column_name": "lastname", "table_name": "users", "role": "name", "is_primary_key": False},
            False,
        ),
        (
            "col_3",
            {"column_name": "id", "table_name": "users", "role": "id", "is_primary_key": True},
            False,
        ),
        (
            "col_4",
            {"column_name": "firstname", "table_name": "users", "role": "name", "is_primary_key": False},
            False,
        ),
        (
            "col_5",
            {"column_name": "login", "table_name": "users", "role": "text", "is_primary_key": False},
            False,
        ),
    ]

    mock_result = MagicMock()
    mock_result.all.return_value = mock_items
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("app.modules.database_knowledgebase.knowledge.retrieval.entity_resolver.get_kb_table_kinds", new_callable=AsyncMock) as mock_kinds:
        mock_kinds.return_value = {"users": "entity"}

        cols = await _get_label_columns_from_knowledge(
            session=mock_session,
            kb_id=KB_ID,
            tenant_id=TENANT_ID,
        )

        col_names = [c["column_name"] for c in cols]
        # Includes login, firstname, lastname
        assert "login" in col_names
        assert "firstname" in col_names
        assert "lastname" in col_names
        # Excludes enum-role column (status)
        assert "status" not in col_names
        # login and firstname are prioritized before lastname
        assert col_names.index("login") < col_names.index("lastname")
        assert col_names.index("firstname") < col_names.index("lastname")


@pytest.mark.asyncio
async def test_live_fallback_ambiguous_two_aruns():
    """Live fallback on a mock DB with two Aruns returns ambiguous=True with 2 choices and pk values."""
    mock_session = AsyncMock()
    mock_adapter = MagicMock()

    class MockAsyncPGConnection:
        async def fetch(self, query, *params):
            # Two matching users: id=29 (Arun S) and id=113 (arun_07)
            return [
                {"tbl": "users", "col": "login", "pk_col": "id", "row_id": "29", "matched_val": "Arun S"},
                {"tbl": "users", "col": "firstname", "pk_col": "id", "row_id": "29", "matched_val": "Arun"},
                {"tbl": "users", "col": "login", "pk_col": "id", "row_id": "113", "matched_val": "arun_07"},
                {"tbl": "users", "col": "firstname", "pk_col": "id", "row_id": "113", "matched_val": "Arun"},
            ]

    class MockReadOnlyContext:
        async def __aenter__(self):
            return MockAsyncPGConnection()
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_adapter.open_readonly_connection.return_value = MockReadOnlyContext()

    with patch("app.modules.database_knowledgebase.knowledge.retrieval.entity_resolver._get_label_columns_from_knowledge", new_callable=AsyncMock) as mock_cols:
        mock_cols.return_value = [
            {"schema_table": "public.users", "schema_name": "public", "table_name": "users", "column_name": "login", "pk_col": "id"},
            {"schema_table": "public.users", "schema_name": "public", "table_name": "users", "column_name": "firstname", "pk_col": "id"},
        ]

        entities = await resolve_entities_live(
            spans=["arun"],
            kb_id=KB_ID,
            tenant_id=TENANT_ID,
            adapter=mock_adapter,
            session=mock_session,
        )

        assert len(entities) == 1
        ent = entities[0]
        assert ent.table_name == "users"
        assert ent.ambiguous is True
        assert len(ent.choices) == 2
        pks = [c.pk_value for c in ent.choices]
        assert 29 in pks and 113 in pks
        assert ent.pk_value == [29, 113] or ent.pk_value == pks
        labels = [c.display_label for c in ent.choices]
        assert any("29" in l for l in labels)
        assert any("113" in l for l in labels)


@pytest.mark.asyncio
async def test_fail_closed_unanswerable():
    """'projects assigned to zzzqq' -> unanswerable with a 'couldn't find' message."""
    mock_session = AsyncMock()
    mock_adapter = MagicMock()

    class MockEmptyConnection:
        async def fetch(self, query, *params):
            return []

    class MockReadOnlyContext:
        async def __aenter__(self):
            return MockEmptyConnection()
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_adapter.open_readonly_connection.return_value = MockReadOnlyContext()

    resolver = LiveEntityResolver(
        db=mock_session,
        tenant_id=TENANT_ID,
        adapter=mock_adapter,
    )

    analyzer = QuestionAnalyzer()
    frame = analyzer.analyze("projects assigned to zzzqq")

    with patch("app.modules.database_knowledgebase.knowledge.retrieval.entity_resolver.resolve_entities", new_callable=AsyncMock) as mock_res, \
         patch("app.modules.database_knowledgebase.knowledge.retrieval.entity_resolver._get_label_columns_from_knowledge", new_callable=AsyncMock) as mock_cols:
        from app.modules.database_knowledgebase.knowledge.retrieval.entity_resolver import EntityResolutionResult
        # Tier 1 returns 0 matches but recorded spans_tried=['zzzqq']
        mock_res.return_value = EntityResolutionResult(
            resolved_entities=[],
            spans_tried=["zzzqq"],
            unanswerable=False,
        )
        mock_cols.return_value = [
            {"schema_table": "public.users", "schema_name": "public", "table_name": "users", "column_name": "login", "pk_col": "id"}
        ]

        result = await resolver.resolve(
            db_knowledgebase_id=KB_ID,
            frame=frame,
            session=mock_session,
        )

        assert result.unanswerable is True
        assert "Couldn't find 'zzzqq' in the data." in result.unanswerable_reason


def test_plan_with_arun_entity_filter_and_context_pack_validation():
    """Plan for the Arun query includes users or assigned_to_id with an entity filter, and all plan tables are in the context pack."""
    # Setup canonical schema with projects, work_packages, and users
    from app.modules.database_knowledgebase.schemas.canonical import SchemaInfo

    tbl_projects = TableSchema(
        schema_name="public",
        table_name="projects",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
            "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        },
    )
    rel_wp_proj = RelationshipSchema(
        source_table="work_packages",
        source_columns=["project_id"],
        target_table="projects",
        target_columns=["id"],
        relationship_type=RelationshipType.MANY_TO_ONE,
    )
    rel_wp_users = RelationshipSchema(
        source_table="work_packages",
        source_columns=["assigned_to_id"],
        target_table="users",
        target_columns=["id"],
        relationship_type=RelationshipType.MANY_TO_ONE,
    )
    tbl_wp = TableSchema(
        schema_name="public",
        table_name="work_packages",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
            "project_id": ColumnSchema(name="project_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_foreign_key=True),
            "assigned_to_id": ColumnSchema(name="assigned_to_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_foreign_key=True),
            "subject": ColumnSchema(name="subject", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        },
        relationships=[rel_wp_proj, rel_wp_users],
    )
    tbl_users = TableSchema(
        schema_name="public",
        table_name="users",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
            "login": ColumnSchema(name="login", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
            "firstname": ColumnSchema(name="firstname", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        },
    )
    rel_mem_proj = RelationshipSchema(
        source_table="members",
        source_columns=["project_id"],
        target_table="projects",
        target_columns=["id"],
        relationship_type=RelationshipType.MANY_TO_ONE,
    )
    rel_mem_users = RelationshipSchema(
        source_table="members",
        source_columns=["user_id"],
        target_table="users",
        target_columns=["id"],
        relationship_type=RelationshipType.MANY_TO_ONE,
    )
    tbl_members = TableSchema(
        schema_name="public",
        table_name="members",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
            "project_id": ColumnSchema(name="project_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_foreign_key=True),
            "user_id": ColumnSchema(name="user_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_foreign_key=True),
        },
        relationships=[rel_mem_proj, rel_mem_users],
    )

    schema = DatabaseSchema(
        database_name="openproject",
        schemas={
            "public": SchemaInfo(
                schema_name="public",
                tables={
                    "projects": tbl_projects,
                    "work_packages": tbl_wp,
                    "users": tbl_users,
                    "members": tbl_members,
                },
            )
        },
    )

    # Retrieval result context pack only has projects, work_packages, users (members is absent!)
    retrieval_res = SchemaRetrievalResult(
        database_name="openproject",
        database_type="postgresql",
        retrieved_tables=[tbl_projects, tbl_wp, tbl_users],
        retrieved_columns={"projects": ["id", "name"], "work_packages": ["id", "project_id", "assigned_to_id"], "users": ["id", "login"]},
        join_paths=[],
        schema_version="mock_v1",
        retrieval_scores={},
        overall_confidence=0.9,
        untrusted_boundary_text="",
    )

    # Arun resolved entities with IDs [29, 113]
    resolved_entities = [
        {
            "type": "user",
            "id": [29, 113],
            "name": "arun",
            "table": "users",
            "column": "login",
            "pk_column": "id",
            "values": ["Arun S (id 29)", "arun_07 (id 113)"],
        }
    ]

    plan = QueryPlanner.plan(
        user_query="what are the projects assigned to arun",
        database_knowledgebase_id=KB_ID,
        canonical_schema=schema,
        retrieval_result=retrieval_res,
        resolved_entities=resolved_entities,
    )

    planned_table_names = [t.table_name.lower() for t in plan.tables]
    # 'members' must be absent / rejected
    assert "members" not in planned_table_names

    # All planned tables must be present in retrieval_result
    retrieved_names = {t.table_name.lower() for t in retrieval_res.retrieved_tables}
    for t_name in planned_table_names:
        assert t_name in retrieved_names

    # An entity filter must exist on users or assigned_to_id with the resolved IDs
    has_filter = False
    for p in plan.predicates:
        if (p.column_name.lower() in ("id", "assigned_to_id", "login")) and (p.value == [29, 113] or p.value in ([29, 113], 29, 113, [29], [113])):
            has_filter = True
            break
    assert has_filter is True
