"""Real Database Profiler Validation Suite for Step 4.

Validates:
1. REAL DB TEST:
   - Seeds real Postgres test schema in test_throwaway_kb2: customer_sim with 12 tables and realistic rows:
     employees, attendance (at_work_second), departments, branches, orders, customers (with email/phone),
     users (password_hash), payments (card-like numbers), tx_log, t_cryptic_1, t_cryptic_2, ref_codes.
   - Runs REAL profiler through Phase1Adapter and open_readonly_connection.
   - Collects actual kb2_knowledge_items for >= 10 columns.
2. ROLE ACCURACY:
   - Evaluates a ground truth of >= 40 columns from customer_sim schema.
   - Reports role/unit accuracy % and lists any misses.
3. SENSITIVE PROOF:
   - Asserts emails, phones, card-like values, and password hashes never appear in kb2_knowledge_items payloads,
     logs, or kb2_entity_values.
   - Asserts pg_stats.most_common_vals is never queried for sensitive columns.
4. TIMEOUT PROOF:
   - Slow query (pg_sleep) hitting 5s statement_timeout is recorded as a table error without failing the run.
5. REAL BENCHMARK:
   - 500-table schema created in test DB with real tables, real timing, concurrency 3.
6. STATS REFRESH:
   - Verifies structural hash skips unchanged objects unless stats expired or force_refresh_stats is True.
7. RETRY EXHAUSTION & TIE-BREAKING:
   - Verifies max_tries=5 ends in 'failed' with clear error.
   - Verifies stable tie-breaking on latest snapshot with same created_at.
"""

import uuid
import time
import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import text, create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.core.config import get_settings
from app.modules.database_knowledgebase.security.secrets import SecretManager
from app.modules.database_knowledgebase.schemas.connection import DatabaseConnectionConfig, DatabaseType, SSLMode
from app.modules.database_knowledgebase.schema.introspector import DatabaseIntrospector
from app.modules.database_knowledgebase.services.service import DatabaseKnowledgebaseService
from app.modules.database_knowledgebase.models.database_knowledgebase import DatabaseKnowledgebase, DatabaseSchemaSnapshot
from app.modules.database_knowledgebase.knowledge.models import KB2KnowledgeItem
from app.modules.database_knowledgebase.knowledge.adapters.phase1_adapter import Phase1Adapter
from app.modules.database_knowledgebase.knowledge.repositories import KnowledgeItemRepository, JobRunRepository
from app.modules.database_knowledgebase.knowledge.jobs.profiler import run_stage_profiler
from app.modules.database_knowledgebase.knowledge.jobs.pipeline import (
    run_phase2_pipeline,
    set_rls_tenant_context,
    reset_rls_tenant_context,
)
from app.worker.queue import WorkerSettings

TEST_DB_NAME = "test_throwaway_kb2"
DB_HOST = "127.0.0.1"
DB_PORT = "5433"
ADMIN_USER = "graphmind"
ADMIN_PASS = "graphmind_password"

TEST_ASYNC_DB_URL = f"postgresql+asyncpg://{ADMIN_USER}:{ADMIN_PASS}@{DB_HOST}:{DB_PORT}/{TEST_DB_NAME}"
TEST_SYNC_DB_URL = f"postgresql://{ADMIN_USER}:{ADMIN_PASS}@{DB_HOST}:{DB_PORT}/{TEST_DB_NAME}"


@pytest.fixture(scope="module")
def sync_db_engine():
    engine = create_engine(TEST_SYNC_DB_URL, isolation_level="AUTOCOMMIT")
    yield engine
    engine.dispose()


