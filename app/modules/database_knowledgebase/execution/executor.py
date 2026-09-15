"""Phase 2C Read-Only Database Executor

Executes authorized ValidatedCandidateSQL within a strict, driver-level read-only
PostgreSQL transaction. Enforces connection lifecycle, transaction rollback, statement
timeouts, result normalization, and produces CanonicalQueryResult.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional
import uuid
import asyncpg

from ..schemas.connection import DatabaseConnectionConfig, SSLMode
from ..security.sanitizer import sanitize_error_message
from ..sql_generator.repair import ValidatedCandidateSQL
from .errors import (
    ExecutionPolicyViolation,
    QueryConnectionError,
    QueryExecutionError,
    QueryExecutionTimeout,
)
from .models import CanonicalQueryResult, ExecutionAuditRecord, ExecutionAuthorization, ExecutionConfig
from .policy import ExecutionPolicyEngine
from .pool_manager import ReadOnlyPoolManager
from .result_limiter import ResultLimiter
from .result_validator import ResultValidator
from .timeout import TimeoutManager
from .transaction import TransactionManager

logger = logging.getLogger(__name__)


class ReadOnlyDatabaseExecutor:
    """
    Orchestrates the safe, read-only physical execution of SQL queries on PostgreSQL.
    Leverages bounded read-only connection pooling with transparent fallback.
    """

    def __init__(
        self,
        execution_config: Optional[ExecutionConfig] = None,
        use_pooling: bool = True,
    ):
        self.config = execution_config or ExecutionConfig()
        self.use_pooling = use_pooling

    def _resolve_ssl(self, db_config: DatabaseConnectionConfig) -> Optional[str]:
        """Convert SSLMode to asyncpg ssl argument."""
        if db_config.ssl_mode == SSLMode.DISABLE:
            return None
        elif db_config.ssl_mode in (SSLMode.REQUIRE, SSLMode.VERIFY_CA, SSLMode.VERIFY_FULL):
            return "require"
        elif db_config.ssl_mode == SSLMode.PREFER:
            return "prefer"
        return None

    async def _acquire_connection(self, db_config: DatabaseConnectionConfig) -> asyncpg.Connection:
        """Establish a dedicated read-only asyncpg connection (unpooled path)."""
        ssl_val = self._resolve_ssl(db_config)
        session_settings = TimeoutManager.get_session_settings(self.config)
        session_settings["default_transaction_read_only"] = "on"

        try:
            conn = await asyncio.wait_for(
                asyncpg.connect(
                    host=db_config.host,
                    port=db_config.port,
                    user=db_config.username,
                    password=db_config.raw_password,
                    database=db_config.database_name,
                    ssl=ssl_val,
                    timeout=self.config.connection_timeout_seconds,
                    command_timeout=self.config.statement_timeout_ms / 1000.0,
                    server_settings=session_settings,
                ),
                timeout=self.config.connection_timeout_seconds + 1.0,
            )
            return conn
        except asyncio.TimeoutError as e:
            logger.warning(f"Connection timeout to {db_config.masked_dsn}")
            raise QueryConnectionError(
                detail=f"Connection to database timed out after {self.config.connection_timeout_seconds}s.",
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

    async def _execute_on_connection(
        self,
        conn: asyncpg.Connection,
        candidate_sql: ValidatedCandidateSQL,
        authorization: ExecutionAuthorization,
        query_id: str,
        t0: float,
        is_pooled: bool = False,
    ) -> CanonicalQueryResult:
        """Execute validated query on active read-only connection and normalize results."""
        # 1. Translate Named Parameters (:p1 -> $1)
        param_sql = candidate_sql.parameterized.parameterized_sql
        params = candidate_sql.parameterized.parameters or {}
        converted_sql, pos_args = TransactionManager.translate_parameters(param_sql, params)

        logger.info(f"EXECUTING SQL: {converted_sql} WITH ARGS: {pos_args}")
        timeout_sec = self.config.statement_timeout_ms / 1000.0
        records = await TransactionManager.execute_in_readonly_transaction(
            conn=conn,
            sql=converted_sql,
            args=pos_args,
            timeout_seconds=timeout_sec,
        )

        # 3. Result Validation and Type Normalization
        columns, column_types, normalized_rows, val_warnings = ResultValidator.validate_and_normalize(
            records=records,
            config=self.config,
            authorized_columns=authorization.authorized_columns,
        )
        warnings = list(val_warnings)

        # 4. Apply Resource Bounds (Row count and serialized size limits)
        bounded_rows, is_truncated, limit_warnings = ResultLimiter.apply_limits(
            rows=normalized_rows,
            config=self.config,
        )
        warnings.extend(limit_warnings)

        duration_ms = (time.perf_counter() - t0) * 1000.0

        # 5. Construct CanonicalQueryResult
        return CanonicalQueryResult(
            query_id=query_id,
            database_knowledgebase_id=authorization.knowledgebase_id,
            schema_version=authorization.schema_version,
            columns=columns,
            column_types=column_types,
            rows=bounded_rows,
            row_count=len(bounded_rows),
            truncated=is_truncated,
            execution_time_ms=round(duration_ms, 2),
            warnings=warnings,
            audit_metadata={
                "tenant_id": authorization.tenant_id,
                "query_hash": authorization.query_hash,
                "raw_row_count": len(records),
                "is_pooled": is_pooled,
            },
        )

    async def execute(
        self,
        candidate_sql: ValidatedCandidateSQL,
        authorization: ExecutionAuthorization,
        db_config: DatabaseConnectionConfig,
    ) -> CanonicalQueryResult:
        """
        Execute an authorized candidate query within a dedicated read-only transaction.
        Guarantees connection cleanup, error sanitization, and result normalization.
        """
        # 1. Authorization Verification Gate
        if not isinstance(authorization, ExecutionAuthorization):
            raise ExecutionPolicyViolation(
                detail="Missing or invalid ExecutionAuthorization token.",
                error_code="INVALID_AUTHORIZATION_TOKEN",
            )
        ExecutionPolicyEngine.verify_authorization(
            authorization=authorization,
            expected_query_hash=authorization.query_hash,
            expected_tenant_id=authorization.tenant_id,
        )

        query_id = str(uuid.uuid4())
        t0 = time.perf_counter()

        if self.use_pooling:
            pool_manager = ReadOnlyPoolManager.get_instance_sync()
            async with pool_manager.acquire(
                tenant_id=authorization.tenant_id,
                kb_id=authorization.knowledgebase_id,
                db_config=db_config,
                config=self.config,
            ) as conn:
                return await self._execute_on_connection(
                    conn=conn,
                    candidate_sql=candidate_sql,
                    authorization=authorization,
                    query_id=query_id,
                    t0=t0,
                    is_pooled=True,
                )
        else:
            conn: Optional[asyncpg.Connection] = None
            try:
                conn = await self._acquire_connection(db_config)
                return await self._execute_on_connection(
                    conn=conn,
                    candidate_sql=candidate_sql,
                    authorization=authorization,
                    query_id=query_id,
                    t0=t0,
                    is_pooled=False,
                )
            finally:
                if conn:
                    try:
                        await conn.close()
                    except Exception:
                        pass
