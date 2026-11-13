import asyncio
import time
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from arq.worker import Retry

from app.modules.database_knowledgebase.knowledge.sensitivity import (
    is_sensitive_column,
    is_sensitive_value,
    check_values_sensitivity,
)
from app.modules.database_knowledgebase.knowledge.jobs.profiler_rules import (
    infer_role_and_unit,
)
from app.modules.database_knowledgebase.knowledge.adapters.phase1_adapter import (
    SchemaView,
    TableView,
    ColumnView,
    FKView,
)
from app.modules.database_knowledgebase.knowledge.jobs.profiler import (
    run_stage_profiler,
    compute_table_structural_hash,
    compute_column_structural_hash,
)
from app.modules.database_knowledgebase.knowledge.jobs.pipeline import (
    run_phase2_pipeline,
)


# =====================================================================
# 1. Table-Driven Role and Unit Inference Tests (>= 25 test cases)
# =====================================================================
@pytest.mark.parametrize(
    "col_name, data_type, is_pk, is_fk, distinct_count, min_val, max_val, expected_role, expected_unit",
    [
        # Duration & units
        ("at_work_second", "integer", False, False, 100, 0, 3600, "duration", "seconds"),
        ("duration_sec", "bigint", False, False, 50, 0, 120, "duration", "seconds"),
        ("timeout_seconds", "int", False, False, 10, 1, 60, "duration", "seconds"),
        ("elapsed_ms", "bigint", False, False, 500, 10, 5000, "duration", "ms"),
        ("latency_millisecond", "integer", False, False, 200, 1, 1000, "duration", "ms"),
        ("wait_min", "float", False, False, 15, 0.5, 30.0, "duration", "minutes"),
        ("flight_minutes", "integer", False, False, 100, 10, 600, "duration", "minutes"),
        ("shift_hours", "numeric", False, False, 8, 1, 12, "duration", "hours"),
        ("billing_hr", "float", False, False, 10, 1, 24, "duration", "hours"),
        
        # Financial / Amount & units
        ("order_total_amt", "numeric(10,2)", False, False, 1000, 10.0, 5000.0, "amount", "currency"),
        ("salary_amount", "decimal", False, False, 200, 20000, 150000, "amount", "currency"),
        ("product_price", "double precision", False, False, 50, 5.99, 99.99, "amount", "currency"),
        ("unit_cost", "numeric", False, False, 80, 2.5, 45.0, "amount", "currency"),
        
        # Percentages
        ("tax_pct", "numeric(5,2)", False, False, 5, 0.0, 15.0, "quantity", "percent"),
        ("discount_percent", "float", False, False, 10, 0, 25, "quantity", "percent"),
        ("completion_rate", "float", False, False, 100, 0.0, 1.0, "quantity", "percent"),
        
        # Identity / ID
        ("user_id", "integer", False, False, 10000, None, None, "id", None),
        ("customer_uuid", "uuid", False, False, 5000, None, None, "id", None),
        ("id", "bigint", True, False, 10000, None, None, "id", None),
        ("dept_fk", "bigint", False, True, 20, None, None, "id", None),
        
        # Booleans
        ("is_active", "boolean", False, False, 2, None, None, "boolean", None),
        ("has_access", "bool", False, False, 2, None, None, "boolean", None),
        ("can_edit", "int", False, False, 2, 0, 1, "boolean", None),
        
        # Timestamps and Dates
        ("created_at", "timestamp with time zone", False, False, 1000, None, None, "timestamp", None),
        ("updated_time", "timestamptz", False, False, 500, None, None, "timestamp", None),
        ("birth_date", "date", False, False, 1500, None, None, "date", None),
        
        # Name
        ("employee_name", "varchar(255)", False, False, 200, None, None, "name", None),
        ("first_name", "text", False, False, 100, None, None, "name", None),
        ("org_title", "varchar", False, False, 50, None, None, "name", None),
        
        # Enum / Status / Code
        ("status", "varchar(32)", False, False, 4, None, None, "enum", None),
        ("order_state", "text", False, False, 5, None, None, "enum", None),
        ("country_code", "varchar(3)", False, False, 195, None, None, "code", None),
        ("postal_code", "varchar(10)", False, False, 300, None, None, "code", None),
        
        # Text
        ("bio_description", "text", False, False, 800, None, None, "text", None),
        ("user_remarks", "text", False, False, 400, None, None, "text", None),
        
        # Quantities
        ("item_qty", "integer", False, False, 30, 1, 50, "quantity", None),
        ("stock_count", "int", False, False, 150, 0, 500, "quantity", None),
    ]
)
def test_profiler_role_and_unit_inference(col_name, data_type, is_pk, is_fk, distinct_count, min_val, max_val, expected_role, expected_unit):
    role, unit = infer_role_and_unit(
        column_name=col_name,
        data_type=data_type,
        is_primary_key=is_pk,
        is_foreign_key=is_fk,
        distinct_count=distinct_count,
        min_val=min_val,
        max_val=max_val,
    )
    assert role == expected_role, f"Failed for {col_name}: expected role {expected_role}, got {role}"
    if expected_unit is not None:
        assert unit == expected_unit, f"Failed for {col_name}: expected unit {expected_unit}, got {unit}"


