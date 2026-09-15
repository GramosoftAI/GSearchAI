"""PostgreSQL Engine Connector Implementation

Provides robust, production-grade PostgreSQL metadata introspection via asyncpg.
Enforces read-only connection attributes, connection timeouts, SSL/TLS negotiation,
and deterministic catalog extraction directly from information_schema and pg_catalog.
"""

import time
import asyncio
import logging
from typing import Optional, List, Dict, Any
import asyncpg

from .base import DatabaseConnector
from ..schemas.connection import DatabaseConnectionConfig, ConnectionTestResult, SSLMode
from ..security.sanitizer import sanitize_error_message
from ..exceptions.errors import (
    DatabaseKnowledgebaseError,
    DatabaseConnectionError,
    DatabaseAuthenticationError,
    DatabaseTimeoutError,
    DatabasePermissionError,
    SchemaIntrospectionError,
)

logger = logging.getLogger(__name__)


class PostgreSQLConnector(DatabaseConnector):
    """
    Production-grade PostgreSQL Connector.
    """

    def __init__(self, config: DatabaseConnectionConfig):
        super().__init__(config)
        self._pool: Optional[asyncpg.Pool] = None

    def _resolve_ssl(self) -> Optional[str]:
        """Convert SSLMode enum to asyncpg ssl argument."""
        if self.config.ssl_mode == SSLMode.DISABLE:
            return None
        elif self.config.ssl_mode in (SSLMode.REQUIRE, SSLMode.VERIFY_CA, SSLMode.VERIFY_FULL):
            return "require"
        elif self.config.ssl_mode == SSLMode.PREFER:
            return "prefer"
        return None

    async def _get_raw_connection(self) -> asyncpg.Connection:
        """Create a dedicated direct asyncpg connection with configured timeouts."""
        ssl_val = self._resolve_ssl()
        try:
            conn = await asyncio.wait_for(
                asyncpg.connect(
                    host=self.config.host,
                    port=self.config.port,
                    user=self.config.username,
                    password=self.config.raw_password,
                    database=self.config.database_name,
                    ssl=ssl_val,
                    timeout=self.config.connection_timeout,
                    command_timeout=self.config.connection_timeout,
                    server_settings={
                        "application_name": "GSearchAI_DB_Introspector",
                        "default_transaction_read_only": "on",
                    },
                ),
                timeout=self.config.connection_timeout + 1.0,
            )
            return conn
        except asyncio.TimeoutError as e:
            logger.warning(f"Connection timeout to {self.config.masked_dsn}")
            raise DatabaseTimeoutError(
                detail=f"Connection to PostgreSQL host '{self.config.host}:{self.config.port}' timed out after {self.config.connection_timeout}s.",
                details={"host": self.config.host, "port": self.config.port},
            ) from e
        except asyncpg.InvalidPasswordError as e:
            logger.warning(f"Authentication failed for user '{self.config.username}' on {self.config.host}")
            raise DatabaseAuthenticationError(
                detail=f"PostgreSQL authentication failed for user '{self.config.username}'. Password incorrect.",
                details={"username": self.config.username},
            ) from e
        except asyncpg.InvalidCatalogNameError as e:
            logger.warning(f"Database '{self.config.database_name}' not found on {self.config.host}")
            raise DatabaseConnectionError(
                detail=f"Database '{self.config.database_name}' does not exist on PostgreSQL server.",
                details={"database_name": self.config.database_name},
            ) from e
        except (asyncpg.PostgresError, OSError) as e:
            safe_msg = sanitize_error_message(e)
            logger.warning(f"PostgreSQL connection error: {safe_msg}")
            raise DatabaseConnectionError(
                detail=f"Failed to connect to PostgreSQL server: {safe_msg}",
                details={"host": self.config.host, "port": self.config.port},
            ) from e

    async def test_connection(self) -> ConnectionTestResult:
        """
        Safely test connectivity to PostgreSQL. Captures latency and server info.
        """
        t0 = time.perf_counter()
        conn: Optional[asyncpg.Connection] = None
        try:
            conn = await self._get_raw_connection()
            latency = (time.perf_counter() - t0) * 1000.0

            # Execute lightweight server info queries
            version_row = await conn.fetchrow("SELECT version() as ver, current_database() as db, current_user as usr;")
            
            # Fetch available schemas
            schemas_rows = await conn.fetch(
                """
                SELECT schema_name 
                FROM information_schema.schemata 
                WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                ORDER BY schema_name;
                """
            )
            schemas = [r["schema_name"] for r in schemas_rows]
            if not schemas:
                schemas = ["public"]

            # Estimate table count from catalog (no scans)
            table_count_row = await conn.fetchrow(
                """
                SELECT count(*)::int as count 
                FROM information_schema.tables 
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast');
                """
            )
            table_count = table_count_row["count"] if table_count_row else 0

            return ConnectionTestResult(
                success=True,
                latency_ms=round(latency, 2),
                database_version=version_row["ver"] if version_row else "PostgreSQL",
                database_type="postgresql",
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
                database_type="postgresql",
            )
        except Exception as e:
            safe_err = sanitize_error_message(e)
            return ConnectionTestResult(
                success=False,
                error_message=safe_err,
                error_code="UNHANDLED_CONNECTION_ERROR",
                database_type="postgresql",
            )
        finally:
            if conn:
                try:
                    await conn.close()
                except Exception:
                    pass

    async def introspect_raw_metadata(self, schemas: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Deterministically query PostgreSQL system catalogs (information_schema, pg_catalog).
        STRICT REQUIREMENT: NO FULL TABLE SCANS (NO SELECT * FROM user_tables).
        """
        target_schemas = schemas or self.config.schema_filter or ["public"]
        conn: Optional[asyncpg.Connection] = None
        try:
            conn = await self._get_raw_connection()

            # 1. Schemas Discovery
            schema_query = """
            SELECT schema_name 
            FROM information_schema.schemata 
            WHERE schema_name = ANY($1::text[])
            ORDER BY schema_name;
            """
            schema_rows = await conn.fetch(schema_query, target_schemas)
            active_schemas = [r["schema_name"] for r in schema_rows]
            if not active_schemas:
                active_schemas = target_schemas

            # 2. Tables and Views Discovery + Table Comments
            tables_query = """
            SELECT 
                t.table_schema,
                t.table_name,
                t.table_type,
                d.description as table_comment
            FROM information_schema.tables t
            LEFT JOIN pg_catalog.pg_namespace n 
                ON n.nspname = t.table_schema
            LEFT JOIN pg_catalog.pg_class c 
                ON c.relname = t.table_name AND c.relnamespace = n.oid
            LEFT JOIN pg_catalog.pg_description d 
                ON d.objoid = c.oid AND d.objsubid = 0
            WHERE t.table_schema = ANY($1::text[])
            ORDER BY t.table_schema, t.table_name;
            """
            table_rows = await conn.fetch(tables_query, active_schemas)

            # 3. Columns Discovery + Column Comments
            columns_query = """
            SELECT 
                c.table_schema,
                c.table_name,
                c.column_name,
                c.data_type,
                c.udt_name,
                c.is_nullable,
                c.column_default,
                c.ordinal_position,
                d.description as column_comment
            FROM information_schema.columns c
            LEFT JOIN pg_catalog.pg_namespace n 
                ON n.nspname = c.table_schema
            LEFT JOIN pg_catalog.pg_class cl 
                ON cl.relname = c.table_name AND cl.relnamespace = n.oid
            LEFT JOIN pg_catalog.pg_description d 
                ON d.objoid = cl.oid AND d.objsubid = c.ordinal_position
            WHERE c.table_schema = ANY($1::text[])
            ORDER BY c.table_schema, c.table_name, c.ordinal_position;
            """
            column_rows = await conn.fetch(columns_query, active_schemas)

            # 4. Primary Keys Discovery (pg_catalog.pg_constraint)
            pk_query = """
            SELECT 
                n.nspname AS table_schema,
                c.relname AS table_name,
                con.conname AS constraint_name,
                a.attname AS column_name,
                array_position(con.conkey, a.attnum) AS ordinal_position
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class c ON c.oid = con.conrelid
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY(con.conkey)
            WHERE con.contype = 'p'
                AND n.nspname = ANY($1::text[])
            ORDER BY n.nspname, c.relname, ordinal_position;
            """
            pk_rows = await conn.fetch(pk_query, active_schemas)

            # 5. Foreign Keys Discovery (pg_catalog.pg_constraint)
            fk_query = """
            SELECT 
                con.conname AS constraint_name,
                src_ns.nspname AS source_schema,
                src_cl.relname AS source_table,
                src_att.attname AS source_column,
                tgt_ns.nspname AS target_schema,
                tgt_cl.relname AS target_table,
                tgt_att.attname AS target_column,
                CASE con.confupdtype
                    WHEN 'a' THEN 'NO ACTION'
                    WHEN 'r' THEN 'RESTRICT'
                    WHEN 'c' THEN 'CASCADE'
                    WHEN 'n' THEN 'SET NULL'
                    WHEN 'd' THEN 'SET DEFAULT'
                    ELSE 'NO ACTION'
                END AS on_update,
                CASE con.confdeltype
                    WHEN 'a' THEN 'NO ACTION'
                    WHEN 'r' THEN 'RESTRICT'
                    WHEN 'c' THEN 'CASCADE'
                    WHEN 'n' THEN 'SET NULL'
                    WHEN 'd' THEN 'SET DEFAULT'
                    ELSE 'NO ACTION'
                END AS on_delete,
                pos.ord AS ordinal_position
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class src_cl ON src_cl.oid = con.conrelid
            JOIN pg_catalog.pg_namespace src_ns ON src_ns.oid = src_cl.relnamespace
            JOIN pg_catalog.pg_class tgt_cl ON tgt_cl.oid = con.confrelid
            JOIN pg_catalog.pg_namespace tgt_ns ON tgt_ns.oid = tgt_cl.relnamespace
            CROSS JOIN LATERAL unnest(con.conkey, con.confkey) WITH ORDINALITY AS pos(src_attnum, tgt_attnum, ord)
            JOIN pg_catalog.pg_attribute src_att ON src_att.attrelid = src_cl.oid AND src_att.attnum = pos.src_attnum
            JOIN pg_catalog.pg_attribute tgt_att ON tgt_att.attrelid = tgt_cl.oid AND tgt_att.attnum = pos.tgt_attnum
            WHERE con.contype = 'f'
                AND src_ns.nspname = ANY($1::text[])
            ORDER BY src_ns.nspname, src_cl.relname, con.conname, pos.ord;
            """
            fk_rows = await conn.fetch(fk_query, active_schemas)

            # 6. Indexes Discovery (pg_indexes)
            indexes_query = """
            SELECT 
                schemaname AS schema_name,
                tablename AS table_name,
                indexname AS index_name,
                indexdef AS index_def
            FROM pg_catalog.pg_indexes
            WHERE schemaname = ANY($1::text[])
            ORDER BY schemaname, tablename, indexname;
            """
            index_rows = await conn.fetch(indexes_query, active_schemas)

            return {
                "database_name": self.config.database_name,
                "database_type": "postgresql",
                "schemas": [dict(r) for r in schema_rows],
                "tables": [dict(r) for r in table_rows],
                "columns": [dict(r) for r in column_rows],
                "primary_keys": [dict(r) for r in pk_rows],
                "foreign_keys": [dict(r) for r in fk_rows],
                "indexes": [dict(r) for r in index_rows],
            }

        except DatabaseKnowledgebaseError:
            raise
        except (asyncpg.PostgresError, OSError) as e:
            safe_msg = sanitize_error_message(e)
            logger.error(f"Failed to introspect PostgreSQL metadata: {safe_msg}")
            raise SchemaIntrospectionError(
                detail=f"PostgreSQL metadata catalog query failed: {safe_msg}",
                details={"database_name": self.config.database_name},
            ) from e
        finally:
            if conn:
                try:
                    await conn.close()
                except Exception:
                    pass

    async def close(self) -> None:
        if self._pool:
            try:
                await self._pool.close()
            except Exception:
                pass
            self._pool = None
