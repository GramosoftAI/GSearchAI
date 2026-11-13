"""STEP 7C.3: Schema-Driven Semantic Metric Resolution Tests

Covers all 10 required investigation scenarios:
1. Schema with orders.total_amount (preserves existing behavior).
2. Schema with orders.order_value and no total_amount.
3. Schema where both candidate columns exist and semantic evidence distinguishes them.
4. Schema where no valid revenue metric exists; planner must not invent a column.
5. Metric that requires a documented expression or verified canonical metric.
6. Metric request that is ambiguous; system must expose ambiguity or fail closed.
7. Schema with renamed tables/columns without familiar words (txns.val) resolved via semantic evidence.
8. Tenant isolation: metric metadata from Tenant A must never influence Tenant B.
9. Non-revenue metric request: legitimate filters and aggregations remain intact.
10. Regression test confirming STEP 7C.2 behavior: "overall revenue" has no phantom filter or join.
"""

import uuid
import pytest

from app.modules.database_knowledgebase.planning.intent_analyzer import QueryIntentAnalyzer
from app.modules.database_knowledgebase.planning.planner import QueryPlanner
from app.modules.database_knowledgebase.planning.models import IntentType, AggregateFunction
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
from app.modules.database_knowledgebase.semantic.metrics import CanonicalMetricRegistry
from app.modules.database_knowledgebase.semantic.models import (
    MetricDefinition,
    MetricType,
    SemanticEntity,
    SemanticAttribute,
    AmbiguityStatus,
)
from app.modules.database_knowledgebase.semantic.registry import SemanticModelRegistry
from app.modules.database_knowledgebase.semantic.resolver import SemanticResolver
from app.modules.database_knowledgebase.semantic.ambiguity import AmbiguityDetector


def _mock_retrieval(schema: DatabaseSchema, table_names: list[str]) -> SchemaRetrievalResult:
    all_t = [schema.schemas["public"].tables[n] for n in table_names]
    scores = {n: TableRetrievalScore(table_name=n, final_score=1.0) for n in table_names}
    return SchemaRetrievalResult(
        database_name=schema.database_name,
        database_type="postgresql",
        schema_version=schema.fingerprint or "test-schema-v1",
        retrieved_tables=all_t,
        retrieval_scores=scores,
        join_paths=[],
        overall_confidence=1.0,
        untrusted_boundary_text="MOCK",
    )


# ==============================================================================
# 1. Schema with orders.total_amount
# ==============================================================================
def test_1_schema_with_total_amount():
    """Schema with orders.total_amount resolves 'What is the total revenue?' to total_amount."""
    order_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "customer_id": ColumnSchema(name="customer_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer"),
        "total_amount": ColumnSchema(name="total_amount", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
        "order_date": ColumnSchema(name="order_date", data_type=ColumnDataType.TIMESTAMP, raw_data_type="timestamp"),
    }
    schema = DatabaseSchema(
        database_name="test_db",
        schemas={"public": SchemaInfo(schema_name="public", tables={"orders": TableSchema(table_name="orders", schema_name="public", columns=order_cols)})},
        fingerprint="fp_total_amount",
    )
    retrieval = _mock_retrieval(schema, ["orders"])
    query = "What is the total revenue?"

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )

    assert plan.confidence > 0.0
    assert len(plan.projections) == 1
    assert plan.projections[0].column_name == "total_amount"
    assert plan.projections[0].aggregation == AggregateFunction.SUM


# ==============================================================================
# 2. Schema with orders.order_value and no total_amount
# ==============================================================================
def test_2_schema_with_order_value_no_total_amount():
    """Schema with orders.order_value (and other numeric columns like shipping_fee) resolves revenue to order_value."""
    order_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "customer_id": ColumnSchema(name="customer_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer"),
        "order_value": ColumnSchema(name="order_value", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric", comment="Total transaction value of the order"),
        "shipping_fee": ColumnSchema(name="shipping_fee", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric", comment="Shipping charge"),
        "order_date": ColumnSchema(name="order_date", data_type=ColumnDataType.TIMESTAMP, raw_data_type="timestamp"),
    }
    schema = DatabaseSchema(
        database_name="test_db",
        schemas={"public": SchemaInfo(schema_name="public", tables={"orders": TableSchema(table_name="orders", schema_name="public", columns=order_cols)})},
        fingerprint="fp_order_value",
    )
    retrieval = _mock_retrieval(schema, ["orders"])
    query = "What is the total revenue?"

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )

    assert plan.confidence > 0.0, "Plan confidence should be > 0.0 when schema has valid monetary order_value column"
    assert len(plan.projections) == 1
    assert plan.projections[0].column_name == "order_value"
    assert plan.projections[0].aggregation == AggregateFunction.SUM


