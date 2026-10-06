"""Phase 2 Knowledge Layer: Relationship Finder Stage & Graph

Discovers relationships between tables:
1. Declared foreign keys (including composite FKs):
   - source='declared', status='confirmed', confidence=1.0.
2. Inferred foreign key candidates:
   - Name patterns (<table>_id, <singular>_id, fk_*, same column name as PK)
   - Data type compatibility
   - Bounded value-overlap check (sample distinct child values vs parent PK, 5s timeout, skip sensitive columns)
   - Confidence = weighted score of name match, type match, overlap ratio, PK/unique target.
   - Cardinality (1:1, 1:N, N:M) from sampled uniqueness.
   - source='inferred', status='draft'.
3. Items stored in kb2_knowledge_items:
   - item_type='relationship'
   - item_key='rel:schema.child.col->schema.parent.col' (or comma-separated composite)
   - payload: child_table, child_columns, parent_table, parent_columns, cardinality, confidence, evidence
"""

import uuid
import re
import hashlib
import json
import logging
import asyncio
from typing import Optional, Dict, Any, List, Set, Tuple
from datetime import datetime, timezone

from ..adapters.phase1_adapter import Phase1Adapter, SchemaView, TableView, ColumnView
from ..repositories.knowledge_item_repository import KnowledgeItemRepository
from ..sensitivity import is_sensitive_column

logger = logging.getLogger(__name__)


def compute_rel_hash(
    child_table: str,
    child_cols: List[str],
    parent_table: str,
    parent_cols: List[str],
    cardinality: str,
    confidence: float,
) -> str:
    """Compute deterministic SHA-256 hash for relationship object."""
    data = {
        "child_table": child_table,
        "child_cols": sorted(child_cols),
        "parent_table": parent_table,
        "parent_cols": sorted(parent_cols),
        "cardinality": cardinality,
        "confidence": round(confidence, 4),
    }
    dumped = json.dumps(data, sort_keys=True)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def _singularize(name: str) -> str:
    """Basic English singularization for table name matching."""
    lower = name.lower()
    if lower.endswith("ies") and len(lower) > 3:
        return lower[:-3] + "y"
    if lower.endswith("es") and len(lower) > 3:
        for suffix in ("sses", "shes", "ches", "xes", "zes"):
            if lower.endswith(suffix):
                return lower[:-2]
        return lower[:-1]
    if lower.endswith("s") and not lower.endswith("ss") and len(lower) > 2:
        return lower[:-1]
    return lower


def _types_compatible(type1: str, type2: str) -> bool:
    """Check if two SQL data types are compatible for a join / foreign key."""
    t1 = type1.lower().split("(")[0].strip()
    t2 = type2.lower().split("(")[0].strip()

    if t1 == t2:
        return True

    # Numeric integer types
    int_types = {"int", "integer", "bigint", "smallint", "int2", "int4", "int8", "serial", "bigserial"}
    if t1 in int_types and t2 in int_types:
        return True

    # UUID types
    uuid_types = {"uuid", "varchar", "text", "char"}
    if t1 == "uuid" and t2 in uuid_types:
        return True
    if t2 == "uuid" and t1 in uuid_types:
        return True

    # String / text types
    text_types = {"varchar", "text", "char", "character varying", "bpchar", "nvarchar", "string"}
    if t1 in text_types and t2 in text_types:
        return True

    return False


def _check_name_match(child_col: str, parent_table: str, parent_col: str) -> Tuple[bool, float, str]:
    """Check name match pattern and return (matches, score, evidence_reason)."""
    c_col = child_col.lower()
    p_tbl = parent_table.lower()
    p_col = parent_col.lower()
    p_tbl_singular = _singularize(p_tbl)

    # 1. <table>_id or <singular>_id -> e.g. customer_id, customers_id
    if c_col in (f"{p_tbl}_id", f"{p_tbl_singular}_id", f"{p_tbl}id", f"{p_tbl_singular}id"):
        return True, 0.40, f"child column '{child_col}' matches pattern '{p_tbl_singular}_id'"

    # 2. fk_<parent> or fk_<table>_<col>
    if c_col.startswith("fk_"):
        suffix = c_col[3:]
        if suffix in (p_tbl, p_tbl_singular, f"{p_tbl}_id", f"{p_tbl_singular}_id", p_col):
            return True, 0.35, f"child column '{child_col}' has fk_ prefix matching parent table or column"

    # 3. Same column name as a PK (e.g. employee_id in both, or uuid, but ignore generic 'id' unless specific)
    if c_col == p_col:
        if c_col == "id":
            # 'id' == 'id' across tables without table qualifier is weak by itself
            return False, 0.0, "generic id name match ignored"
        return True, 0.30, f"child column '{child_col}' exactly matches parent PK column name"

    # 4. Column contains parent table singular (e.g. author_ref -> authors.id)
    if p_tbl_singular in c_col and ("id" in c_col or "key" in c_col or "code" in c_col):
        return True, 0.25, f"child column '{child_col}' contains singular parent table name '{p_tbl_singular}'"

    return False, 0.0, "no name match"


