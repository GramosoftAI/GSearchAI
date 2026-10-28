"""STEP 7C.3.4: Deterministic Temporal Propagation Unit Tests

Validates all 10 required temporal planning scenarios:
Test 1 — last month: TimeRange resolves to September 2026, consumed by planner into canonical predicates, compilable deterministically.
Test 2 — today: Existing behavior remains deterministic with CURRENT_DATE.
Test 3 — yesterday: Existing behavior remains deterministic with CURRENT_DATE - INTERVAL '1 day'.
Test 4 — this week: Existing behavior remains deterministic with DATE_TRUNC('week', CURRENT_DATE).
Test 5 — this month: Existing behavior remains deterministic with DATE_TRUNC('month', CURRENT_DATE).
Test 6 — last week: Existing behavior remains deterministic with DATE_TRUNC('week', CURRENT_DATE - INTERVAL '1 week').
Test 7 — recurring Friday: Friday remains EXTRACT_DOW = 5 and is NOT converted into a date range.
Test 8 — dynamic date column: Schema with non-order_date column (e.g. invoice_date, payment_date) dynamically resolves date column without hardcoding.
Test 9 — no temporal expression: Normal query without temporal intent receives no artificial date filter.
Test 10 — no duplicate predicates: Plan contains no duplicate or conflicting temporal predicates.
"""

import uuid
from datetime import date
import pytest

from app.modules.database_knowledgebase.knowledge.retrieval.analyzer import QuestionAnalyzer, TimeRange, extract_time_range
from app.modules.database_knowledgebase.knowledge.retrieval.context_pack import ContextPack
from app.modules.database_knowledgebase.planning.planner import QueryPlanner
from app.modules.database_knowledgebase.planning.models import IntentType
from app.modules.database_knowledgebase.retrieval.retriever import SchemaRetrievalResult
from app.modules.database_knowledgebase.retrieval.scorer import TableRetrievalScore
from app.modules.database_knowledgebase.schemas.canonical import (
    DatabaseSchema,
    SchemaInfo,
    TableSchema,
    ColumnSchema,
    ColumnDataType,
)
from app.modules.database_knowledgebase.sql_generator.repair import SQLRepairEngine
from app.modules.database_knowledgebase.sql_generator.generator import CandidateSQLGenerator


REF_DATE = date(2026, 10, 20)


def _build_orders_schema() -> DatabaseSchema:
    order_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "customer_id": ColumnSchema(name="customer_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer"),
        "order_date": ColumnSchema(name="order_date", data_type=ColumnDataType.TIMESTAMP, raw_data_type="timestamp"),
        "total_amount": ColumnSchema(name="total_amount", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
    }
    customer_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "name": ColumnSchema(name="name", data_type=ColumnDataType.VARCHAR, raw_data_type="varchar"),
    }
    return DatabaseSchema(
        database_name="golden_db",
        schemas={
            "public": SchemaInfo(
                schema_name="public",
                tables={
                    "orders": TableSchema(table_name="orders", schema_name="public", columns=order_cols),
                    "customers": TableSchema(table_name="customers", schema_name="public", columns=customer_cols),
                },
            )
        },
        fingerprint="fp_orders_test",
    )


def _build_invoices_schema() -> DatabaseSchema:
    invoice_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "customer_id": ColumnSchema(name="customer_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer"),
        "invoice_date": ColumnSchema(name="invoice_date", data_type=ColumnDataType.DATE, raw_data_type="date"),
        "created_at": ColumnSchema(name="created_at", data_type=ColumnDataType.TIMESTAMP, raw_data_type="timestamp"),
        "amount": ColumnSchema(name="amount", data_type=ColumnDataType.NUMERIC, raw_data_type="numeric"),
    }
    return DatabaseSchema(
        database_name="invoices_db",
        schemas={
            "public": SchemaInfo(
                schema_name="public",
                tables={
                    "invoices": TableSchema(table_name="invoices", schema_name="public", columns=invoice_cols),
                },
            )
        },
        fingerprint="fp_invoices_test",
    )