# ==============================================================================
# 3. Both candidate columns exist; semantic evidence distinguishes them
# ==============================================================================
def test_3_semantic_evidence_distinguishes_candidate_columns():
    """When orders has order_value, shipping_fee, tax_amount, semantic evidence resolves correctly."""
    order_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "customer_id": ColumnSchema(name="customer_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer"),
        "order_value": ColumnSchema(name="order_value", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric", comment="Order revenue / sales value"),
        "shipping_fee": ColumnSchema(name="shipping_fee", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric", comment="Shipping fee charged"),
        "tax_amount": ColumnSchema(name="tax_amount", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric", comment="Sales tax amount"),
    }
    schema = DatabaseSchema(
        database_name="test_db",
        schemas={"public": SchemaInfo(schema_name="public", tables={"orders": TableSchema(table_name="orders", schema_name="public", columns=order_cols)})},
        fingerprint="fp_multi_candidates",
    )
    retrieval = _mock_retrieval(schema, ["orders"])

    # 3a. Revenue resolves to order_value (not shipping_fee or tax_amount)
    plan_rev = QueryPlanner.plan(
        user_query="What is the total revenue?",
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )
    assert plan_rev.confidence > 0.0
    assert plan_rev.projections[0].column_name == "order_value"
    assert plan_rev.projections[0].aggregation == AggregateFunction.SUM

    # 3b. Shipping fee resolves specifically to shipping_fee
    plan_ship = QueryPlanner.plan(
        user_query="What is the total shipping fee?",
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )
    assert plan_ship.confidence > 0.0
    assert plan_ship.projections[0].column_name == "shipping_fee"
    assert plan_ship.projections[0].aggregation == AggregateFunction.SUM


# ==============================================================================
# 4. No valid revenue metric exists; planner must not invent a column
# ==============================================================================
def test_4_no_valid_revenue_metric_fails_closed():
    """A schema with no monetary or revenue column must decline deterministic compilation rather than inventing a column."""
    user_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "username": ColumnSchema(name="username", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "email": ColumnSchema(name="email", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "login_count": ColumnSchema(name="login_count", data_type=ColumnDataType.INTEGER, raw_data_type="integer"),
    }
    schema = DatabaseSchema(
        database_name="test_db",
        schemas={"public": SchemaInfo(schema_name="public", tables={"users": TableSchema(table_name="users", schema_name="public", columns=user_cols)})},
        fingerprint="fp_no_revenue",
    )
    retrieval = _mock_retrieval(schema, ["users"])
    query = "What is the total revenue?"

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )

    # Must fail closed: either confidence 0.0, empty projections, or reasoning indicating unresolvable aggregate
    assert plan.confidence == 0.0 or len(plan.projections) == 0, (
        f"Planner invented a revenue metric when none exists: projections={plan.projections}"
    )


# ==============================================================================
# 5. Metric that requires a documented expression / canonical metric
# ==============================================================================
def test_5_documented_expression_canonical_metric():
    """CanonicalMetricRegistry definition binds authoritative expression into plan."""
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    order_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "order_value": ColumnSchema(name="order_value", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
        "discount": ColumnSchema(name="discount", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
    }
    schema = DatabaseSchema(
        database_name="test_db",
        schemas={"public": SchemaInfo(schema_name="public", tables={"orders": TableSchema(table_name="orders", schema_name="public", columns=order_cols)})},
        fingerprint="fp_canonical_metric",
    )
    retrieval = _mock_retrieval(schema, ["orders"])

    # Register canonical metric in registry
    metric_reg = CanonicalMetricRegistry()
    metric_def = MetricDefinition(
        metric_id="net_revenue",
        name="net_revenue",
        display_name="Net Revenue",
        expression="SUM(orders.order_value)",
        aggregation=MetricType.SUM,
        source_entity="orders",
        source_column="order_value",
        synonyms=["net revenue", "net sales"],
        tenant_id=tenant_id,
        knowledgebase_id=kb_id,
    )
    metric_reg.register_metric(metric_def)

    # Resolve via SemanticResolver
    resolver = SemanticResolver(metric_registry=metric_reg)
    sem_res = resolver.resolve(
        query="What is the net revenue?",
        tenant_id=tenant_id,
        knowledgebase_id=kb_id,
        schema_version=schema.fingerprint,
    )

    assert sem_res.resolved_metric is not None
    assert sem_res.resolved_metric.metric_id == "net_revenue"

    # Plan with semantic context
    plan = QueryPlanner.plan(
        user_query="What is the net revenue?",
        database_knowledgebase_id=kb_id,
        canonical_schema=schema,
        retrieval_result=retrieval,
        semantic_context=sem_res,
        tenant_id=tenant_id,
    )

    assert plan.confidence > 0.0
    assert len(plan.projections) == 1
    assert plan.projections[0].column_name == "order_value"
    assert plan.projections[0].aggregation == AggregateFunction.SUM


# ==============================================================================
# 6. Ambiguous metric request exposes ambiguity or fails closed
# ==============================================================================
def test_6_ambiguous_metric_request_fails_closed_or_exposes_ambiguity():
    """When gross_sales and net_sales exist and query is 'total sales' without distinction, system does not guess."""
    sales_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "gross_sales": ColumnSchema(name="gross_sales", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
        "net_sales": ColumnSchema(name="net_sales", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
    }
    schema = DatabaseSchema(
        database_name="test_db",
        schemas={"public": SchemaInfo(schema_name="public", tables={"sales": TableSchema(table_name="sales", schema_name="public", columns=sales_cols)})},
        fingerprint="fp_ambiguous_sales",
    )
    retrieval = _mock_retrieval(schema, ["sales"])

    query = "What are the total sales?"
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )

    # Multiple equally plausible columns matching 'sales' without distinguishing evidence:
    # System must decline deterministic compilation rather than silently picking one.
    assert plan.confidence == 0.0 or len(plan.projections) == 0, (
        f"Planner silently guessed one sales column among equally plausible candidates: {plan.projections}"
    )


# ==============================================================================
# 7. Renamed schema with unfamiliar names (txns.val) resolved via semantic evidence
# ==============================================================================
def test_7_renamed_tables_and_columns_with_semantic_evidence():
    """Table txns with column val (no 'order', 'revenue', 'amount') resolves via semantic metadata / metric registry."""
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    txn_cols = {
        "tx_id": ColumnSchema(name="tx_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "acct_id": ColumnSchema(name="acct_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer"),
        "val": ColumnSchema(name="val", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric", comment="Transaction revenue in USD"),
    }
    schema = DatabaseSchema(
        database_name="test_db",
        schemas={"public": SchemaInfo(schema_name="public", tables={"txns": TableSchema(table_name="txns", schema_name="public", columns=txn_cols)})},
        fingerprint="fp_renamed_txns",
    )
    retrieval = _mock_retrieval(schema, ["txns"])

    # Register semantic metric definition for this custom schema
    metric_reg = CanonicalMetricRegistry()
    metric_def = MetricDefinition(
        metric_id="revenue",
        name="revenue",
        display_name="Total Revenue",
        expression="SUM(txns.val)",
        aggregation=MetricType.SUM,
        source_entity="txns",
        source_column="val",
        synonyms=["revenue", "sales", "turnover"],
        tenant_id=tenant_id,
        knowledgebase_id=kb_id,
    )
    metric_reg.register_metric(metric_def)

    resolver = SemanticResolver(metric_registry=metric_reg)
    sem_res = resolver.resolve(
        query="What is the total revenue?",
        tenant_id=tenant_id,
        knowledgebase_id=kb_id,
        schema_version=schema.fingerprint,
    )

    plan = QueryPlanner.plan(
        user_query="What is the total revenue?",
        database_knowledgebase_id=kb_id,
        canonical_schema=schema,
        retrieval_result=retrieval,
        semantic_context=sem_res,
        tenant_id=tenant_id,
    )

    assert plan.confidence > 0.0
    assert len(plan.projections) == 1
    assert plan.projections[0].column_name == "val"
    assert plan.projections[0].aggregation == AggregateFunction.SUM


# ==============================================================================
# 8. Tenant isolation: Tenant A's metric metadata never influences Tenant B
# ==============================================================================
def test_8_tenant_isolation_metric_resolution():
    """Metric metadata registered by Tenant A must never be used or visible to Tenant B."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    kb_a = uuid.uuid4()
    kb_b = uuid.uuid4()

    metric_reg = CanonicalMetricRegistry()
    # Tenant A registers custom metric mapping "revenue" -> txns.val
    metric_reg.register_metric(
        MetricDefinition(
            metric_id="tenant_a_rev",
            name="revenue",
            display_name="Tenant A Revenue",
            expression="SUM(txns.val)",
            aggregation=MetricType.SUM,
            source_entity="txns",
            source_column="val",
            synonyms=["revenue"],
            tenant_id=tenant_a,
            knowledgebase_id=kb_a,
        )
    )

    # Tenant B tries to resolve "revenue"
    resolver = SemanticResolver(metric_registry=metric_reg)
    sem_res_b = resolver.resolve(
        query="What is the total revenue?",
        tenant_id=tenant_b,
        knowledgebase_id=kb_b,
        schema_version="fp_tenant_b",
    )

    # Tenant B must NOT have resolved Tenant A's metric
    assert sem_res_b.resolved_metric is None, "Tenant B leaked Tenant A's metric definition!"


# ==============================================================================
# 9. Non-revenue metric request: legitimate filters and aggregations remain intact
# ==============================================================================
def test_9_non_revenue_metric_filters_and_aggregations_intact():
    """Non-revenue query preserves legitimate filter (status='active') and aggregation (salary)."""
    emp_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "salary": ColumnSchema(name="salary", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
        "status": ColumnSchema(name="status", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
        "department_id": ColumnSchema(name="department_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer"),
    }
    schema = DatabaseSchema(
        database_name="test_db",
        schemas={"public": SchemaInfo(schema_name="public", tables={"employees": TableSchema(table_name="employees", schema_name="public", columns=emp_cols)})},
        fingerprint="fp_employees",
    )
    retrieval = _mock_retrieval(schema, ["employees"])
    query = "What is the average salary of employees where status = 'active'?"

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )

    assert plan.confidence > 0.0
    # Aggregation on salary
    assert len(plan.projections) == 1
    assert plan.projections[0].column_name == "salary"
    assert plan.projections[0].aggregation == AggregateFunction.AVG
    # Legitimate filter on status='active'
    status_preds = [p for p in plan.predicates if p.column_name == "status"]
    assert len(status_preds) >= 1
    assert "active" in str(status_preds[0].value).lower()


# ==============================================================================
# 10. Regression test confirming STEP 7C.2 behavior: overall revenue
# ==============================================================================
def test_10_overall_revenue_regression_no_phantom_filter_or_join():
    """'What is the overall order revenue?' must resolve revenue without phantom entity filter or joins."""
    order_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "customer_id": ColumnSchema(name="customer_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer"),
        "total_amount": ColumnSchema(name="total_amount", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
        "order_date": ColumnSchema(name="order_date", data_type=ColumnDataType.TIMESTAMP, raw_data_type="timestamp"),
    }
    prod_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
    }
    schema = DatabaseSchema(
        database_name="test_db",
        schemas={"public": SchemaInfo(schema_name="public", tables={
            "orders": TableSchema(table_name="orders", schema_name="public", columns=order_cols),
            "products": TableSchema(table_name="products", schema_name="public", columns=prod_cols),
        })},
        fingerprint="fp_regression_overall",
    )
    retrieval = _mock_retrieval(schema, ["orders", "products"])
    query = "What is the overall order revenue?"

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )

    # 1. No phantom predicate containing 'overall'
    phantom_preds = [p for p in plan.predicates if "overall" in str(p.value).lower()]
    assert len(phantom_preds) == 0, f"Phantom predicate detected: {phantom_preds}"

    # 2. No unrelated join to products
    plan_tables = {t.table_name for t in plan.tables}
    assert "products" not in plan_tables

    # 3. Correct revenue projection
    assert len(plan.projections) == 1
    assert plan.projections[0].column_name == "total_amount"
    assert plan.projections[0].aggregation == AggregateFunction.SUM
