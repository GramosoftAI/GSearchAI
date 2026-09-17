"""Phase 2C Transaction Management and Parameter Translation

Provides safe translation from named parameters (:p1) to PostgreSQL positional
parameters ($1) and coordinates read-only asyncpg transaction blocks.
"""

import asyncio
import datetime
import logging
import re
from typing import Any, Dict, List, Tuple
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
    def translate_parameters(cls, parameterized_sql: str, parameters: Dict[str, Any]) -> Tuple[str, List[Any]]:
        """
        Translates :p1, :p2 named placeholders to $1, $2 positional placeholders for asyncpg.
        Guarantees that positional argument order strictly corresponds to the SQL placeholders.
        Also safeguards time comparisons against timestamp columns by ensuring CAST(... AS time)
        if an uncast column is compared against a time parameter.
        """
        sql_working = parameterized_sql

        # If any parameter is a time object/string, ensure comparisons against columns are cast to time
        for key, raw_val in parameters.items():
            coerced_check = cls._coerce_param_value(raw_val)
            if isinstance(coerced_check, datetime.time):
                # Ensure comparisons like `col > :key` become `CAST(col AS time) > :key`
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
            return f"${len(pos_args)}"

        converted_sql = re.sub(r":([a-zA-Z0-9_]+)\b", replacer, sql_working)
        return converted_sql, pos_args

    @classmethod
    async def execute_in_readonly_transaction(
        cls,
        conn: asyncpg.Connection,
        sql: str,
        args: List[Any],
        timeout_seconds: float,
    ) -> List[asyncpg.Record]:
        """
        Execute query inside an explicit PostgreSQL read-only transaction block.
        Ensures automatic rollback on failure and raises strongly-typed sanitized exceptions.
        """
        try:
            async with conn.transaction(readonly=True):
                records = await conn.fetch(sql, *args, timeout=timeout_seconds)
                return records
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