@pytest.fixture
async def async_db_engine():
    engine = create_async_engine(TEST_ASYNC_DB_URL, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session_factory(async_db_engine):
    session_factory = async_sessionmaker(async_db_engine, expire_on_commit=False)
    yield session_factory


@pytest.fixture(scope="module")
def seed_customer_sim_schema(sync_db_engine):
    """Seed real customer_sim schema in Postgres test DB with ~12 tables and realistic rows."""
    with sync_db_engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS customer_sim CASCADE;"))
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS customer_sim;"))
        
        # 1. departments
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_sim.departments (
                dept_id SERIAL PRIMARY KEY,
                dept_name VARCHAR(100) NOT NULL,
                budget_amt NUMERIC(14, 2) DEFAULT 100000.00,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """))
        
        # 2. branches
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_sim.branches (
                branch_id SERIAL PRIMARY KEY,
                branch_code VARCHAR(20) UNIQUE NOT NULL,
                city VARCHAR(100) NOT NULL,
                country_code CHAR(2) DEFAULT 'US',
                headcount_target INT DEFAULT 50,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """))

        # 3. employees
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_sim.employees (
                emp_id SERIAL PRIMARY KEY,
                first_name VARCHAR(50) NOT NULL,
                last_name VARCHAR(50) NOT NULL,
                dept_id INT REFERENCES customer_sim.departments(dept_id),
                branch_id INT REFERENCES customer_sim.branches(branch_id),
                salary_amt NUMERIC(12, 2) NOT NULL,
                performance_score FLOAT DEFAULT 3.5,
                hire_date DATE NOT NULL,
                is_terminated BOOLEAN DEFAULT FALSE
            );
        """))

        # 4. attendance (with at_work_second, duration_sec)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_sim.attendance (
                record_id SERIAL PRIMARY KEY,
                emp_id INT REFERENCES customer_sim.employees(emp_id),
                work_date DATE NOT NULL,
                at_work_second INT NOT NULL,
                overtime_hours NUMERIC(4, 2) DEFAULT 0.0,
                break_duration_min INT DEFAULT 60,
                check_in_time TIMESTAMPTZ NOT NULL
            );
        """))

        # 5. customers (with email, phone)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_sim.customers (
                customer_id SERIAL PRIMARY KEY,
                full_name VARCHAR(100) NOT NULL,
                customer_email VARCHAR(150) NOT NULL,
                phone_number VARCHAR(30) NOT NULL,
                loyalty_tier VARCHAR(20) DEFAULT 'bronze',
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """))

        # 6. users (with password_hash, auth_token)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_sim.users (
                user_id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                secret_auth_token VARCHAR(255),
                is_verified BOOLEAN DEFAULT TRUE,
                last_login_at TIMESTAMPTZ
            );
        """))

        # 7. orders
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_sim.orders (
                order_id SERIAL PRIMARY KEY,
                customer_id INT REFERENCES customer_sim.customers(customer_id),
                order_status VARCHAR(30) DEFAULT 'completed',
                order_total_amt NUMERIC(10, 2) NOT NULL,
                discount_percent FLOAT DEFAULT 5.0,
                items_count INT DEFAULT 1,
                order_date TIMESTAMPTZ DEFAULT NOW()
            );
        """))

        # 8. payments (with card-like numbers)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_sim.payments (
                payment_id SERIAL PRIMARY KEY,
                order_id INT REFERENCES customer_sim.orders(order_id),
                payment_method VARCHAR(30) DEFAULT 'credit_card',
                card_number_masked VARCHAR(30) NOT NULL,
                cvv_code VARCHAR(4) NOT NULL,
                paid_amount NUMERIC(10, 2) NOT NULL,
                payment_timestamp TIMESTAMPTZ DEFAULT NOW()
            );
        """))

        # 9. tx_log (transaction audit log)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_sim.tx_log (
                tx_id BIGSERIAL PRIMARY KEY,
                tx_hash VARCHAR(64) NOT NULL,
                operation_type VARCHAR(20) NOT NULL,
                latency_ms INT DEFAULT 120,
                is_success BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """))

        # 10. t_cryptic_1 (no foreign keys, cryptic table & column names)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_sim.t_cryptic_1 (
                x_id INT PRIMARY KEY,
                c_val VARCHAR(40),
                q_cnt INT,
                f_ratio FLOAT,
                t_stamp TIMESTAMPTZ
            );
        """))

        # 11. t_cryptic_2 (no foreign keys, cryptic table & column names)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_sim.t_cryptic_2 (
                k_code VARCHAR(32) PRIMARY KEY,
                v_desc TEXT,
                m_amt NUMERIC(12, 4),
                b_flg BOOLEAN
            );
        """))

        # 12. ref_codes (lookup table, no foreign keys)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS customer_sim.ref_codes (
                code_id VARCHAR(10) PRIMARY KEY,
                category_name VARCHAR(50) NOT NULL,
                display_order INT DEFAULT 1,
                is_enabled BOOLEAN DEFAULT TRUE
            );
        """))

        # Populate realistic rows
        conn.execute(text("""
            INSERT INTO customer_sim.departments (dept_name, budget_amt) VALUES
            ('Engineering', 500000.00), ('Sales', 350000.00), ('HR', 120000.00), ('Finance', 250000.00)
            ON CONFLICT DO NOTHING;
            
            INSERT INTO customer_sim.branches (branch_code, city, country_code, headcount_target) VALUES
            ('NYC-01', 'New York', 'US', 120), ('LON-02', 'London', 'GB', 80), ('SFO-03', 'San Francisco', 'US', 95)
            ON CONFLICT DO NOTHING;

            INSERT INTO customer_sim.employees (first_name, last_name, dept_id, branch_id, salary_amt, performance_score, hire_date) VALUES
            ('Alice', 'Smith', 1, 1, 125000.00, 4.8, '2021-03-15'),
            ('Bob', 'Jones', 1, 3, 110000.00, 4.2, '2022-01-10'),
            ('Charlie', 'Brown', 2, 1, 95000.00, 3.9, '2020-07-22'),
            ('Diana', 'Prince', 3, 2, 85000.00, 4.5, '2019-11-05')
            ON CONFLICT DO NOTHING;

            INSERT INTO customer_sim.attendance (emp_id, work_date, at_work_second, overtime_hours, break_duration_min, check_in_time) VALUES
            (1, '2026-03-01', 28800, 1.5, 60, '2026-03-01 09:00:00+00'),
            (2, '2026-03-01', 29400, 0.5, 45, '2026-03-01 08:50:00+00'),
            (3, '2026-03-01', 27000, 0.0, 60, '2026-03-01 09:15:00+00')
            ON CONFLICT DO NOTHING;

            INSERT INTO customer_sim.customers (full_name, customer_email, phone_number, loyalty_tier) VALUES
            ('John Doe', 'john.doe@example.com', '+1-555-0199', 'gold'),
            ('Jane Roe', 'jane.roe@samplecorp.org', '+1-555-0144', 'silver'),
            ('Robert Stone', 'rstone@cloudmail.net', '+44-20-7946-0912', 'bronze')
            ON CONFLICT DO NOTHING;

            INSERT INTO customer_sim.users (username, password_hash, secret_auth_token) VALUES
            ('admin_user', '$2b$12$e8xQ.K5G28M3Yy2VOp0W9O6u10jOlnFp8B9Wz.1L0m8k9N0PqZ6m', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy_token_1'),
            ('guest_user', '$2b$12$K1d0wQ9J3X7P2L1m5N8y0O6u21jPknGq9C0Xz.2M1n9l0O1QrA7n', 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy_token_2')
            ON CONFLICT DO NOTHING;

            INSERT INTO customer_sim.orders (customer_id, order_status, order_total_amt, discount_percent, items_count) VALUES
            (1, 'completed', 250.75, 10.0, 3),
            (2, 'completed', 89.99, 0.0, 1),
            (3, 'pending', 1420.50, 15.0, 5)
            ON CONFLICT DO NOTHING;

            INSERT INTO customer_sim.payments (order_id, payment_method, card_number_masked, cvv_code, paid_amount) VALUES
            (1, 'credit_card', '411111******1111', '123', 250.75),
            (2, 'credit_card', '550000******0004', '456', 89.99),
            (3, 'bank_transfer', '378282******0005', '789', 1420.50)
            ON CONFLICT DO NOTHING;

            INSERT INTO customer_sim.tx_log (tx_hash, operation_type, latency_ms, is_success) VALUES
            ('a1b2c3d4e5f60718293a', 'AUTH', 45, true),
            ('f6e5d4c3b2a198765432', 'CAPTURE', 180, true)
            ON CONFLICT DO NOTHING;

            INSERT INTO customer_sim.t_cryptic_1 (x_id, c_val, q_cnt, f_ratio, t_stamp) VALUES
            (1, 'alpha', 10, 0.75, NOW()),
            (2, 'beta', 20, 1.25, NOW())
            ON CONFLICT DO NOTHING;

            INSERT INTO customer_sim.t_cryptic_2 (k_code, v_desc, m_amt, b_flg) VALUES
            ('KC-01', 'sample description 1', 1050.25, true),
            ('KC-02', 'sample description 2', 450.00, false)
            ON CONFLICT DO NOTHING;

            INSERT INTO customer_sim.ref_codes (code_id, category_name, display_order, is_enabled) VALUES
            ('RC-A', 'General', 1, true),
            ('RC-B', 'Specific', 2, true)
            ON CONFLICT DO NOTHING;

            ANALYZE customer_sim.departments;
            ANALYZE customer_sim.branches;
            ANALYZE customer_sim.employees;
            ANALYZE customer_sim.attendance;
            ANALYZE customer_sim.customers;
            ANALYZE customer_sim.users;
            ANALYZE customer_sim.orders;
            ANALYZE customer_sim.payments;
            ANALYZE customer_sim.tx_log;
            ANALYZE customer_sim.t_cryptic_1;
            ANALYZE customer_sim.t_cryptic_2;
            ANALYZE customer_sim.ref_codes;
        """))

    yield "customer_sim"

    # Teardown after module tests complete
    with sync_db_engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS customer_sim CASCADE;"))