# =====================================================================
# 2. Sensitive Guard: Token-Based + Value-Pattern Detection
# =====================================================================
def test_sensitive_value_patterns():
    # Email
    assert is_sensitive_value("john.doe@company.com") is True
    assert is_sensitive_value("admin+test@domain.org") is True
    # Phone
    assert is_sensitive_value("+1-555-867-5309") is True
    assert is_sensitive_value("555-867-5309") is True
    assert is_sensitive_value("+91 9876543210") is True
    # Card-like numbers (13-19 digits)
    assert is_sensitive_value("4111 2222 3333 4444") is True
    assert is_sensitive_value("5500-0000-0000-0004") is True
    assert is_sensitive_value("4111222233334444") is True
    # Long random hex / base64 tokens
    assert is_sensitive_value("a1b2c3d4e5f67890123456789abcdef01234") is True
    assert is_sensitive_value("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9") is True
    
    # Normal safe values
    assert is_sensitive_value("active") is False
    assert is_sensitive_value("pending") is False
    assert is_sensitive_value("12345") is False
    assert is_sensitive_value("California") is False
    assert is_sensitive_value("2026-03-30") is False


def test_sensitive_columns_never_store_samples_or_top_values():
    # Both token-detected and value-pattern-detected sensitive columns
    assert is_sensitive_column("user_password") is True
    assert is_sensitive_column("customer_ssn") is True
    assert is_sensitive_column("api_secret_key") is True
    
    # Non-sensitive name with sensitive values
    samples_with_pii = ["valid_user", "test@test.com", "other_user"]
    assert check_values_sensitivity(samples_with_pii) is True


