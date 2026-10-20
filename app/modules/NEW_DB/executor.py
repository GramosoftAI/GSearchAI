"""Read-Only Database Query Executor with Zero-Row Temporal Recovery for NEW_DB

Executes validated SQL against the target database in strict READ ONLY mode,
enforcing timeouts and automatically relaxing date filters if zero rows are returned.
"""

import re
import logging
from typing import Dict, Any, List, Tuple, Optional

from .schemas import DBConnectionConfig
from .connection import DatabaseConnector
from .validator import SQLValidator

logger = logging.getLogger(__name__)


class QueryExecutor:
    """Executes read-only queries with safety limits and dynamic temporal relaxation."""

    @classmethod
    async def execute_query(
        cls,
        config: DBConnectionConfig,
        sql: str,
        timeout_seconds: float = 30.0,
        max_rows: int = 200,
    ) -> Tuple[List[Dict[str, Any]], List[str], int, float, bool, Optional[str]]:
        """
        Executes query safely.
        Returns: (rows, columns, row_count, execution_time_ms, is_truncated, temporal_notice)
        """
        rows, columns, exec_ms, truncated = await DatabaseConnector.execute_readonly_query(
            config=config,
            sql=sql,
            timeout_seconds=timeout_seconds,
            max_rows=max_rows,
        )

        temporal_notice = None

        # Zero-Row Dynamic Temporal Relaxation Recovery
        if len(rows) == 0 and any(
            kw in sql.lower()
            for kw in ("current_date", "now()", "interval", "_at::date", "date =", "date >=", "date <=")
        ):
            logger.info("[NEW_DB] Zero rows returned with temporal filter. Attempting temporal relaxation...")
            lines = sql.splitlines()
            filtered_lines = [
                ln for ln in lines
                if not any(kw in ln.lower() for kw in ("current_date", "now()", "interval", "_at::date", "_at >=", "_at <="))
            ]
            relaxed_sql = "\n".join(filtered_lines)
            relaxed_sql = re.sub(r"\bWHERE\s+AND\b", "WHERE", relaxed_sql, flags=re.IGNORECASE)
            relaxed_sql = re.sub(r"\bAND\s*$", "", relaxed_sql, flags=re.MULTILINE)

            if relaxed_sql != sql:
                try:
                    relaxed_clean = SQLValidator.validate_and_sanitize(relaxed_sql)
                    rel_rows, rel_cols, rel_ms, rel_trunc = await DatabaseConnector.execute_readonly_query(
                        config=config,
                        sql=relaxed_clean,
                        timeout_seconds=timeout_seconds,
                        max_rows=max_rows,
                    )
                    if len(rel_rows) > 0:
                        logger.info(f"[NEW_DB] Relaxed query recovered {len(rel_rows)} rows!")
                        rows = rel_rows
                        columns = rel_cols
                        exec_ms += rel_ms
                        truncated = rel_trunc
                        temporal_notice = "Notice: No records found strictly for the specified date. Showing latest associated activity."
                except Exception as rel_err:
                    logger.debug(f"[NEW_DB] Relaxed query failed: {rel_err}")

        return rows, columns, len(rows), exec_ms, truncated, temporal_notice