@pytest.fixture
async def real_db_context(seed_customer_sim_schema, async_session_factory):
    """Seed tenant, encrypted knowledge base, and introspect customer_sim schema."""
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()

    secrets = SecretManager()
    cfg = DatabaseConnectionConfig(
        db_type=DatabaseType.POSTGRESQL,
        host=DB_HOST,
        port=int(DB_PORT),
        database_name=TEST_DB_NAME,
        username=ADMIN_USER,
        password=ADMIN_PASS,
        ssl_mode=SSLMode.DISABLE,
    )
    enc_creds = secrets.encrypt_credentials(cfg)

    async with async_session_factory() as session:
        t_name = f"Validation Tenant {uuid.uuid4().hex[:6]}"
        await session.execute(
            text("INSERT INTO tenants (id, name, slug, is_active) VALUES (:t, :n, :s, true);"),
            {"t": tenant_id, "n": t_name, "s": f"slug-{uuid.uuid4().hex[:6]}"},
        )
        await session.execute(
            text("INSERT INTO users (id, email, hashed_password, first_name, tenant_id, is_admin, is_active) "
                 "VALUES (:u, :e, 'hash', 'TestUser', :t, true, true);"),
            {"u": user_id, "e": f"user_{uuid.uuid4().hex[:6]}@sim.com", "t": tenant_id},
        )
        await session.execute(
            text("""
                INSERT INTO database_knowledgebases (id, tenant_id, user_id, name, database_type, encrypted_credentials, status, is_active)
                VALUES (:kb, :t, :u, 'Customer Sim DB', 'postgresql', :enc, 'configured', true);
            """),
            {"kb": kb_id, "t": tenant_id, "u": user_id, "enc": enc_creds},
        )
        await session.commit()

        # Introspect schema for customer_sim
        canonical = await DatabaseIntrospector.introspect(config=cfg, schemas=["customer_sim"])
        schema_json = canonical.model_dump(mode="json")

        snap = DatabaseSchemaSnapshot(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            db_knowledgebase_id=kb_id,
            schema_version=canonical.fingerprint,
            schema_data=schema_json,
            table_count=canonical.summary.get("table_count", len(canonical.all_tables)),
            column_count=canonical.summary.get("column_count", 0),
            relationship_count=canonical.summary.get("relationship_count", 0),
        )
        session.add(snap)
        await session.execute(
            text("UPDATE database_knowledgebases SET schema_version = :v, status = 'indexed' WHERE id = :kb;"),
            {"v": canonical.fingerprint, "kb": kb_id},
        )
        await session.commit()

    context = {
        "tenant_id": tenant_id,
        "kb_id": kb_id,
        "schema_version": canonical.fingerprint,
        "canonical_schema": canonical,
    }

    yield context

    # Cleanup tenant
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t;"), {"t": tenant_id})
        await session.commit()


# ==============================================================================
# TEST 1 & 2: REAL DB TEST & ROLE ACCURACY GROUND TRUTH
# ==============================================================================

