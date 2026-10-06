"""Phase 2 Knowledge Layer: Quality Report & Readiness Evaluation

Evaluates the readiness and completeness of the database knowledge base:
Metrics:
- % tables with description and grain
- % columns with meaning
- % items confirmed vs draft
- relationship confidence distribution (high >= 0.85, medium 0.65-0.85, low < 0.65)
- columns needing admin mapping (coded values)
- sensitive column count
- tables with no relationships (isolated tables)
- value index coverage (% categorical columns indexed)
- seed example count in query memory
- last run status and token cost
- Single readiness verdict: 'READY', 'NEEDS_REVIEW', or 'NOT_READY' based on configurable thresholds
- Top 10 actionable review priorities for admin
"""

import uuid
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pydantic import BaseModel, Field

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.knowledge_items import (
    KB2KnowledgeItem,
    KB2EntityValue,
    KB2QueryMemory,
    KB2JobRun,
)


class QualityThresholds(BaseModel):
    min_table_desc_pct: float = 80.0
    min_column_meaning_pct: float = 70.0
    min_confirmed_item_pct: float = 60.0
    max_unmapped_coded_cols: int = 10
    min_seed_examples: int = 10


class QualityReportResult(BaseModel):
    db_knowledgebase_id: str
    tenant_id: str
    evaluated_at: str

    total_tables: int = 0
    tables_with_description_pct: float = 0.0
    tables_with_grain_pct: float = 0.0

    total_columns: int = 0
    columns_with_meaning_pct: float = 0.0
    columns_needing_admin_mapping: List[str] = Field(default_factory=list)
    sensitive_columns_count: int = 0

    total_items: int = 0
    confirmed_items_pct: float = 0.0
    draft_items_pct: float = 0.0
    conflict_items_count: int = 0

    total_relationships: int = 0
    relationship_confidence_distribution: Dict[str, int] = Field(default_factory=dict)
    tables_with_no_relationships: List[str] = Field(default_factory=list)

    total_entity_values_indexed: int = 0
    categorical_columns_indexed_count: int = 0

    seed_example_count: int = 0

    last_run_status: Optional[str] = None
    last_run_tokens: int = 0
    last_run_at: Optional[str] = None

    readiness_verdict: str = "NOT_READY"  # READY, NEEDS_REVIEW, NOT_READY
    top_10_review_priorities: List[Dict[str, Any]] = Field(default_factory=list)


