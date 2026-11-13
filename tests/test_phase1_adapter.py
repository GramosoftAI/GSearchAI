"""Test Phase 2 Knowledge Layer: Phase 1 Adapter Unit and Integration Tests.

Validates:
1. Mapping fake/mocked DatabaseSchema snapshot JSON to Phase 2 dataclasses:
   (SchemaView, TableView, ColumnView, FKView).
2. get_schema_version enforcing tenant isolation.
3. open_readonly_connection:
   - Sets default_transaction_read_only = 'on'
   - Sets statement_timeout = 5000 (5s)
   - Connection closed on exit
   - Zero credentials leaked outside context manager
   - Fails if tenant_id does not match
4. Integration test loading a real snapshot from the database.
"""

import uuid
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.modules.database_knowledgebase.models.database_knowledgebase import (
    DatabaseKnowledgebase,
    DatabaseSchemaSnapshot,
)
from app.modules.database_knowledgebase.security.secrets import SecretManager
from app.modules.database_knowledgebase.schemas.connection import (
    DatabaseConnectionConfig,
    DatabaseType,
    SSLMode,
)
from app.modules.database_knowledgebase.knowledge.adapters.phase1_adapter import (
    Phase1Adapter,
    SchemaView,
    TableView,
    ColumnView,
    FKView,
)

# Test throwaway database URL for adapter tests
TEST_ASYNC_DB_URL = "postgresql+asyncpg://graphmind:graphmind_password@127.0.0.1:5433/test_throwaway_kb2"