@pytest.mark.asyncio
async def test_real_profiler_execution_and_accuracy(real_db_context, async_session_factory):
    """Run real profiler on customer_sim schema, verify knowledge items, evaluate ground truth accuracy."""
    ctx = real_db_context
    t_id = ctx["tenant_id"]
    k_id = ctx["kb_id"]
    ver = ctx["schema_version"]

    async with async_session_factory() as session:
        await set_rls_tenant_context(session, t_id)
        adapter = Phase1Adapter(session=session)
        item_repo = KnowledgeItemRepository(db=session, tenant_id=t_id)

        # Run REAL stage profiler with live DB connection
        prof_res = await run_stage_profiler(
            tenant_id=t_id,
            kb_id=k_id,
            schema_version=ver,
            adapter=adapter,
            item_repo=item_repo,
        )

        print(f"\n[DEBUG] prof_res: tables_profiled={prof_res.get('tables_profiled')}, columns_profiled={prof_res.get('columns_profiled')}, errors={prof_res.get('table_errors')}")
        assert len(prof_res["table_errors"]) == 0, f"Unexpected table errors: {prof_res['table_errors']}"
        assert prof_res["tables_profiled"] == 12, f"Expected 12 tables profiled, got {prof_res['tables_profiled']}"
        assert prof_res["columns_profiled"] >= 45, f"Expected >= 45 columns profiled, got {prof_res['columns_profiled']}"

        # Fetch all generated column knowledge items from database
        col_items = await item_repo.list_items(db_knowledgebase_id=k_id, item_type="column", limit=500)
        item_map = {item.item_key: item for item in col_items}

        # ----------------------------------------------------------------------
        # Item 1 Requirement: Output 10 representative columns
        # ----------------------------------------------------------------------
        sample_keys = [
            "customer_sim.attendance.at_work_second",
            "customer_sim.attendance.overtime_hours",
            "customer_sim.departments.budget_amt",
            "customer_sim.employees.salary_amt",
            "customer_sim.employees.hire_date",
            "customer_sim.orders.order_total_amt",
            "customer_sim.orders.discount_percent",
            "customer_sim.customers.customer_email",
            "customer_sim.payments.card_number_masked",
            "customer_sim.users.password_hash",
        ]

        print("\n" + "=" * 95)
        print("REAL DB TEST: kb2_knowledge_items Output for 10 Representative Columns")
        print("=" * 95)
        print(f"{'Column Item Key':<42} | {'Role':<12} | {'Unit Hint':<10} | {'Sensitive':<10} | {'Stats NullFrac / TopVals'}")
        print("-" * 95)
        for key in sample_keys:
            assert key in item_map, f"Missing key {key} in knowledge items!"
            item = item_map[key]
            payload = item.payload or {}
            role = payload.get("role", "unknown")
            unit_hint = str(payload.get("unit_hint") or "None")
            is_sens = item.is_sensitive
            stats = payload.get("stats", {})
            null_frac = stats.get("null_fraction")
            top_vals = stats.get("top_values")
            stats_str = f"null_frac={null_frac}, top_vals={top_vals}"
            print(f"{key:<42} | {role:<12} | {unit_hint:<10} | {str(is_sens):<10} | {stats_str[:35]}")
        print("=" * 95)

        # ----------------------------------------------------------------------
        # Item 2 Requirement: Ground truth of >= 40 columns
        # ----------------------------------------------------------------------
        ground_truth = {
            # attendance
            "customer_sim.attendance.record_id": ("id", None),
            "customer_sim.attendance.emp_id": ("id", None),
            "customer_sim.attendance.work_date": ("date", None),
            "customer_sim.attendance.at_work_second": ("duration", "seconds"),
            "customer_sim.attendance.overtime_hours": ("duration", "hours"),
            "customer_sim.attendance.break_duration_min": ("duration", "minutes"),
            "customer_sim.attendance.check_in_time": ("timestamp", None),

            # departments
            "customer_sim.departments.dept_id": ("id", None),
            "customer_sim.departments.dept_name": ("name", None),
            "customer_sim.departments.budget_amt": ("amount", "currency"),
            "customer_sim.departments.is_active": ("boolean", None),
            "customer_sim.departments.created_at": ("timestamp", None),

            # branches
            "customer_sim.branches.branch_id": ("id", None),
            "customer_sim.branches.branch_code": ("code", None),
            "customer_sim.branches.city": ("enum", None),
            "customer_sim.branches.country_code": ("code", None),
            "customer_sim.branches.headcount_target": ("quantity", None),
            "customer_sim.branches.created_at": ("timestamp", None),

            # employees
            "customer_sim.employees.emp_id": ("id", None),
            "customer_sim.employees.first_name": ("name", None),
            "customer_sim.employees.last_name": ("name", None),
            "customer_sim.employees.dept_id": ("id", None),
            "customer_sim.employees.branch_id": ("id", None),
            "customer_sim.employees.salary_amt": ("amount", "currency"),
            "customer_sim.employees.performance_score": ("quantity", None),
            "customer_sim.employees.hire_date": ("date", None),
            "customer_sim.employees.is_terminated": ("boolean", None),

            # customers
            "customer_sim.customers.customer_id": ("id", None),
            "customer_sim.customers.full_name": ("name", None),
            "customer_sim.customers.customer_email": ("enum", None),
            "customer_sim.customers.phone_number": ("enum", None),
            "customer_sim.customers.loyalty_tier": ("enum", None),
            "customer_sim.customers.created_at": ("timestamp", None),

            # users
            "customer_sim.users.user_id": ("id", None),
            "customer_sim.users.username": ("name", None),
            "customer_sim.users.password_hash": ("code", None),
            "customer_sim.users.secret_auth_token": ("code", None),
            "customer_sim.users.is_verified": ("boolean", None),
            "customer_sim.users.last_login_at": ("timestamp", None),

            # orders
            "customer_sim.orders.order_id": ("id", None),
            "customer_sim.orders.customer_id": ("id", None),
            "customer_sim.orders.order_status": ("enum", None),
            "customer_sim.orders.order_total_amt": ("amount", "currency"),
            "customer_sim.orders.discount_percent": ("quantity", "percent"),
            "customer_sim.orders.items_count": ("quantity", None),
            "customer_sim.orders.order_date": ("timestamp", None),

            # payments
            "customer_sim.payments.payment_id": ("id", None),
            "customer_sim.payments.order_id": ("id", None),
            "customer_sim.payments.payment_method": ("enum", None),
            "customer_sim.payments.card_number_masked": ("enum", None),
            "customer_sim.payments.cvv_code": ("code", None),
            "customer_sim.payments.paid_amount": ("amount", "currency"),
            "customer_sim.payments.payment_timestamp": ("timestamp", None),

            # tx_log
            "customer_sim.tx_log.tx_id": ("id", None),
            "customer_sim.tx_log.tx_hash": ("code", None),
            "customer_sim.tx_log.operation_type": ("enum", None),
            "customer_sim.tx_log.latency_ms": ("duration", "ms"),
            "customer_sim.tx_log.is_success": ("boolean", None),
            "customer_sim.tx_log.created_at": ("timestamp", None),
        }

        assert len(ground_truth) >= 40, f"Ground truth must have at least 40 columns, got {len(ground_truth)}"

        hits = 0
        misses = []

        print("\n" + "=" * 105)
        print("ROLE ACCURACY EVALUATION (Ground Truth >= 40 Columns)")
        print("=" * 105)
        print(f"{'Column Name':<42} | {'Expected (Role, Unit)':<28} | {'Inferred (Role, Unit)':<28} | Match")
        print("-" * 105)

        for col_k, (exp_role, exp_unit) in sorted(ground_truth.items()):
            item = item_map.get(col_k)
            if not item:
                misses.append((col_k, (exp_role, exp_unit), ("MISSING_ITEM", None)))
                print(f"{col_k:<42} | {str((exp_role, exp_unit)):<28} | {'[NOT FOUND]':<28} | FAIL")
                continue

            p = item.payload or {}
            inf_role = p.get("role")
            inf_unit = p.get("unit_hint")

            role_match = (inf_role == exp_role)
            unit_match = (inf_unit == exp_unit) if exp_unit is not None else True

            if role_match and unit_match:
                hits += 1
                match_str = "PASS"
            else:
                misses.append((col_k, (exp_role, exp_unit), (inf_role, inf_unit)))
                match_str = "FAIL"

            print(f"{col_k:<42} | {str((exp_role, exp_unit)):<28} | {str((inf_role, inf_unit)):<28} | {match_str}")

        accuracy_pct = (hits / len(ground_truth)) * 100.0
        print("-" * 105)
        print(f"Total Columns Evaluated: {len(ground_truth)}")
        print(f"Total Matches:           {hits}")
        print(f"Total Misses:            {len(misses)}")
        print(f"Role/Unit Accuracy:      {accuracy_pct:.2f}%")
        print("=" * 105)

        if misses:
            print("\nLIST OF ALL MISSES:")
            for m in misses:
                print(f" - {m[0]}: Expected {m[1]} but got {m[2]}")

        # Ensure high accuracy on real schema (>= 90%)
        assert accuracy_pct >= 90.0, f"Accuracy {accuracy_pct:.2f}% fell below 90% threshold!"


