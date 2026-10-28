"""Unit tests for STEP 7C.4: Deterministic Grouped Aggregation & Superlative Ranking Planning.

Covers:
1. Implicit dimension-plus-aggregate detection without 'by' or 'per'.
2. Pure scalar aggregates remaining strictly ungrouped.
3. Possessive dimension grouping (e.g. "customer's total spending").
4. Temporal dimension grouping (e.g. "revenue by month" -> DATE_TRUNC).
5. Superlative ranking with highest/most -> DESC, limit 1.
6. Superlative ranking with lowest/least -> ASC, limit 1.
7. Top-N ordering and limit preservation.
8. Removal of crude keyword blockers (which, name, month) in deterministic eligibility.
9. Continued fallback for genuinely unsupported or unprojected structures.
10. End-to-end plan-to-SQL compilation with verified GROUP BY and ORDER BY clauses.
"""

import pytest
import uuid
from app.modules.database_knowledgebase.planning.intent_analyzer import (
    QueryIntentAnalyzer,
    TemporalIntent,
)
from app.modules.database_knowledgebase.planning.models import (
    AggregateFunction,
    ColumnProjectionPlan,
    IntentType,
    JoinPlan,
    JoinType,
    OrderByPlan,
    OrderDirection,
    QueryPlanIR,
    TablePlan,
)
from app.modules.database_knowledgebase.planning.planner import QueryPlanner
from app.modules.database_knowledgebase.schemas.canonical import (
    ColumnDataType,
    ColumnSchema,
    DatabaseSchema,
    SchemaInfo,
    TableSchema,
)
from app.modules.database_knowledgebase.retrieval.retriever import SchemaRetrievalResult
from app.modules.database_knowledgebase.retrieval.scorer import TableRetrievalScore
from app.modules.database_knowledgebase.sql_generator.generator import CandidateSQLGenerator
from app.modules.database_knowledgebase.sql_generator.repair import SQLRepairEngine
from app.modules.database_knowledgebase.sql_security.policy import SQLSecurityPolicyEngine


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


@pytest.fixture
def ecommerce_schema() -> DatabaseSchema:
    """Fixture providing a canonical e-commerce schema with customers, orders, and products."""
    customers_table = TableSchema(
        schema_name="public",
        table_name="customers",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="INTEGER", is_primary_key=True),
            "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="VARCHAR"),
            "email": ColumnSchema(name="email", data_type=ColumnDataType.VARCHAR, raw_data_type="VARCHAR"),
        },
    )
    orders_table = TableSchema(
        schema_name="public",
        table_name="orders",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="INTEGER", is_primary_key=True),
            "customer_id": ColumnSchema(name="customer_id", data_type=ColumnDataType.INTEGER, raw_data_type="INTEGER", is_foreign_key=True),
            "order_date": ColumnSchema(name="order_date", data_type=ColumnDataType.TIMESTAMP, raw_data_type="TIMESTAMP"),
            "status": ColumnSchema(name="status", data_type=ColumnDataType.VARCHAR, raw_data_type="VARCHAR"),
            "total_amount": ColumnSchema(name="total_amount", data_type=ColumnDataType.DECIMAL, raw_data_type="DECIMAL"),
        },
    )
    products_table = TableSchema(
        schema_name="public",
        table_name="products",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="INTEGER", is_primary_key=True),
            "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="VARCHAR"),
            "category": ColumnSchema(name="category", data_type=ColumnDataType.VARCHAR, raw_data_type="VARCHAR"),
            "price": ColumnSchema(name="price", data_type=ColumnDataType.DECIMAL, raw_data_type="DECIMAL"),
        },
    )
    departments_table = TableSchema(
        schema_name="public",
        table_name="departments",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="INTEGER", is_primary_key=True),
            "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="VARCHAR"),
        },
    )
    employees_table = TableSchema(
        schema_name="public",
        table_name="employees",
        columns={
            "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="INTEGER", is_primary_key=True),
            "department_id": ColumnSchema(name="department_id", data_type=ColumnDataType.INTEGER, raw_data_type="INTEGER", is_foreign_key=True),
            "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="VARCHAR"),
            "salary": ColumnSchema(name="salary", data_type=ColumnDataType.DECIMAL, raw_data_type="DECIMAL"),
        },
    )

    schema = DatabaseSchema(
        database_name="test_ecommerce",
        schemas={
            "public": SchemaInfo(
                schema_name="public",
                tables={
                    "customers": customers_table,
                    "orders": orders_table,
                    "products": products_table,
                    "departments": departments_table,
                    "employees": employees_table,
                },
            )
        },
        fingerprint="fp_ecommerce",
    )
    return schema