async def _sample_value_overlap(
    adapter: Phase1Adapter,
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    child_table_name: str,
    child_col_name: str,
    parent_table_name: str,
    parent_col_name: str,
) -> Tuple[float, str]:
    """Sample distinct child values and check overlap with parent column.
    
    Returns (overlap_ratio: float, cardinality: str).
    Guarded with statement_timeout=5000 in open_readonly_connection.
    """
    try:
        async with adapter.open_readonly_connection(tenant_id, kb_id) as conn:
            # Safe quoting
            # Query child distinct sample (up to 200 non-null values)
            c_query = f'SELECT "{child_col_name}" FROM "{child_table_name}" WHERE "{child_col_name}" IS NOT NULL LIMIT 200;'
            child_rows = await conn.fetch(c_query)
            if not child_rows:
                return 0.0, "1:N"

            raw_child_vals = [r[0] for r in child_rows]
            child_set = set(raw_child_vals)
            if not child_set:
                return 0.0, "1:N"

            # Check uniqueness in child sample for cardinality
            child_unique_ratio = len(child_set) / max(1, len(raw_child_vals))
            is_child_unique = child_unique_ratio > 0.95 and len(raw_child_vals) > 5

            # Sample parent values matching child values
            # Using parameter array
            p_query = f'SELECT DISTINCT "{parent_col_name}" FROM "{parent_table_name}" WHERE "{parent_col_name}" = ANY($1::text[]) LIMIT 200;'
            # Convert values to strings for matching
            child_str_vals = [str(v) for v in list(child_set)[:100]]
            # Fallback if types don't cast to text directly: query by IN clause with parameterized query
            placeholders = ", ".join(f"${i+1}" for i in range(len(child_str_vals)))
            p_sql = f'SELECT DISTINCT "{parent_col_name}"::text FROM "{parent_table_name}" WHERE "{parent_col_name}"::text IN ({placeholders});'
            matched_rows = await conn.fetch(p_sql, *child_str_vals)

            matched_count = len(matched_rows)
            overlap_ratio = matched_count / max(1, len(child_str_vals))

            # Cardinality determination
            cardinality = "1:1" if is_child_unique else "1:N"
            return float(overlap_ratio), cardinality
    except Exception as exc:
        logger.debug(f"Overlap check skipped or failed for {child_table_name}.{child_col_name} -> {parent_table_name}.{parent_col_name}: {exc}")
        return 0.0, "1:N"


