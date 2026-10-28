"""MariaDB / MySQL Engine Connector Implementation

Provides robust, production-grade MariaDB/MySQL metadata introspection via asyncmy.
Enforces read-only connection attributes, connection timeouts, SSL/TLS negotiation,
and deterministic catalog extraction directly from information_schema.
"""

import time
import ssl
import asyncio
import logging
from typing import Optional, List, Dict, Any
try:
    import aiomysql
    from aiomysql.cursors import DictCursor
    import pymysql.err as mysql_errors
except ImportError:
    aiomysql = None
    DictCursor = None
    mysql_errors = None

from .base import DatabaseConnector
from ..schemas.connection import DatabaseConnectionConfig, ConnectionTestResult, SSLMode
from ..security.sanitizer import sanitize_error_message
from ..exceptions.errors import (
    DatabaseKnowledgebaseError,
    DatabaseConnectionError,
    DatabaseAuthenticationError,
    DatabaseTimeoutError,
    SchemaIntrospectionError,
)

logger = logging.getLogger(__name__)


class MariaDBConnector(DatabaseConnector):
    """
    Production-grade MariaDB and MySQL Connector using asyncmy.
    """

    def __init__(self, config: DatabaseConnectionConfig):
        super().__init__(config)
        self._pool = None

    def _resolve_ssl(self) -> Optional[ssl.SSLContext]:
        """Convert SSLMode enum to ssl.SSLContext or None."""
        if self.config.ssl_mode == SSLMode.DISABLE:
            return None
        try:
            ctx = ssl.create_default_context()
            if self.config.ssl_mode in (SSLMode.DISABLE, SSLMode.ALLOW, SSLMode.PREFER):
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            return ctx
        except Exception:
            return None

    async def _get_raw_connection(self) -> Any:
        """Create a dedicated direct aiomysql connection with configured timeouts."""
        if aiomysql is None:
            raise DatabaseConnectionError(
                detail="aiomysql driver is not available.",
                details={"host": self.config.host, "port": self.config.port},
            )
        ssl_ctx = self._resolve_ssl()
        try:
            conn = await asyncio.wait_for(
                aiomysql.connect(
                    host=self.config.host,
                    port=self.config.port or 3306,
                    user=self.config.username,
                    password=self.config.raw_password,
                    db=self.config.database_name,
                    connect_timeout=self.config.connection_timeout,
                    ssl=ssl_ctx,
                    autocommit=True,
                    cursorclass=DictCursor,
                ),
                timeout=self.config.connection_timeout + 1.0,
            )
            return conn
        except asyncio.TimeoutError as e:
            logger.warning(f"Connection timeout to {self.config.masked_dsn}")
            raise DatabaseTimeoutError(
                detail=f"Connection to MariaDB host '{self.config.host}:{self.config.port}' timed out after {self.config.connection_timeout}s.",
                details={"host": self.config.host, "port": self.config.port},
            ) from e
        except Exception as e:
            err_code = getattr(e, "args", [None])[0] if getattr(e, "args", None) else None
            # 1045 is ER_ACCESS_DENIED_ERROR
            if err_code == 1045:
                logger.warning(f"Authentication failed for user '{self.config.username}' on {self.config.host}")
                raise DatabaseAuthenticationError(
                    detail=f"MariaDB authentication failed for user '{self.config.username}'. Access denied.",
                    details={"username": self.config.username},
                ) from e
            # 1049 is ER_BAD_DB_ERROR
            elif err_code == 1049:
                logger.warning(f"Database '{self.config.database_name}' not found on {self.config.host}")
                raise DatabaseConnectionError(
                    detail=f"Database '{self.config.database_name}' does not exist on MariaDB server.",
                    details={"database_name": self.config.database_name},
                ) from e
            safe_msg = sanitize_error_message(e)
            logger.warning(f"MariaDB connection error: {safe_msg}")
            raise DatabaseConnectionError(
                detail=f"Failed to connect to MariaDB server: {safe_msg}",
                details={"host": self.config.host, "port": self.config.port},
            ) from e

    async def test_connection(self) -> ConnectionTestResult:
        """
        Safely test connectivity to MariaDB/MySQL. Captures latency and server info.
        """
        t0 = time.perf_counter()
        conn: Optional[Any] = None
        try:
            conn = await self._get_raw_connection()
            latency = (time.perf_counter() - t0) * 1000.0

            async with conn.cursor() as cursor:
                # 1. Execute lightweight server info queries
                await cursor.execute("SELECT VERSION() as ver, DATABASE() as db, CURRENT_USER() as usr;")
                version_row = await cursor.fetchone()

                # 2. Fetch available database schemas (excluding internal MySQL schemas)
                await cursor.execute(
                    """
                    SELECT schema_name 
                    FROM information_schema.schemata 
                    WHERE schema_name NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
                    ORDER BY schema_name;
                    """
                )
                schemas_rows = await cursor.fetchall()
                schemas = [r["schema_name"] for r in schemas_rows] if schemas_rows else []
                if not schemas:
                    schemas = [self.config.database_name]

                # 3. Estimate table count in target database
                await cursor.execute(
                    """
                    SELECT count(*) as count 
                    FROM information_schema.tables 
                    WHERE table_schema = %s;
                    """,
                    (self.config.database_name,),
                )
                table_count_row = await cursor.fetchone()
                table_count = int(table_count_row["count"]) if table_count_row and "count" in table_count_row else 0

            return ConnectionTestResult(
                success=True,
                latency_ms=round(latency, 2),
                database_version=version_row["ver"] if version_row else "MariaDB",
                database_type="mariadb",
                schemas_found=schemas,
                table_count_estimate=table_count,
                server_info={
                    "current_database": version_row["db"] if version_row else self.config.database_name,
                    "current_user": version_row["usr"] if version_row else self.config.username,
                },
            )
        except DatabaseKnowledgebaseError as e:
            return ConnectionTestResult(
                success=False,
                error_message=e.detail,
                error_code=e.error_code,
                database_type="mariadb",
            )
        except Exception as e:
            safe_err = sanitize_error_message(e)
            return ConnectionTestResult(
                success=False,
                error_message=safe_err,
                error_code="UNHANDLED_CONNECTION_ERROR",
                database_type="mariadb",
            )
        finally:
            if conn:
                try:
                    await conn.ensure_closed()
                except Exception:
                    pass

    async def introspect_raw_metadata(self, schemas: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Deterministically query MariaDB/MySQL information_schema.
        STRICT REQUIREMENT: NO FULL TABLE SCANS (NO SELECT * FROM user_tables).
        """
        # In MariaDB/MySQL, schema = database
        target_schemas = schemas or self.config.schema_filter or [self.config.database_name]
        conn: Optional[Any] = None
        try:
            conn = await self._get_raw_connection()

            async with conn.cursor() as cursor:
                # 1. Schemas Discovery
                format_strings = ",".join(["%s"] * len(target_schemas))
                schema_query = f"""
                SELECT schema_name 
                FROM information_schema.schemata 
                WHERE schema_name IN ({format_strings})
                ORDER BY schema_name;
                """
                await cursor.execute(schema_query, tuple(target_schemas))
                schema_rows = await cursor.fetchall()
                active_schemas = [r["schema_name"] for r in schema_rows] if schema_rows else target_schemas

                # 2. Tables and Views Discovery + Table Comments
                tables_format = ",".join(["%s"] * len(active_schemas))
                tables_query = f"""
                SELECT 
                    table_schema,
                    table_name,
                    table_type,
                    table_comment
                FROM information_schema.tables
                WHERE table_schema IN ({tables_format})
                ORDER BY table_schema, table_name;
                """
                await cursor.execute(tables_query, tuple(active_schemas))
                table_rows = await cursor.fetchall()

                # 3. Columns Discovery + Column Comments
                columns_query = f"""
                SELECT 
                    table_schema,
                    table_name,
                    column_name,
                    data_type,
                    column_type as udt_name,
                    is_nullable,
                    column_default,
                    ordinal_position,
                    column_comment
                FROM information_schema.columns
                WHERE table_schema IN ({tables_format})
                ORDER BY table_schema, table_name, ordinal_position;
                """
                await cursor.execute(columns_query, tuple(active_schemas))
                column_rows = await cursor.fetchall()

                # 4. Primary Keys Discovery
                pk_query = f"""
                SELECT 
                    k.table_schema,
                    k.table_name,
                    k.constraint_name,
                    k.column_name,
                    k.ordinal_position
                FROM information_schema.table_constraints t
                JOIN information_schema.key_column_usage k 
                    ON t.constraint_schema = k.constraint_schema 
                    AND t.table_name = k.table_name 
                    AND t.constraint_name = k.constraint_name
                WHERE t.constraint_type = 'PRIMARY KEY'
                    AND t.table_schema IN ({tables_format})
                ORDER BY k.table_schema, k.table_name, k.ordinal_position;
                """
                await cursor.execute(pk_query, tuple(active_schemas))
                pk_rows = await cursor.fetchall()

                # 5. Foreign Keys Discovery
                fk_query = f"""
                SELECT 
                    rc.constraint_name,
                    kcu.table_schema AS source_schema,
                    kcu.table_name AS source_table,
                    kcu.column_name AS source_column,
                    kcu.referenced_table_schema AS target_schema,
                    kcu.referenced_table_name AS target_table,
                    kcu.referenced_column_name AS target_column,
                    rc.update_rule AS on_update,
                    rc.delete_rule AS on_delete,
                    kcu.ordinal_position
                FROM information_schema.referential_constraints rc
                JOIN information_schema.key_column_usage kcu
                    ON rc.constraint_schema = kcu.constraint_schema
                    AND rc.constraint_name = kcu.constraint_name
                WHERE kcu.table_schema IN ({tables_format})
                    AND kcu.referenced_table_name IS NOT NULL
                ORDER BY kcu.table_schema, kcu.table_name, rc.constraint_name, kcu.ordinal_position;
                """
                await cursor.execute(fk_query, tuple(active_schemas))
                fk_rows = await cursor.fetchall()

                # 6. Indexes Discovery
                indexes_query = f"""
                SELECT 
                    table_schema AS schema_name,
                    table_name,
                    index_name,
                    column_name,
                    non_unique,
                    seq_in_index
                FROM information_schema.statistics
                WHERE table_schema IN ({tables_format})
                ORDER BY table_schema, table_name, index_name, seq_in_index;
                """
                await cursor.execute(indexes_query, tuple(active_schemas))
                index_rows = await cursor.fetchall()

            return {
                "database_name": self.config.database_name,
                "database_type": "mariadb",
                "schemas": [dict(r) for r in (schema_rows or [])],
                "tables": [dict(r) for r in (table_rows or [])],
                "columns": [dict(r) for r in (column_rows or [])],
                "primary_keys": [dict(r) for r in (pk_rows or [])],
                "foreign_keys": [dict(r) for r in (fk_rows or [])],
                "indexes": [dict(r) for r in (index_rows or [])],
            }
        except DatabaseKnowledgebaseError:
            raise
        except Exception as e:
            safe_msg = sanitize_error_message(e)
            logger.error(f"Failed to introspect MariaDB metadata: {safe_msg}")
            raise SchemaIntrospectionError(
                detail=f"MariaDB metadata catalog query failed: {safe_msg}",
                details={"database_name": self.config.database_name},
            ) from e
        finally:
            if conn:
                try:
                    await conn.ensure_closed()
                except Exception:
                    pass

    async def close(self) -> None:
        if self._pool:
            try:
                self._pool.close()
                await self._pool.wait_closed()
            except Exception:
                pass
            self._pool = None
