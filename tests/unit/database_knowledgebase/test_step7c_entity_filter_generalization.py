"""STEP 7C.2: Focused Regression Tests for Entity Filter Generalization

Reproduces & verifies:
1. "What is the overall order revenue?" -> no phantom '%overall%' filter, single-table orders aggregation.
2. "What is the total revenue across all orders?" -> no phantom filter, SUM(orders.total_amount).
3. "Show the overall sales total." -> no phantom filter.
4. "Show revenue grouped by year." -> DATE_TRUNC('YEAR', order_date), no phantom filter.
5. Legitimate product-name filter preserved: "Show orders for Mechanical Keyboard".
6. Legitimate customer-name filter preserved: "Show orders for Alice Johnson".
7. Aggregation with legitimate customer filter: "What is the total revenue for Alice Johnson?".
8. General quantifiers & modifiers ("overall", "entire", "complete", "general", "combined") do not become entity filters.
"""

import uuid
import pytest

from app.modules.database_knowledgebase.planning.entity_value_resolver import EntityValueResolver
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


@pytest.fixture
def ecommerce_schema() -> DatabaseSchema:
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
        "status": ColumnSchema(name="status", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
    }
    item_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "order_id": ColumnSchema(name="order_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_foreign_key=True),
        "product_id": ColumnSchema(name="product_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_foreign_key=True),
        "quantity": ColumnSchema(name="quantity", data_type=ColumnDataType.INTEGER, raw_data_type="integer"),
        "unit_price": ColumnSchema(name="unit_price", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
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
    }
    schema_info = SchemaInfo(schema_name="public", tables=tables)
    return DatabaseSchema(database_name="gsearch_golden_db", schemas={"public": schema_info}, fingerprint="fp_ecommerce_001")


def _mock_retrieval(schema: DatabaseSchema, table_names: list[str]) -> SchemaRetrievalResult:
    all_t = [schema.schemas["public"].tables[n] for n in table_names]
    scores = {n: TableRetrievalScore(table_name=n, final_score=1.0) for n in table_names}
    return SchemaRetrievalResult(
        database_name=schema.database_name,
        database_type="postgresql",
        schema_version="test-schema-v1",
        retrieved_tables=all_t,
        retrieval_scores=scores,
        join_paths=[],
        overall_confidence=1.0,
        untrusted_boundary_text="MOCK",
    )


def test_reproduce_overall_revenue_not_extracted_as_literal(ecommerce_schema):
    """Linguistic quantifiers like 'overall' must not be extracted as entity literals."""
    query = "What is the overall order revenue?"
    candidates = EntityValueResolver.extract_literal_candidates(query, canonical_schema=ecommerce_schema)
    assert "overall" not in [c.lower() for c in candidates], (
        f"Defect reproduced: 'overall' was incorrectly extracted as literal candidate: {candidates}"
    )


def test_reproduce_general_quantifiers_not_extracted_as_literals(ecommerce_schema):
    """General modifiers (overall, entire, complete, general, combined) must not become literals."""
    test_queries = [
        ("What is the entire order revenue?", "entire"),
        ("What is the complete sales total?", "complete"),
        ("What is the general revenue?", "general"),
        ("What is the combined revenue?", "combined"),
        ("Show the overall sales total.", "overall"),
    ]
    for query, word in test_queries:
        candidates = EntityValueResolver.extract_literal_candidates(query, canonical_schema=ecommerce_schema)
        assert word not in [c.lower() for c in candidates], (
            f"Defect reproduced: '{word}' was incorrectly extracted as literal candidate from '{query}': {candidates}"
        )


@pytest.mark.asyncio
async def test_reproduce_overall_order_revenue_plan_has_no_phantom_predicate(ecommerce_schema):
    """Plan for 'What is the overall order revenue?' must not inject an ILIKE '%overall%' predicate."""
    query = "What is the overall order revenue?"
    analyzer = QueryIntentAnalyzer()
    analysis = analyzer.analyze(query)

    retrieval = _mock_retrieval(ecommerce_schema, ["orders", "order_items", "products", "customers"])
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )

    # 1. Must NOT have any predicate mentioning 'overall'
    phantom_preds = [p for p in plan.predicates if "overall" in str(p.value).lower()]
    assert len(phantom_preds) == 0, f"Defect reproduced: Plan has phantom predicate: {phantom_preds}"

    # 2. Must NOT join to products
    plan_tables = {t.table_name for t in plan.tables}
    assert "products" not in plan_tables, f"Products table was pulled into order revenue query: {plan_tables}"

    # 3. Must project SUM of order total_amount
    assert plan.projections[0].column_name == "total_amount"
    assert plan.projections[0].aggregation == AggregateFunction.SUM


@pytest.mark.asyncio
async def test_total_revenue_across_all_orders_plan_clean(ecommerce_schema):
    """Plan for 'What is the total revenue across all orders?' must have no phantom filters."""
    query = "What is the total revenue across all orders?"
    analyzer = QueryIntentAnalyzer()
    analysis = analyzer.analyze(query)

    retrieval = _mock_retrieval(ecommerce_schema, ["orders", "order_items", "products"])
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )

    assert len(plan.predicates) == 0
    assert {t.table_name for t in plan.tables} == {"orders"}
    assert plan.projections[0].column_name == "total_amount"
    assert plan.projections[0].aggregation == AggregateFunction.SUM


