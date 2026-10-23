"""Shared connection helper for external PostgreSQL databases.

Enforces discrete connection arguments (host, port, user, password, database, ssl)
to avoid URI / DSN parsing errors when passwords or usernames contain reserved characters.
"""

import asyncio
import logging
import ssl
from typing import Any, Dict, Optional
import asyncpg
import asyncmy
from asyncmy.cursors import DictCursor

from ..schemas.connection import DatabaseConnectionConfig, DatabaseType, SSLMode
from ..security.sanitizer import sanitize_error_message
from .errors import QueryConnectionError

logger = logging.getLogger(__name__)


def resolve_ssl_mode(ssl_mode: SSLMode) -> Any:
    """Convert SSLMode enum to asyncpg ssl argument string or False."""
    if ssl_mode == SSLMode.DISABLE:
        return False
    elif ssl_mode in (SSLMode.REQUIRE, SSLMode.VERIFY_CA, SSLMode.VERIFY_FULL):
        return "require"
    elif ssl_mode == SSLMode.PREFER:
        return "prefer"
    return False


async def connect_to_database(
    db_config: DatabaseConnectionConfig,
    timeout_seconds: float = 10.0,
    statement_timeout_ms: Optional[float] = None,
    server_settings: Optional[Dict[str, str]] = None,
    read_only: bool = True,
    tenant_id: Optional[str] = None,
) -> Any:
    """
    Establish a dedicated connection using discrete connection parameters.
    Supports PostgreSQL (via asyncpg) and MariaDB/MySQL (via asyncmy).
    
    CRITICAL: Never formats a string DSN with credentials. Passing discrete parameters
    guarantees that passwords with special characters do not corrupt host/port resolution.
    """
    logger.info(
        f"[DB_CONNECT] Connecting to external database type='{db_config.db_type}' host='{db_config.host}', port={db_config.port}, "
        f"db='{db_config.database_name}', user='{db_config.username}', ssl_mode='{db_config.ssl_mode}'"
    )

    if db_config.db_type in (DatabaseType.MARIADB, DatabaseType.MYSQL) or getattr(db_config, "port", None) in (3306, 3307):
        ssl_ctx = None
        if db_config.ssl_mode != SSLMode.DISABLE:
            try:
                ssl_ctx = ssl.create_default_context()
                if db_config.ssl_mode in (SSLMode.DISABLE, SSLMode.ALLOW, SSLMode.PREFER):
                    ssl_ctx.check_hostname = False
                    ssl_ctx.verify_mode = ssl.CERT_NONE
            except Exception:
                ssl_ctx = None

        try:
            conn = await asyncio.wait_for(
                asyncmy.connect(
                    host=db_config.host,
                    port=db_config.port or 3306,
                    user=db_config.username,
                    password=db_config.raw_password,
                    database=db_config.database_name,
                    connect_timeout=timeout_seconds,
                    ssl=ssl_ctx,
                    autocommit=True,
                    cursor_cls=DictCursor,
                ),
                timeout=timeout_seconds + 1.0,
            )
            return conn
        except asyncio.TimeoutError as e:
            logger.warning(f"Connection timeout to {db_config.masked_dsn}")
            raise QueryConnectionError(
                detail=f"Connection to database timed out after {timeout_seconds}s.",
            ) from e
        except Exception as e:
            safe_msg = sanitize_error_message(e)
            logger.error(f"MariaDB connection failure: {safe_msg}")
            raise QueryConnectionError(
                detail=f"Database connection error: {safe_msg}",
            ) from e

    # Default path: PostgreSQL via asyncpg
    ssl_val = resolve_ssl_mode(db_config.ssl_mode)
    
    settings = dict(server_settings or {})
    if read_only:
        settings["default_transaction_read_only"] = "on"
    if "app.current_tenant" not in settings or not settings["app.current_tenant"]:
        settings["app.current_tenant"] = str(tenant_id or "00000000-0000-0000-0000-000000000000")

    command_timeout = (statement_timeout_ms / 1000.0) if statement_timeout_ms is not None else None

    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(
                host=db_config.host,
                port=db_config.port,
                user=db_config.username,
                password=db_config.raw_password,
                database=db_config.database_name,
                ssl=ssl_val,
                timeout=timeout_seconds,
                command_timeout=command_timeout,
                server_settings=settings if settings else None,
            ),
            timeout=timeout_seconds + 1.0,
        )
        return conn
    except asyncio.TimeoutError as e:
        logger.warning(f"Connection timeout to {db_config.masked_dsn}")
        raise QueryConnectionError(
            detail=f"Connection to database timed out after {timeout_seconds}s.",
        ) from e
    except asyncpg.PostgresError as e:
        safe_msg = sanitize_error_message(e)
        logger.warning(f"PostgreSQL connection failed: {safe_msg}")
        raise QueryConnectionError(
            detail=f"Failed to connect to database: {safe_msg}",
        ) from e
    except Exception as e:
        safe_msg = sanitize_error_message(e)
        logger.error(f"Unexpected connection failure: {safe_msg}")
        raise QueryConnectionError(
            detail=f"Database connection error: {safe_msg}",
        ) from e