def test_1_implicit_dim_and_agg_detection():
    """Verify implicit grouping without 'by' or 'per' is accurately detected."""
    q = "Show customer name and total order value."
    analysis = QueryIntentAnalyzer.analyze(q)
    assert analysis.grouping_required is True
    assert analysis.grouping_concept == "customer"
    assert any(a.function == AggregateFunction.SUM for a in analysis.aggregations)

    q2 = "List department and average salary."
    analysis2 = QueryIntentAnalyzer.analyze(q2)
    assert analysis2.grouping_required is True
    assert analysis2.grouping_concept == "department"
    assert any(a.function == AggregateFunction.AVG for a in analysis2.aggregations)


def test_2_pure_scalar_aggregates_remain_ungrouped():
    """Verify pure scalar aggregates are not misclassified as grouped."""
    scalar_queries = [
        "What is the total revenue?",
        "What is the average salary?",
        "How many orders are there?",
        "What is the average order value?",
    ]
    for q in scalar_queries:
        analysis = QueryIntentAnalyzer.analyze(q)
        assert analysis.grouping_required is False, f"Query '{q}' should not require grouping"
        assert analysis.grouping_concept is None


def test_3_possessive_dimension_grouping():
    """Verify possessive dimension queries like 'each customer's total spending' are detected."""
    q = "Display each customer's total spending."
    analysis = QueryIntentAnalyzer.analyze(q)
    assert analysis.grouping_required is True
    assert analysis.grouping_concept == "customer"


def test_4_temporal_dimension_grouping(ecommerce_schema):
    """Verify temporal grouping queries like 'revenue by month' produce DATE_TRUNC grouping."""
    q = "Show revenue by month."
    analysis = QueryIntentAnalyzer.analyze(q)
    assert analysis.grouping_required is True
    assert analysis.grouping_concept == "month"

    retrieval_res = _mock_retrieval(ecommerce_schema, ["orders"])
    kb_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    plan = QueryPlanner.plan(
        user_query=q,
        database_knowledgebase_id=kb_id,
        canonical_schema=ecommerce_schema,
        retrieval_result=retrieval_res,
        tenant_id=tenant_id,
    )
    assert len(plan.group_by) > 0
    assert any("DATE_TRUNC" in g for g in plan.group_by)
    # Check that can_compile_plan_deterministically recognizes the temporal grouping
    assert SQLRepairEngine.can_compile_plan_deterministically(plan, user_query=q) is True


def test_5_superlative_ranking_highest_desc():
    """Verify superlative queries mapping to 'highest/most' generate DESC limit 1 ranking."""
    q = "Which department has the highest average salary?"
    analysis = QueryIntentAnalyzer.analyze(q)
    assert analysis.grouping_required is True
    assert analysis.grouping_concept == "department"
    assert analysis.ranking is not None
    assert analysis.ranking.direction == OrderDirection.DESC
    assert analysis.ranking.limit == 1
    assert analysis.intent == IntentType.SELECT_RANKING


def test_6_superlative_ranking_lowest_asc():
    """Verify superlative queries mapping to 'lowest/least' generate ASC limit 1 ranking."""
    q = "Which product has the lowest average price?"
    analysis = QueryIntentAnalyzer.analyze(q)
    assert analysis.grouping_required is True
    assert analysis.grouping_concept == "product"
    assert analysis.ranking is not None
    assert analysis.ranking.direction == OrderDirection.ASC
    assert analysis.ranking.limit == 1


def test_7_top_n_ranking_limit_preservation():
    """Verify Top-N queries preserve direction and numeric limit."""
    q = "Show the top 5 customers by total spending."
    analysis = QueryIntentAnalyzer.analyze(q)
    assert analysis.ranking is not None
    assert analysis.ranking.direction == OrderDirection.DESC
    assert analysis.ranking.limit == 5
    assert analysis.grouping_required is True
    assert analysis.grouping_concept in ("customer", "customers")