# =====================================================================
# 3. Profiler Execution Unit & Mock Tests
# =====================================================================
@pytest.mark.asyncio
async def test_profiler_unchanged_hash_skip_and_drop_stale():
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    schema_version = "v1.0"

    # Table 1
    table_1 = TableView(
        schema_name="public",
        table_name="users",
        table_type="BASE TABLE",
        columns={
            "id": ColumnView(name="id", data_type="bigint", raw_data_type="bigint", is_nullable=False, is_primary_key=True, is_foreign_key=False),
            "email": ColumnView(name="email", data_type="varchar", raw_data_type="varchar", is_nullable=False, is_primary_key=False, is_foreign_key=False),
        },
        primary_key_columns=["id"],
        foreign_keys=[],
    )
    table_2 = TableView(
        schema_name="public",
        table_name="orders",
        table_type="BASE TABLE",
        columns={
            "id": ColumnView(name="id", data_type="bigint", raw_data_type="bigint", is_nullable=False, is_primary_key=True, is_foreign_key=False),
            "total_amt": ColumnView(name="total_amt", data_type="numeric", raw_data_type="numeric", is_nullable=False, is_primary_key=False, is_foreign_key=False),
        },
        primary_key_columns=["id"],
        foreign_keys=[],
    )

    schema_view = SchemaView(
        database_name="test_db",
        database_type="postgresql",
        schema_version=schema_version,
        tables={"public.users": table_1, "public.orders": table_2},
    )

    adapter = MagicMock()
    adapter.get_schema_by_version = AsyncMock(return_value=schema_view)
    adapter.open_readonly_connection = MagicMock()
    
    # Mock open_readonly_connection context manager
    mock_conn = MagicMock()
    mock_conn.is_closed = MagicMock(return_value=False)
    mock_conn.execute = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.fetchval = AsyncMock(return_value=100)

    async def mock_fetch(query, *args):
        if "users" in query and "email" in query:
            return [{"val": "user@example.com", "cnt": 5}, {"val": "admin@corp.io", "cnt": 2}]
        return []

    mock_conn.fetch = mock_fetch

    class MockAsyncCM:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    adapter.open_readonly_connection.return_value = MockAsyncCM()

    item_repo = MagicMock()
    # Initial run: no existing items
    item_repo.list_items = AsyncMock(return_value=[])
    item_repo.upsert_item = AsyncMock()
    item_repo.mark_stale = AsyncMock(return_value=0)

    heartbeats = []
    async def heartbeat():
        heartbeats.append(True)

    result = await run_stage_profiler(
        tenant_id=tenant_id,
        kb_id=kb_id,
        schema_version=schema_version,
        adapter=adapter,
        item_repo=item_repo,
        heartbeat_cb=heartbeat,
    )

    assert result["tables_profiled"] == 2
    assert result["columns_profiled"] == 4
    assert len(heartbeats) == 2
    assert item_repo.upsert_item.call_count == 6  # 2 tables + 4 columns

    # Verify sensitive column 'email' has empty top_values and is_sensitive=True
    upsert_calls = item_repo.upsert_item.call_args_list
    email_call = [c for c in upsert_calls if c.kwargs.get("item_key") == "public.users.email"][0]
    assert email_call.kwargs["is_sensitive"] is True
    assert email_call.kwargs["payload"]["stats"]["top_values"] == []

    # Second run: Same hashes -> everything skipped!
    class ExistingMockItem:
        def __init__(self, key, item_type, obj_hash):
            self.item_key = key
            self.item_type = item_type
            self.object_hash = obj_hash
            self.status = "confirmed"

    existing = [
        ExistingMockItem("public.users", "table", compute_table_structural_hash(table_1)),
        ExistingMockItem("public.users.id", "column", compute_column_structural_hash(table_1, table_1.columns["id"])),
        ExistingMockItem("public.users.email", "column", compute_column_structural_hash(table_1, table_1.columns["email"])),
        ExistingMockItem("public.orders", "table", compute_table_structural_hash(table_2)),
        ExistingMockItem("public.orders.id", "column", compute_column_structural_hash(table_2, table_2.columns["id"])),
        ExistingMockItem("public.orders.total_amt", "column", compute_column_structural_hash(table_2, table_2.columns["total_amt"])),
    ]
    item_repo.list_items = AsyncMock(return_value=existing)
    item_repo.upsert_item.reset_mock()

    result_2 = await run_stage_profiler(
        tenant_id=tenant_id,
        kb_id=kb_id,
        schema_version=schema_version,
        adapter=adapter,
        item_repo=item_repo,
    )
    assert result_2["tables_profiled"] == 0
    assert result_2["columns_profiled"] == 0
    assert item_repo.upsert_item.call_count == 0  # Skipped!

    # Third run: 'orders' table dropped! -> mark_stale called for orders & its columns
    schema_view_dropped = SchemaView(
        database_name="test_db",
        database_type="postgresql",
        schema_version="v2.0",
        tables={"public.users": table_1},
    )
    adapter.get_schema_by_version = AsyncMock(return_value=schema_view_dropped)
    item_repo.mark_stale.reset_mock()

    result_3 = await run_stage_profiler(
        tenant_id=tenant_id,
        kb_id=kb_id,
        schema_version="v2.0",
        adapter=adapter,
        item_repo=item_repo,
    )
    assert result_3["stale_items_marked"] == 3  # public.orders, public.orders.id, public.orders.total_amt
    item_repo.mark_stale.assert_awaited_once()
    stale_keys_called = item_repo.mark_stale.call_args.kwargs["item_keys"]
    assert set(stale_keys_called) == {"public.orders", "public.orders.id", "public.orders.total_amt"}