@pytest.fixture
async def async_session_factory():
    engine = create_async_engine(TEST_ASYNC_DB_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    yield session_factory
    await engine.dispose()


def test_schema_view_mapping_from_fake_snapshot():
    """Unit test: Verify that raw snapshot dictionary cleanly maps to Phase 2 dataclasses."""
    fake_data = {
        "database_name": "ecommerce_db",
        "database_type": "postgresql",
        "fingerprint": "fp_hash_12345",
        "summary": {"table_count": 2, "column_count": 5},
        "schemas": {
            "public": {
                "tables": {
                    "customers": {
                        "schema_name": "public",
                        "table_name": "customers",
                        "table_type": "TABLE",
                        "columns": {
                            "id": {
                                "name": "id",
                                "data_type": "UUID",
                                "raw_data_type": "uuid",
                                "is_nullable": False,
                                "is_primary_key": True,
                                "is_foreign_key": False,
                                "ordinal_position": 1,
                            },
                            "name": {
                                "name": "name",
                                "data_type": "VARCHAR",
                                "raw_data_type": "character varying(100)",
                                "is_nullable": True,
                                "is_primary_key": False,
                                "is_foreign_key": False,
                                "ordinal_position": 2,
                            },
                        },
                        "primary_key": {"constrained_columns": ["id"]},
                        "foreign_keys": [],
                    },
                    "orders": {
                        "schema_name": "public",
                        "table_name": "orders",
                        "table_type": "TABLE",
                        "columns": {
                            "order_id": {
                                "name": "order_id",
                                "data_type": "INTEGER",
                                "raw_data_type": "integer",
                                "is_nullable": False,
                                "is_primary_key": True,
                                "is_foreign_key": False,
                            },
                            "customer_id": {
                                "name": "customer_id",
                                "data_type": "UUID",
                                "raw_data_type": "uuid",
                                "is_nullable": False,
                                "is_primary_key": False,
                                "is_foreign_key": True,
                            },
                        },
                        "primary_key": {"constrained_columns": ["order_id"]},
                        "foreign_keys": [
                            {
                                "name": "fk_orders_customer",
                                "constrained_columns": ["customer_id"],
                                "referred_schema": "public",
                                "referred_table": "customers",
                                "referred_columns": ["id"],
                                "on_delete": "CASCADE",
                            }
                        ],
                    },
                }
            }
        },
    }

    schema_view = Phase1Adapter._map_to_schema_view(fake_data, "fp_hash_12345")
    assert isinstance(schema_view, SchemaView)
    assert schema_view.database_name == "ecommerce_db"
    assert schema_view.schema_version == "fp_hash_12345"
    assert len(schema_view.tables) == 2

    # Verify TableView
    orders = schema_view.tables["orders"]
    assert isinstance(orders, TableView)
    assert orders.primary_key_columns == ["order_id"]
    assert len(orders.foreign_keys) == 1

    fk = orders.foreign_keys[0]
    assert isinstance(fk, FKView)
    assert fk.referred_table == "customers"
    assert fk.constrained_columns == ["customer_id"]
    assert fk.referred_columns == ["id"]

    # Verify ColumnView
    cust_id_col = orders.columns["customer_id"]
    assert isinstance(cust_id_col, ColumnView)
    assert cust_id_col.data_type == "UUID"
    assert cust_id_col.is_foreign_key is True


@pytest.mark.asyncio
async def test_get_current_schema_and_version_tenant_isolation(async_session_factory):
    """Test get_current_schema and get_schema_version enforcing tenant isolation."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    kb_a = uuid.uuid4()
    user_id = uuid.uuid4()
    version_a = "fp_version_alpha_999"

    async with async_session_factory() as session:
        t_name = f"Ten A {uuid.uuid4().hex[:6]}"
        await session.execute(
            text("INSERT INTO tenants (id, name, slug, is_active) VALUES (:t, :n, :slug, true);"),
            {"t": tenant_a, "n": t_name, "slug": f"ten-{uuid.uuid4().hex[:6]}"},
        )
        await session.execute(
            text("INSERT INTO users (id, email, hashed_password, first_name, tenant_id, is_admin, is_active) "
                 "VALUES (:u, :e, 'hash', 'U', :t, true, true);"),
            {"u": user_id, "e": f"u_{uuid.uuid4().hex[:6]}@test.com", "t": tenant_a},
        )
        await session.execute(
            text("""
                INSERT INTO database_knowledgebases (id, tenant_id, user_id, name, database_type, encrypted_credentials, status, schema_version, is_active)
                VALUES (:kb, :t, :u, 'Alpha DB', 'postgresql', 'dummy_enc', 'configured', :v, true);
            """),
            {"kb": kb_a, "t": tenant_a, "u": user_id, "v": version_a},
        )
        # Seed snapshot
        snapshot = DatabaseSchemaSnapshot(
            id=uuid.uuid4(),
            tenant_id=tenant_a,
            db_knowledgebase_id=kb_a,
            schema_version=version_a,
            schema_data={
                "database_name": "alpha_db",
                "database_type": "postgresql",
                "schemas": {
                    "public": {
                        "tables": {
                            "items": {
                                "schema_name": "public",
                                "table_name": "items",
                                "table_type": "TABLE",
                                "columns": {
                                    "id": {"name": "id", "data_type": "INTEGER", "is_primary_key": True}
                                },
                            }
                        }
                    }
                },
            },
            table_count=1,
            column_count=1,
            relationship_count=0,
        )
        session.add(snapshot)
        await session.commit()

    async with async_session_factory() as session:
        adapter = Phase1Adapter(session=session)

        # 1. Tenant A successfully retrieves version and schema
        ver = await adapter.get_schema_version(tenant_id=tenant_a, kb_id=kb_a)
        assert ver == version_a

        schema_view = await adapter.get_current_schema(tenant_id=tenant_a, kb_id=kb_a)
        assert schema_view.schema_version == version_a
        assert "items" in schema_view.tables

        # 2. Tenant B is rejected (raises ValueError due to tenant isolation)
        with pytest.raises(ValueError, match="No schema version found"):
            await adapter.get_schema_version(tenant_id=tenant_b, kb_id=kb_a)

        with pytest.raises(ValueError, match="No schema snapshot found"):
            await adapter.get_current_schema(tenant_id=tenant_b, kb_id=kb_a)

    # Cleanup
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t;"), {"t": tenant_a})
        await session.commit()


@pytest.mark.asyncio
async def test_open_readonly_connection_attributes_and_closure(async_session_factory):
    """Test open_readonly_connection connects with read-only & timeout settings and closes cleanly."""
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()

    # Create real valid credentials pointing to test throwaway DB
    secrets = SecretManager()
    cfg = DatabaseConnectionConfig(
        db_type=DatabaseType.POSTGRESQL,
        host="127.0.0.1",
        port=5433,
        database_name="test_throwaway_kb2",
        username="graphmind",
        password="graphmind_password",
        ssl_mode=SSLMode.DISABLE,
        connection_timeout=5,
    )
    enc_creds = secrets.encrypt_credentials(cfg)

    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, slug, is_active) VALUES (:t, 'Ten Conn', :slug, true);"),
            {"t": tenant_id, "slug": f"ten-{uuid.uuid4().hex[:6]}"},
        )
        await session.execute(
            text("INSERT INTO users (id, email, hashed_password, first_name, tenant_id, is_admin, is_active) "
                 "VALUES (:u, :e, 'hash', 'U', :t, true, true);"),
            {"u": user_id, "e": f"u_{uuid.uuid4().hex[:6]}@test.com", "t": tenant_id},
        )
        await session.execute(
            text("""
                INSERT INTO database_knowledgebases (id, tenant_id, user_id, name, database_type, encrypted_credentials, status, is_active)
                VALUES (:kb, :t, :u, 'Conn DB', 'postgresql', :enc, 'configured', true);
            """),
            {"kb": kb_id, "t": tenant_id, "u": user_id, "enc": enc_creds},
        )
        await session.commit()

    async with async_session_factory() as session:
        adapter = Phase1Adapter(session=session, secret_manager=secrets)

        captured_conn = None
        async with adapter.open_readonly_connection(tenant_id=tenant_id, kb_id=kb_id) as conn:
            captured_conn = conn
            assert not conn.is_closed()

            # Verify read-only is on
            ro_setting = await conn.fetchval("SHOW default_transaction_read_only;")
            assert ro_setting == "on"

            # Verify statement timeout is 5s (5000ms)
            to_setting = await conn.fetchval("SHOW statement_timeout;")
            assert to_setting in ("5000ms", "5s")

            # Verify write operation is blocked by read-only
            with pytest.raises(Exception):
                await conn.execute("CREATE TABLE should_fail_readonly(id int);")

        # After exiting context manager, connection MUST be closed
        assert captured_conn is not None
        assert captured_conn.is_closed()

        # Wrong tenant must be denied access
        wrong_tenant = uuid.uuid4()
        with pytest.raises(PermissionError, match="Access denied"):
            async with adapter.open_readonly_connection(tenant_id=wrong_tenant, kb_id=kb_id):
                pass

    # Cleanup
    async with async_session_factory() as session:
        await session.execute(text("DELETE FROM tenants WHERE id = :t;"), {"t": tenant_id})
        await session.commit()


@pytest.mark.asyncio
async def test_load_snapshot_integration(async_session_factory):
    """Integration test: Load a database snapshot seeded in throwaway DB and verify mapped SchemaView."""
    tenant_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    user_id = uuid.uuid4()
    expected_fp = f"fp_int_{uuid.uuid4().hex}"

    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, slug, is_active) VALUES (:t, 'Ten Real Test', :slug, true);"),
            {"t": tenant_id, "slug": f"ten-{uuid.uuid4().hex[:6]}"},
        )
        await session.execute(
            text("INSERT INTO users (id, email, hashed_password, first_name, tenant_id, is_admin, is_active) "
                 "VALUES (:u, :e, 'hash', 'U', :t, true, true);"),
            {"u": user_id, "e": f"u_{uuid.uuid4().hex[:6]}@test.com", "t": tenant_id},
        )
        await session.execute(
            text("""
                INSERT INTO database_knowledgebases (id, tenant_id, user_id, name, database_type, encrypted_credentials, status, schema_version, is_active)
                VALUES (:kb, :t, :u, 'Seeded DB', 'postgresql', 'dummy_enc', 'configured', :v, true);
            """),
            {"kb": kb_id, "t": tenant_id, "u": user_id, "v": expected_fp},
        )
        snapshot = DatabaseSchemaSnapshot(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            db_knowledgebase_id=kb_id,
            schema_version=expected_fp,
            schema_data={
                "database_name": "seeded_db",
                "database_type": "postgresql",
                "introspected_at": "2026-10-06T12:00:00Z",
                "summary": {"table_count": 2, "column_count": 4, "foreign_key_count": 1},
                "schemas": {
                    "public": {
                        "tables": {
                            "departments": {
                                "schema_name": "public",
                                "table_name": "departments",
                                "table_type": "TABLE",
                                "columns": {
                                    "id": {
                                        "name": "id",
                                        "data_type": "INTEGER",
                                        "raw_data_type": "integer",
                                        "is_nullable": False,
                                        "is_primary_key": True,
                                        "is_foreign_key": False,
                                    },
                                    "dept_name": {
                                        "name": "dept_name",
                                        "data_type": "VARCHAR",
                                        "raw_data_type": "varchar(100)",
                                        "is_nullable": False,
                                        "is_primary_key": False,
                                        "is_foreign_key": False,
                                    },
                                },
                                "primary_key": {"constrained_columns": ["id"]},
                                "foreign_keys": [],
                            },
                            "employees": {
                                "schema_name": "public",
                                "table_name": "employees",
                                "table_type": "TABLE",
                                "columns": {
                                    "id": {
                                        "name": "id",
                                        "data_type": "INTEGER",
                                        "raw_data_type": "integer",
                                        "is_nullable": False,
                                        "is_primary_key": True,
                                        "is_foreign_key": False,
                                    },
                                    "dept_id": {
                                        "name": "dept_id",
                                        "data_type": "INTEGER",
                                        "raw_data_type": "integer",
                                        "is_nullable": True,
                                        "is_primary_key": False,
                                        "is_foreign_key": True,
                                    },
                                },
                                "primary_key": {"constrained_columns": ["id"]},
                                "foreign_keys": [
                                    {
                                        "name": "fk_emp_dept",
                                        "constrained_columns": ["dept_id"],
                                        "referred_schema": "public",
                                        "referred_table": "departments",
                                        "referred_columns": ["id"],
                                    }
                                ],
                            },
                        }
                    }
                },
            },
            table_count=2,
            column_count=4,
            relationship_count=1,
        )
        session.add(snapshot)
        await session.commit()

    try:
        async with async_session_factory() as session:
            adapter = Phase1Adapter(session=session)

            # 1. Fetch version
            version = await adapter.get_schema_version(tenant_id=tenant_id, kb_id=kb_id)
            assert version == expected_fp

            # 2. Fetch full mapped schema
            schema_view = await adapter.get_current_schema(tenant_id=tenant_id, kb_id=kb_id)
            assert isinstance(schema_view, SchemaView)
            assert schema_view.database_name == "seeded_db"
            assert schema_view.schema_version == expected_fp
            assert len(schema_view.tables) == 2

            # Verify tables & FKs
            assert "departments" in schema_view.tables
            assert "employees" in schema_view.tables
            emp_tbl = schema_view.tables["employees"]
            assert len(emp_tbl.foreign_keys) == 1
            assert emp_tbl.foreign_keys[0].referred_table == "departments"
    finally:
        async with async_session_factory() as session:
            await session.execute(text("DELETE FROM tenants WHERE id = :t;"), {"t": tenant_id})
            await session.commit()
