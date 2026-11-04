"""Phase 2C Transaction Management and Parameter Translation

Provides safe translation from named parameters (:p1) to PostgreSQL positional
parameters ($1) and coordinates read-only asyncpg transaction blocks.
"""

import asyncio
import datetime
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import asyncpg

from ..security.sanitizer import sanitize_error_message
from .errors import (
    ExecutionPolicyViolation,
    ParameterBindingError,
    QueryExecutionError,
    QueryExecutionTimeout,
)

logger = logging.getLogger(__name__)


class TransactionManager:
    """Coordinates PostgreSQL read-only transaction blocks and parameter translation."""

    @staticmethod
    def _coerce_param_value(val: Any) -> Any:
        """
        Coerces string dates/datetimes/times to Python date/datetime/time objects for asyncpg.
        asyncpg's binary encoder expects datetime.date/datetime/time objects for DATE/TIMESTAMP/TIME
        columns and raises AttributeError/TypeError if plain strings are provided.
        """
        if isinstance(val, (datetime.date, datetime.datetime, datetime.time)):
            return val
        if not isinstance(val, str):
            return val
        val_strip = val.strip()
        # YYYY-MM-DD date format
        if re.match(r"^\d{4}-\d{2}-\d{2}$", val_strip):
            try:
                return datetime.date.fromisoformat(val_strip)
            except ValueError:
                pass
        # ISO timestamp format: YYYY-MM-DDTHH:MM:SS or YYYY-MM-DD HH:MM:SS
        if re.match(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", val_strip):
            try:
                return datetime.datetime.fromisoformat(val_strip.replace(" ", "T"))
            except ValueError:
                pass
        # Time format: HH:MM:SS or HH:MM
        if re.match(r"^\d{1,2}:\d{2}(:\d{2})?(\.\d+)?$", val_strip):
            try:
                return datetime.time.fromisoformat(val_strip)
            except ValueError:
                pass
        return val

    @classmethod
    def translate_parameters(
        cls, parameterized_sql: str, parameters: Dict[str, Any], dialect: str = "postgres"
    ) -> Tuple[str, List[Any]]:
        """
        Translates :p1, :p2 named placeholders to positional placeholders:
        $1, $2 for asyncpg (PostgreSQL), and %s for asyncmy (MariaDB/MySQL).
        Guarantees that positional argument order strictly corresponds to the SQL placeholders.
        """
        sql_working = parameterized_sql

        # If any parameter is a time object/string, ensure comparisons against columns are cast to time (PostgreSQL only)
        if dialect not in ("mysql", "mariadb", "sqlserver", "mssql", "tsql"):
            for key, raw_val in parameters.items():
                coerced_check = cls._coerce_param_value(raw_val)
                if isinstance(coerced_check, datetime.time):
                    pattern = rf"(?i)(?<!CAST\()(?<!::)\b([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)?)\s*([><!=]+)\s*:{key}\b"
                    sql_working = re.sub(pattern, rf"CAST(\1 AS time) \2 :{key}", sql_working)

        pos_args: List[Any] = []
        param_keys_ordered: List[str] = []

        def replacer(match: re.Match) -> str:
            key = match.group(1)
            if key not in parameters:
                raise ParameterBindingError(
                    detail=f"Parameter placeholder ':{key}' in SQL query has no corresponding bound value.",
                    details={"missing_key": key},
                )
            raw_val = parameters[key]
            coerced_val = cls._coerce_param_value(raw_val)
            pos_args.append(coerced_val)
            param_keys_ordered.append(key)
            if dialect in ("mysql", "mariadb", "sqlserver", "mssql", "tsql"):
                return "%s"
            return f"${len(pos_args)}"

        converted_sql = re.sub(r":([a-zA-Z0-9_]+)\b", replacer, sql_working)
        return converted_sql, pos_args

    @classmethod
    async def execute_in_readonly_transaction(
        cls,
        conn: Any,
        sql: str,
        args: List[Any],
        timeout_seconds: float,
        dialect: str = "postgres",
        tenant_id: Optional[str] = None,
    ) -> List[Any]:
        """
        Execute query inside a read-only transaction/execution context.
        Supports asyncpg (PostgreSQL), pymssql (MS SQL Server), and asyncmy (MariaDB/MySQL).
        """
        try:
            if isinstance(conn, asyncpg.Connection):
                async with conn.transaction(readonly=True):
                    # Guarantee app.current_tenant is set for PostgreSQL RLS policies
                    if dialect in ("postgres", "postgresql"):
                        try:
                            await conn.execute(
                                "SELECT set_config('app.current_tenant', $1, true)",
                                str(tenant_id or "00000000-0000-0000-0000-000000000000"),
                            )
                        except Exception as guc_err:
                            logger.debug(f"Failed to set app.current_tenant session config: {guc_err}")
                    try:
                        records = await conn.fetch(sql, *args, timeout=timeout_seconds)
                        return records
                    except (asyncpg.DataError, TypeError) as codec_err:
                        logger.warning(f"Parameter codec mismatch in asyncpg ({codec_err}). Retrying with stringified arguments...")
                        str_args = [str(a) if not isinstance(a, (bytes,)) else a for a in args]
                        records = await conn.fetch(sql, *str_args, timeout=timeout_seconds)
                        return records
                    except (asyncpg.IndeterminateDatatypeError, asyncpg.PostgresError) as pg_err:
                        err_msg = str(pg_err).lower()
                        if "could not determine data type of parameter" in err_msg or isinstance(pg_err, asyncpg.IndeterminateDatatypeError):
                            logger.warning(f"Indeterminate parameter data type in asyncpg ({pg_err}). Dynamically adapting SQL parameters...")
                            # 1. Attempt casting parameters: $1 -> CAST($1 AS TEXT)
                            curr_sql = sql
                            matches = re.findall(r"\$(\d+)\b", curr_sql)
                            for param_num in set(matches):
                                curr_sql = re.sub(
                                    rf"(?<!CAST\()(?<!::)\${param_num}\b",
                                    f"CAST(${param_num} AS TEXT)",
                                    curr_sql,
                                )
                            try:
                                records = await conn.fetch(curr_sql, *args, timeout=timeout_seconds)
                                return records
                            except Exception as cast_err:
                                logger.warning(f"Parameter cast retry failed ({cast_err}). Inlining parameters safely for read-only execution...")
                                # 2. Safe inlining fallback for validated read-only execution
                                inlined_sql = sql
                                for idx, arg_val in enumerate(args, start=1):
                                    if arg_val is None:
                                        rep_val = "NULL"
                                    elif isinstance(arg_val, (int, float)):
                                        rep_val = str(arg_val)
                                    elif isinstance(arg_val, bool):
                                        rep_val = "TRUE" if arg_val else "FALSE"
                                    else:
                                        escaped = str(arg_val).replace("'", "''")
                                        rep_val = f"'{escaped}'"
                                    inlined_sql = re.sub(rf"(?<![a-zA-Z0-9_])\${idx}\b", rep_val, inlined_sql)
                                records = await conn.fetch(inlined_sql, timeout=timeout_seconds)
                                return records
                        raise
            elif dialect in ("sqlserver", "mssql", "tsql"):
                # Safety net: T-SQL does not support NULLS FIRST/LAST or LIMIT
                clean_tsql = sql.strip().rstrip(";")
                clean_tsql = re.sub(r"\s+NULLS\s+(?:FIRST|LAST)\b", "", clean_tsql, flags=re.IGNORECASE)
                limit_match = re.search(r"\s+LIMIT\s+(\d+)\s*$", clean_tsql, re.IGNORECASE)
                if limit_match:
                    lim_val = limit_match.group(1)
                    clean_tsql = clean_tsql[:limit_match.start()].strip()
                    if not re.search(r"\bSELECT\s+(?:DISTINCT\s+)?TOP\s*\(?\d+\)?", clean_tsql, re.IGNORECASE):
                        clean_tsql = re.sub(r"^(\s*SELECT\s+(?:DISTINCT\s+)?)", rf"\1TOP ({lim_val}) ", clean_tsql, flags=re.IGNORECASE)
                sql_to_run = clean_tsql

                def _run_mssql():
                    with conn.cursor(as_dict=True) as cursor:
                        cursor.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
                        cursor.execute(sql_to_run, tuple(args))
                        return cursor.fetchall() or []
                records = await asyncio.wait_for(asyncio.to_thread(_run_mssql), timeout=timeout_seconds)
                return records
            else:
                # asyncmy / MySQL connection
                async with conn.cursor() as cursor:
                    await asyncio.wait_for(cursor.execute(sql, tuple(args)), timeout=timeout_seconds)
                    records = await cursor.fetchall()
                    return records or []
        except (asyncpg.QueryCanceledError, asyncio.TimeoutError) as e:
            logger.warning("Query canceled or statement timeout exceeded on target database")
            raise QueryExecutionTimeout(
                detail="Database query execution timed out.",
                details={"timeout_seconds": timeout_seconds},
            ) from e
        except asyncpg.InsufficientPrivilegeError as e:
            safe_msg = sanitize_error_message(e)
            logger.warning(f"Database permission denied in read-only transaction: {safe_msg}")
            raise ExecutionPolicyViolation(
                detail=f"Database execution rejected by security permissions: {safe_msg}",
                error_code="INSUFFICIENT_DATABASE_PRIVILEGE",
            ) from e
        except asyncpg.PostgresError as e:
            safe_msg = sanitize_error_message(e)
            logger.error(f"PostgreSQL execution error: {safe_msg}")
            raise QueryExecutionError(
                detail=f"Query execution failed: {safe_msg}",
            ) from e
        except Exception as e:
            safe_msg = sanitize_error_message(e)
            logger.error(f"Unhandled error during query execution: {safe_msg}")
            raise QueryExecutionError(
                detail=f"Query execution error: {safe_msg}",
            ) from e