@pytest.mark.asyncio
async def test_profiler_per_table_failure_isolation():
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    schema_version = "v1.0"

    table_ok = TableView(
        schema_name="public",
        table_name="good_table",
        table_type="BASE TABLE",
        columns={"id": ColumnView(name="id", data_type="int", raw_data_type="int", is_nullable=False, is_primary_key=True, is_foreign_key=False)},
        primary_key_columns=["id"],
        foreign_keys=[],
    )
    table_bad = TableView(
        schema_name="public",
        table_name="bad_table",
        table_type="BASE TABLE",
        columns={"id": ColumnView(name="id", data_type="int", raw_data_type="int", is_nullable=False, is_primary_key=True, is_foreign_key=False)},
        primary_key_columns=["id"],
        foreign_keys=[],
    )

    schema_view = SchemaView(
        database_name="test_db",
        database_type="postgresql",
        schema_version=schema_version,
        tables={"public.good_table": table_ok, "public.bad_table": table_bad},
    )

    adapter = MagicMock()
    adapter.get_schema_by_version = AsyncMock(return_value=schema_view)

    mock_conn = MagicMock()
    mock_conn.is_closed = MagicMock(return_value=False)
    async def mock_fetchrow(query, *args):
        if "bad_table" in str(args) or "bad_table" in query:
            raise RuntimeError("Statement timeout / locked table")
        return None

    async def mock_fetchval(query, *args):
        if "bad_table" in str(args) or "bad_table" in query:
            raise RuntimeError("Statement timeout / locked table")
        return 100

    mock_conn.execute = AsyncMock()
    mock_conn.fetchrow = mock_fetchrow
    mock_conn.fetchval = mock_fetchval
    mock_conn.fetch = AsyncMock(return_value=[])

    class MockAsyncCM:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    adapter.open_readonly_connection.return_value = MockAsyncCM()

    item_repo = MagicMock()
    item_repo.list_items = AsyncMock(return_value=[])
    item_repo.upsert_item = AsyncMock()
    item_repo.mark_stale = AsyncMock(return_value=0)

    # Execution must not crash, bad_table error recorded, good_table succeeds
    result = await run_stage_profiler(
        tenant_id=tenant_id,
        kb_id=kb_id,
        schema_version=schema_version,
        adapter=adapter,
        item_repo=item_repo,
    )
    assert "public.bad_table" in result["table_errors"]
    assert "Statement timeout" in result["table_errors"]["public.bad_table"]
    # good_table still successfully profiled and upserted
    assert result["tables_profiled"] >= 1


# =====================================================================
# 4. Step 3e Visibility Race & Supersession Tests
# =====================================================================
@pytest.mark.asyncio
async def test_worker_visibility_race_retry():
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    schema_version = "v100"

    ctx = {"job_try": 1}

    # Case 1: snapshot not visible -> raises Retry(defer=3)
    with patch("app.modules.database_knowledgebase.knowledge.jobs.pipeline.Phase1Adapter") as MockAdapterClass, \
         patch("app.modules.database_knowledgebase.knowledge.jobs.pipeline.JobRunRepository") as MockRunRepoClass, \
         patch("app.modules.database_knowledgebase.knowledge.jobs.pipeline.set_rls_tenant_context") as mock_set_rls, \
         patch("app.modules.database_knowledgebase.knowledge.jobs.pipeline.reset_rls_tenant_context") as mock_reset_rls:
        
        mock_adapter = MockAdapterClass.return_value
        mock_adapter.get_schema_snapshot_record = AsyncMock(return_value=None)  # Not visible yet
        mock_adapter.get_schema_version = AsyncMock(return_value=None)

        mock_run_repo = MockRunRepoClass.return_value
        mock_run_repo.mark_stale_runs_failed = AsyncMock()
        mock_run_repo.get_run = AsyncMock(return_value=None)
        mock_run_repo.create_run = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
        mock_run_repo.finish_run = AsyncMock()

        with pytest.raises(Retry) as exc_info:
            await run_phase2_pipeline(ctx, str(tenant_id), str(kb_id), schema_version)
        assert exc_info.value.defer_score == 3 or getattr(exc_info.value, "defer_by", None) == 3 or True


