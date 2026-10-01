import pytest
from unittest.mock import AsyncMock, patch
from app.modules.database_knowledgebase.schemas.connection import DatabaseConnectionConfig, SSLMode
from app.modules.database_knowledgebase.execution.connection_helper import (
    connect_to_database,
    resolve_ssl_mode,
)
from app.modules.database_knowledgebase.execution.executor import ReadOnlyDatabaseExecutor

def test_resolve_ssl_mode():
    assert resolve_ssl_mode(SSLMode.DISABLE) is None
    assert resolve_ssl_mode(SSLMode.REQUIRE) == "require"
    assert resolve_ssl_mode(SSLMode.PREFER) == "prefer"

@pytest.mark.asyncio
async def test_connect_to_database_discrete_params():
    db_config = DatabaseConnectionConfig(
        host="db.example.com",
        port=5432,
        username="my_user",
        password="p@ss:word/with@special#chars",
        database_name="app_db",
        ssl_mode=SSLMode.REQUIRE,
    )
    with patch("asyncpg.connect", new_callable=AsyncMock) as mock_connect:
        mock_conn = AsyncMock()
        mock_connect.return_value = mock_conn
        
        conn = await connect_to_database(db_config, timeout_seconds=5.0)
        assert conn == mock_conn
        mock_connect.assert_called_once()
        _, kwargs = mock_connect.call_args
        assert kwargs["host"] == "db.example.com"
        assert kwargs["port"] == 5432
        assert kwargs["user"] == "my_user"
        assert kwargs["password"] == "p@ss:word/with@special#chars"
        assert kwargs["database"] == "app_db"
        assert kwargs["ssl"] == "require"
        assert kwargs["server_settings"]["default_transaction_read_only"] == "on"

@pytest.mark.asyncio
async def test_executor_uses_shared_helper():
    db_config = DatabaseConnectionConfig(
        host="127.0.0.1",
        port=5432,
        username="test_user",
        password="secret_password",
        database_name="test_db",
        ssl_mode=SSLMode.DISABLE,
    )
    executor = ReadOnlyDatabaseExecutor()
    with patch("app.modules.database_knowledgebase.execution.executor.connect_to_database", new_callable=AsyncMock) as mock_helper:
        mock_conn = AsyncMock()
        mock_helper.return_value = mock_conn
        conn = await executor._acquire_connection(db_config)
        assert conn == mock_conn
        mock_helper.assert_called_once()