def _mock_retrieval(schema: DatabaseSchema, table_names: list[str], time_range: TimeRange = None) -> SchemaRetrievalResult:
    tables = [schema.schemas["public"].tables[n] for n in table_names]
    scores = {n: TableRetrievalScore(table_name=n, final_score=1.0) for n in table_names}
    context_pack = None
    if time_range:
        context_pack = ContextPack(
            question="mock question",
            tables=[{"name": n, "description": f"Table {n}", "score": 1.0} for n in table_names],
            time_range={"start_date": time_range.start_date, "end_date": time_range.end_date, "expression": time_range.expression},
        )
    return SchemaRetrievalResult(
        database_name=schema.database_name,
        database_type="postgresql",
        schema_version=schema.fingerprint or "mock_fp",
        retrieved_tables=tables,
        retrieval_scores=scores,
        join_paths=[],
        overall_confidence=1.0,
        untrusted_boundary_text="MOCK",
        context_pack=context_pack,
    )


# ==============================================================================
# Test 1 — last month
# ==============================================================================
def test_1_last_month():
    """TimeRange resolves to September 2026 for ref date 2026-10-20, flows into planner, and compiles deterministically."""
    query = "Show orders created last month."
    tr = extract_time_range(query, REF_DATE)
    assert tr is not None
    assert tr.start_date == "2026-09-01"
    assert tr.end_date == "2026-09-30"
    assert tr.expression == "last month"

    schema = _build_orders_schema()
    retrieval = _mock_retrieval(schema, ["orders"], time_range=tr)

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
        reference_date=REF_DATE,
    )

    # Verify canonical temporal range
    assert len(plan.predicates) == 2
    preds_by_op = {p.operator: p for p in plan.predicates}
    assert ">=" in preds_by_op
    assert "<" in preds_by_op
    assert preds_by_op[">="].column_name == "order_date"
    assert preds_by_op[">="].value == "2026-09-01"
    assert preds_by_op["<"].column_name == "order_date"
    assert preds_by_op["<"].value == "2026-10-01"

    # Deterministic compilation gate
    can_compile = SQLRepairEngine.can_compile_plan_deterministically(plan, user_query=query)
    assert can_compile is True

    # Compile SQL
    sql = CandidateSQLGenerator.compile_plan_to_sql(plan, dialect="postgresql")
    assert "order_date >= '2026-09-01'" in sql
    assert "order_date < '2026-10-01'" in sql
    assert "CURRENT_TIMESTAMP" not in sql
    assert "INTERVAL '1 MONTH'" not in sql


# ==============================================================================
# Test 2 — today
# ==============================================================================
def test_2_today():
    """Verify 'today' remains deterministic using CURRENT_DATE."""
    query = "Show orders created today."
    schema = _build_orders_schema()
    tr = extract_time_range(query, REF_DATE)
    retrieval = _mock_retrieval(schema, ["orders"], time_range=tr)

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
        reference_date=REF_DATE,
    )

    assert any("CURRENT_DATE" in str(p.value) for p in plan.predicates)
    assert SQLRepairEngine.can_compile_plan_deterministically(plan, user_query=query) is True


# ==============================================================================
# Test 3 — yesterday
# ==============================================================================
def test_3_yesterday():
    """Verify 'yesterday' remains deterministic using CURRENT_DATE - INTERVAL '1 day'."""
    query = "Show orders created yesterday."
    schema = _build_orders_schema()
    tr = extract_time_range(query, REF_DATE)
    retrieval = _mock_retrieval(schema, ["orders"], time_range=tr)

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
        reference_date=REF_DATE,
    )

    assert any("CURRENT_DATE - INTERVAL '1 day'" in str(p.value) for p in plan.predicates)
    assert SQLRepairEngine.can_compile_plan_deterministically(plan, user_query=query) is True


# ==============================================================================
# Test 4 — this week
# ==============================================================================
def test_4_this_week():
    """Verify 'this week' remains deterministic using DATE_TRUNC('week', CURRENT_DATE)."""
    query = "Show orders created this week."
    schema = _build_orders_schema()
    retrieval = _mock_retrieval(schema, ["orders"])

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
        reference_date=REF_DATE,
    )

    assert any("DATE_TRUNC('week', CURRENT_DATE)" in str(p.value) for p in plan.predicates)
    assert SQLRepairEngine.can_compile_plan_deterministically(plan, user_query=query) is True


# ==============================================================================
# Test 5 — this month
# ==============================================================================
def test_5_this_month():
    """Verify 'this month' remains deterministic using DATE_TRUNC('month', CURRENT_DATE)."""
    query = "Show orders created this month."
    schema = _build_orders_schema()
    tr = extract_time_range(query, REF_DATE)
    retrieval = _mock_retrieval(schema, ["orders"], time_range=tr)

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
        reference_date=REF_DATE,
    )

    assert any("DATE_TRUNC('month', CURRENT_DATE)" in str(p.value) for p in plan.predicates)
    assert SQLRepairEngine.can_compile_plan_deterministically(plan, user_query=query) is True


