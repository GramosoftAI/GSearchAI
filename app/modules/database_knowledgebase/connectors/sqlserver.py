"""MS SQL Server Engine Connector Implementation

Provides robust, production-grade MS SQL Server metadata introspection via pymssql.
Enforces read-only connection attributes, connection timeouts, SSL/TLS negotiation,
and deterministic catalog extraction directly from sys.* catalog views and INFORMATION_SCHEMA.
"""

import time
import asyncio
import logging
from typing import Optional, List, Dict, Any

try:
    import pymssql
except ImportError:
    pymssql = None

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


class SQLServerConnector(DatabaseConnector):
    """
    Production-grade MS SQL Server Connector using pymssql.
    Uses asyncio.to_thread to maintain fully non-blocking operation in async contexts.
    """

    def __init__(self, config: DatabaseConnectionConfig):
        super().__init__(config)
        self._conn = None

    def _sync_connect(self) -> Any:
        """Create a dedicated direct pymssql connection with configured timeouts."""
        if pymssql is None:
            raise DatabaseConnectionError(
                detail="pymssql driver is not available in Python environment.",
                details={"host": self.config.host, "port": self.config.port},
            )

        timeout = max(int(self.config.connection_timeout or 10), 1)
        port = int(self.config.port or 1433)

        try:
            conn = pymssql.connect(
                server=self.config.host,
                port=port,
                user=self.config.username,
                password=self.config.raw_password,
                database=self.config.database_name,
                login_timeout=timeout,
                timeout=timeout,
                as_dict=True,
                autocommit=True,
            )
            return conn
        except pymssql.OperationalError as e:
            msg = str(e)
            logger.warning(f"SQL Server operational error for {self.config.masked_dsn}: {msg}")
            if "Login failed" in msg or "adaptive Server is unavailable" not in msg and "18456" in msg:
                raise DatabaseAuthenticationError(
                    detail=f"MS SQL Server authentication failed for user '{self.config.username}'.",
                    details={"username": self.config.username},
                ) from e
            elif "timeout" in msg.lower():
                raise DatabaseTimeoutError(
                    detail=f"Connection to MS SQL Server '{self.config.host}:{port}' timed out after {timeout}s.",
                    details={"host": self.config.host, "port": port},
                ) from e
            safe_msg = sanitize_error_message(e)
            raise DatabaseConnectionError(
                detail=f"Failed to connect to MS SQL Server: {safe_msg}",
                details={"host": self.config.host, "port": port},
            ) from e
        except Exception as e:
            safe_msg = sanitize_error_message(e)
            logger.warning(f"MS SQL Server connection failed: {safe_msg}")
            raise DatabaseConnectionError(
                detail=f"MS SQL Server connection error: {safe_msg}",
                details={"host": self.config.host, "port": port},
            ) from e

    async def _get_raw_connection(self) -> Any:
        """Asynchronously acquire a dedicated pymssql connection."""
        return await asyncio.to_thread(self._sync_connect)

    def _sync_test_connection(self, conn: Any, latency: float) -> ConnectionTestResult:
        """Execute lightweight metadata checks on the live SQL Server connection."""
        with conn.cursor(as_dict=True) as cursor:
            # 1. Server & DB info
            cursor.execute("SELECT @@VERSION as ver, DB_NAME() as db, SYSTEM_USER as usr;")
            version_row = cursor.fetchone() or {}

            # 2. User schemas
            cursor.execute(
                """
                SELECT schema_name 
                FROM information_schema.schemata 
                WHERE schema_name NOT IN (
                    'guest', 'INFORMATION_SCHEMA', 'sys', 'db_owner', 'db_accessadmin', 
                    'db_securityadmin', 'db_ddladmin', 'db_backupoperator', 'db_datareader', 
                    'db_datawriter', 'db_denydatareader', 'db_denydatawriter'
                )
                ORDER BY schema_name;
                """
            )
            schema_rows = cursor.fetchall()
            schemas = [r["schema_name"] for r in schema_rows] if schema_rows else ["dbo"]

            # 3. Table count estimate
            cursor.execute(
                """
                SELECT COUNT(*) as count 
                FROM sys.tables t
                JOIN sys.schemas s ON t.schema_id = s.schema_id
                WHERE s.name NOT IN ('sys', 'guest', 'INFORMATION_SCHEMA');
                """
            )
            count_row = cursor.fetchone() or {}
            table_count = count_row.get("count", 0)

            ver_str = version_row.get("ver", "Microsoft SQL Server")
            # Keep first line of @@VERSION for clean display
            short_version = ver_str.split("\n")[0] if isinstance(ver_str, str) else "Microsoft SQL Server"

            return ConnectionTestResult(
                success=True,
                latency_ms=round(latency, 2),
                database_version=short_version,
                database_type="sqlserver",
                schemas_found=schemas,
                table_count_estimate=table_count,
                server_info={
                    "current_database": version_row.get("db", self.config.database_name),
                    "current_user": version_row.get("usr", self.config.username),
                },
            )

    async def test_connection(self) -> ConnectionTestResult:
        """Safely test connectivity to MS SQL Server. Captures latency and server info."""
        t0 = time.perf_counter()
        conn = None
        try:
            conn = await self._get_raw_connection()
            latency = (time.perf_counter() - t0) * 1000.0
            return await asyncio.to_thread(self._sync_test_connection, conn, latency)
        except DatabaseKnowledgebaseError as e:
            return ConnectionTestResult(
                success=False,
                error_message=e.detail,
                error_code=e.error_code,
                database_type="sqlserver",
            )
        except Exception as e:
            safe_err = sanitize_error_message(e)
            return ConnectionTestResult(
                success=False,
                error_message=safe_err,
                error_code="UNHANDLED_CONNECTION_ERROR",
                database_type="sqlserver",
            )
        finally:
            if conn:
                try:
                    await asyncio.to_thread(conn.close)
                except Exception:
                    pass

    def _sync_introspect(self, conn: Any, target_schemas: List[str]) -> Dict[str, Any]:
        """Synchronously query MS SQL Server sys catalogs and return raw metadata."""
        with conn.cursor(as_dict=True) as cursor:
            # Create parameterized IN clause using tuple placeholders (%s)
            placeholders = ", ".join(["%s"] * len(target_schemas))

            # 1. Schemas Discovery
            schema_query = f"""
            SELECT schema_name 
            FROM information_schema.schemata 
            WHERE schema_name IN ({placeholders})
            ORDER BY schema_name;
            """
            cursor.execute(schema_query, tuple(target_schemas))
            schema_rows = cursor.fetchall()
            active_schemas = [r["schema_name"] for r in schema_rows]
            if not active_schemas:
                active_schemas = target_schemas
                schema_rows = [{"schema_name": s} for s in target_schemas]

            active_placeholders = ", ".join(["%s"] * len(active_schemas))
            active_tuple = tuple(active_schemas)

            # 2. Tables and Views Discovery + Extended Property Comments
            tables_query = f"""
            SELECT 
                s.name AS table_schema,
                t.name AS table_name,
                CASE WHEN t.type = 'V' THEN 'VIEW' ELSE 'BASE TABLE' END AS table_type,
                CAST(ep.value AS NVARCHAR(MAX)) AS table_comment
            FROM (
                SELECT object_id, schema_id, name, type FROM sys.tables
                UNION ALL
                SELECT object_id, schema_id, name, type FROM sys.views
            ) t
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            LEFT JOIN sys.extended_properties ep 
                ON ep.major_id = t.object_id AND ep.minor_id = 0 AND ep.name = 'MS_Description'
            WHERE s.name IN ({active_placeholders})
            ORDER BY s.name, t.name;
            """
            cursor.execute(tables_query, active_tuple)
            table_rows = cursor.fetchall()

            # 3. Columns Discovery + Extended Property Comments
            columns_query = f"""
            SELECT 
                s.name AS table_schema,
                t.name AS table_name,
                c.name AS column_name,
                tp.name AS data_type,
                tp.name AS udt_name,
                CASE WHEN c.is_nullable = 1 THEN 'YES' ELSE 'NO' END AS is_nullable,
                OBJECT_DEFINITION(c.default_object_id) AS column_default,
                c.column_id AS ordinal_position,
                CAST(ep.value AS NVARCHAR(MAX)) AS column_comment
            FROM (
                SELECT object_id, schema_id, name FROM sys.tables
                UNION ALL
                SELECT object_id, schema_id, name FROM sys.views
            ) t
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            JOIN sys.columns c ON t.object_id = c.object_id
            JOIN sys.types tp ON c.user_type_id = tp.user_type_id
            LEFT JOIN sys.extended_properties ep 
                ON ep.major_id = t.object_id AND ep.minor_id = c.column_id AND ep.name = 'MS_Description'
            WHERE s.name IN ({active_placeholders})
            ORDER BY s.name, t.name, c.column_id;
            """
            cursor.execute(columns_query, active_tuple)
            column_rows = cursor.fetchall()

            # 4. Primary Keys Discovery
            pk_query = f"""
            SELECT 
                s.name AS table_schema,
                t.name AS table_name,
                kc.name AS constraint_name,
                c.name AS column_name,
                ic.key_ordinal AS ordinal_position
            FROM sys.key_constraints kc
            JOIN sys.tables t ON kc.parent_object_id = t.object_id
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            JOIN sys.index_columns ic ON ic.object_id = t.object_id AND ic.index_id = kc.unique_index_id
            JOIN sys.columns c ON c.object_id = t.object_id AND c.column_id = ic.column_id
            WHERE kc.type = 'PK' AND s.name IN ({active_placeholders})
            ORDER BY s.name, t.name, ic.key_ordinal;
            """
            cursor.execute(pk_query, active_tuple)
            pk_rows = cursor.fetchall()

            # 5. Foreign Keys Discovery
            fk_query = f"""
            SELECT 
                fk.name AS constraint_name,
                src_s.name AS source_schema,
                src_t.name AS source_table,
                src_c.name AS source_column,
                tgt_s.name AS target_schema,
                tgt_t.name AS target_table,
                tgt_c.name AS target_column,
                fk.update_referential_action_desc AS on_update,
                fk.delete_referential_action_desc AS on_delete,
                fkc.constraint_column_id AS ordinal_position
            FROM sys.foreign_keys fk
            JOIN sys.tables src_t ON fk.parent_object_id = src_t.object_id
            JOIN sys.schemas src_s ON src_t.schema_id = src_s.schema_id
            JOIN sys.tables tgt_t ON fk.referenced_object_id = tgt_t.object_id
            JOIN sys.schemas tgt_s ON tgt_t.schema_id = tgt_s.schema_id
            JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
            JOIN sys.columns src_c ON src_t.object_id = src_c.object_id AND fkc.parent_column_id = src_c.column_id
            JOIN sys.columns tgt_c ON tgt_t.object_id = tgt_c.object_id AND fkc.referenced_column_id = tgt_c.column_id
            WHERE src_s.name IN ({active_placeholders})
            ORDER BY src_s.name, src_t.name, fk.name, fkc.constraint_column_id;
            """
            cursor.execute(fk_query, active_tuple)
            fk_rows = cursor.fetchall()

            # 6. Indexes Discovery
            indexes_query = f"""
            SELECT 
                s.name AS schema_name,
                t.name AS table_name,
                i.name AS index_name,
                CASE WHEN i.is_unique = 1 THEN 'UNIQUE ' ELSE '' END + i.type_desc AS index_def
            FROM sys.indexes i
            JOIN sys.tables t ON i.object_id = t.object_id
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE i.name IS NOT NULL AND i.is_hypothetical = 0 AND s.name IN ({active_placeholders})
            ORDER BY s.name, t.name, i.name;
            """
            cursor.execute(indexes_query, active_tuple)
            index_rows = cursor.fetchall()

            return {
                "database_name": self.config.database_name,
                "database_type": "sqlserver",
                "schemas": [dict(r) for r in schema_rows],
                "tables": [dict(r) for r in table_rows],
                "columns": [dict(r) for r in column_rows],
                "primary_keys": [dict(r) for r in pk_rows],
                "foreign_keys": [dict(r) for r in fk_rows],
                "indexes": [dict(r) for r in index_rows],
            }

    async def introspect_raw_metadata(self, schemas: Optional[List[str]] = None) -> Dict[str, Any]:
        """Deterministically query MS SQL Server system catalogs."""
        target_schemas = schemas or self.config.schema_filter or ["dbo"]
        conn = None
        try:
            conn = await self._get_raw_connection()
            return await asyncio.to_thread(self._sync_introspect, conn, target_schemas)
        except DatabaseKnowledgebaseError:
            raise
        except Exception as e:
            safe_msg = sanitize_error_message(e)
            logger.error(f"Failed to introspect MS SQL Server metadata: {safe_msg}")
            raise SchemaIntrospectionError(
                detail=f"MS SQL Server metadata catalog query failed: {safe_msg}",
                details={"database_name": self.config.database_name},
            ) from e
        finally:
            if conn:
                try:
                    await asyncio.to_thread(conn.close)
                except Exception:
                    pass

    async def close(self) -> None:
        """Release any open connection resources."""
        if self._conn:
            try:
                await asyncio.to_thread(self._conn.close)
            except Exception:
                pass
            self._conn = None
