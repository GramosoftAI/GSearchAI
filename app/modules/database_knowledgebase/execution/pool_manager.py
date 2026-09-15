"""Phase 3C Bounded Read-Only Connection Pool Manager

Provides pooled, tenant-isolated, bounded asyncpg connection pools for target relational databases.
Strictly enforces driver-level read-only transaction semantics on every pooled connection
(`default_transaction_read_only = 'on'`), statement timeouts, and connection bounds.
"""

import asyncio
from contextlib import asynccontextmanager
import hashlib
import logging
from typing import Any, AsyncIterator, Dict, Optional, Tuple
import uuid
import asyncpg

from ..schemas.connection import DatabaseConnectionConfig, SSLMode
from .errors import QueryConnectionError
from .models import ExecutionConfig
from .timeout import TimeoutManager
from ..security.sanitizer import sanitize_error_message

logger = logging.getLogger(__name__)


class ReadOnlyPoolManager:
    """
    Thread-safe, tenant-isolated connection pool manager for target PostgreSQL databases.
    Pools are strictly isolated by (tenant_id, knowledgebase_id, credential_fingerprint).
    """

    _instance: Optional["ReadOnlyPoolManager"] = None
    _singleton_lock = asyncio.Lock()

    def __init__(self, min_size: int = 2, max_size: int = 10, pool_timeout_seconds: float = 5.0):
        self.min_size = min_size
        self.max_size = max_size
        self.pool_timeout_seconds = pool_timeout_seconds
        self._pools: Dict[str, asyncpg.Pool] = {}
        self._pool_metadata: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    @classmethod
    async def get_instance(
        cls,
        min_size: int = 2,
        max_size: int = 10,
        pool_timeout_seconds: float = 5.0,
    ) -> "ReadOnlyPoolManager":
        """Asynchronous singleton accessor."""
        if cls._instance is None:
            async with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = cls(
                        min_size=min_size,
                        max_size=max_size,
                        pool_timeout_seconds=pool_timeout_seconds,
                    )
        return cls._instance

    @classmethod
    def get_instance_sync(cls) -> "ReadOnlyPoolManager":
        """Synchronous singleton accessor for existing instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    async def reset_instance(cls) -> None:
        """Testing utility to close all active pools and clear singleton."""
        if cls._instance is not None:
            await cls._instance.close_all_pools()
            async with cls._singleton_lock:
                cls._instance = None

    @staticmethod
    def _resolve_ssl(db_config: DatabaseConnectionConfig) -> Optional[str]:
        """Convert SSLMode to asyncpg ssl argument."""
        if db_config.ssl_mode == SSLMode.DISABLE:
            return None
        elif db_config.ssl_mode in (SSLMode.REQUIRE, SSLMode.VERIFY_CA, SSLMode.VERIFY_FULL):
            return "require"
        elif db_config.ssl_mode == SSLMode.PREFER:
            return "prefer"
        return None

    @classmethod
    def generate_pool_key(
        cls,
        tenant_id: str,
        kb_id: uuid.UUID,
        db_config: DatabaseConnectionConfig,
    ) -> str:
        """
        Generate cryptographic isolation key ensuring connections cannot cross
        tenant boundaries, knowledge base boundaries, or credential revisions.
        """
        cred_blob = f"{db_config.host}:{db_config.port}:{db_config.database_name}:{db_config.username}:{db_config.raw_password}"
        cred_hash = hashlib.sha256(cred_blob.encode("utf-8")).hexdigest()[:16]
        return f"tenant:{str(tenant_id)}|kb:{str(kb_id)}|creds:{cred_hash}"

    async def get_or_create_pool(
        self,
        tenant_id: str,
        kb_id: uuid.UUID,
        db_config: DatabaseConnectionConfig,
        config: ExecutionConfig,
    ) -> asyncpg.Pool:
        """
        Retrieve existing connection pool or establish a new bounded read-only pool.
        Enforces server_settings with default_transaction_read_only='on'.
        """
        pool_key = self.generate_pool_key(tenant_id, kb_id, db_config)

        # Fast path check
        pool = self._pools.get(pool_key)
        if pool is not None:
            return pool

        async with self._lock:
            # Re-check under lock
            if pool_key in self._pools:
                return self._pools[pool_key]

            ssl_val = self._resolve_ssl(db_config)
            session_settings = TimeoutManager.get_session_settings(config)
            # HARD INVARIANT: Read-only transaction enforcement at session level
            session_settings["default_transaction_read_only"] = "on"

            logger.info(
                f"Creating bounded read-only connection pool for KB {kb_id} "
                f"(min={self.min_size}, max={self.max_size}, tenant={tenant_id})"
            )

            try:
                new_pool = await asyncpg.create_pool(
                    host=db_config.host,
                    port=db_config.port,
                    user=db_config.username,
                    password=db_config.raw_password,
                    database=db_config.database_name,
                    ssl=ssl_val,
                    min_size=self.min_size,
                    max_size=self.max_size,
                    max_inactive_connection_lifetime=300.0,
                    command_timeout=config.statement_timeout_ms / 1000.0,
                    server_settings=session_settings,
                    timeout=self.pool_timeout_seconds,
                )
                self._pools[pool_key] = new_pool
                self._pool_metadata[pool_key] = {
                    "tenant_id": str(tenant_id),
                    "kb_id": str(kb_id),
                    "created_at": asyncio.get_event_loop().time(),
                }
                return new_pool

            except Exception as e:
                safe_msg = sanitize_error_message(e)
                logger.error(f"Failed to create read-only connection pool: {safe_msg}")
                raise QueryConnectionError(
                    detail=f"Failed to establish read-only connection pool: {safe_msg}"
                ) from e

    @asynccontextmanager
    async def acquire(
        self,
        tenant_id: str,
        kb_id: uuid.UUID,
        db_config: DatabaseConnectionConfig,
        config: Optional[ExecutionConfig] = None,
    ) -> AsyncIterator[asyncpg.Connection]:
        """
        Acquire a pooled connection with strict timeout and lease lifecycle management.
        Guarantees release back to pool upon context manager exit.
        """
        exec_config = config or ExecutionConfig()
        pool = await self.get_or_create_pool(tenant_id, kb_id, db_config, exec_config)

        conn: Optional[asyncpg.Connection] = None
        try:
            conn = await asyncio.wait_for(
                pool.acquire(),
                timeout=self.pool_timeout_seconds,
            )
            yield conn

        except asyncio.TimeoutError as e:
            logger.warning(
                f"Connection pool exhausted for KB {kb_id} (timeout after {self.pool_timeout_seconds}s)"
            )
            raise QueryConnectionError(
                detail=f"Read-only database connection pool exhausted for KB '{kb_id}'. "
                       f"All {self.max_size} connections are busy."
            ) from e
        finally:
            if conn is not None:
                try:
                    await pool.release(conn)
                except Exception as exc:
                    logger.debug(f"Error releasing connection back to pool: {exc}")

    async def close_pool(self, tenant_id: str, kb_id: uuid.UUID) -> bool:
        """Close and discard a specific knowledgebase pool."""
        tid = str(tenant_id)
        kid = str(kb_id)
        closed = False

        async with self._lock:
            keys_to_remove = [
                k for k, meta in self._pool_metadata.items()
                if meta["tenant_id"] == tid and meta["kb_id"] == kid
            ]
            for key in keys_to_remove:
                pool = self._pools.pop(key, None)
                self._pool_metadata.pop(key, None)
                if pool:
                    try:
                        await pool.close()
                        closed = True
                    except Exception as e:
                        logger.warning(f"Error closing pool for {key}: {e}")
        return closed

    async def close_all_pools(self) -> int:
        """Gracefully close all active connection pools."""
        count = 0
        async with self._lock:
            for key, pool in list(self._pools.items()):
                try:
                    await pool.close()
                    count += 1
                except Exception as e:
                    logger.warning(f"Error closing pool {key}: {e}")
            self._pools.clear()
            self._pool_metadata.clear()
        return count

    def get_pool_status(self, tenant_id: str, kb_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Return operational pool telemetry for a specific knowledgebase."""
        tid = str(tenant_id)
        kid = str(kb_id)

        for key, meta in self._pool_metadata.items():
            if meta["tenant_id"] == tid and meta["kb_id"] == kid:
                pool = self._pools.get(key)
                if pool:
                    return {
                        "is_pooled": True,
                        "pool_key": key[:32] + "...",
                        "size": pool.get_size(),
                        "idle": pool.get_idle_size(),
                        "min_size": pool.get_min_size(),
                        "max_size": pool.get_max_size(),
                    }
        return None
