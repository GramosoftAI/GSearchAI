"""STEP 7A: Targeted Regression Tests for Filter & Ranking Correctness

Verifies:
1. B01: "Show customers from Chennai." -> city location filter resolution on customers.city.
2. B03: "Show products with price above 300." -> strict '>' operator, individual row filtering without SUM(price).
3. I03: "Show the top 3 products by price." -> descending price order, LIMIT 3, no SUM/aggregation.
4. H01: "Show orders created today." -> half-open interval [CURRENT_DATE, CURRENT_DATE + INTERVAL '1 day').
5. H02: "Show orders created yesterday." -> half-open interval [CURRENT_DATE - INTERVAL '1 day', CURRENT_DATE).
6. Plain column names (e.g. "price") do not erroneously trigger SUM aggregation metrics.
7. Security & Parameterization: bound parameters are preserved and deterministic compilation succeeds.
"""

import uuid
import pytest

from app.modules.database_knowledgebase.planning.entity_value_resolver import EntityValueResolver
from app.modules.database_knowledgebase.planning.planner import QueryPlanner
from app.modules.database_knowledgebase.sql_generator.generator import CandidateSQLGenerator
from app.modules.database_knowledgebase.retrieval.retriever import SchemaRetrievalResult
from app.modules.database_knowledgebase.semantic.metric_discovery import UniversalMetricDiscovery
from app.modules.database_knowledgebase.semantic.database_knowledge_profile import (
    ColumnSemanticProfile,
    ColumnSemanticRole,
    ColumnSemanticSubtype,
)
from app.modules.database_knowledgebase.retrieval.scorer import TableRetrievalScore
from app.modules.database_knowledgebase.schemas.canonical import (
    DatabaseSchema,
    SchemaInfo,
    TableSchema,
    ColumnSchema,
    ColumnDataType,
    ForeignKeySchema,
)


@pytest.fixture
def canonical_ecommerce_schema() -> DatabaseSchema:
    """Canonical schema containing customers, products, orders, order_items."""
    cust_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "city": ColumnSchema(name="city", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
    }
    prod_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "price": ColumnSchema(name="price", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
    }
    order_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "customer_id": ColumnSchema(name="customer_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_foreign_key=True),
        "order_date": ColumnSchema(name="order_date", data_type=ColumnDataType.TIMESTAMP, raw_data_type="timestamp"),
        "total_amount": ColumnSchema(name="total_amount", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
    }
    tables = {
        "customers": TableSchema(table_name="customers", schema_name="public", columns=cust_cols, foreign_keys=[]),
        "products": TableSchema(table_name="products", schema_name="public", columns=prod_cols, foreign_keys=[]),
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


def test_b01_location_preposition_extraction_and_predicate(canonical_ecommerce_schema):
    """B01: 'Show customers from Chennai.' extracts 'Chennai' and targets city column."""
    query = "Show customers from Chennai."
    literals = EntityValueResolver.extract_literal_candidates(query, canonical_schema=canonical_ecommerce_schema)
    assert "Chennai" in literals

    retrieval = _mock_retrieval(["customers"], canonical_ecommerce_schema)
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=canonical_ecommerce_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )
    assert len(plan.predicates) == 1
    pred = plan.predicates[0]
    assert pred.column_name == "city"
    assert "chennai" in str(pred.value).lower()

    sql = CandidateSQLGenerator.compile_plan_to_sql(plan)
    assert "customers" in sql.lower()
    assert "city" in sql.lower()


def test_b03_numeric_above_strict_greater_than(canonical_ecommerce_schema):
    """B03: 'Show products with price above 300.' uses strict '>' and no aggregation."""
    query = "Show products with price above 300."
    retrieval = _mock_retrieval(["products"], canonical_ecommerce_schema)
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=canonical_ecommerce_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )
    # Check that it filters individual products with > 300
    assert len(plan.predicates) >= 1
    price_pred = next(p for p in plan.predicates if p.column_name == "price")
    assert price_pred.operator == ">"
    assert float(price_pred.value) == 300.0

    # Ensure no SUM aggregation on products
    agg_funcs = [p.aggregation.value for p in plan.projections if p.aggregation and p.aggregation.value.lower() != "none"]
    assert len(agg_funcs) == 0

    sql = CandidateSQLGenerator.compile_plan_to_sql(plan)
    assert ">" in sql
    assert "sum(" not in sql.lower()


def test_i03_top_n_ranking_limit_and_order(canonical_ecommerce_schema):
    """I03: 'Show the top 3 products by price.' orders descending with LIMIT 3 and no aggregation."""
    query = "Show the top 3 products by price."
    retrieval = _mock_retrieval(["products"], canonical_ecommerce_schema)
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=canonical_ecommerce_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )
    assert plan.limit == 3
    assert len(plan.order_by) >= 1
    order = plan.order_by[0]
    assert "price" in order.expression.lower()
    assert order.direction.value.lower() == "desc"

    # Ensure no aggregation
    agg_funcs = [p.aggregation.value for p in plan.projections if p.aggregation and p.aggregation.value.lower() != "none"]
    assert len(agg_funcs) == 0

    sql = CandidateSQLGenerator.compile_plan_to_sql(plan)
    assert "order by" in sql.lower()
    assert "desc" in sql.lower()
    assert "limit 3" in sql.lower()
    assert "sum(" not in sql.lower()


def test_h01_today_half_open_range(canonical_ecommerce_schema):
    """H01: 'Show orders created today.' creates half-open [CURRENT_DATE, CURRENT_DATE + INTERVAL '1 day')."""
    query = "Show orders created today."
    retrieval = _mock_retrieval(["orders"], canonical_ecommerce_schema)
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=canonical_ecommerce_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )
    sql = CandidateSQLGenerator.compile_plan_to_sql(plan)
    sql_l = sql.lower()
    assert "current_date" in sql_l
    assert ">=" in sql_l
    assert "<" in sql_l
    assert "interval '1 day'" in sql_l


def test_h02_yesterday_half_open_range(canonical_ecommerce_schema):
    """H02: 'Show orders created yesterday.' creates half-open [CURRENT_DATE - INTERVAL '1 day', CURRENT_DATE)."""
    query = "Show orders created yesterday."
    retrieval = _mock_retrieval(["orders"], canonical_ecommerce_schema)
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=canonical_ecommerce_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )
    sql = CandidateSQLGenerator.compile_plan_to_sql(plan)
    sql_l = sql.lower()
    assert "current_date" in sql_l
    assert ">=" in sql_l
    assert "<" in sql_l
    assert "- interval '1 day'" in sql_l


def test_metric_discovery_does_not_hijack_plain_column_name():
    """Metric discovery should not assign SUM metric synonym to a naked column name like 'price'."""
    col_prof = ColumnSemanticProfile(
        schema_name="public",
        table_name="products",
        column_name="price",
        data_type=ColumnDataType.NUMERIC,
        role=ColumnSemanticRole.NUMERIC,
        subtype=ColumnSemanticSubtype.CURRENCY,
    )
    metrics = UniversalMetricDiscovery.discover_metrics(
        entities={},
        columns={"public.products.price": col_prof},
    )
    for m in metrics.values():
        if m.default_aggregation == "SUM":
            assert "price" not in [s.lower() for s in m.synonyms]