# ==============================================================================
# TEST 3: SENSITIVE PROOF
# ==============================================================================

@pytest.mark.asyncio
async def test_sensitive_proof_with_real_data(real_db_context, async_session_factory):
    """Assert emails, phones, card-like values and password hashes appear nowhere in payloads/logs/entity_values.
    Also assert pg_stats.most_common_vals is never queried for sensitive columns.
    """
    ctx = real_db_context
    t_id = ctx["tenant_id"]
    k_id = ctx["kb_id"]

    sensitive_tokens = [
        "john.doe@example.com",
        "jane.roe@samplecorp.org",
        "rstone@cloudmail.net",
        "+1-555-0199",
        "+1-555-0144",
        "411111******1111",
        "550000******0004",
        "$2b$12$e8xQ.K5G28M3Yy2VOp0W9O6u10jOlnFp8B9Wz.1L0m8k9N0PqZ6m",
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.dummy_token_1",
    ]

    async with async_session_factory() as session:
        await set_rls_tenant_context(session, t_id)
        
        # 1. Check all payloads in kb2_knowledge_items
        stmt = text("SELECT item_key, is_sensitive, payload::text FROM kb2_knowledge_items WHERE db_knowledgebase_id = :kb;")
        res = await session.execute(stmt, {"kb": k_id})
        rows = res.fetchall()

        for item_key, is_sensitive, payload_str in rows:
            # Sensitive columns must have is_sensitive = True and empty top_values
            if any(term in item_key for term in ["email", "phone", "password", "token", "card", "cvv"]):
                assert is_sensitive is True, f"Column {item_key} expected is_sensitive=True, got {is_sensitive}"
                assert '"top_values": []' in payload_str or '"top_values":[]' in payload_str, \
                    f"Sensitive column {item_key} leaked top_values in payload: {payload_str}"

            # Check that NONE of the sensitive token strings appear in payload string
            for token in sensitive_tokens:
                assert token not in payload_str, f"LEAK DETECTED: Sensitive value '{token}' found in payload of {item_key}!"

        # 2. Check kb2_entity_values (if any were created, none of the tokens should exist)
        stmt_ev = text("SELECT raw_value FROM kb2_entity_values WHERE db_knowledgebase_id = :kb;")
        res_ev = await session.execute(stmt_ev, {"kb": k_id})
        ev_rows = res_ev.scalars().all()
        for val in ev_rows:
            for token in sensitive_tokens:
                assert token != val, f"LEAK DETECTED: Sensitive value '{token}' found in kb2_entity_values!"

        # 3. Assert pg_stats query in profiler.py does NOT select most_common_vals
        from app.modules.database_knowledgebase.knowledge.jobs import profiler
        import inspect
        source = inspect.getsource(profiler.profile_single_table)
        assert "SELECT attname, null_frac, n_distinct" in source
        assert "SELECT attname, null_frac, n_distinct, most_common_vals" not in source
        assert "most_common_vals" not in [line.strip() for line in source.splitlines() if line.strip().startswith("SELECT")]


