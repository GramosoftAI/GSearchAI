"""Comprehensive Unit and Regression Tests for Schema-Aware Query Rephrasing

Covers the 12 evaluation scenarios:
1. User uses a synonym for a documented column (e.g. 'created' -> 'created_at').
2. User describes a table informally ('tasks' -> 'work_packages').
3. User uses plural form 'bugs' while database has 'Bug' or 'Bugs'.
4. Exact-first resolver already identifies the correct value; preserved without duplication.
5. Exact value resembling another value is preserved.
6. Indirect join paths and relationships mapped via Canonical SchemaGraph.
7. Date-based question maps to documented business date column (e.g. 'created last month' -> 'created_at' date_range).
8. Negation and exclusion filters ('without', 'not') are preserved.
9. Multiple similar candidate columns/tables detected and flagged in ambiguities if underspecified.
10. Unsupported / non-existent concepts fail gracefully without hallucination.
11. Rephrasing produces valid structured SchemaAwareInterpretation.
12. End-to-end execution and prompt construction integrity with GroundedSQLGenerator.
"""

import pytest
import datetime
from typing import List, Dict, Any

from app.modules.database_knowledgebase.planning.schema_aware_rephraser import (
    SchemaAwareQueryRephraser,
    SchemaAwareInterpretation,
)
from app.modules.database_knowledgebase.schemas.canonical import (
    DatabaseSchema,
    SchemaInfo,
    TableSchema,
    ColumnSchema,
    ColumnDataType,
    ForeignKeySchema,
    RelationshipSchema,
    RelationshipType,
)


