import pytest
from app.modules.database_knowledgebase.schemas.canonical import (
    DatabaseSchema,
    SchemaInfo,
    TableSchema,
    ColumnSchema,
    ColumnDataType,
)
from app.modules.database_knowledgebase.retrieval.retriever import SchemaRetrievalResult
from app.modules.database_knowledgebase.retrieval.pruner import SchemaPruner
from app.modules.database_knowledgebase.retrieval.scorer import TableRetrievalScore
from app.modules.database_knowledgebase.sql_security.policy import (
    SQLSecurityPolicyEngine,
    DenyPolicyConfig,
)


def _col(name: str, data_type: ColumnDataType, is_pk: bool = False) -> ColumnSchema:
    return ColumnSchema(
        name=name,
        data_type=data_type,
        raw_data_type=data_type.value.lower(),
        is_primary_key=is_pk,
    )


@pytest.fixture
def sample_schema() -> DatabaseSchema:
    users_table = TableSchema(
        table_name="users",
        schema_name="public",
        columns={
            "id": _col("id", ColumnDataType.INTEGER, is_pk=True),
            "username": _col("username", ColumnDataType.TEXT),
            "password_hash": _col("password_hash", ColumnDataType.TEXT),
            "access_token": _col("access_token", ColumnDataType.TEXT),
        },
    )
    tokens_table = TableSchema(
        table_name="oidc_user_tokens",
        schema_name="public",
        columns={
            "id": _col("id", ColumnDataType.INTEGER, is_pk=True),
            "token": _col("token", ColumnDataType.TEXT),
        },
    )
    items_table = TableSchema(
        table_name="items",
        schema_name="public",
        columns={
            "id": _col("id", ColumnDataType.INTEGER, is_pk=True),
            "name": _col("name", ColumnDataType.TEXT),
            "owner_id": _col("owner_id", ColumnDataType.INTEGER),
        },
    )

    return DatabaseSchema(
        database_name="testdb",
        database_type="postgresql",
        schemas={
            "public": SchemaInfo(
                schema_name="public",
                tables={
                    "users": users_table,
                    "oidc_user_tokens": tokens_table,
                    "items": items_table,
                },
            )
        },
    )


@pytest.fixture
def sample_retrieval(sample_schema: DatabaseSchema) -> SchemaRetrievalResult:
    return SchemaRetrievalResult(
        database_name="testdb",
        database_type="postgresql",
        schema_version="dummy_fingerprint",
        retrieved_tables=[
            sample_schema.schemas["public"].tables["users"],
            sample_schema.schemas["public"].tables["items"],
        ],
        retrieval_scores={},
        join_paths=[],
        overall_confidence=0.9,
        untrusted_boundary_text="<database></database>",
    )


def test_deny_table_in_select(sample_schema, sample_retrieval):
    sql = "SELECT id FROM oidc_user_tokens"
    res = SQLSecurityPolicyEngine.validate_sql(sql, sample_schema, sample_retrieval)
    assert not res.is_valid
    codes = [e.error_code for e in res.errors]
    assert "DENIED_TABLE" in codes


def test_deny_table_in_join(sample_schema, sample_retrieval):
    sql = "SELECT u.id FROM users u JOIN oidc_user_tokens t ON u.id = t.id"
    res = SQLSecurityPolicyEngine.validate_sql(sql, sample_schema, sample_retrieval)
    assert not res.is_valid
    assert any(e.error_code == "DENIED_TABLE" for e in res.errors)


def test_deny_table_in_subquery_and_cte(sample_schema, sample_retrieval):
    sql_sub = "SELECT id FROM users WHERE id IN (SELECT id FROM oidc_user_tokens)"
    res_sub = SQLSecurityPolicyEngine.validate_sql(sql_sub, sample_schema, sample_retrieval)
    assert not res_sub.is_valid
    assert any(e.error_code == "DENIED_TABLE" for e in res_sub.errors)

    sql_cte = "WITH token_cte AS (SELECT id FROM oidc_user_tokens) SELECT id FROM users"
    res_cte = SQLSecurityPolicyEngine.validate_sql(sql_cte, sample_schema, sample_retrieval)
    assert not res_cte.is_valid
    assert any(e.error_code == "DENIED_TABLE" for e in res_cte.errors)


