import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.modules.database_knowledgebase.schemas.connection import DatabaseConnectionConfig, SSLMode
from app.modules.database_knowledgebase.disambiguation.collision_detector import CollisionDetector
from app.modules.database_knowledgebase.disambiguation.exceptions import DisambiguationRequiredError
from app.modules.database_knowledgebase.schemas.canonical import (
    DatabaseSchema,
    SchemaInfo,
    TableSchema,
    ColumnSchema,
    ColumnDataType,
)

def build_mock_schema():
    tbl_people = TableSchema(
        schema_name="public",
        table_name="staff_members",
        columns={
            "member_id": ColumnSchema(
                name="member_id",
                data_type=ColumnDataType.INTEGER,
                raw_data_type="integer",
                is_primary_key=True,
            ),
            "first_name": ColumnSchema(
                name="first_name",
                data_type=ColumnDataType.VARCHAR,
                raw_data_type="varchar(50)",
            ),
            "last_name": ColumnSchema(
                name="last_name",
                data_type=ColumnDataType.VARCHAR,
                raw_data_type="varchar(50)",
            ),
        },
    )
    return DatabaseSchema(
        database_name="test_db",
        schemas={"public": SchemaInfo(schema_name="public", tables={"staff_members": tbl_people})},
    )

def test_discover_person_table_dynamic():
    schema = build_mock_schema()
    discovery = CollisionDetector.discover_person_table_and_columns(schema)
    assert discovery is not None
    table_name, pk_col, name_cols = discovery
    assert table_name == "staff_members"
    assert pk_col == "member_id"
    assert "first_name" in name_cols
    assert "last_name" in name_cols

def test_discover_person_table_skipped_when_none():
    discovery = CollisionDetector.discover_person_table_and_columns(None)
    assert discovery is None

@pytest.mark.asyncio
async def test_collision_detector_drops_non_matching_name():
    schema = build_mock_schema()
    kb_entity = MagicMock()
    kb_entity.encrypted_credentials = "enc_creds"
    kb_entity.tenant_id = "t1"
    kb_entity.id = "kb1"

    secret_mgr = MagicMock()
    secret_mgr.decrypt_credentials.return_value = DatabaseConnectionConfig(
        host="127.0.0.1",
        port=5432,
        username="db_user",
        password="db_password",
        database_name="app_db",
    )

    with patch("app.modules.database_knowledgebase.disambiguation.collision_detector.connect_to_database", new_callable=AsyncMock) as mock_connect:
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = []  # 0 rows returned
        mock_connect.return_value = mock_conn

        res = await CollisionDetector.check_for_user_collisions(
            extracted_name="details",
            kb_entity=kb_entity,
            secret_manager=secret_mgr,
            canonical_schema=schema,
        )
        assert res is None  # Dropped!

@pytest.mark.asyncio
async def test_collision_detector_resolves_single_match():
    schema = build_mock_schema()
    kb_entity = MagicMock()
    kb_entity.encrypted_credentials = "enc_creds"
    kb_entity.tenant_id = "t1"
    kb_entity.id = "kb1"

    secret_mgr = MagicMock()
    secret_mgr.decrypt_credentials.return_value = DatabaseConnectionConfig(
        host="127.0.0.1",
        port=5432,
        username="db_user",
        password="db_password",
        database_name="app_db",
    )

    with patch("app.modules.database_knowledgebase.disambiguation.collision_detector.connect_to_database", new_callable=AsyncMock) as mock_connect:
        mock_conn = AsyncMock()
        mock_conn.fetch.return_value = [{"member_id": 42, "first_name": "Girinath", "last_name": "K"}]
        mock_connect.return_value = mock_conn

        res = await CollisionDetector.check_for_user_collisions(
            extracted_name="girinath",
            kb_entity=kb_entity,
            secret_manager=secret_mgr,
            canonical_schema=schema,
        )
        assert res == 42

@pytest.mark.asyncio
async def test_collision_detector_fails_loudly_on_connection_error():
    schema = build_mock_schema()
    kb_entity = MagicMock()
    kb_entity.encrypted_credentials = "enc_creds"
    kb_entity.tenant_id = "t1"
    kb_entity.id = "kb1"

    secret_mgr = MagicMock()
    secret_mgr.decrypt_credentials.return_value = DatabaseConnectionConfig(
        host="bad.host.internal",
        port=5432,
        username="db_user",
        password="p@ss:word",
        database_name="app_db",
    )

    notices = []
    with patch("app.modules.database_knowledgebase.disambiguation.collision_detector.connect_to_database", side_effect=Exception("getaddrinfo failed")):
        with patch("app.modules.database_knowledgebase.disambiguation.collision_detector.DatabaseAuditLogger.emit_event") as mock_audit:
            res = await CollisionDetector.check_for_user_collisions(
                extracted_name="girinath",
                kb_entity=kb_entity,
                secret_manager=secret_mgr,
                canonical_schema=schema,
                notices_out=notices,
            )
            assert res is None
            assert len(notices) == 1
            assert "unavailable" in notices[0].lower()
            mock_audit.assert_called_once()
            _, kwargs = mock_audit.call_args
            assert kwargs["event_name"] == "DISAMBIGUATION_UNAVAILABLE"