@pytest.mark.asyncio
async def test_revenue_grouped_by_year_plan(ecommerce_schema):
    """Plan for 'Show revenue grouped by year.' must preserve YEAR truncation without phantom filters."""
    query = "Show revenue grouped by year."
    analyzer = QueryIntentAnalyzer()
    analysis = analyzer.analyze(query)

    retrieval = _mock_retrieval(ecommerce_schema, ["orders"])
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )

    assert len(plan.predicates) == 0
    # Must group by YEAR
    has_year_group = any("YEAR" in str(g).upper() for g in plan.group_by)
    assert has_year_group, f"Expected YEAR in group_by: {plan.group_by}"


@pytest.mark.asyncio
async def test_legitimate_customer_name_filter_preserved(ecommerce_schema):
    """Legitimate customer filter must be preserved when explicitly provided."""
    query = "Show orders for Alice Johnson"
    analyzer = QueryIntentAnalyzer()
    analysis = analyzer.analyze(query)

    retrieval = _mock_retrieval(ecommerce_schema, ["orders", "customers"])
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
        resolved_entities=[{"type": "user", "id": 1, "name": "Alice Johnson", "table": "customers"}],
    )

    # Must retain customer filter
    plan_tables = {t.table_name for t in plan.tables}
    assert "customers" in plan_tables
    assert "orders" in plan_tables
    # Check that a predicate exists for Alice Johnson (either by id or name)
    alice_preds = [
        p for p in plan.predicates
        if "alice" in str(p.value).lower() or p.value in (1, "1", [1], ["1"])
    ]
    assert len(alice_preds) > 0, f"Expected customer predicate for Alice Johnson, got: {plan.predicates}"


def test_legitimate_product_name_filter_preserved(ecommerce_schema):
    """Legitimate product filter must be preserved when user explicitly queries a product."""
    query = "Show orders for Ergonomic Mechanical Keyboard"
    analyzer = QueryIntentAnalyzer()
    analysis = analyzer.analyze(query)

    retrieval = _mock_retrieval(ecommerce_schema, ["orders", "order_items", "products"])
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
        resolved_entities=[{"type": "product", "id": 1, "name": "Ergonomic Mechanical Keyboard", "table": "products"}],
    )

    plan_tables = {t.table_name for t in plan.tables}
    assert "products" in plan_tables
    kb_preds = [
        p for p in plan.predicates
        if "keyboard" in str(p.value).lower() or p.value in (1, "1", [1], ["1"])
    ]
    assert len(kb_preds) > 0, f"Expected product predicate for Ergonomic Mechanical Keyboard, got: {plan.predicates}"


def test_aggregation_with_real_entity_filter_preserved(ecommerce_schema):
    """Aggregation query with legitimate customer filter must preserve both filter and aggregation."""
    query = "What is the total revenue for Alice Johnson?"
    analyzer = QueryIntentAnalyzer()
    analysis = analyzer.analyze(query)

    retrieval = _mock_retrieval(ecommerce_schema, ["orders", "customers"])
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
        resolved_entities=[{"type": "user", "id": 1, "name": "Alice Johnson", "table": "customers"}],
    )

    # Both customer filter AND sum(total_amount) must exist
    plan_tables = {t.table_name for t in plan.tables}
    assert "customers" in plan_tables
    assert "orders" in plan_tables
    alice_preds = [
        p for p in plan.predicates
        if "alice" in str(p.value).lower() or p.value in (1, "1", [1], ["1"])
    ]
    assert len(alice_preds) > 0, f"Customer filter missing: {plan.predicates}"
    assert any(p.column_name == "total_amount" and p.aggregation == AggregateFunction.SUM for p in plan.projections)


@pytest.mark.asyncio
async def test_show_the_overall_sales_total_plan(ecommerce_schema):
    """'Show the overall sales total.' must produce clean aggregation without phantom predicates."""
    query = "Show the overall sales total."
    analyzer = QueryIntentAnalyzer()
    analysis = analyzer.analyze(query)

    retrieval = _mock_retrieval(ecommerce_schema, ["orders", "order_items", "products"])
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
    )

    # Must NOT have any phantom predicate
    phantom_preds = [p for p in plan.predicates if "overall" in str(p.value).lower()]
    assert len(phantom_preds) == 0, f"Phantom predicate found: {phantom_preds}"
    assert "products" not in {t.table_name for t in plan.tables}
    assert any(p.column_name == "total_amount" and p.aggregation == AggregateFunction.SUM for p in plan.projections)


@pytest.mark.asyncio
async def test_unresolved_ambiguous_entity_handling(ecommerce_schema):
    """When an entity is ambiguous (multiple IDs), planner must bind IN (id1, id2, ...) rather than guessing."""
    query = "Show orders created by John Doe."
    analyzer = QueryIntentAnalyzer()
    analysis = analyzer.analyze(query)

    retrieval = _mock_retrieval(ecommerce_schema, ["orders", "customers"])
    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=ecommerce_schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
        resolved_entities=[
            {
                "type": "user",
                "name": "John Doe",
                "ids": [101, 102, 103],
                "table": "customers",
                "pk_column": "id",
            }
        ],
    )

    # Must have an IN predicate preserving all 3 candidate IDs rather than guessing one
    in_preds = [p for p in plan.predicates if p.operator == "IN" and p.column_name == "id"]
    assert len(in_preds) == 1, f"Expected IN predicate with ambiguous IDs, got: {plan.predicates}"
    assert set(in_preds[0].value) == {101, 102, 103}