async def generate_quality_report(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    db_session: AsyncSession,
    thresholds: Optional[QualityThresholds] = None,
) -> QualityReportResult:
    """Compute comprehensive quality metrics and readiness verdict for a knowledge base."""
    th = thresholds or QualityThresholds()
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Fetch all knowledge items for this KB
    stmt_items = select(KB2KnowledgeItem).where(
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
    )
    res_items = await db_session.execute(stmt_items)
    all_items = res_items.scalars().all()

    tables = [it for it in all_items if it.item_type == "table"]
    columns = [it for it in all_items if it.item_type == "column"]
    relationships = [it for it in all_items if it.item_type == "relationship"]

    total_tables = len(tables)
    tables_with_desc = 0
    tables_with_grain = 0
    for t in tables:
        sem = (t.payload or {}).get("semantic", {})
        if sem.get("description"):
            tables_with_desc += 1
        if sem.get("row_grain"):
            tables_with_grain += 1

    tbl_desc_pct = round((tables_with_desc / total_tables * 100), 1) if total_tables else 0.0
    tbl_grain_pct = round((tables_with_grain / total_tables * 100), 1) if total_tables else 0.0

    total_columns = len(columns)
    columns_with_meaning = 0
    coded_columns = []
    sensitive_columns = []
    for c in columns:
        p = c.payload or {}
        sem = p.get("semantic", {})
        if sem.get("meaning"):
            columns_with_meaning += 1
        if sem.get("is_coded_value"):
            coded_columns.append(c.item_key)
        if c.is_sensitive or p.get("is_sensitive"):
            sensitive_columns.append(c.item_key)

    col_meaning_pct = round((columns_with_meaning / total_columns * 100), 1) if total_columns else 0.0

    # Status distribution
    total_items = len(all_items)
    confirmed_count = sum(1 for it in all_items if it.status == "confirmed")
    draft_count = sum(1 for it in all_items if it.status == "draft")
    conflict_count = sum(1 for it in all_items if it.status == "conflict")

    confirmed_pct = round((confirmed_count / total_items * 100), 1) if total_items else 0.0
    draft_pct = round((draft_count / total_items * 100), 1) if total_items else 0.0

    # Relationship analysis
    rel_conf_dist = {"high_85_plus": 0, "medium_65_85": 0, "low_sub_65": 0}
    rel_connected_tables = set()
    for r in relationships:
        conf = r.confidence
        if conf >= 0.85:
            rel_conf_dist["high_85_plus"] += 1
        elif conf >= 0.65:
            rel_conf_dist["medium_65_85"] += 1
        else:
            rel_conf_dist["low_sub_65"] += 1

        rp = r.payload or {}
        if rp.get("child_table"):
            rel_connected_tables.add(rp["child_table"].lower())
        if rp.get("parent_table"):
            rel_connected_tables.add(rp["parent_table"].lower())

    isolated_tables = []
    for t in tables:
        t_name = (t.payload or {}).get("table_name") or t.item_key.split(".")[-1]
        if t_name.lower() not in rel_connected_tables:
            isolated_tables.append(t_name)

    # 2. Distinct Value Index stats
    stmt_ev = select(func.count(KB2EntityValue.id), func.count(func.distinct(KB2EntityValue.column_name))).where(
        KB2EntityValue.tenant_id == tenant_id,
        KB2EntityValue.db_knowledgebase_id == kb_id,
    )
    res_ev = await db_session.execute(stmt_ev)
    ev_total, ev_cols = res_ev.one()

    # 3. Query Memory seed examples
    stmt_qm = select(func.count(KB2QueryMemory.id)).where(
        KB2QueryMemory.tenant_id == tenant_id,
        KB2QueryMemory.db_knowledgebase_id == kb_id,
        KB2QueryMemory.status == "verified",
    )
    res_qm = await db_session.execute(stmt_qm)
    seed_example_count = res_qm.scalar_one() or 0

    # 4. Last run stats
    stmt_run = (
        select(KB2JobRun)
        .where(
            KB2JobRun.tenant_id == tenant_id,
            KB2JobRun.db_knowledgebase_id == kb_id,
        )
        .order_by(desc(KB2JobRun.created_at))
        .limit(1)
    )
    res_run = await db_session.execute(stmt_run)
    last_run = res_run.scalar_one_or_none()

    last_run_status = last_run.status if last_run else None
    last_run_tokens = 0
    last_run_at = last_run.finished_at.isoformat() if (last_run and last_run.finished_at) else None
    if last_run and last_run.stages:
        for s_v in last_run.stages.values():
            last_run_tokens += (s_v.get("metrics") or {}).get("approx_tokens_used", 0)

    # 5. Top 10 Review Priorities for Admin
    # Ranking priority:
    # 1. Unresolved conflicts
    # 2. Coded columns needing mapping
    # 3. Low-confidence relationships (<0.65)
    # 4. Tables with missing description
    priorities: List[Dict[str, Any]] = []

    # 1. Conflicts
    for it in all_items:
        if it.status == "conflict":
            priorities.append({
                "type": "conflict",
                "item_key": it.item_key,
                "reason": "Admin-locked item has conflicting pipeline changes",
            })
            if len(priorities) >= 10:
                break

    # 2. Coded columns
    if len(priorities) < 10:
        for c_key in coded_columns:
            priorities.append({
                "type": "coded_column",
                "item_key": c_key,
                "reason": "Column contains encoded values requiring business mapping",
            })
            if len(priorities) >= 10:
                break

    # 3. Low confidence relationships
    if len(priorities) < 10:
        for r in relationships:
            if r.status == "draft" and r.confidence < 0.65:
                priorities.append({
                    "type": "low_confidence_relationship",
                    "item_key": r.item_key,
                    "reason": f"Inferred join with low confidence ({r.confidence:.2f})",
                })
                if len(priorities) >= 10:
                    break

    # 4. Tables missing description
    if len(priorities) < 10:
        for t in tables:
            sem = (t.payload or {}).get("semantic", {})
            if not sem.get("description"):
                priorities.append({
                    "type": "missing_description",
                    "item_key": t.item_key,
                    "reason": "Table missing high-level business description",
                })
                if len(priorities) >= 10:
                    break

    # 6. Overall Readiness Verdict
    verdict = "READY"
    if conflict_count > 0 or tbl_desc_pct < th.min_table_desc_pct or col_meaning_pct < th.min_column_meaning_pct:
        verdict = "NOT_READY"
    elif len(coded_columns) > th.max_unmapped_coded_cols or confirmed_pct < th.min_confirmed_item_pct or seed_example_count < th.min_seed_examples:
        verdict = "NEEDS_REVIEW"

    return QualityReportResult(
        db_knowledgebase_id=str(kb_id),
        tenant_id=str(tenant_id),
        evaluated_at=now_iso,
        total_tables=total_tables,
        tables_with_description_pct=tbl_desc_pct,
        tables_with_grain_pct=tbl_grain_pct,
        total_columns=total_columns,
        columns_with_meaning_pct=col_meaning_pct,
        columns_needing_admin_mapping=coded_columns,
        sensitive_columns_count=len(sensitive_columns),
        total_items=total_items,
        confirmed_items_pct=confirmed_pct,
        draft_items_pct=draft_pct,
        conflict_items_count=conflict_count,
        total_relationships=len(relationships),
        relationship_confidence_distribution=rel_conf_dist,
        tables_with_no_relationships=isolated_tables,
        total_entity_values_indexed=ev_total or 0,
        categorical_columns_indexed_count=ev_cols or 0,
        seed_example_count=seed_example_count,
        last_run_status=last_run_status,
        last_run_tokens=last_run_tokens,
        last_run_at=last_run_at,
        readiness_verdict=verdict,
        top_10_review_priorities=priorities,
    )