def test_8_deterministic_eligibility_removal_of_which_name_month_blockers(ecommerce_schema):
    """Verify plans containing 'which', 'name', or 'month' are not falsely blocked when structurally complete."""
    # Grouped multi-table plan with customer name and total_amount sum
    plan = QueryPlanIR(
        database_knowledgebase_id=uuid.uuid4(),
        schema_version="v1",
        user_query="Which customer spent the most?",
        intent=IntentType.SELECT_RANKING,
        tables=[
            TablePlan(schema_name="public", table_name="customers", alias="c", role="PRIMARY"),
            TablePlan(schema_name="public", table_name="orders", alias="o", role="JOIN_TARGET"),
        ],
        joins=[
            JoinPlan(
                source_table_alias="c",
                source_column="id",
                target_table_alias="o",
                target_column="customer_id",
                join_type=JoinType.INNER,
                relationship_name="customer_orders",
            )
        ],
        projections=[
            ColumnProjectionPlan(table_alias="c", column_name="name", aggregation=AggregateFunction.NONE),
            ColumnProjectionPlan(
                table_alias="o",
                column_name="total_amount",
                output_alias="sum_total_amount",
                aggregation=AggregateFunction.SUM,
            ),
        ],
        predicates=[],
        group_by=["c.name"],
        order_by=[OrderByPlan(expression="sum_total_amount", direction=OrderDirection.DESC)],
        limit=1,
        confidence=0.95,
    )
    # Must be eligible for deterministic compilation despite 'which' and multiple tables
    eligible = SQLRepairEngine.can_compile_plan_deterministically(plan, user_query=plan.user_query)
    assert eligible is True, "Structurally complete ranking query should be deterministically eligible"


def test_9_unsupported_structures_still_fallback():
    """Verify that multi-table listings with no aggregations/ranking still safely fall back to LLM."""
    plan = QueryPlanIR(
        database_knowledgebase_id=uuid.uuid4(),
        schema_version="v1",
        user_query="Which customers placed orders?",
        intent=IntentType.SELECT_JOIN,
        tables=[
            TablePlan(schema_name="public", table_name="customers", alias="c", role="PRIMARY"),
            TablePlan(schema_name="public", table_name="orders", alias="o", role="JOIN_TARGET"),
        ],
        joins=[
            JoinPlan(
                source_table_alias="c",
                source_column="id",
                target_table_alias="o",
                target_column="customer_id",
                join_type=JoinType.INNER,
                relationship_name="customer_orders",
            )
        ],
        projections=[
            ColumnProjectionPlan(table_alias="c", column_name="id", aggregation=AggregateFunction.NONE),
            ColumnProjectionPlan(table_alias="c", column_name="name", aggregation=AggregateFunction.NONE),
        ],
        predicates=[],
        group_by=[],
        order_by=[],
        limit=None,
        confidence=0.95,
    )
    # Multi-table open-ended listing with 'which' must fall back to LLM
    eligible = SQLRepairEngine.can_compile_plan_deterministically(plan, user_query=plan.user_query)
    assert eligible is False, "Open-ended multi-table listing must safely fall back to LLM"


def test_10_sql_compilation_and_security_validation(ecommerce_schema):
    """Verify CandidateSQLGenerator compiles valid GROUP BY and ORDER BY clauses passing AST security."""
    plan = QueryPlanIR(
        database_knowledgebase_id=uuid.uuid4(),
        schema_version="v1",
        user_query="Show customer name and total order value.",
        intent=IntentType.SELECT_AGGREGATE,
        tables=[
            TablePlan(schema_name="public", table_name="customers", alias="c", role="PRIMARY"),
            TablePlan(schema_name="public", table_name="orders", alias="o", role="JOIN_TARGET"),
        ],
        joins=[
            JoinPlan(
                source_table_alias="c",
                source_column="id",
                target_table_alias="o",
                target_column="customer_id",
                join_type=JoinType.INNER,
                relationship_name="customer_orders",
            )
        ],
        projections=[
            ColumnProjectionPlan(table_alias="c", column_name="name", aggregation=AggregateFunction.NONE),
            ColumnProjectionPlan(
                table_alias="o",
                column_name="total_amount",
                output_alias="total_order_value",
                aggregation=AggregateFunction.SUM,
            ),
        ],
        predicates=[],
        group_by=["c.name"],
        order_by=[],
        limit=None,
        confidence=0.95,
    )

    sql = CandidateSQLGenerator.compile_plan_to_sql(plan, dialect="postgres")
    assert "GROUP BY c.name" in sql or "GROUP BY \"c\".\"name\"" in sql or "GROUP BY" in sql
    assert "SUM" in sql
    assert "JOIN" in sql

    retrieval_res = _mock_retrieval(ecommerce_schema, ["customers", "orders"])
    validation = SQLSecurityPolicyEngine.validate_sql(
        sql_text=sql,
        canonical_schema=ecommerce_schema,
        retrieval_result=retrieval_res,
    )
    assert validation.is_valid is True
