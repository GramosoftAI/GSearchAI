"""STEP 6: Targeted Regression Tests for Planner Entity Anchor Hijacking Fixes

Verifies:
1. "Show the latest 10 orders." does not select `users` as the anchor.
2. "Show sales by customer." does not replace the business tables with `users`.
3. "Show revenue by month." does not fail due to a false person anchor.
4. "Compare this month revenue with last month." does not fail due to structural words.
5. "Show customers named John." preserves correct customer routing and disambiguation.
6. Exact product entity resolution from STEP 5 continues to work.
7. Raw `INSERT INTO ...` is rejected by the security layer.
8. Ordinary NL questions containing similar vocabulary are not incorrectly rejected.
9. Tenant isolation and validated join-path behavior remain intact.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.modules.database_knowledgebase.planning.entity_value_resolver import EntityValueResolver
from app.modules.database_knowledgebase.planning.planner import QueryPlanner
from app.modules.database_knowledgebase.retrieval.retriever import SchemaRetrievalResult
from app.modules.database_knowledgebase.retrieval.scorer import TableRetrievalScore
from app.modules.database_knowledgebase.knowledge.retrieval.analyzer import QuestionAnalyzer
from app.modules.database_knowledgebase.schemas.canonical import (
    DatabaseSchema,
    SchemaInfo,
    TableSchema,
    ColumnSchema,
    ColumnDataType,
    ForeignKeySchema,
)
from app.modules.database_knowledgebase.exceptions import SQLValidationError
from app.modules.database_knowledgebase.services.service import DatabaseKnowledgebaseService


@pytest.fixture
def ecommerce_canonical_schema() -> DatabaseSchema:
    """Canonical schema containing business tables (customers, orders, order_items, products) and users."""
    cust_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "email": ColumnSchema(name="email", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
    }
    order_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "customer_id": ColumnSchema(name="customer_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_foreign_key=True),
        "total_amount": ColumnSchema(name="total_amount", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
        "order_date": ColumnSchema(name="order_date", data_type=ColumnDataType.TIMESTAMP, raw_data_type="timestamp"),
    }
    item_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "order_id": ColumnSchema(name="order_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_foreign_key=True),
        "product_id": ColumnSchema(name="product_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_foreign_key=True),
        "quantity": ColumnSchema(name="quantity", data_type=ColumnDataType.INTEGER, raw_data_type="integer"),
        "unit_price": ColumnSchema(name="unit_price", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
    }
    prod_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "category": ColumnSchema(name="category", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "price": ColumnSchema(name="price", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
    }
    user_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "username": ColumnSchema(name="username", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "full_name": ColumnSchema(name="full_name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "email": ColumnSchema(name="email", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
    }

    tables = {
        "customers": TableSchema(table_name="customers", schema_name="public", columns=cust_cols, foreign_keys=[]),
        "orders": TableSchema(
            table_name="orders",
            schema_name="public",
            columns=order_cols,
            foreign_keys=[
                ForeignKeySchema(
                    name="fk_orders_customer",
                    constrained_columns=["customer_id"],
                    referred_table="customers",
                    referred_columns=["id"],
                )
            ],
        ),
        "order_items": TableSchema(
            table_name="order_items",
            schema_name="public",
            columns=item_cols,
            foreign_keys=[
                ForeignKeySchema(
                    name="fk_items_order",
                    constrained_columns=["order_id"],
                    referred_table="orders",
                    referred_columns=["id"],
                ),
                ForeignKeySchema(
                    name="fk_items_product",
                    constrained_columns=["product_id"],
                    referred_table="products",
                    referred_columns=["id"],
                ),
            ],
        ),
        "products": TableSchema(table_name="products", schema_name="public", columns=prod_cols, foreign_keys=[]),
        "users": TableSchema(table_name="users", schema_name="public", columns=user_cols, foreign_keys=[]),
    }

    schema_info = SchemaInfo(schema_name="public", tables=tables)
    return DatabaseSchema(
        database_name="test_ecommerce",
        database_type="postgresql",
        schemas={"public": schema_info},
        fingerprint="fp_ecommerce_001",
    )


def _mock_retrieval(tables_to_include, canonical_schema: DatabaseSchema) -> SchemaRetrievalResult:
    pub_tables = canonical_schema.schemas["public"].tables
    retrieved = [pub_tables[t] for t in tables_to_include if t in pub_tables]
    return SchemaRetrievalResult(
        database_name=canonical_schema.database_name,
        database_type=canonical_schema.database_type,
        schema_version=canonical_schema.fingerprint or "v1",
        retrieved_tables=retrieved,
        retrieval_scores={t.table_name: TableRetrievalScore(table_name=t.table_name) for t in retrieved},
        join_paths=[],
        overall_confidence=0.95,
        untrusted_boundary_text="",
        execution_time_ms=1.0,
    )


def test_1_latest_orders_does_not_anchor_on_users(ecommerce_canonical_schema):
    """1. 'Show the latest 10 orders.' does not select users as the anchor."""
    q = "Show the latest 10 orders."
    candidates = EntityValueResolver.extract_literal_candidates(q, canonical_schema=ecommerce_canonical_schema)
    assert "latest" not in [c.lower() for c in candidates]
    assert "orders" not in [c.lower() for c in candidates]

    retrieval = _mock_retrieval(["orders", "order_items"], ecommerce_canonical_schema)
    plan = QueryPlanner.plan(
        user_query=q,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_canonical_schema,
        retrieval_result=retrieval,
    )

    planned_table_names = [t.table_name for t in plan.tables]
    assert "orders" in planned_table_names
    assert "users" not in planned_table_names
    assert plan.tables[0].table_name == "orders"


def test_2_sales_by_customer_preserves_business_tables(ecommerce_canonical_schema):
    """2. 'Show sales by customer.' does not replace the business tables with users."""
    q = "Show sales by customer."
    candidates = EntityValueResolver.extract_literal_candidates(q, canonical_schema=ecommerce_canonical_schema)
    assert "sales" not in [c.lower() for c in candidates]

    retrieval = _mock_retrieval(["customers", "orders"], ecommerce_canonical_schema)
    plan = QueryPlanner.plan(
        user_query=q,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_canonical_schema,
        retrieval_result=retrieval,
    )

    planned_table_names = [t.table_name for t in plan.tables]
    assert "customers" in planned_table_names
    assert "users" not in planned_table_names


def test_3_revenue_by_month_does_not_fail_due_to_person_anchor(ecommerce_canonical_schema):
    """3. 'Show revenue by month.' does not fail due to a false person anchor."""
    q = "Show revenue by month."
    candidates = EntityValueResolver.extract_literal_candidates(q, canonical_schema=ecommerce_canonical_schema)
    assert "revenue" not in [c.lower() for c in candidates]
    assert "month" not in [c.lower() for c in candidates]

    retrieval = _mock_retrieval(["orders", "order_items"], ecommerce_canonical_schema)
    plan = QueryPlanner.plan(
        user_query=q,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_canonical_schema,
        retrieval_result=retrieval,
    )

    planned_table_names = [t.table_name for t in plan.tables]
    assert "orders" in planned_table_names
    assert "users" not in planned_table_names


def test_4_compare_revenue_does_not_fail_on_structural_words(ecommerce_canonical_schema):
    """4. 'Compare this month revenue with last month.' does not fail due to structural words."""
    q = "Compare this month revenue with last month."
    candidates = EntityValueResolver.extract_literal_candidates(q, canonical_schema=ecommerce_canonical_schema)
    candidates_lower = [c.lower() for c in candidates]
    for w in ("compare", "month", "revenue", "last"):
        assert w not in candidates_lower

    retrieval = _mock_retrieval(["orders"], ecommerce_canonical_schema)
    plan = QueryPlanner.plan(
        user_query=q,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_canonical_schema,
        retrieval_result=retrieval,
    )

    planned_table_names = [t.table_name for t in plan.tables]
    assert "orders" in planned_table_names
    assert "users" not in planned_table_names


def test_5_customers_named_john_preserves_customer_disambiguation(ecommerce_canonical_schema):
    """5. 'Show customers named John.' preserves correct customer routing and disambiguation."""
    q = "Show customers named John."
    retrieval = _mock_retrieval(["customers"], ecommerce_canonical_schema)
    
    # Simulate disambiguation entity for John in customers table
    disambig = [
        {"table": "customers", "column": "name", "value": "John", "ids": [101, 102]}
    ]

    plan = QueryPlanner.plan(
        user_query=q,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_canonical_schema,
        retrieval_result=retrieval,
        resolved_entities=disambig,
    )

    planned_table_names = [t.table_name for t in plan.tables]
    assert "customers" in planned_table_names
    assert "users" not in planned_table_names
    assert plan.tables[0].table_name == "customers"
    assert any(p.table_alias == "c" and "id" in p.column_name for p in plan.predicates) or \
           any(p.table_alias == "c" and "name" in p.column_name for p in plan.predicates)


def test_6_exact_product_entity_resolution_preserved(ecommerce_canonical_schema):
    """6. Exact product entity resolution from STEP 5 continues to work."""
    q = "Which customers bought the Ultra-HD 27-inch Monitor?"
    analyzer = QuestionAnalyzer()
    frame = analyzer.analyze(q)
    assert any("Ultra" in s or "Monitor" in s for s in frame.entity_candidates)

    retrieval = _mock_retrieval(["customers", "orders", "order_items", "products"], ecommerce_canonical_schema)
    disambig = [
        {"table": "products", "column": "name", "value": "Ultra-HD 27-inch Monitor", "ids": [42]}
    ]
    plan = QueryPlanner.plan(
        user_query=q,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_canonical_schema,
        retrieval_result=retrieval,
        resolved_entities=disambig,
    )

    planned_table_names = [t.table_name for t in plan.tables]
    assert "products" in planned_table_names
    assert any(p.table_alias == "p" and p.column_name == "id" and p.value == 42 for p in plan.predicates)


@pytest.mark.asyncio
async def test_7_raw_insert_is_rejected_by_security():
    """7. Raw `INSERT INTO ...` is rejected by the security layer."""
    mock_db = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_by_id = AsyncMock(return_value=MagicMock(settings={}))
    mock_repo.get_latest_schema_snapshot = AsyncMock(return_value=None)

    service = DatabaseKnowledgebaseService(db=mock_db, tenant_id=uuid.uuid4())
    service.repo = mock_repo
    
    raw_insert = "INSERT INTO customers (name, email) VALUES ('Hacker', 'h@ck.er');"
    with pytest.raises(SQLValidationError) as exc_info:
        await service.query_database(
            kb_id=uuid.uuid4(),
            user_query=raw_insert,
            use_llm=False,
        )
    assert "Security policy rejection" in str(exc_info.value)
    assert "Non-SELECT" in str(exc_info.value) or "INSERT" in str(exc_info.value)


@pytest.mark.asyncio
async def test_8_ordinary_nl_with_insert_word_not_falsely_rejected():
    """8. Ordinary NL questions containing similar vocabulary are not incorrectly rejected."""
    mock_db = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_by_id = AsyncMock(return_value=MagicMock(settings={}))
    mock_repo.get_latest_schema_snapshot = AsyncMock(return_value=None)
    
    service = DatabaseKnowledgebaseService(db=mock_db, tenant_id=uuid.uuid4())
    service.repo = mock_repo

    nl_query = "Can I insert items into the list?"
    try:
        # Pre-validation should pass; any subsequent error should not be SQLValidationError
        await service.query_database(
            kb_id=uuid.uuid4(),
            user_query=nl_query,
            use_llm=False,
        )
    except SQLValidationError:
        pytest.fail("Ordinary NL query mentioning 'insert' was incorrectly rejected by SQL security policy!")
    except Exception:
        # Subsequent pipeline errors (e.g. execution/mock db) are expected and acceptable
        pass


def test_9_tenant_isolation_and_join_path_intact(ecommerce_canonical_schema):
    """9. Tenant isolation and validated join-path behavior remain intact."""
    from app.modules.database_knowledgebase.pipeline.context import QueryPipelineContext
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    kb_id = uuid.uuid4()

    # Verify tenant isolation via pipeline context
    ctx = QueryPipelineContext.create(tenant_id=tenant_a, knowledgebase_id=kb_id, original_question="Show customer orders.")
    ctx.assert_scope(tenant_a, kb_id)
    with pytest.raises(Exception):
        ctx.assert_scope(tenant_b, kb_id)

    q = "Show customer orders."
    retrieval = _mock_retrieval(["customers", "orders"], ecommerce_canonical_schema)

    plan = QueryPlanner.plan(
        user_query=q,
        database_knowledgebase_id=kb_id,
        canonical_schema=ecommerce_canonical_schema,
        retrieval_result=retrieval,
        tenant_id=tenant_a,
    )

    # Verified join path customers <-> orders must be planned
    planned_table_names = [t.table_name for t in plan.tables]
    assert "customers" in planned_table_names
    assert "orders" in planned_table_names
    assert len(plan.joins) >= 1
    join = plan.joins[0]
    assert (join.source_table_alias, join.target_table_alias) in [("c", "o"), ("o", "c")]
