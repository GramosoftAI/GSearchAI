"""Phase 2 Knowledge Layer: Schema Drift Detection & Dependency Invalidation

Computes structural differences between schema snapshots:
Events:
- TABLE_ADDED
- TABLE_DROPPED
- COLUMN_ADDED
- COLUMN_MODIFIED
- COLUMN_DROPPED

Dependents Handling:
- Dropped/modified objects mark related relationships, glossary, metric, rule items:
  - If item is locked by admin: write staged_payload / mark 'conflict'
  - Else: mark 'stale'
- Deprecates verified query memory records whose referenced_items contain dropped/modified objects.
"""

import uuid
import logging
from enum import Enum
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..adapters.phase1_adapter import SchemaView, TableView, ColumnView
from ..models.knowledge_items import KB2KnowledgeItem, KB2QueryMemory

logger = logging.getLogger(__name__)


class DriftEventType(str, Enum):
    TABLE_ADDED = "TABLE_ADDED"
    TABLE_DROPPED = "TABLE_DROPPED"
    COLUMN_ADDED = "COLUMN_ADDED"
    COLUMN_MODIFIED = "COLUMN_MODIFIED"
    COLUMN_DROPPED = "COLUMN_DROPPED"


@dataclass
class DriftEvent:
    event_type: DriftEventType
    table_name: str
    column_name: Optional[str] = None
    old_details: Dict[str, Any] = field(default_factory=dict)
    new_details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SchemaDiffResult:
    events: List[DriftEvent] = field(default_factory=list)
    added_tables: Set[str] = field(default_factory=set)
    dropped_tables: Set[str] = field(default_factory=set)
    modified_tables: Set[str] = field(default_factory=set)
    added_columns: Dict[str, Set[str]] = field(default_factory=dict)
    dropped_columns: Dict[str, Set[str]] = field(default_factory=dict)
    modified_columns: Dict[str, Set[str]] = field(default_factory=dict)

    @property
    def has_changes(self) -> bool:
        return len(self.events) > 0

    @property
    def affected_tables(self) -> Set[str]:
        return self.added_tables | self.dropped_tables | self.modified_tables


def compute_schema_diff(
    old_schema: Optional[SchemaView],
    new_schema: SchemaView,
) -> SchemaDiffResult:
    """Compare two SchemaView snapshots and produce detailed DriftEvents."""
    diff = SchemaDiffResult()

    if not old_schema:
        # First sync: all tables and columns are added
        for t_name, t_view in new_schema.tables.items():
            diff.added_tables.add(t_name)
            diff.events.append(
                DriftEvent(
                    event_type=DriftEventType.TABLE_ADDED,
                    table_name=t_name,
                    new_details={"columns": list(t_view.columns.keys())},
                )
            )
            diff.added_columns[t_name] = set(t_view.columns.keys())
        return diff

    old_tables = old_schema.tables
    new_tables = new_schema.tables

    old_t_names = set(old_tables.keys())
    new_t_names = set(new_tables.keys())

    # 1. Added Tables
    for t_name in new_t_names - old_t_names:
        diff.added_tables.add(t_name)
        t_view = new_tables[t_name]
        diff.events.append(
            DriftEvent(
                event_type=DriftEventType.TABLE_ADDED,
                table_name=t_name,
                new_details={"columns": list(t_view.columns.keys())},
            )
        )
        diff.added_columns[t_name] = set(t_view.columns.keys())

    # 2. Dropped Tables
    for t_name in old_t_names - new_t_names:
        diff.dropped_tables.add(t_name)
        t_view = old_tables[t_name]
        diff.events.append(
            DriftEvent(
                event_type=DriftEventType.TABLE_DROPPED,
                table_name=t_name,
                old_details={"columns": list(t_view.columns.keys())},
            )
        )
        diff.dropped_columns[t_name] = set(t_view.columns.keys())

    # 3. Tables present in both -> check column changes
    for t_name in old_t_names & new_t_names:
        old_cols = old_tables[t_name].columns
        new_cols = new_tables[t_name].columns

        old_c_names = set(old_cols.keys())
        new_c_names = set(new_cols.keys())

        table_modified = False

        # Columns Added
        for c_name in new_c_names - old_c_names:
            table_modified = True
            diff.added_columns.setdefault(t_name, set()).add(c_name)
            diff.events.append(
                DriftEvent(
                    event_type=DriftEventType.COLUMN_ADDED,
                    table_name=t_name,
                    column_name=c_name,
                    new_details={"data_type": new_cols[c_name].data_type},
                )
            )

        # Columns Dropped
        for c_name in old_c_names - new_c_names:
            table_modified = True
            diff.dropped_columns.setdefault(t_name, set()).add(c_name)
            diff.events.append(
                DriftEvent(
                    event_type=DriftEventType.COLUMN_DROPPED,
                    table_name=t_name,
                    column_name=c_name,
                    old_details={"data_type": old_cols[c_name].data_type},
                )
            )

        # Columns Modified
        for c_name in old_c_names & new_c_names:
            oc = old_cols[c_name]
            nc = new_cols[c_name]
            type_changed = oc.data_type != nc.data_type
            null_changed = oc.is_nullable != nc.is_nullable
            pk_changed = oc.is_primary_key != nc.is_primary_key

            if type_changed or null_changed or pk_changed:
                table_modified = True
                diff.modified_columns.setdefault(t_name, set()).add(c_name)
                diff.events.append(
                    DriftEvent(
                        event_type=DriftEventType.COLUMN_MODIFIED,
                        table_name=t_name,
                        column_name=c_name,
                        old_details={"data_type": oc.data_type, "is_nullable": oc.is_nullable, "is_pk": oc.is_primary_key},
                        new_details={"data_type": nc.data_type, "is_nullable": nc.is_nullable, "is_pk": nc.is_primary_key},
                    )
                )

        if table_modified:
            diff.modified_tables.add(t_name)

    return diff


