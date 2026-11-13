"""Test Phase 2 Step 1: KB2 Tables, Migrations, Constraints, and Tenant RLS Isolation.

Runs against a dedicated throwaway test database ('test_throwaway_kb2') to ensure
the development database on 5433/graphmind is never touched or polluted.

Validates:
1. Migration upgrade to head and downgrade back to c09550784c22.
2. Sensitivity guard rejection at write time (model @validates and bulk insert pipeline validation).
3. Non-superuser execution asserting rolbypassrls = false.
4. Tenant isolation for kb2_knowledge_items.
5. Tenant isolation for kb2_entity_values.
6. Tenant isolation for kb2_query_memory.
"""

import os
import uuid
import pytest
from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker
from alembic import command
from alembic.config import Config

from app.modules.database_knowledgebase.knowledge.sensitivity import (
    is_sensitive_column,
    validate_not_sensitive,
)
from app.modules.database_knowledgebase.knowledge.models import (
    KB2KnowledgeItem,
    KB2EntityValue,
    KB2QueryMemory,
)

# Test database configuration (strictly separated from dev DB)
TEST_DB_NAME = "test_throwaway_kb2"
DB_HOST = "127.0.0.1"
DB_PORT = "5433"
ADMIN_USER = "graphmind"
ADMIN_PASS = "graphmind_password"
TEST_USER = "kb2_test_user"
TEST_PASS = "kb2_test_pass"

ADMIN_DB_URL = f"postgresql://{ADMIN_USER}:{ADMIN_PASS}@{DB_HOST}:{DB_PORT}/{TEST_DB_NAME}"
TEST_USER_DB_URL = f"postgresql://{TEST_USER}:{TEST_PASS}@{DB_HOST}:{DB_PORT}/{TEST_DB_NAME}"


