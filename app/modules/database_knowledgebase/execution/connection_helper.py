"""Shared connection helper for external PostgreSQL databases.

Enforces discrete connection arguments (host, port, user, password, database, ssl)
to avoid URI / DSN parsing errors when passwords or usernames contain reserved characters.
"""

import asyncio
import logging
from typing import Any, Dict, Optional
import asyncpg

from ..schemas.connection import DatabaseConnectionConfig, SSLMode
from ..security.sanitizer import sanitize_error_message
from .errors import QueryConnectionError

logger = logging.getLogger(__name__)


def resolve_ssl_mode(ssl_mode: SSLMode) -> Optional[str]:
    """Convert SSLMode enum to asyncpg ssl argument string or None."""
    if ssl_mode == SSLMode.DISABLE:
        return None
    elif ssl_mode in (SSLMode.REQUIRE, SSLMode.VERIFY_CA, SSLMode.VERIFY_FULL):
        return "require"
    elif ssl_mode == SSLMode.PREFER:
        return "prefer"
    return None


async def connect_to_database(
    db_config: DatabaseConnectionConfig,
    timeout_seconds: float = 10.0,
    statement_timeout_ms: Optional[float] = None,
    server_settings: Optional[Dict[str, str]] = None,
    read_only: bool = True,
) -> asyncpg.Connection:
    """
    Establish a dedicated asyncpg connection using discrete connection parameters.
    
    CRITICAL: Never formats a string DSN with credentials. Passing discrete parameters
    guarantees that passwords with special characters (e.g., '@', ':', '/') do not
    corrupt host/port resolution and cause getaddrinfo errors.
    """
    logger.info(
        f"[DB_CONNECT] Connecting to external database host='{db_config.host}', port={db_config.port}, "
        f"db='{db_config.database_name}', user='{db_config.username}', ssl_mode='{db_config.ssl_mode}'"
    )

    ssl_val = resolve_ssl_mode(db_config.ssl_mode)
    
    settings = dict(server_settings or {})
    if read_only:
        settings["default_transaction_read_only"] = "on"

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
