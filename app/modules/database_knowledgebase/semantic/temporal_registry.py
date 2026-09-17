"""Temporal Registry

Discovers, classifies, and manages temporal columns (dates, timestamps, time-of-day,
durations) across client databases. Distinguishes operational business dates from
system audit timestamps, and provides structured capabilities for date filtering and grouping.
"""

from typing import Dict, List, Optional, Set
from pydantic import BaseModel, ConfigDict, Field

from .database_knowledge_profile import (
    ColumnSemanticProfile,
    ColumnSemanticRole,
    ColumnSemanticSubtype,
    TemporalColumnProfile,
)


class UniversalTemporalRegistry:
    """
    Manages temporal capabilities across discovered tables and columns.
    """

    def __init__(self):
        self._profiles: Dict[str, TemporalColumnProfile] = {}  # Key: f"{schema}.{table}.{column}".lower()
        self._table_temporals: Dict[str, List[TemporalColumnProfile]] = {}

    def register_from_columns(
        self, columns: Dict[str, ColumnSemanticProfile]
    ) -> Dict[str, TemporalColumnProfile]:
        """
        Discovers and registers temporal profiles for all date/time columns.
        """
        discovered: Dict[str, TemporalColumnProfile] = {}

        for col_key, c_prof in columns.items():
            if c_prof.role != ColumnSemanticRole.TEMPORAL:
                continue

            supports_time_filter = c_prof.subtype in (
                ColumnSemanticSubtype.DATETIME,
                ColumnSemanticSubtype.TIME_OF_DAY,
                ColumnSemanticSubtype.CREATED_AT,
                ColumnSemanticSubtype.UPDATED_AT,
            )
            supports_date_range = c_prof.subtype in (
                ColumnSemanticSubtype.DATE,
                ColumnSemanticSubtype.DATETIME,
                ColumnSemanticSubtype.CREATED_AT,
                ColumnSemanticSubtype.UPDATED_AT,
            )

            profile = TemporalColumnProfile(
                schema_name=c_prof.schema_name,
                table_name=c_prof.table_name,
                column_name=c_prof.column_name,
                temporal_subtype=c_prof.subtype,
                supports_time_filter=supports_time_filter,
                supports_date_range=supports_date_range,
            )

            key = f"{c_prof.schema_name}.{c_prof.table_name}.{c_prof.column_name}".lower()
            discovered[key] = profile
            self._profiles[key] = profile

            tbl_key = f"{c_prof.schema_name}.{c_prof.table_name}".lower()
            if tbl_key not in self._table_temporals:
                self._table_temporals[tbl_key] = []
            self._table_temporals[tbl_key].append(profile)

        return discovered

    def get_temporal_columns_for_table(
        self, table_name: str, schema_name: str = "public"
    ) -> List[TemporalColumnProfile]:
        """Returns all temporal columns for a table."""
        tbl_key = f"{schema_name}.{table_name}".lower()
        return self._table_temporals.get(tbl_key, [])

    def get_primary_business_date(
        self, table_name: str, schema_name: str = "public"
    ) -> Optional[TemporalColumnProfile]:
        """
        Finds the primary operational business date for a table.
        Prioritizes DATE/DATETIME over system audit columns (CREATED_AT, UPDATED_AT).
        """
        cols = self.get_temporal_columns_for_table(table_name, schema_name)
        if not cols:
            return None

        # 1. Operational dates
        for c in cols:
            if c.temporal_subtype in (ColumnSemanticSubtype.DATE, ColumnSemanticSubtype.DATETIME):
                return c

        # 2. Audit dates fallback
        for c in cols:
            if c.temporal_subtype == ColumnSemanticSubtype.CREATED_AT:
                return c

        return cols[0]
