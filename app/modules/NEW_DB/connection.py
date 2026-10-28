"""Database Connection and Execution Helper for NEW_DB

Provides safe, pooled, and read-only database connections using asyncpg,
with credential encryption and safe connection string masking.
"""

import asyncpg
import time
import base64
import hashlib
import json
import logging
from typing import Optional, Dict, Any, List, Tuple
from cryptography.fernet import Fernet

from app.core.config import get_settings
from .schemas import DBConnectionConfig, ConnectionTestResult

logger = logging.getLogger(__name__)
settings = get_settings()


class CredentialVault:
    """Manages Fernet symmetric encryption of database passwords."""

    @classmethod
    def _get_cipher(cls) -> Fernet:
        master_key = getattr(settings, "jwt_secret_key", "default-fallback-secret-key-min-32-chars-long")
        derived_bytes = hashlib.sha256(master_key.encode("utf-8")).digest()
        fernet_key = base64.urlsafe_b64encode(derived_bytes)
        return Fernet(fernet_key)

    @classmethod
    def encrypt_config(cls, config: DBConnectionConfig) -> str:
        data = config.model_dump(mode="json")
        json_bytes = json.dumps(data).encode("utf-8")
        return cls._get_cipher().encrypt(json_bytes).decode("utf-8")

    @classmethod
    def decrypt_config(cls, encrypted_token: str) -> DBConnectionConfig:
        raw_bytes = cls._get_cipher().decrypt(encrypted_token.encode("utf-8"))
        data = json.loads(raw_bytes.decode("utf-8"))
        return DBConnectionConfig(**data)


class DatabaseConnector:
    """Handles connections and safe query execution against target databases."""

    @classmethod
    async def get_asyncpg_connection(cls, config: DBConnectionConfig) -> asyncpg.Connection:
        """Create a single asyncpg connection using connection parameters."""
        ssl_ctx = None
        if config.ssl_mode in ("require", "prefer"):
            import ssl
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        return await asyncpg.connect(
            user=config.username,
            password=config.password,
            database=config.database_name,
            host=config.host,
            port=config.port,
            timeout=config.connection_timeout,
            ssl=ssl_ctx,
        )

    @classmethod
    async def test_connection(cls, config: DBConnectionConfig) -> ConnectionTestResult:
        """Safely test connection by executing SELECT 1 and querying server version."""
        start_time = time.perf_counter()
        try:
            conn = await cls.get_asyncpg_connection(config)
            try:
                version_val = await conn.fetchval("SELECT version();")
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return ConnectionTestResult(
                    success=True,
                    latency_ms=round(elapsed_ms, 2),
                    server_version=version_val,
                )
            finally:
                await conn.close()
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.warning(f"[NEW_DB] Connection test failed for {config.masked_dsn}: {e}")
            return ConnectionTestResult(
                success=False,
                latency_ms=round(elapsed_ms, 2),
                error_message=str(e),
            )

    @classmethod
    async def execute_readonly_query(
        cls,
        config: DBConnectionConfig,
        sql: str,
        timeout_seconds: float = 30.0,
        max_rows: int = 200,
    ) -> Tuple[List[Dict[str, Any]], List[str], float, bool]:
        """
        Execute SQL query in strict READ ONLY transaction mode.
        Returns: (rows, column_names, execution_time_ms, is_truncated)
        """
        conn = await cls.get_asyncpg_connection(config)
        start_time = time.perf_counter()
        try:
            # Enforce read-only transaction and strict statement timeout
            async with conn.transaction(readonly=True):
                await conn.execute(f"SET LOCAL statement_timeout = '{int(timeout_seconds * 1000)}';")
                records = await conn.fetch(sql)

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            is_truncated = len(records) > max_rows
            capped_records = records[:max_rows]

            rows: List[Dict[str, Any]] = []
            columns: List[str] = []
            if capped_records:
                columns = list(capped_records[0].keys())
                for rec in capped_records:
                    rows.append({k: (str(v) if not isinstance(v, (int, float, bool, type(None))) else v) for k, v in dict(rec).items()})

            return rows, columns, round(elapsed_ms, 2), is_truncated
        finally:
            await conn.close()