def test_deny_column_in_select(sample_schema, sample_retrieval):
    sql = "SELECT id, password_hash FROM users"
    res = SQLSecurityPolicyEngine.validate_sql(sql, sample_schema, sample_retrieval)
    assert not res.is_valid
    assert any(e.error_code == "DENIED_COLUMN" for e in res.errors)


def test_deny_column_in_where(sample_schema, sample_retrieval):
    sql = "SELECT id FROM users WHERE access_token = 'xyz'"
    res = SQLSecurityPolicyEngine.validate_sql(sql, sample_schema, sample_retrieval)
    assert not res.is_valid
    assert any(e.error_code == "DENIED_COLUMN" for e in res.errors)


def test_select_star_expansion_with_denied_column(sample_schema, sample_retrieval):
    # users has password_hash and access_token, both matching deny patterns
    sql = "SELECT * FROM users"
    res = SQLSecurityPolicyEngine.validate_sql(sql, sample_schema, sample_retrieval)
    assert not res.is_valid
    assert any(e.error_code == "DENIED_COLUMN" for e in res.errors)


def test_per_kb_overrides_allow_and_deny(sample_schema, sample_retrieval):
    # Allow oidc_user_tokens via override
    overrides_allow = {
        "allowed_table_patterns": ["oidc_*"],
    }
    sql = "SELECT id FROM oidc_user_tokens"
    res = SQLSecurityPolicyEngine.validate_sql(
        sql, sample_schema, sample_retrieval, security_overrides=overrides_allow
    )
    # Shouldn't fail with DENIED_TABLE (might fail with UNRETRIEVED_TABLE since oidc_user_tokens not in sample_retrieval)
    denied_errors = [e for e in res.errors if e.error_code == "DENIED_TABLE"]
    assert len(denied_errors) == 0

    # Deny items table via extra deny override
    overrides_deny = {
        "denied_table_patterns": ["items"],
    }
    sql_item = "SELECT id FROM items"
    res_item = SQLSecurityPolicyEngine.validate_sql(
        sql_item, sample_schema, sample_retrieval, security_overrides=overrides_deny
    )
    assert not res_item.is_valid
    assert any(e.error_code == "DENIED_TABLE" for e in res_item.errors)


def test_pruner_strips_denied_tables_and_columns(sample_schema):
    selected_scores = {
        "public.users": TableRetrievalScore(
            table_name="public.users",
            vector_score=0.9,
            keyword_score=0.9,
            graph_score=0.0,
            final_score=0.9,
            matched_columns=["id", "username", "access_token"],
        ),
        "public.oidc_user_tokens": TableRetrievalScore(
            table_name="public.oidc_user_tokens",
            vector_score=0.95,
            keyword_score=0.9,
            graph_score=0.0,
            final_score=0.95,
            matched_columns=["token"],
        ),
    }

    pruned_tables, _, xml_context = SchemaPruner.prune_schema(
        canonical_schema=sample_schema,
        selected_scores=selected_scores,
        active_relationships=[],
    )

    table_names = [t.table_name for t in pruned_tables]
    # oidc_user_tokens must be stripped
    assert "oidc_user_tokens" not in table_names
    assert "users" in table_names

    users_tbl = next(t for t in pruned_tables if t.table_name == "users")
    # password_hash and access_token must NOT be present in columns
    assert "password_hash" not in users_tbl.columns
    assert "access_token" not in users_tbl.columns
    assert "id" in users_tbl.columns
    assert "username" in users_tbl.columns

    # Check XML string does not contain denied column names or tables
    assert "password_hash" not in xml_context
    assert "access_token" not in xml_context
    assert "oidc_user_tokens" not in xml_context