# ==============================================================================
# Test 6 — last week
# ==============================================================================
def test_6_last_week():
    """Verify 'last week' remains deterministic using DATE_TRUNC('week', CURRENT_DATE - INTERVAL '1 week')."""
    query = "Show orders created last week."
    schema = _build_orders_schema()
    tr = extract_time_range(query, REF_DATE)
    retrieval = _mock_retrieval(schema, ["orders"], time_range=tr)

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
        reference_date=REF_DATE,
    )

    assert any("DATE_TRUNC('week', CURRENT_DATE - INTERVAL '1 week')" in str(p.value) for p in plan.predicates)
    assert SQLRepairEngine.can_compile_plan_deterministically(plan, user_query=query) is True


# ==============================================================================
# Test 7 — recurring Friday
# ==============================================================================
def test_7_recurring_friday():
    """Verify Friday remains EXTRACT_DOW = 5 and is NOT converted to continuous date range."""
    query = "Show attendance on Friday."
    att_cols = {
        "id": ColumnSchema(name="id", data_type=ColumnDataType.INTEGER, raw_data_type="integer", is_primary_key=True),
        "employee_id": ColumnSchema(name="employee_id", data_type=ColumnDataType.INTEGER, raw_data_type="integer"),
        "attendance_date": ColumnSchema(name="attendance_date", data_type=ColumnDataType.DATE, raw_data_type="date"),
    }
    schema = DatabaseSchema(
        database_name="att_db",
        schemas={"public": SchemaInfo(schema_name="public", tables={"attendance": TableSchema(table_name="attendance", schema_name="public", columns=att_cols)})},
        fingerprint="fp_att",
    )
    retrieval = _mock_retrieval(schema, ["attendance"])

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
        reference_date=REF_DATE,
    )

    dow_preds = [p for p in plan.predicates if p.operator == "EXTRACT_DOW"]
    assert len(dow_preds) == 1
    assert dow_preds[0].value == 5
    assert dow_preds[0].column_name == "attendance_date"


# ==============================================================================
# Test 8 — dynamic date column
# ==============================================================================
def test_8_dynamic_date_column():
    """Schema where date column is invoice_date (not order_date) dynamically resolves."""
    query = "Show invoices created last month."
    tr = extract_time_range(query, REF_DATE)
    schema = _build_invoices_schema()
    retrieval = _mock_retrieval(schema, ["invoices"], time_range=tr)

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
        reference_date=REF_DATE,
    )

    assert len(plan.predicates) == 2
    # Verify invoice_date was selected over created_at
    for p in plan.predicates:
        assert p.column_name == "invoice_date"
    assert SQLRepairEngine.can_compile_plan_deterministically(plan, user_query=query) is True


# ==============================================================================
# Test 9 — no temporal expression
# ==============================================================================
def test_9_no_temporal_expression():
    """A normal query without temporal intent receives no artificial date filter."""
    query = "Show all customers."
    schema = _build_orders_schema()
    retrieval = _mock_retrieval(schema, ["customers"])

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
        reference_date=REF_DATE,
    )

    temporal_cols = {"order_date", "date", "created_at"}
    temporal_preds = [p for p in plan.predicates if p.column_name in temporal_cols]
    assert len(temporal_preds) == 0


# ==============================================================================
# Test 10 — no duplicate predicates
# ==============================================================================
def test_10_no_duplicate_predicates():
    """If both TimeRange and intent analyzer process temporal expressions, only one canonical condition remains."""
    query = "Show orders created today."
    tr = TimeRange(start_date="2026-10-20", end_date="2026-10-20", expression="today")
    schema = _build_orders_schema()
    retrieval = _mock_retrieval(schema, ["orders"], time_range=tr)

    plan = QueryPlanner.plan(
        user_query=query,
        database_knowledgebase_id=uuid.uuid4(),
        canonical_schema=schema,
        retrieval_result=retrieval,
        tenant_id=uuid.uuid4(),
        reference_date=REF_DATE,
    )

    # Confirm no duplicate >= or < on order_date
    seen_ops = []
    for p in plan.predicates:
        if p.column_name == "order_date":
            seen_ops.append(p.operator)
    # Exactly one >= and one < (for half-open today), no duplicate >=
    assert seen_ops.count(">=") == 1
    assert seen_ops.count("<") == 1