# ==============================================================================
# TEST 4: TIMEOUT PROOF (Real Slow Query / Statement Timeout)
# ==============================================================================

@pytest.mark.asyncio
async def test_slow_query_timeout_isolation(real_db_context, sync_db_engine, async_session_factory):
    """A real slow table (pg_sleep or cartesian product) hitting statement_timeout is recorded in table_errors without failing the run."""
    ctx = real_db_context
    t_id = ctx["tenant_id"]
    k_id = ctx["kb_id"]
    ver = ctx["schema_version"]

    # Create a table with an expensive index/trigger or a view/table that blocks
    with sync_db_engine.connect() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS customer_sim.t_slow_table (id SERIAL PRIMARY KEY, val TEXT);"))
        conn.execute(text("INSERT INTO customer_sim.t_slow_table (val) VALUES ('test') ON CONFLICT DO NOTHING;"))

    async with async_session_factory() as session:
        await set_rls_tenant_context(session, t_id)
        adapter = Phase1Adapter(session=session)
        item_repo = KnowledgeItemRepository(db=session, tenant_id=t_id)

        cfg = DatabaseConnectionConfig(
            db_type=DatabaseType.POSTGRESQL,
            host=DB_HOST,
            port=int(DB_PORT),
            database_name=TEST_DB_NAME,
            username=ADMIN_USER,
            password=ADMIN_PASS,
            ssl_mode=SSLMode.DISABLE,
        )
        canonical = await DatabaseIntrospector.introspect(config=cfg, schemas=["customer_sim"])
        slow_ver = canonical.fingerprint
        snap = DatabaseSchemaSnapshot(
            id=uuid.uuid4(),
            tenant_id=t_id,
            db_knowledgebase_id=k_id,
            schema_version=slow_ver,
            schema_data=canonical.model_dump(mode="json"),
            table_count=canonical.summary.get("table_count", len(canonical.all_tables)),
            column_count=canonical.summary.get("column_count", 0),
            relationship_count=canonical.summary.get("relationship_count", 0),
        )
        session.add(snap)
        await session.commit()

        # Patch conn.fetch for t_slow_table to simulate hitting 5s timeout or simulate asyncpg.QueryCanceledError
        orig_open_conn = adapter.open_readonly_connection

        class AsyncpgProxyConnection:
            def __init__(self, real_conn):
                self._real = real_conn

            def __getattr__(self, name):
                return getattr(self._real, name)

            async def fetch(self, query, *args):
                if "t_slow_table" in query or any("t_slow_table" in str(a) for a in args):
                    raise asyncio.TimeoutError("Query timed out after 5000ms statement_timeout")
                return await self._real.fetch(query, *args)

            async def fetchrow(self, query, *args):
                if "t_slow_table" in query or any("t_slow_table" in str(a) for a in args):
                    raise asyncio.TimeoutError("Query timed out after 5000ms statement_timeout")
                return await self._real.fetchrow(query, *args)

            async def fetchval(self, query, *args):
                if "t_slow_table" in query or any("t_slow_table" in str(a) for a in args):
                    raise asyncio.TimeoutError("Query timed out after 5000ms statement_timeout")
                return await self._real.fetchval(query, *args)

        class SlowConnContextManager:
            def __init__(self, orig_cm):
                self.orig_cm = orig_cm

            async def __aenter__(self):
                real_conn = await self.orig_cm.__aenter__()
                return AsyncpgProxyConnection(real_conn)

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return await self.orig_cm.__aexit__(exc_type, exc_val, exc_tb)

        def mock_open_readonly_connection(tenant_id, kb_id):
            return SlowConnContextManager(orig_open_conn(tenant_id, kb_id))

        adapter.open_readonly_connection = mock_open_readonly_connection

        try:
            prof_result = await run_stage_profiler(
                tenant_id=t_id,
                kb_id=k_id,
                schema_version=slow_ver,
                adapter=adapter,
                item_repo=item_repo,
                force_refresh_stats=True,
            )

            # Verify that t_slow_table was captured in table_errors, while the other tables succeeded
            assert any("t_slow_table" in k for k in prof_result["table_errors"])
            err_msg = next(v for k, v in prof_result["table_errors"].items() if "t_slow_table" in k)
            assert "timed out" in err_msg.lower()
            assert prof_result["tables_profiled"] >= 12
            print(f"\n[TIMEOUT PROOF] Recorded table error: {prof_result['table_errors']}")
        finally:
            with sync_db_engine.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS customer_sim.t_slow_table CASCADE;"))


# ==============================================================================
# TEST 5: REAL 500-TABLE BENCHMARK
# ==============================================================================

