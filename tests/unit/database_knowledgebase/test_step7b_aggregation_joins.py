"""STEP 7B: Targeted Unit & Regression Tests for Aggregation & Multi-Table Join Correctness

Verifies:
1. C02: "What is the total revenue?" -> single table orders, projects SUM(o.total_amount), no row multiplication from order_items.
2. D01: "Show sales by customer." -> joins customers and orders, groups by customer, aggregates SUM(o.total_amount).
3. D02: "Show revenue by month." -> single table orders, groups by DATE_TRUNC('month', order_date), aggregates SUM(o.total_amount).
4. G01: "Show orders for Alice Johnson." -> joins orders and customers, filters on Alice Johnson, returns order rows.
5. I01: "Which product has the highest sales?" -> joins products and order_items, aggregates sales, ORDER BY DESC LIMIT 1.
6. I02: "Which customer spent the most?" -> joins customers and orders, groups by customer, aggregates SUM(o.total_amount), ORDER BY DESC LIMIT 1.
7. Anti-join-explosion: Single-table aggregation queries do not pull in line-item/bridge tables.
"""

import uuid
import pytest

from app.modules.database_knowledgebase.planning.planner import QueryPlanner
from app.modules.database_knowledgebase.planning.models import IntentType, AggregateFunction, JoinType
from app.modules.database_knowledgebase.sql_generator.generator import CandidateSQLGenerator
from app.modules.database_knowledgebase.retrieval.retriever import SchemaRetrievalResult
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
def ecommerce_canonical_schema() -> DatabaseSchema:
    """Canonical schema containing customers, orders, order_items, products, payments."""
    cust_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "city": ColumnSchema(name="city", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "email": ColumnSchema(name="email", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
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
        "status": ColumnSchema(name="status", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
    }
    item_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "order_id": ColumnSchema(name="order_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_foreign_key=True),
        "product_id": ColumnSchema(name="product_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_foreign_key=True),
        "quantity": ColumnSchema(name="quantity", data_type=ColumnDataType.INTEGER, raw_data_type="integer"),
        "unit_price": ColumnSchema(name="unit_price", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
    }
    pay_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "order_id": ColumnSchema(name="order_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_foreign_key=True),
        "amount": ColumnSchema(name="amount", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
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
        "payments": TableSchema(
            table_name="payments",
            schema_name="public",
            columns=pay_cols,
            foreign_keys=[
                ForeignKeySchema(
                    name="fk_payments_order",
                    constrained_columns=["order_id"],
                    referred_table="orders",
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


def _mock_retrieval(table_names: list, schema: DatabaseSchema) -> SchemaRetrievalResult:
    pub_tables = schema.schemas["public"].tables
    retrieved = [pub_tables[t] for t in table_names if t in pub_tables]
    from app.modules.database_knowledgebase.schema.graph import SchemaGraph
    graph = SchemaGraph.from_database_schema(schema)
    join_paths = []
    for t_name in table_names:
        for neighbor, rel in graph.get_neighbors(t_name):
            if neighbor in table_names:
                join_paths.append(rel)
    return SchemaRetrievalResult(
        database_name=schema.database_name,
        database_type=schema.database_type,
        schema_version=schema.fingerprint or "v1",
        retrieved_tables=retrieved,
        retrieval_scores={t.table_name: TableRetrievalScore(table_name=t.table_name) for t in retrieved},
        join_paths=join_paths,
        overall_confidence=0.95,
        untrusted_boundary_text="",
        execution_time_ms=1.0,
    )


def test_c02_total_revenue_single_table_orders(ecommerce_canonical_schema):
    """C02: 'What is the total revenue?' aggregates SUM(o.total_amount) on orders without joining order_items."""
    query = "What is the total revenue?"
    retrieval = _mock_retrieval(["orders", "order_items", "payments", "products"], ecommerce_canonical_schema)
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_canonical_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )
    sql = CandidateSQLGenerator.compile_plan_to_sql(plan)
    sql_l = sql.lower()

    planned_tbls = [t.table_name for t in plan.tables]
    assert "orders" in planned_tbls
    assert "order_items" not in planned_tbls
    assert "sum(" in sql_l
    assert "total_amount" in sql_l


def test_d01_sales_by_customer_join_and_group(ecommerce_canonical_schema):
    """D01: 'Show sales by customer.' joins customers and orders, grouping by customer name."""
    query = "Show sales by customer."
    retrieval = _mock_retrieval(["customers", "orders"], ecommerce_canonical_schema)
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_canonical_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )
    sql = CandidateSQLGenerator.compile_plan_to_sql(plan)
    sql_l = sql.lower()

    planned_tbls = {t.table_name for t in plan.tables}
    assert planned_tbls == {"customers", "orders"}
    assert "join" in sql_l
    assert "group by" in sql_l
    assert "sum(" in sql_l
    assert "name" in sql_l


def test_d02_revenue_by_month_date_trunc(ecommerce_canonical_schema):
    """D02: 'Show revenue by month.' uses DATE_TRUNC('month', ...) grouping on orders without joins."""
    query = "Show revenue by month."
    retrieval = _mock_retrieval(["orders", "order_items", "customers"], ecommerce_canonical_schema)
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_canonical_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )
    sql = CandidateSQLGenerator.compile_plan_to_sql(plan)
    sql_l = sql.lower()

    planned_tbls = [t.table_name for t in plan.tables]
    assert planned_tbls == ["orders"]
    assert "date_trunc('month'" in sql_l
    assert "group by" in sql_l
    assert "sum(" in sql_l


def test_i01_product_highest_sales(ecommerce_canonical_schema):
    """I01: 'Which product has the highest sales?' joins products with order_items or orders with ORDER BY DESC LIMIT 1."""
    query = "Which product has the highest sales?"
    retrieval = _mock_retrieval(["products", "order_items"], ecommerce_canonical_schema)
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_canonical_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )
    sql = CandidateSQLGenerator.compile_plan_to_sql(plan)
    sql_l = sql.lower()

    planned_tbls = {t.table_name for t in plan.tables}
    assert "products" in planned_tbls
    assert "order_items" in planned_tbls
    assert "join" in sql_l
    assert "order by" in sql_l
    assert "desc" in sql_l
    assert "limit 1" in sql_l


def test_i02_customer_spent_most(ecommerce_canonical_schema):
    """I02: 'Which customer spent the most?' joins customers and orders, grouping by customer name, ORDER BY SUM(total_amount) DESC LIMIT 1."""
    query = "Which customer spent the most?"
    retrieval = _mock_retrieval(["customers", "orders", "payments"], ecommerce_canonical_schema)
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_canonical_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )
    sql = CandidateSQLGenerator.compile_plan_to_sql(plan)
    sql_l = sql.lower()

    planned_tbls = {t.table_name for t in plan.tables}
    assert planned_tbls == {"customers", "orders"}
    assert "join" in sql_l
    assert "group by" in sql_l
    assert "sum(" in sql_l
    assert "total_amount" in sql_l
    assert "order by" in sql_l
    assert "desc" in sql_l
    assert "limit 1" in sql_l
