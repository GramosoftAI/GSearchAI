"""Deterministic Canonical Table Filter

Implements rule-based canonicality detection to eliminate table collisions
(historical tracking, backup tables, unconstrained unindexed tables)
deterministically without relying on LLMs or soft heuristic scoring.
"""

from typing import Dict, Optional
from ..schemas.canonical import TableSchema


def is_canonical_table(
    table: TableSchema,
    canonical_overrides: Optional[Dict[str, bool]] = None,
) -> bool:
    """
    Deterministic rule chain, evaluated in order.

    If canonical_overrides is provided (e.g. from DatabaseKnowledgebase.metadata["canonical_overrides"]
    or operator whitelist), any explicit boolean entry for this table:
      - table.table_name.lower()
      - f"{table.schema_name}.{table.table_name}".lower()
    takes precedence over all automatic rules.
    """
    name = getattr(table, "name", None) or getattr(table, "table_name", "")
    name = name.lower().strip()
    schema_name = (getattr(table, "schema_name", None) or "public").lower().strip()
    qualified_name = f"{schema_name}.{name}"

    # Operator whitelist / override precedence
    if canonical_overrides:
        if qualified_name in canonical_overrides:
            return canonical_overrides[qualified_name]
        if name in canonical_overrides:
            return canonical_overrides[name]
        for k, v in canonical_overrides.items():
            k_clean = k.lower().strip()
            if k_clean in (name, qualified_name):
                return v

    # Rule 1: Historical tracking tables (e.g. historical*, *_historical*, *_history*, *_hist)
    if (
        "historical" in name
        or "_history" in name
        or name.endswith("_hist")
        or name.startswith("hist_")
        or "_hist_" in name
    ):
        return False

    # Rule 2: Backup and temporary tables (e.g. attendance_backup, employees_bak, backup_events)
    if (
        "_backup" in name
        or name.startswith("backup_")
        or "_bak" in name
        or name.startswith("bak_")
    ):
        return False

    # Rule 3: Tables lacking a primary key constraint
    if not table.has_primary_key:
        return False

    # Rule 4: Tables with ID-like FK naming convention but zero declared FK constraints
    # (e.g. employee_id_id present but no FK constraint declared —
    # flag, do not silently trust naming convention alone at this gate)
    if table.has_id_like_fk_columns and not table.has_declared_fk:
        return False

    return True