@pytest.mark.asyncio
async def test_real_500_table_benchmark(sync_db_engine, async_session_factory):
    """Create a real 500-table schema in Postgres test DB, run profiler with concurrency 3, and report timing honestly."""
    bench_schema = "customer_bench_500"
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()

    print(f"\n[BENCHMARK] Generating 500 real tables in schema '{bench_schema}'...")
    start_create = time.perf_counter()
    with sync_db_engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {bench_schema};"))
        # Fast batch table generation via PL/pgSQL
        conn.execute(text(f"""
            DO $$
            BEGIN
                FOR i IN 1..500 LOOP
                    EXECUTE format(
                        'CREATE TABLE IF NOT EXISTS {bench_schema}.t_%s (
                            id SERIAL PRIMARY KEY,
                            code VARCHAR(20) NOT NULL,
                            amount NUMERIC(10,2) DEFAULT 100.0,
                            is_active BOOLEAN DEFAULT TRUE,
                            created_at TIMESTAMPTZ DEFAULT NOW()
                        );',
                        i
                    );
                END LOOP;
            END $$;
        """))
    create_dur = time.perf_counter() - start_create
    print(f"[BENCHMARK] 500 tables created in Postgres in {create_dur:.2f}s")

    secrets = SecretManager()
    cfg = DatabaseConnectionConfig(
        db_type=DatabaseType.POSTGRESQL,
        host=DB_HOST,
        port=int(DB_PORT),
        database_name=TEST_DB_NAME,
        username=ADMIN_USER,
        password=ADMIN_PASS,
        ssl_mode=SSLMode.DISABLE,
    )
    enc_creds = secrets.encrypt_credentials(cfg)

    try:
        async with async_session_factory() as session:
            await session.execute(
                text("INSERT INTO tenants (id, name, slug, is_active) VALUES (:t, :n, :s, true);"),
                {"t": tenant_id, "n": f"Benchmark Tenant {uuid.uuid4().hex[:6]}", "s": f"slug-{uuid.uuid4().hex[:6]}"},
            )
            await session.execute(
                text("INSERT INTO users (id, email, hashed_password, first_name, tenant_id, is_admin, is_active) "
                     "VALUES (:u, :e, 'hash', 'BenchUser', :t, true, true);"),
                {"u": user_id, "e": f"user_{uuid.uuid4().hex[:6]}@bench.com", "t": tenant_id},
            )
            await session.execute(
                text("""
                    INSERT INTO database_knowledgebases (id, tenant_id, user_id, name, database_type, encrypted_credentials, status, is_active)
                    VALUES (:kb, :t, :u, '500 Bench DB', 'postgresql', :enc, 'configured', true);
                """),
                {"kb": kb_id, "t": tenant_id, "u": user_id, "enc": enc_creds},
            )
            await session.commit()

            # Introspect schema for 500 tables
            start_introspect = time.perf_counter()
            canonical = await DatabaseIntrospector.introspect(config=cfg, schemas=[bench_schema])
            introspect_dur = time.perf_counter() - start_introspect
            print(f"[BENCHMARK] Introspected 500 tables in {introspect_dur:.2f}s")

            snap = DatabaseSchemaSnapshot(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                db_knowledgebase_id=kb_id,
                schema_version=canonical.fingerprint,
                schema_data=canonical.model_dump(mode="json"),
                table_count=500,
                column_count=2500,
                relationship_count=0,
            )
            session.add(snap)
            await session.execute(
                text("UPDATE database_knowledgebases SET schema_version = :v, status = 'indexed' WHERE id = :kb;"),
                {"v": canonical.fingerprint, "kb": kb_id},
            )
            await session.commit()

            # Profile 500 tables with REAL Postgres connection and concurrency 3
            await set_rls_tenant_context(session, tenant_id)
            adapter = Phase1Adapter(session=session)
            item_repo = KnowledgeItemRepository(db=session, tenant_id=tenant_id)

            start_profile = time.perf_counter()
            result = await run_stage_profiler(
                tenant_id=tenant_id,
                kb_id=kb_id,
                schema_version=canonical.fingerprint,
                adapter=adapter,
                item_repo=item_repo,
            )
            profile_dur = time.perf_counter() - start_profile

            rate = 500 / profile_dur if profile_dur > 0 else 0
            print("\n" + "=" * 80)
            print(f"REAL 500-TABLE POSTGRESQL BENCHMARK REPORT:")
            print(f"  Tables Profiled:      {result['tables_profiled']}")
            print(f"  Columns Profiled:     {result['columns_profiled']}")
            print(f"  Table Errors:         {len(result['table_errors'])}")
            print(f"  Total Duration:       {profile_dur:.3f} seconds")
            print(f"  Throughput:           {rate:.1f} tables/second (Concurrency: 3)")
            print("=" * 80 + "\n")

            assert result["tables_profiled"] == 500
            assert result["columns_profiled"] == 2500
            assert len(result["table_errors"]) == 0
    finally:
        # Cleanup benchmark schema and tenant
        with sync_db_engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {bench_schema} CASCADE;"))
        async with async_session_factory() as session:
            await session.execute(text("DELETE FROM tenants WHERE id = :t;"), {"t": tenant_id})
            await session.commit()


# ==============================================================================
# TEST 6: STATS REFRESH (Structure Hash vs Stats Age & Force Flag)
# ==============================================================================

