"""Factual Schema Profiler

Computes strict facts about tables and columns via read-only SQL:
- Row count estimate / count
- Column data type, nullable, PK/FK status
- Distinct count, null percentage, min/max values
- Distinct values list for low-cardinality text columns (e.g. <= 25 distinct values)
- Random row sampling (10-20 random rows via TABLESAMPLE or RANDOM() with statement timeout)
- Strictly avoids sampling or distinct value profiling on sensitive columns

Code/SQL ONLY — NEVER invented or estimated by an LLM.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
import asyncpg

from ..schemas.canonical import DatabaseSchema, TableSchema, ColumnSchema
from ..schemas.connection import DatabaseConnectionConfig
from .sensitivity import SensitivityGuard

logger = logging.getLogger(__name__)

STATEMENT_TIMEOUT_MS = 5000  # 5s safety timeout per query
MAX_DISTINCT_VALUES_CARDINALITY = 25  # Limit for low-cardinality values list
SAMPLE_ROW_COUNT = 15  # 10-20 random rows


class TableFacts:
    """Facts computed for a table."""
    def __init__(self, table_name: str, schema_name: str = "public"):
        self.table_name = table_name
        self.schema_name = schema_name
        self.total_rows: int = 0
        self.columns: Dict[str, Dict[str, Any]] = {}
        self.samples: List[Dict[str, Any]] = []


class FactProfiler:
    """Extracts factual statistics and masked samples from target database."""

    @classmethod
    async def profile_table(
        cls,
        conn: asyncpg.Connection,
        table: TableSchema,
    ) -> TableFacts:
        """Profile a single table: facts + masked random samples."""
        facts = TableFacts(table_name=table.table_name, schema_name=table.schema_name)
        quoted_table = f'"{table.schema_name}"."{table.table_name}"'

        # 1. Total row count (with statement timeout)
        try:
            row_count_res = await conn.fetchval(
                f"SELECT count(*) FROM {quoted_table};",
                timeout=STATEMENT_TIMEOUT_MS / 1000.0,
            )
            facts.total_rows = int(row_count_res or 0)
        except Exception as e:
            logger.warning(f"Could not get exact row count for {table.table_name}: {e}")
            facts.total_rows = table.row_count_estimate or 0

        # 2. Per-column facts
        for col_name, col in table.columns.items():
            is_sens = SensitivityGuard.is_sensitive_column(col_name)
            col_info: Dict[str, Any] = {
                "name": col_name,
                "data_type": col.raw_data_type,
                "is_nullable": col.is_nullable,
                "is_primary_key": col.is_primary_key,
                "is_foreign_key": col.is_foreign_key,
                "is_sensitive": is_sens,
                "distinct_count": None,
                "null_percentage": None,
                "min_value": None,
                "max_value": None,
                "distinct_values": None,
            }

            # If column is sensitive, DO NOT compute stats or distinct values
            if is_sens:
                facts.columns[col_name] = col_info
                continue

            # Compute stats for safe column
            quoted_col = f'"{col_name}"'
            try:
                # Distinct count & null count in a single efficient query
                stat_sql = f"""
                SELECT 
                    count(DISTINCT {quoted_col}) AS distinct_count,
                    count(*) FILTER (WHERE {quoted_col} IS NULL) AS null_count,
                    count(*) AS total_count
                FROM {quoted_table};
                """
                stat_res = await conn.fetchrow(stat_sql, timeout=STATEMENT_TIMEOUT_MS / 1000.0)
                if stat_res:
                    dist_cnt = stat_res["distinct_count"] or 0
                    null_cnt = stat_res["null_count"] or 0
                    tot_cnt = stat_res["total_count"] or 1
                    null_pct = round((null_cnt / max(1, tot_cnt)) * 100)

                    col_info["distinct_count"] = dist_cnt
                    col_info["null_percentage"] = null_pct

                    # Check for min/max on scalar types (numeric, date, text length)
                    raw_type = col.raw_data_type.lower()
                    if any(t in raw_type for t in ["int", "numeric", "float", "decimal", "date", "time"]):
                        min_max_sql = f"SELECT min({quoted_col})::text AS min_val, max({quoted_col})::text AS max_val FROM {quoted_table};"
                        min_max_res = await conn.fetchrow(min_max_sql, timeout=STATEMENT_TIMEOUT_MS / 1000.0)
                        if min_max_res:
                            col_info["min_value"] = str(min_max_res["min_val"]) if min_max_res["min_val"] is not None else None
                            col_info["max_value"] = str(min_max_res["max_val"]) if min_max_res["max_val"] is not None else None

                    # If low-cardinality text/varchar column, fetch full list of distinct values
                    if any(t in raw_type for t in ["char", "text", "varchar"]) and 0 < dist_cnt <= MAX_DISTINCT_VALUES_CARDINALITY:
                        dist_val_sql = f"""
                        SELECT DISTINCT {quoted_col}::text AS val 
                        FROM {quoted_table} 
                        WHERE {quoted_col} IS NOT NULL 
                        ORDER BY val 
                        LIMIT {MAX_DISTINCT_VALUES_CARDINALITY};
                        """
                        dist_rows = await conn.fetch(dist_val_sql, timeout=STATEMENT_TIMEOUT_MS / 1000.0)
                        col_info["distinct_values"] = [r["val"] for r in dist_rows if r["val"] is not None]

            except Exception as stat_err:
                logger.debug(f"Could not compute full stats for column {table.table_name}.{col_name}: {stat_err}")

            facts.columns[col_name] = col_info

        # 3. Random Row Sampling (10-20 random rows, NOT first-N)
        if facts.total_rows > 0:
            try:
                # Using RANDOM() with limit
                sample_sql = f"SELECT * FROM {quoted_table} ORDER BY RANDOM() LIMIT {SAMPLE_ROW_COUNT};"
                sample_rows = await conn.fetch(sample_sql, timeout=STATEMENT_TIMEOUT_MS / 1000.0)
                raw_samples = [dict(r) for r in sample_rows]

                # Apply sensitive column deny-list and PII masking BEFORE anything leaves
                col_names = list(table.columns.keys())
                facts.samples = SensitivityGuard.sanitize_sample_rows(col_names, raw_samples)
            except Exception as sample_err:
                logger.warning(f"Could not fetch random samples for table {table.table_name}: {sample_err}")
                facts.samples = []

        return facts