async def invalidate_dependents_on_drift(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    diff: SchemaDiffResult,
    db_session: AsyncSession,
) -> Dict[str, int]:
    """Mark dependent items stale or conflict, and deprecate query memory affected by dropped/modified objects."""
    if not diff.has_changes:
        return {"stale_items": 0, "conflict_items": 0, "deprecated_queries": 0}

    now_utc = datetime.now(timezone.utc)
    stale_count = 0
    conflict_count = 0
    deprecated_queries_count = 0

    # Build set of invalidated identifiers (e.g. table:orders, column:orders.col, orders, orders.col)
    invalidated_tokens: Set[str] = set()
    for t in diff.dropped_tables:
        invalidated_tokens.add(t.lower())
        invalidated_tokens.add(f"table:{t.lower()}")

    for t, cols in diff.dropped_columns.items():
        for c in cols:
            invalidated_tokens.add(f"{t.lower()}.{c.lower()}")
            invalidated_tokens.add(f"column:{t.lower()}.{c.lower()}")

    for t, cols in diff.modified_columns.items():
        for c in cols:
            invalidated_tokens.add(f"{t.lower()}.{c.lower()}")
            invalidated_tokens.add(f"column:{t.lower()}.{c.lower()}")

    # 1. Fetch active knowledge items (relationships, metrics, glossary, rules)
    stmt = select(KB2KnowledgeItem).where(
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
        KB2KnowledgeItem.item_type.in_(["relationship", "metric", "glossary", "rule"]),
        KB2KnowledgeItem.status.in_(["confirmed", "draft"]),
    )
    res = await db_session.execute(stmt)
    items = res.scalars().all()

    for it in items:
        p = it.payload or {}
        is_affected = False

        if it.item_type == "relationship":
            c_tbl = (p.get("child_table") or "").lower()
            p_tbl = (p.get("parent_table") or "").lower()
            c_cols = [c.lower() for c in p.get("child_columns", [])]
            p_cols = [c.lower() for c in p.get("parent_columns", [])]

            if c_tbl in diff.dropped_tables or p_tbl in diff.dropped_tables:
                is_affected = True
            for c in c_cols:
                if f"{c_tbl}.{c}" in invalidated_tokens:
                    is_affected = True
            for c in p_cols:
                if f"{p_tbl}.{c}" in invalidated_tokens:
                    is_affected = True

        elif it.item_type in ("metric", "rule"):
            deps = [d.lower() for d in p.get("depends_on", [])]
            for d in deps:
                for inv in invalidated_tokens:
                    if inv in d:
                        is_affected = True
                        break

        elif it.item_type == "glossary":
            tgt = (p.get("target_key") or "").lower()
            for inv in invalidated_tokens:
                if inv in tgt:
                    is_affected = True
                    break

        if is_affected:
            if it.is_locked_by_admin:
                it.status = "conflict"
                it.staged_payload = {"stale_reason": "dependent object dropped or modified in schema drift"}
                conflict_count += 1
            else:
                it.status = "stale"
                stale_count += 1
            it.updated_at = now_utc

    # 2. Deprecate query memory items referencing dropped / modified objects
    stmt_qm = select(KB2QueryMemory).where(
        KB2QueryMemory.tenant_id == tenant_id,
        KB2QueryMemory.db_knowledgebase_id == kb_id,
        KB2QueryMemory.status == "verified",
    )
    res_qm = await db_session.execute(stmt_qm)
    qm_items = res_qm.scalars().all()

    for qm in qm_items:
        refs = [r.lower() for r in (qm.referenced_items or [])]
        is_qm_affected = False
        for r in refs:
            for inv in invalidated_tokens:
                if inv in r:
                    is_qm_affected = True
                    break
            if is_qm_affected:
                break

        if is_qm_affected:
            qm.status = "deprecated"
            deprecated_queries_count += 1

    await db_session.commit()

    logger.info(
        f"[Drift Invalidation] Marked stale: {stale_count}, "
        f"conflict: {conflict_count}, deprecated queries: {deprecated_queries_count}"
    )

    return {
        "stale_items": stale_count,
        "conflict_items": conflict_count,
        "deprecated_queries": deprecated_queries_count,
    }