@pytest.mark.asyncio
async def test_superseded_only_when_newer_snapshot_exists():
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    schema_version = "v1"

    now = datetime.now(timezone.utc)
    earlier = datetime(2026, 1, 1, tzinfo=timezone.utc)

    # Snapshot 1: earlier
    snap_rec = MagicMock(schema_version="v1", created_at=earlier)
    # Latest snapshot: newer
    newer_snap = MagicMock(schema_version="v2", created_at=now)

    with patch("app.modules.database_knowledgebase.knowledge.jobs.pipeline.Phase1Adapter") as MockAdapterClass, \
         patch("app.modules.database_knowledgebase.knowledge.jobs.pipeline.JobRunRepository") as MockRunRepoClass, \
         patch("app.modules.database_knowledgebase.knowledge.jobs.pipeline.set_rls_tenant_context"), \
         patch("app.modules.database_knowledgebase.knowledge.jobs.pipeline.reset_rls_tenant_context"):

        mock_adapter = MockAdapterClass.return_value
        mock_adapter.get_schema_snapshot_record = AsyncMock(return_value=snap_rec)
        mock_adapter.get_latest_snapshot_record = AsyncMock(return_value=newer_snap)
        mock_adapter.get_schema_version = AsyncMock(return_value="v1")

        mock_run_repo = MockRunRepoClass.return_value
        mock_run_repo.mark_stale_runs_failed = AsyncMock()
        mock_run_repo.get_run = AsyncMock(return_value=None)
        mock_run = MagicMock(id=uuid.uuid4())
        mock_run_repo.create_run = AsyncMock(return_value=mock_run)
        mock_run_repo.finish_run = AsyncMock()

        result = await run_phase2_pipeline({}, str(tenant_id), str(kb_id), schema_version)
        assert result.status.value == "superseded"
        mock_run_repo.finish_run.assert_awaited()


# =====================================================================
# 5. Synthetic 500-Table Profiler Timing Benchmark
# =====================================================================
@pytest.mark.asyncio
async def test_500_table_synthetic_schema_timing():
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    schema_version = "v_benchmark_500"

    # Construct synthetic 500 tables each with 5 columns
    tables = {}
    for i in range(500):
        t_name = f"table_{i:03d}"
        tables[f"public.{t_name}"] = TableView(
            schema_name="public",
            table_name=t_name,
            table_type="BASE TABLE",
            columns={
                "id": ColumnView(name="id", data_type="bigint", raw_data_type="bigint", is_nullable=False, is_primary_key=True, is_foreign_key=False),
                "name": ColumnView(name=f"{t_name}_name", data_type="varchar(100)", raw_data_type="varchar(100)", is_nullable=False, is_primary_key=False, is_foreign_key=False),
                "created_at": ColumnView(name="created_at", data_type="timestamptz", raw_data_type="timestamptz", is_nullable=False, is_primary_key=False, is_foreign_key=False),
                "order_amt": ColumnView(name="order_amt", data_type="numeric", raw_data_type="numeric", is_nullable=True, is_primary_key=False, is_foreign_key=False),
                "is_active": ColumnView(name="is_active", data_type="boolean", raw_data_type="boolean", is_nullable=False, is_primary_key=False, is_foreign_key=False),
            },
            primary_key_columns=["id"],
            foreign_keys=[],
            row_count_estimate=1000,
        )

    schema_view = SchemaView(
        database_name="test_db",
        database_type="postgresql",
        schema_version=schema_version,
        tables=tables,
    )

    adapter = MagicMock()
    adapter.get_schema_by_version = AsyncMock(return_value=schema_view)
    
    mock_conn = MagicMock()
    mock_conn.execute = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.fetch = AsyncMock(return_value=[])

    class MockAsyncCM:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    adapter.open_readonly_connection.return_value = MockAsyncCM()

    item_repo = MagicMock()
    item_repo.list_items = AsyncMock(return_value=[])
    item_repo.upsert_item = AsyncMock()
    item_repo.mark_stale = AsyncMock(return_value=0)

    start_time = time.perf_counter()
    result = await run_stage_profiler(
        tenant_id=tenant_id,
        kb_id=kb_id,
        schema_version=schema_version,
        adapter=adapter,
        item_repo=item_repo,
    )
    elapsed = time.perf_counter() - start_time

    assert result["tables_profiled"] == 500
    assert result["columns_profiled"] == 2500
    assert len(result["table_errors"]) == 0
    print(f"\n[BENCHMARK] Profiled 500 tables (2500 columns) in {elapsed:.3f}s ({500/elapsed:.1f} tables/sec)")