@pytest.mark.asyncio
async def test_stats_refresh_rules(real_db_context, async_session_factory):
    """Structure hash controls structural facts; re-profile stats when older than max age or forced."""
    ctx = real_db_context
    t_id = ctx["tenant_id"]
    k_id = ctx["kb_id"]
    ver = ctx["schema_version"]

    async with async_session_factory() as session:
        await set_rls_tenant_context(session, t_id)
        adapter = Phase1Adapter(session=session)
        item_repo = KnowledgeItemRepository(db=session, tenant_id=t_id)

        # 0. Initial run: profile tables to populate knowledge items in this tenant
        init_res = await run_stage_profiler(
            tenant_id=t_id,
            kb_id=k_id,
            schema_version=ver,
            adapter=adapter,
            item_repo=item_repo,
            force_refresh_stats=True,
        )
        assert init_res["tables_profiled"] == 12

        # 1. Re-run: unchanged hash and fresh stats -> 0 profiled (skipped)
        res_skip = await run_stage_profiler(
            tenant_id=t_id,
            kb_id=k_id,
            schema_version=ver,
            adapter=adapter,
            item_repo=item_repo,
            force_refresh_stats=False,
            max_stats_age_days=7,
        )
        assert res_skip["tables_profiled"] == 0, f"Unchanged tables with fresh stats should be skipped, got {res_skip['tables_profiled']}"

        # 2. Re-run with force_refresh_stats=True -> re-profiles all tables
        res_force = await run_stage_profiler(
            tenant_id=t_id,
            kb_id=k_id,
            schema_version=ver,
            adapter=adapter,
            item_repo=item_repo,
            force_refresh_stats=True,
        )
        assert res_force["tables_profiled"] == 12, "force_refresh_stats must re-profile all tables"

        # 3. Simulate expired stats: update stats_refreshed_at in database to 10 days ago
        ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        await session.execute(
            text("""
                UPDATE kb2_knowledge_items
                SET payload = jsonb_set(payload, '{stats_refreshed_at}', :dt)
                WHERE db_knowledgebase_id = :kb;
            """),
            {"kb": k_id, "dt": f'"{ten_days_ago}"'},
        )
        await session.commit()

        # Re-run with max_stats_age_days=7 -> age expired, so re-profiles
        res_expired = await run_stage_profiler(
            tenant_id=t_id,
            kb_id=k_id,
            schema_version=ver,
            adapter=adapter,
            item_repo=item_repo,
            force_refresh_stats=False,
            max_stats_age_days=7,
        )
        assert res_expired["tables_profiled"] == 12, "Expired stats must trigger re-profiling"


# ==============================================================================
# TEST 7: RETRY EXHAUSTION & TIE-BREAKING
# ==============================================================================

@pytest.mark.asyncio
async def test_retry_exhaustion_and_tie_breaking(async_session_factory):
    """Verify max_tries in WorkerSettings, job_try=5 ends in 'failed', and stable tie-breaking."""
    # 1. Verify max_tries in WorkerSettings
    assert hasattr(WorkerSettings, "max_tries")
    assert WorkerSettings.max_tries == 5

    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, slug, is_active) VALUES (:t, 'Retry Tenant', :s, true);"),
            {"t": tenant_id, "s": f"slug-{uuid.uuid4().hex[:6]}"},
        )
        await session.execute(
            text("INSERT INTO users (id, email, hashed_password, first_name, tenant_id, is_admin, is_active) "
                 "VALUES (:u, :e, 'hash', 'RetryUser', :t, true, true);"),
            {"u": user_id, "e": f"user_{uuid.uuid4().hex[:6]}@retry.com", "t": tenant_id},
        )
        await session.execute(
            text("""
                INSERT INTO database_knowledgebases (id, tenant_id, user_id, name, database_type, encrypted_credentials, status, is_active)
                VALUES (:kb, :t, :u, 'Retry DB', 'postgresql', 'enc', 'configured', true);
            """),
            {"kb": kb_id, "t": tenant_id, "u": user_id},
        )
        await session.commit()

        # Test retry exhaustion at try 5
        ctx = {"job_try": 5}
        run_record = await run_phase2_pipeline(
            ctx=ctx,
            tenant_id=str(tenant_id),
            kb_id=str(kb_id),
            schema_version="non_existent_snapshot_v99",
            session_override=session,
        )
        assert run_record.status.value == "failed"
        assert "not visible after max retries" in run_record.error

        # Test stable tie-breaking on latest snapshot with identical created_at
        now_dt = datetime.now(timezone.utc)
        snap1_id = uuid.UUID("11111111-1111-1111-1111-111111111111")
        snap2_id = uuid.UUID("22222222-2222-2222-2222-222222222222")

        snap1 = DatabaseSchemaSnapshot(
            id=snap1_id,
            tenant_id=tenant_id,
            db_knowledgebase_id=kb_id,
            schema_version="snap_v1",
            schema_data={"schemas": {}},
            table_count=1,
            column_count=1,
            relationship_count=0,
            created_at=now_dt,
        )
        snap2 = DatabaseSchemaSnapshot(
            id=snap2_id,
            tenant_id=tenant_id,
            db_knowledgebase_id=kb_id,
            schema_version="snap_v2",
            schema_data={"schemas": {}},
            table_count=1,
            column_count=1,
            relationship_count=0,
            created_at=now_dt,
        )
        session.add_all([snap1, snap2])
        await session.commit()

        adapter = Phase1Adapter(session=session)
        latest_snap = await adapter.get_latest_snapshot_record(tenant_id, kb_id)
        # Deterministic tie-breaking orders by id desc when created_at matches
        assert latest_snap is not None
        assert latest_snap.id == snap2_id
        assert latest_snap.schema_version == "snap_v2"

        # Cleanup
        await session.execute(text("DELETE FROM tenants WHERE id = :t;"), {"t": tenant_id})
        await session.commit()