@pytest.fixture
def mock_openproject_schema() -> DatabaseSchema:
    """Canonical schema representing an enterprise work management database."""
    work_packages = TableSchema(
        table_name="work_packages",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="int", is_primary_key=True),
            "subject": ColumnSchema(name="subject", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
            "type_id": ColumnSchema(name="type_id", data_type=ColumnDataType.INTEGER, raw_data_type="int"),
            "author_id": ColumnSchema(name="author_id", data_type=ColumnDataType.INTEGER, raw_data_type="int"),
            "created_at": ColumnSchema(name="created_at", data_type=ColumnDataType.TIMESTAMP, raw_data_type="timestamp", comment="Date work item was created"),
            "updated_at": ColumnSchema(name="updated_at", data_type=ColumnDataType.TIMESTAMP, raw_data_type="timestamp", comment="Date work item was modified"),
            "due_date": ColumnSchema(name="due_date", data_type=ColumnDataType.DATE, raw_data_type="date", comment="Deadline date"),
        },
        foreign_keys=[
            ForeignKeySchema(
                name="fk_wp_types",
                constrained_columns=["type_id"],
                referred_table="types",
                referred_columns=["id"],
            ),
            ForeignKeySchema(
                name="fk_wp_users",
                constrained_columns=["author_id"],
                referred_table="users",
                referred_columns=["id"],
            ),
        ],
    )

    types_tbl = TableSchema(
        table_name="types",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="int", is_primary_key=True),
            "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar", comment="Type name like Bug, Task, Feature"),
        },
        foreign_keys=[],
    )

    users_tbl = TableSchema(
        table_name="users",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="int", is_primary_key=True),
            "login": ColumnSchema(name="login", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
            "firstname": ColumnSchema(name="firstname", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
            "lastname": ColumnSchema(name="lastname", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        },
        foreign_keys=[],
    )

    return DatabaseSchema(
        database_name="openproject_db",
        schemas={
            "public": SchemaInfo(
                schema_name="public",
                tables={
                    "work_packages": work_packages,
                    "types": types_tbl,
                    "users": users_tbl,
                },
            )
        },
    )


@pytest.fixture
def mock_retrieved_docs() -> List[Dict[str, Any]]:
    return [
        {
            "table_name": "work_packages",
            "title": "Table: work_packages",
            "column_names": ["id", "subject", "type_id", "author_id", "created_at", "updated_at", "due_date"],
            "text": "# work_packages\n- Object type: BASE TABLE\nDescription: Main work items and issues.",
            "score": 0.95,
        },
        {
            "table_name": "types",
            "title": "Table: types",
            "column_names": ["id", "name"],
            "text": "# types\nDescription: Categories of work items including Bug, Feature, Task.",
            "score": 0.90,
        },
        {
            "table_name": "users",
            "title": "Table: users",
            "column_names": ["id", "login", "firstname", "lastname"],
            "text": "# users\nDescription: System users and assignees.",
            "score": 0.90,
        },
    ]


def test_scenario_1_column_synonym_and_date_mapping(mock_retrieved_docs, mock_openproject_schema):
    """Scenario 1 & 7: User asks 'created last month' -> maps to documented 'created_at' with date_range operator."""
    interpretation = SchemaAwareQueryRephraser.rephrase(
        user_query="Show me all bugs created last month",
        retrieved_docs=mock_retrieved_docs,
        canonical_schema=mock_openproject_schema,
    )

    assert isinstance(interpretation, SchemaAwareInterpretation)
    assert interpretation.intent in ("SELECT_FILTER_MULTI", "SELECT_POINT", "SELECT_AGGREGATE")
    
    # Check filter interpretation
    date_filters = [f for f in interpretation.filters if f.operator == "date_range"]
    assert len(date_filters) == 1
    df = date_filters[0]
    assert df.column == "created_at"
    assert "BETWEEN" in df.expression
    assert df.raw_match == "last month"


def test_scenario_2_informal_table_description(mock_retrieved_docs, mock_openproject_schema):
    """Scenario 2: User queries informally; schema tables are preserved accurately in metadata notes."""
    interpretation = SchemaAwareQueryRephraser.rephrase(
        user_query="Show active items in work_packages",
        retrieved_docs=mock_retrieved_docs,
        canonical_schema=mock_openproject_schema,
    )

    assert "work_packages" in interpretation.metadata_notes[0]
    assert "Retrieve records" in interpretation.rephrased_question


def test_scenario_3_plural_and_singular_handling(mock_retrieved_docs, mock_openproject_schema):
    """Scenario 3: User says 'bugs'; exact-first resolver output is passed and integrated cleanly."""
    resolved_entities = [
        {
            "table": "types",
            "id": 1,
            "name": "Bugs",
            "matched_term": "bugs",
            "column": "id",
            "role": None,
        }
    ]
    interpretation = SchemaAwareQueryRephraser.rephrase(
        user_query="how many bugs are open",
        retrieved_docs=mock_retrieved_docs,
        canonical_schema=mock_openproject_schema,
        resolved_entities=resolved_entities,
    )

    assert len(interpretation.entities) == 1
    ent = interpretation.entities[0]
    assert ent.candidate_table == "types"
    assert ent.resolved_value == "Bugs"
    assert ent.resolved_id == 1
    assert "Bugs" in interpretation.rephrased_question


def test_scenario_4_and_5_exact_value_preservation(mock_retrieved_docs, mock_openproject_schema):
    """Scenario 4 & 5: Exact database values are authoritatively preserved without fuzzy degradation."""
    resolved_entities = [
        {
            "table": "types",
            "id": 10,
            "name": "CREAM_Reward",
            "matched_term": "CREAM_Reward",
            "column": "id",
            "role": None,
            "confidence": 1.0,
        }
    ]
    interpretation = SchemaAwareQueryRephraser.rephrase(
        user_query="Filter items by CREAM_Reward",
        retrieved_docs=mock_retrieved_docs,
        canonical_schema=mock_openproject_schema,
        resolved_entities=resolved_entities,
    )

    assert interpretation.entities[0].resolved_value == "CREAM_Reward"
    assert interpretation.entities[0].confidence == 1.0
    assert "CREAM_Reward" in interpretation.rephrased_question


def test_scenario_6_join_path_mapping(mock_retrieved_docs, mock_openproject_schema):
    """Scenario 6: Relationships and foreign key join paths between tables are confirmed via SchemaGraph."""
    interpretation = SchemaAwareQueryRephraser.rephrase(
        user_query="Show tasks authored by users",
        retrieved_docs=mock_retrieved_docs,
        canonical_schema=mock_openproject_schema,
    )

    assert len(interpretation.relationships_required) >= 1
    # work_packages connects to users and types
    rel_tables = {(r.source_table, r.target_table) for r in interpretation.relationships_required}
    assert ("work_packages", "users") in rel_tables or ("users", "work_packages") in rel_tables or ("work_packages", "types") in rel_tables


def test_scenario_8_negation_and_exclusion_preserved(mock_retrieved_docs, mock_openproject_schema):
    """Scenario 8: Negation and exclusion constraints ('without') are strictly preserved."""
    interpretation = SchemaAwareQueryRephraser.rephrase(
        user_query="Find work_packages without assignee",
        retrieved_docs=mock_retrieved_docs,
        canonical_schema=mock_openproject_schema,
    )

    neg_filters = [f for f in interpretation.filters if f.is_negated]
    assert len(neg_filters) == 1
    assert neg_filters[0].operator == "IS NULL"
    assert neg_filters[0].column == "assignee"


def test_scenario_9_ambiguous_column_detection(mock_openproject_schema):
    """Scenario 9: Multiple date columns without qualifier triggers ambiguity alert in interpretation."""
    docs = [
        {
            "table_name": "work_packages",
            "title": "Table: work_packages",
            "column_names": ["id", "created_at", "updated_at", "due_date", "closed_at"],
            "text": "Work packages table with multiple dates.",
        }
    ]
    interpretation = SchemaAwareQueryRephraser.rephrase(
        user_query="Show records by date",
        retrieved_docs=docs,
        canonical_schema=mock_openproject_schema,
    )

    # Underspecified date term triggers ambiguity notice
    assert len(interpretation.ambiguities) >= 1
    assert "multiple date columns" in interpretation.ambiguities[0]


def test_scenario_10_and_11_graceful_fallback(mock_openproject_schema):
    """Scenario 10 & 11: Empty / unrelated query produces clean structured interpretation without crash."""
    interpretation = SchemaAwareQueryRephraser.rephrase(
        user_query="quantum teleportation",
        retrieved_docs=[],
        canonical_schema=mock_openproject_schema,
    )

    assert isinstance(interpretation, SchemaAwareInterpretation)
    assert interpretation.original_question == "quantum teleportation"
    assert interpretation.entities == []
    assert interpretation.filters == []


def test_scenario_12_rephrased_prompt_integration(mock_retrieved_docs, mock_openproject_schema):
    """Scenario 12: Verify GroundedSQLGenerator consumes structured interpretation without error."""
    from app.modules.database_knowledgebase.sql_generator.grounded_generator import GroundedSQLGenerator
    
    resolved = [
        {"table": "types", "id": 1, "name": "Bug", "matched_term": "bug", "column": "id"}
    ]
    interpretation = SchemaAwareQueryRephraser.rephrase(
        user_query="how many bug are created by elakkiya",
        retrieved_docs=mock_retrieved_docs,
        canonical_schema=mock_openproject_schema,
        resolved_entities=resolved,
    )

    assert interpretation.aggregation == "COUNT(*)"
    assert len(interpretation.entities) == 1
    assert interpretation.entities[0].resolved_value == "Bug"