async def run_stage_relationships(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    schema_version: str,
    adapter: Phase1Adapter,
    item_repo: KnowledgeItemRepository,
    heartbeat_cb: Optional[Any] = None,
    min_inferred_confidence: float = 0.50,
) -> Dict[str, Any]:
    """Execute Stage 2: Declared and Inferred Relationship Discovery."""
    logger.info(f"[Stage: Relationships] Starting for KB={kb_id}, schema_version={schema_version}")
    schema_view = await adapter.get_current_schema(tenant_id, kb_id)
    if not schema_view or not schema_view.tables:
        logger.info("[Stage: Relationships] No tables found in schema view.")
        return {"declared_relationships": 0, "inferred_relationships": 0}

    tables = schema_view.tables
    declared_count = 0
    inferred_count = 0

    declared_rel_pairs: Set[Tuple[str, str, str, str]] = set()

    # --------------------------------------------------------------------------
    # 1. Declared Foreign Keys (incl. Composite)
    # --------------------------------------------------------------------------
    for t_name, table in tables.items():
        if heartbeat_cb:
            await heartbeat_cb()

        for fk in table.foreign_keys:
            c_cols = fk.constrained_columns
            p_table = fk.referred_table
            p_cols = fk.referred_columns

            c_cols_str = ",".join(c_cols)
            p_cols_str = ",".join(p_cols)
            item_key = f"rel:{table.schema_name}.{table.table_name}.{c_cols_str}->{fk.referred_schema or table.schema_name}.{p_table}.{p_cols_str}"

            # Track to avoid inferring already declared FKs
            for cc in c_cols:
                for pc in p_cols:
                    declared_rel_pairs.add((table.table_name.lower(), cc.lower(), p_table.lower(), pc.lower()))

            cardinality = "1:N"
            # If constrained columns form the PK or unique constraint, it's 1:1
            if set(c_cols) == set(table.primary_key_columns):
                cardinality = "1:1"

            payload = {
                "child_schema": table.schema_name,
                "child_table": table.table_name,
                "child_columns": c_cols,
                "parent_schema": fk.referred_schema or table.schema_name,
                "parent_table": p_table,
                "parent_columns": p_cols,
                "cardinality": cardinality,
                "confidence": 1.0,
                "evidence": {
                    "constraint_name": fk.name,
                    "on_delete": fk.on_delete,
                    "on_update": fk.on_update,
                    "type": "declared_foreign_key",
                },
            }

            obj_hash = compute_rel_hash(table.table_name, c_cols, p_table, p_cols, cardinality, 1.0)

            await item_repo.upsert_item(
                db_knowledgebase_id=kb_id,
                item_type="relationship",
                item_key=item_key,
                valid_from_version=schema_version,
                object_hash=obj_hash,
                source="declared",
                payload=payload,
                confidence=1.0,
                status="confirmed",
            )
            declared_count += 1

    # --------------------------------------------------------------------------
    # 2. Inferred FK Candidates
    # --------------------------------------------------------------------------
    for c_tname, c_table in tables.items():
        if heartbeat_cb:
            await heartbeat_cb()

        for c_colname, c_col in c_table.columns.items():
            # Skip declared FK columns
            if c_col.is_foreign_key:
                continue
            # Skip sensitive columns
            if is_sensitive_column(c_colname):
                continue

            for p_tname, p_table in tables.items():
                if c_tname == p_tname:
                    continue  # skip self-joins for candidate inference

                # Must target a PK column or column named id / uuid
                target_cols = [p_table.columns[pk] for pk in p_table.primary_key_columns if pk in p_table.columns]
                if not target_cols:
                    # Fallback to column named 'id' if present
                    if "id" in p_table.columns:
                        target_cols = [p_table.columns["id"]]

                for p_col in target_cols:
                    p_colname = p_col.name
                    # Skip sensitive parent
                    if is_sensitive_column(p_colname):
                        continue

                    # Check if already declared
                    if (c_table.table_name.lower(), c_colname.lower(), p_table.table_name.lower(), p_colname.lower()) in declared_rel_pairs:
                        continue

                    # 2a. Name pattern check
                    name_matched, name_score, name_reason = _check_name_match(c_colname, p_table.table_name, p_colname)
                    if not name_matched:
                        continue

                    # 2b. Type compatibility
                    if not _types_compatible(c_col.data_type, p_col.data_type):
                        continue
                    type_score = 0.20

                    # 2c. Target is PK / Unique bonus
                    target_score = 0.15 if p_col.is_primary_key else 0.05

                    # 2d. Value overlap sampling (bounded 5s)
                    overlap_ratio, sampled_cardinality = await _sample_value_overlap(
                        adapter=adapter,
                        tenant_id=tenant_id,
                        kb_id=kb_id,
                        child_table_name=c_table.table_name,
                        child_col_name=c_colname,
                        parent_table_name=p_table.table_name,
                        parent_col_name=p_colname,
                    )

                    overlap_score = min(0.25, overlap_ratio * 0.25)
                    confidence = round(name_score + type_score + target_score + overlap_score, 2)

                    if confidence >= min_inferred_confidence and (overlap_ratio > 0.0 or name_score >= 0.35):
                        item_key = f"rel:{c_table.schema_name}.{c_table.table_name}.{c_colname}->{p_table.schema_name}.{p_table.table_name}.{p_colname}"
                        payload = {
                            "child_schema": c_table.schema_name,
                            "child_table": c_table.table_name,
                            "child_columns": [c_colname],
                            "parent_schema": p_table.schema_name,
                            "parent_table": p_table.table_name,
                            "parent_columns": [p_colname],
                            "cardinality": sampled_cardinality,
                            "confidence": confidence,
                            "evidence": {
                                "name_match": name_reason,
                                "name_score": name_score,
                                "type_score": type_score,
                                "target_score": target_score,
                                "overlap_ratio": round(overlap_ratio, 3),
                                "overlap_score": overlap_score,
                            },
                        }
                        obj_hash = compute_rel_hash(c_table.table_name, [c_colname], p_table.table_name, [p_colname], sampled_cardinality, confidence)

                        await item_repo.upsert_item(
                            db_knowledgebase_id=kb_id,
                            item_type="relationship",
                            item_key=item_key,
                            valid_from_version=schema_version,
                            object_hash=obj_hash,
                            source="inferred",
                            payload=payload,
                            confidence=confidence,
                            status="draft",
                        )
                        inferred_count += 1

    await item_repo.db.commit()

    logger.info(
        f"[Stage: Relationships] Finished for KB={kb_id}. "
        f"Declared: {declared_count}, Inferred: {inferred_count}"
    )
    return {
        "declared_relationships": declared_count,
        "inferred_relationships": inferred_count,
    }