@pytest.fixture(scope="session", autouse=True)
def setup_throwaway_database_and_role():
    """Ensure test_throwaway_kb2 database and non-superuser role kb2_test_user exist.
    
    Creates kb2_test_user with NOSUPERUSER NOBYPASSRLS specifically for testing RLS,
    and cleanly tears down the role afterwards.
    """
    sys_url = f"postgresql://{ADMIN_USER}:{ADMIN_PASS}@{DB_HOST}:{DB_PORT}/graphmind"
    sys_engine = create_engine(sys_url, isolation_level="AUTOCOMMIT")

    with sys_engine.connect() as conn:
        # 1. Ensure test database exists
        db_exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :d;"), {"d": TEST_DB_NAME}
        ).fetchone()
        if not db_exists:
            conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME};"))

        # 2. Re-create non-superuser role
        conn.execute(text(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{TEST_USER}') THEN
                    CREATE ROLE {TEST_USER} WITH LOGIN PASSWORD '{TEST_PASS}' NOSUPERUSER NOBYPASSRLS INHERIT;
                ELSE
                    ALTER ROLE {TEST_USER} WITH LOGIN PASSWORD '{TEST_PASS}' NOSUPERUSER NOBYPASSRLS;
                END IF;
            END
            $$;
        """))

    # Grant privileges on test_throwaway_kb2 database to kb2_test_user
    test_db_admin_engine = create_engine(ADMIN_DB_URL, isolation_level="AUTOCOMMIT")
    with test_db_admin_engine.connect() as conn:
        conn.execute(text(f"GRANT CONNECT ON DATABASE {TEST_DB_NAME} TO {TEST_USER};"))
        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {TEST_USER};"))
        conn.execute(text(f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO {TEST_USER};"))
        conn.execute(text(f"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO {TEST_USER};"))
        conn.execute(text(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {TEST_USER};"))

    yield

    # Teardown: Reassign/drop owned objects in test_throwaway_kb2 and drop kb2_test_user
    with test_db_admin_engine.connect() as conn:
        conn.execute(text(f"REASSIGN OWNED BY {TEST_USER} TO {ADMIN_USER};"))
        conn.execute(text(f"DROP OWNED BY {TEST_USER};"))

    with sys_engine.connect() as conn:
        conn.execute(text(f"DROP ROLE IF EXISTS {TEST_USER};"))

    sys_engine.dispose()
    test_db_admin_engine.dispose()


@pytest.fixture(scope="session")
def alembic_cfg():
    """Alembic configuration pointing to throwaway database."""
    # Ensure migrations/env.py reads test throwaway db from environment
    os.environ["POSTGRES_DB"] = TEST_DB_NAME
    ini_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    cfg = Config(ini_path)
    cfg.set_main_option("sqlalchemy.url", ADMIN_DB_URL)
    return cfg


@pytest.fixture(scope="session")
def admin_engine():
    engine = create_engine(ADMIN_DB_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def non_super_engine():
    """Engine using non-superuser role (kb2_test_user) where rolbypassrls = False."""
    engine = create_engine(TEST_USER_DB_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


def test_alembic_migration_upgrade_and_downgrade(alembic_cfg, admin_engine):
    """Test Alembic migration upgrade to head, downgrade to c09550784c22, and re-upgrade."""
    # 1. Downgrade to c09550784c22 (pre-phase 2 head)
    command.downgrade(alembic_cfg, "c09550784c22")
    with admin_engine.connect() as conn:
        res = conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'kb2_%';")
        ).fetchall()
        assert len(res) == 0, f"Expected kb2_ tables to be dropped on downgrade, found: {res}"

    # 2. Upgrade to head (applies b2f3c4d5e6a7)
    command.upgrade(alembic_cfg, "head")
    with admin_engine.connect() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'kb2_%';")
            ).fetchall()
        ]
        assert "kb2_knowledge_items" in tables
        assert "kb2_entity_values" in tables
        assert "kb2_query_memory" in tables

        # Verify CHECK constraint on normalized_value length exists
        constraints = [
            r[0]
            for r in conn.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'kb2_entity_values'::regclass;"
                )
            ).fetchall()
        ]
        assert "ck_kb2_ev_normalized_value_len" in constraints


def test_sensitive_column_guard_unit_and_bulk_validation():
    """Test token-based sensitivity matching, model @validates, and bulk validation helper."""
    # 1. Token-based matching unit checks
    assert is_sensitive_column("password") is True
    assert is_sensitive_column("user_password") is True
    assert is_sensitive_column("passwordHash") is True
    assert is_sensitive_column("employeeSalary") is True
    assert is_sensitive_column("ssn_number") is True
    assert is_sensitive_column("api_key") is True
    assert is_sensitive_column("apiKey") is True

    # Safe columns should NOT trigger false positives
    assert is_sensitive_column("status") is False
    assert is_sensitive_column("order_total") is False
    assert is_sensitive_column("category_name") is False
    assert is_sensitive_column("department_id") is False

    # 2. Model @validates rejection
    with pytest.raises(ValueError, match="identified as sensitive"):
        KB2EntityValue(
            tenant_id=uuid.uuid4(),
            db_knowledgebase_id=uuid.uuid4(),
            table_name="users",
            column_name="user_password_hash",
            raw_value="secret123",
            normalized_value="secret123",
        )

    # 3. Bulk insert / repository guard validation
    bulk_records = [
        {"table_name": "orders", "column_name": "order_status", "raw_value": "PAID"},
        {"table_name": "employees", "column_name": "annual_salary", "raw_value": "100000"},
    ]
    with pytest.raises(ValueError, match="annual_salary"):
        for rec in bulk_records:
            validate_not_sensitive(rec["column_name"])


def test_non_superuser_role_asserts_no_bypass_rls(non_super_engine):
    """Assert that the test connection runs as non-superuser and rolbypassrls is False."""
    with non_super_engine.connect() as conn:
        res = conn.execute(
            text("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user;")
        ).fetchone()
        assert res is not None
        current_user, rolsuper, rolbypassrls = res
        assert current_user == TEST_USER
        assert rolsuper is False, f"Expected rolsuper=False, got {rolsuper}"
        assert rolbypassrls is False, f"Expected rolbypassrls=False, got {rolbypassrls}"


def test_tenant_isolation_kb2_knowledge_items(admin_engine, non_super_engine):
    """Test RLS tenant isolation on kb2_knowledge_items using non-superuser role."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    kb_a = uuid.uuid4()
    kb_b = uuid.uuid4()
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    # Seed parents via admin connection
    with admin_engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO tenants (id, name, slug, is_active) VALUES
                (:t_a, 'Tenant Alpha', :slug_a, true),
                (:t_b, 'Tenant Beta', :slug_b, true)
                ON CONFLICT (id) DO NOTHING;
            """),
            {"t_a": tenant_a, "slug_a": f"a-{uuid.uuid4().hex[:6]}", "t_b": tenant_b, "slug_b": f"b-{uuid.uuid4().hex[:6]}"},
        )
        conn.execute(
            text("""
                INSERT INTO users (id, email, hashed_password, first_name, tenant_id, is_admin, is_active) VALUES
                (:u_a, :e_a, 'hash', 'A', :t_a, true, true),
                (:u_b, :e_b, 'hash', 'B', :t_b, true, true)
                ON CONFLICT (id) DO NOTHING;
            """),
            {"u_a": user_a, "e_a": f"a_{uuid.uuid4().hex[:6]}@test.com", "t_a": tenant_a,
             "u_b": user_b, "e_b": f"b_{uuid.uuid4().hex[:6]}@test.com", "t_b": tenant_b},
        )
        conn.execute(
            text("""
                INSERT INTO database_knowledgebases (id, tenant_id, user_id, name, database_type, encrypted_credentials, status, is_active)
                VALUES
                (:kb_a, :t_a, :u_a, 'DB Alpha', 'postgresql', 'enc', 'configured', true),
                (:kb_b, :t_b, :u_b, 'DB Beta', 'postgresql', 'enc', 'configured', true)
                ON CONFLICT (id) DO NOTHING;
            """),
            {"kb_a": kb_a, "t_a": tenant_a, "u_a": user_a, "kb_b": kb_b, "t_b": tenant_b, "u_b": user_b},
        )
        conn.commit()

    Session = sessionmaker(bind=non_super_engine)
    try:
        # Non-superuser writes records for both tenants (switching context appropriately)
        with Session() as session:
            session.execute(text("SELECT set_config('app.current_tenant', :t, true);"), {"t": str(tenant_a)})
            item_a = KB2KnowledgeItem(
                id=uuid.uuid4(),
                tenant_id=tenant_a,
                db_knowledgebase_id=kb_a,
                item_type="table",
                item_key="public.orders",
                valid_from_version="v1",
                object_hash="hash_a",
                source="declared",
                status="draft",
                reviewed_by=user_a,
                payload={"desc": "Orders A"},
            )
            session.add(item_a)
            session.commit()

        with Session() as session:
            session.execute(text("SELECT set_config('app.current_tenant', :t, true);"), {"t": str(tenant_b)})
            item_b = KB2KnowledgeItem(
                id=uuid.uuid4(),
                tenant_id=tenant_b,
                db_knowledgebase_id=kb_b,
                item_type="table",
                item_key="public.orders",
                valid_from_version="v1",
                object_hash="hash_b",
                source="declared",
                status="draft",
                reviewed_by=user_b,
                payload={"desc": "Orders B"},
            )
            session.add(item_b)
            session.commit()

        # Query as Tenant A
        with Session() as session:
            session.execute(text("SELECT set_config('app.current_tenant', :t, true);"), {"t": str(tenant_a)})
            rows = session.execute(text("SELECT id, tenant_id FROM kb2_knowledge_items;")).fetchall()
            assert len(rows) == 1
            assert rows[0][1] == tenant_a

        # Query as Tenant B
        with Session() as session:
            session.execute(text("SELECT set_config('app.current_tenant', :t, true);"), {"t": str(tenant_b)})
            rows = session.execute(text("SELECT id, tenant_id FROM kb2_knowledge_items;")).fetchall()
            assert len(rows) == 1
            assert rows[0][1] == tenant_b

        # Query with unset/zero tenant -> 0 rows
        with Session() as session:
            session.execute(text("SELECT set_config('app.current_tenant', '00000000-0000-0000-0000-000000000000', true);"))
            rows = session.execute(text("SELECT id FROM kb2_knowledge_items;")).fetchall()
            assert len(rows) == 0

    finally:
        with admin_engine.connect() as conn:
            conn.execute(text("DELETE FROM tenants WHERE id IN (:t_a, :t_b);"), {"t_a": tenant_a, "t_b": tenant_b})
            conn.commit()


def test_tenant_isolation_kb2_entity_values(admin_engine, non_super_engine):
    """Test RLS tenant isolation on kb2_entity_values using non-superuser role."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    kb_a = uuid.uuid4()
    kb_b = uuid.uuid4()

    with admin_engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO tenants (id, name, slug, is_active) VALUES
                (:t_a, 'Tenant Alpha', :slug_a, true),
                (:t_b, 'Tenant Beta', :slug_b, true)
                ON CONFLICT (id) DO NOTHING;
            """),
            {"t_a": tenant_a, "slug_a": f"a-{uuid.uuid4().hex[:6]}", "t_b": tenant_b, "slug_b": f"b-{uuid.uuid4().hex[:6]}"},
        )
        user_id = uuid.uuid4()
        conn.execute(
            text("""
                INSERT INTO users (id, email, hashed_password, first_name, tenant_id, is_admin, is_active) VALUES
                (:u, :e, 'hash', 'U', :t_a, true, true);
            """),
            {"u": user_id, "e": f"u_{uuid.uuid4().hex[:6]}@test.com", "t_a": tenant_a},
        )
        conn.execute(
            text("""
                INSERT INTO database_knowledgebases (id, tenant_id, user_id, name, database_type, encrypted_credentials, status, is_active)
                VALUES
                (:kb_a, :t_a, :u, 'DB Alpha', 'postgresql', 'enc', 'configured', true),
                (:kb_b, :t_b, :u, 'DB Beta', 'postgresql', 'enc', 'configured', true)
                ON CONFLICT (id) DO NOTHING;
            """),
            {"kb_a": kb_a, "t_a": tenant_a, "u": user_id, "kb_b": kb_b, "t_b": tenant_b},
        )
        conn.commit()

    Session = sessionmaker(bind=non_super_engine)
    try:
        with Session() as session:
            session.execute(text("SELECT set_config('app.current_tenant', :t, true);"), {"t": str(tenant_a)})
            ev_a = KB2EntityValue(
                id=uuid.uuid4(),
                tenant_id=tenant_a,
                db_knowledgebase_id=kb_a,
                table_name="orders",
                column_name="status",
                raw_value="DELIVERED",
                normalized_value="delivered",
            )
            session.add(ev_a)
            session.commit()

        with Session() as session:
            session.execute(text("SELECT set_config('app.current_tenant', :t, true);"), {"t": str(tenant_b)})
            ev_b = KB2EntityValue(
                id=uuid.uuid4(),
                tenant_id=tenant_b,
                db_knowledgebase_id=kb_b,
                table_name="orders",
                column_name="status",
                raw_value="CANCELLED",
                normalized_value="cancelled",
            )
            session.add(ev_b)
            session.commit()

        # Query Tenant A
        with Session() as session:
            session.execute(text("SELECT set_config('app.current_tenant', :t, true);"), {"t": str(tenant_a)})
            rows = session.execute(text("SELECT id, tenant_id FROM kb2_entity_values;")).fetchall()
            assert len(rows) == 1
            assert rows[0][1] == tenant_a

        # Query Tenant B
        with Session() as session:
            session.execute(text("SELECT set_config('app.current_tenant', :t, true);"), {"t": str(tenant_b)})
            rows = session.execute(text("SELECT id, tenant_id FROM kb2_entity_values;")).fetchall()
            assert len(rows) == 1
            assert rows[0][1] == tenant_b

    finally:
        with admin_engine.connect() as conn:
            conn.execute(text("DELETE FROM tenants WHERE id IN (:t_a, :t_b);"), {"t_a": tenant_a, "t_b": tenant_b})
            conn.commit()


def test_tenant_isolation_kb2_query_memory(admin_engine, non_super_engine):
    """Test RLS tenant isolation on kb2_query_memory using non-superuser role."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    kb_a = uuid.uuid4()
    kb_b = uuid.uuid4()

    with admin_engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO tenants (id, name, slug, is_active) VALUES
                (:t_a, 'Tenant Alpha', :slug_a, true),
                (:t_b, 'Tenant Beta', :slug_b, true)
                ON CONFLICT (id) DO NOTHING;
            """),
            {"t_a": tenant_a, "slug_a": f"a-{uuid.uuid4().hex[:6]}", "t_b": tenant_b, "slug_b": f"b-{uuid.uuid4().hex[:6]}"},
        )
        user_id = uuid.uuid4()
        conn.execute(
            text("""
                INSERT INTO users (id, email, hashed_password, first_name, tenant_id, is_admin, is_active) VALUES
                (:u, :e, 'hash', 'U', :t_a, true, true);
            """),
            {"u": user_id, "e": f"u_{uuid.uuid4().hex[:6]}@test.com", "t_a": tenant_a},
        )
        conn.execute(
            text("""
                INSERT INTO database_knowledgebases (id, tenant_id, user_id, name, database_type, encrypted_credentials, status, is_active)
                VALUES
                (:kb_a, :t_a, :u, 'DB Alpha', 'postgresql', 'enc', 'configured', true),
                (:kb_b, :t_b, :u, 'DB Beta', 'postgresql', 'enc', 'configured', true)
                ON CONFLICT (id) DO NOTHING;
            """),
            {"kb_a": kb_a, "t_a": tenant_a, "u": user_id, "kb_b": kb_b, "t_b": tenant_b},
        )
        conn.commit()

    Session = sessionmaker(bind=non_super_engine)
    try:
        with Session() as session:
            session.execute(text("SELECT set_config('app.current_tenant', :t, true);"), {"t": str(tenant_a)})
            qm_a = KB2QueryMemory(
                id=uuid.uuid4(),
                tenant_id=tenant_a,
                db_knowledgebase_id=kb_a,
                schema_version="v1_fp",
                natural_query="Count alpha orders",
                normalized_query="count alpha orders",
                compiled_sql="SELECT COUNT(*) FROM orders",
                plan_ir={"op": "count"},
                referenced_items=["public.orders"],
            )
            session.add(qm_a)
            session.commit()

        with Session() as session:
            session.execute(text("SELECT set_config('app.current_tenant', :t, true);"), {"t": str(tenant_b)})
            qm_b = KB2QueryMemory(
                id=uuid.uuid4(),
                tenant_id=tenant_b,
                db_knowledgebase_id=kb_b,
                schema_version="v1_fp",
                natural_query="Count beta orders",
                normalized_query="count beta orders",
                compiled_sql="SELECT COUNT(*) FROM orders",
                plan_ir={"op": "count"},
                referenced_items=["public.orders"],
            )
            session.add(qm_b)
            session.commit()

        # Query Tenant A
        with Session() as session:
            session.execute(text("SELECT set_config('app.current_tenant', :t, true);"), {"t": str(tenant_a)})
            rows = session.execute(text("SELECT id, tenant_id FROM kb2_query_memory;")).fetchall()
            assert len(rows) == 1
            assert rows[0][1] == tenant_a

        # Query Tenant B
        with Session() as session:
            session.execute(text("SELECT set_config('app.current_tenant', :t, true);"), {"t": str(tenant_b)})
            rows = session.execute(text("SELECT id, tenant_id FROM kb2_query_memory;")).fetchall()
            assert len(rows) == 1
            assert rows[0][1] == tenant_b

    finally:
        with admin_engine.connect() as conn:
            conn.execute(text("DELETE FROM tenants WHERE id IN (:t_a, :t_b);"), {"t_a": tenant_a, "t_b": tenant_b})
            conn.commit()
