"""Phase 2 Knowledge Layer: Admin Review API Router

Provides REST API endpoints for reviewing, confirming, editing, rejecting,
and managing Phase 2 knowledge items, entity values, and conflicts:
- Filter items by type, status, source, sensitive.
- Priority ordering: conflicts -> coded columns -> low-confidence relationships -> drafts.
- Endpoints:
  - GET /{kb_id}/items: list items with review priority ordering and filters
  - GET /{kb_id}/items/{item_key}: get single item details
  - POST /{kb_id}/items/{item_key}/confirm: confirm draft item
  - POST /{kb_id}/items/{item_key}/edit: update payload, set locked=True, source='admin', reviewed_by/at
  - POST /{kb_id}/items/{item_key}/reject: reject item
  - POST /{kb_id}/items/bulk-confirm: bulk-confirm items above a confidence threshold
  - POST /{kb_id}/items/{item_key}/mark-sensitive: mark sensitive, clear top_values, delete from kb2_entity_values
  - POST /{kb_id}/items/{item_key}/hide: hide table/column item (status='hidden' / 'rejected')
  - POST /{kb_id}/items/{item_key}/resolve-conflict: resolve conflict (accept staged payload or keep admin payload)
  - GET /{kb_id}/conflicts: list items with status='conflict'
  - GET /{kb_id}/stats: summary statistics of knowledge layer items
- Every mutating endpoint writes an audit row to kb2_audit_log.
"""

import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, Request, HTTPException, Query, status
from sqlalchemy import select, update, delete, func, desc, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from ..models.knowledge_items import (
    KB2KnowledgeItem,
    KB2EntityValue,
    KB2AuditLog,
)
from ..repositories.knowledge_item_repository import KnowledgeItemRepository

router = APIRouter(
    prefix="/{kb_id}/knowledge",
    tags=["Database Knowledgebase Admin Review"],
)


# ==============================================================================
# Request / Response Schemas
# ==============================================================================

class EditPayloadRequest(BaseModel):
    payload: Dict[str, Any]
    comment: Optional[str] = None


class BulkConfirmRequest(BaseModel):
    item_type: Optional[str] = None
    min_confidence: float = 0.80


class ResolveConflictRequest(BaseModel):
    resolution: str  # 'accept_staged' or 'keep_current'


async def _write_audit_log(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    actor: str,
    action: str,
    item_key: str,
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
) -> None:
    """Helper to persist an audit entry."""
    audit = KB2AuditLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        db_knowledgebase_id=kb_id,
        actor=actor,
        action=action,
        item_key=item_key,
        before=before,
        after=after,
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    await db.flush()


def _get_tenant_and_actor(request: Request) -> tuple[uuid.UUID, str]:
    """Extract tenant_id and actor identity from request state / auth."""
    tenant_id_raw = getattr(request.state, "tenant_id", None)
    if not tenant_id_raw:
        # Fallback for dev / tests if state not set
        tenant_id_raw = "00000000-0000-0000-0000-000000000000"
    tenant_id = uuid.UUID(str(tenant_id_raw))

    user = getattr(request.state, "user", None)
    actor = getattr(user, "email", None) or getattr(user, "id", None) or "admin"
    return tenant_id, str(actor)


# ==============================================================================
# Endpoints
# ==============================================================================

@router.get("/items", summary="List Knowledge Items with Review Priority")
async def list_items(
    kb_id: uuid.UUID,
    request: Request,
    item_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    is_sensitive: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    tenant_id, _ = _get_tenant_and_actor(request)

    # Order priority:
    # 1. conflicts (status == 'conflict')
    # 2. coded columns (is_coded_value == True in payload)
    # 3. low-confidence relationships (confidence < 0.8)
    # 4. drafts (status == 'draft')
    # 5. confirmed / other
    priority_order = case(
        (KB2KnowledgeItem.status == "conflict", 1),
        (
            (KB2KnowledgeItem.item_type == "column")
            & (func.jsonb_extract_path_text(KB2KnowledgeItem.payload, "semantic", "is_coded_value") == "true"),
            2,
        ),
        (
            (KB2KnowledgeItem.item_type == "relationship")
            & (KB2KnowledgeItem.confidence < 0.8),
            3,
        ),
        (KB2KnowledgeItem.status == "draft", 4),
        else_=5,
    )

    query = select(KB2KnowledgeItem).where(
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
    )
    if item_type:
        query = query.where(KB2KnowledgeItem.item_type == item_type)
    if status:
        query = query.where(KB2KnowledgeItem.status == status)
    if source:
        query = query.where(KB2KnowledgeItem.source == source)
    if is_sensitive is not None:
        query = query.where(KB2KnowledgeItem.is_sensitive == is_sensitive)

    query = query.order_by(priority_order, KB2KnowledgeItem.updated_at.desc()).offset(offset).limit(limit)

    res = await db.execute(query)
    items = res.scalars().all()

    return {
        "items": [
            {
                "id": str(it.id),
                "item_type": it.item_type,
                "item_key": it.item_key,
                "source": it.source,
                "status": it.status,
                "is_locked_by_admin": it.is_locked_by_admin,
                "is_sensitive": it.is_sensitive,
                "confidence": it.confidence,
                "payload": it.payload,
                "staged_payload": it.staged_payload,
                "updated_at": it.updated_at.isoformat() if it.updated_at else None,
            }
            for it in items
        ]
    }


@router.get("/items/{item_key:path}", summary="Get Single Knowledge Item")
async def get_item(
    kb_id: uuid.UUID,
    item_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id, _ = _get_tenant_and_actor(request)
    stmt = select(KB2KnowledgeItem).where(
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
        KB2KnowledgeItem.item_key == item_key,
    )
    res = await db.execute(stmt)
    it = res.scalar_one_or_none()
    if not it:
        raise HTTPException(status_code=404, detail="Item not found")

    return {
        "id": str(it.id),
        "item_type": it.item_type,
        "item_key": it.item_key,
        "source": it.source,
        "status": it.status,
        "is_locked_by_admin": it.is_locked_by_admin,
        "is_sensitive": it.is_sensitive,
        "confidence": it.confidence,
        "payload": it.payload,
        "staged_payload": it.staged_payload,
        "reviewed_by": str(it.reviewed_by) if it.reviewed_by else None,
        "reviewed_at": it.reviewed_at.isoformat() if it.reviewed_at else None,
    }


@router.post("/items/{item_key:path}/confirm", summary="Confirm Knowledge Item")
async def confirm_item(
    kb_id: uuid.UUID,
    item_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id, actor = _get_tenant_and_actor(request)
    stmt = select(KB2KnowledgeItem).where(
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
        KB2KnowledgeItem.item_key == item_key,
    )
    res = await db.execute(stmt)
    it = res.scalar_one_or_none()
    if not it:
        raise HTTPException(status_code=404, detail="Item not found")

    before_status = it.status
    it.status = "confirmed"
    it.reviewed_at = datetime.now(timezone.utc)
    it.updated_at = datetime.now(timezone.utc)

    await _write_audit_log(
        db=db,
        tenant_id=tenant_id,
        kb_id=kb_id,
        actor=actor,
        action="confirm",
        item_key=item_key,
        before={"status": before_status},
        after={"status": "confirmed"},
    )
    await db.commit()
    return {"status": "confirmed", "item_key": item_key}


@router.post("/items/{item_key:path}/edit", summary="Edit Item Payload (Locks Item)")
async def edit_item(
    kb_id: uuid.UUID,
    item_key: str,
    body: EditPayloadRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id, actor = _get_tenant_and_actor(request)
    stmt = select(KB2KnowledgeItem).where(
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
        KB2KnowledgeItem.item_key == item_key,
    )
    res = await db.execute(stmt)
    it = res.scalar_one_or_none()
    if not it:
        raise HTTPException(status_code=404, detail="Item not found")

    before_payload = it.payload
    it.payload = body.payload
    it.is_locked_by_admin = True
    it.source = "admin"
    it.status = "confirmed"
    it.reviewed_at = datetime.now(timezone.utc)
    it.updated_at = datetime.now(timezone.utc)

    await _write_audit_log(
        db=db,
        tenant_id=tenant_id,
        kb_id=kb_id,
        actor=actor,
        action="edit_payload",
        item_key=item_key,
        before={"payload": before_payload},
        after={"payload": body.payload, "comment": body.comment},
    )
    await db.commit()
    return {"status": "confirmed", "is_locked_by_admin": True, "item_key": item_key}


@router.post("/items/{item_key:path}/reject", summary="Reject Knowledge Item")
async def reject_item(
    kb_id: uuid.UUID,
    item_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id, actor = _get_tenant_and_actor(request)
    stmt = select(KB2KnowledgeItem).where(
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
        KB2KnowledgeItem.item_key == item_key,
    )
    res = await db.execute(stmt)
    it = res.scalar_one_or_none()
    if not it:
        raise HTTPException(status_code=404, detail="Item not found")

    before_status = it.status
    it.status = "rejected"
    it.reviewed_at = datetime.now(timezone.utc)
    it.updated_at = datetime.now(timezone.utc)

    await _write_audit_log(
        db=db,
        tenant_id=tenant_id,
        kb_id=kb_id,
        actor=actor,
        action="reject",
        item_key=item_key,
        before={"status": before_status},
        after={"status": "rejected"},
    )
    await db.commit()
    return {"status": "rejected", "item_key": item_key}


@router.post("/items/bulk-confirm", summary="Bulk Confirm Above Confidence Threshold")
async def bulk_confirm(
    kb_id: uuid.UUID,
    body: BulkConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id, actor = _get_tenant_and_actor(request)
    conditions = [
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
        KB2KnowledgeItem.status == "draft",
        KB2KnowledgeItem.confidence >= body.min_confidence,
    ]
    if body.item_type:
        conditions.append(KB2KnowledgeItem.item_type == body.item_type)

    stmt = (
        update(KB2KnowledgeItem)
        .where(*conditions)
        .values(
            status="confirmed",
            reviewed_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    res = await db.execute(stmt)
    confirmed_count = res.rowcount

    await _write_audit_log(
        db=db,
        tenant_id=tenant_id,
        kb_id=kb_id,
        actor=actor,
        action="bulk_confirm",
        item_key="*",
        after={"count": confirmed_count, "min_confidence": body.min_confidence},
    )
    await db.commit()
    return {"confirmed_count": confirmed_count}


@router.post("/items/{item_key:path}/mark-sensitive", summary="Mark Column Item Sensitive")
async def mark_sensitive(
    kb_id: uuid.UUID,
    item_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id, actor = _get_tenant_and_actor(request)
    stmt = select(KB2KnowledgeItem).where(
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
        KB2KnowledgeItem.item_key == item_key,
    )
    res = await db.execute(stmt)
    it = res.scalar_one_or_none()
    if not it:
        raise HTTPException(status_code=404, detail="Item not found")

    it.is_sensitive = True
    # Clear top_values in payload
    p = dict(it.payload or {})
    stats = dict(p.get("stats") or {})
    stats["top_values"] = []
    p["stats"] = stats
    p["is_sensitive"] = True
    it.payload = p
    it.updated_at = datetime.now(timezone.utc)

    # Delete column's rows from kb2_entity_values
    col_name = (it.payload or {}).get("column_name") or item_key.split(".")[-1]
    tbl_name = (it.payload or {}).get("table_name")
    del_stmt = delete(KB2EntityValue).where(
        KB2EntityValue.tenant_id == tenant_id,
        KB2EntityValue.db_knowledgebase_id == kb_id,
        KB2EntityValue.column_name == col_name,
    )
    if tbl_name:
        del_stmt = del_stmt.where(KB2EntityValue.table_name == tbl_name)
    await db.execute(del_stmt)

    await _write_audit_log(
        db=db,
        tenant_id=tenant_id,
        kb_id=kb_id,
        actor=actor,
        action="mark_sensitive",
        item_key=item_key,
        after={"is_sensitive": True, "top_values_cleared": True},
    )
    await db.commit()
    return {"status": "ok", "is_sensitive": True, "item_key": item_key}


@router.post("/items/{item_key:path}/hide", summary="Hide Table or Column")
async def hide_item(
    kb_id: uuid.UUID,
    item_key: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id, actor = _get_tenant_and_actor(request)
    stmt = select(KB2KnowledgeItem).where(
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
        KB2KnowledgeItem.item_key == item_key,
    )
    res = await db.execute(stmt)
    it = res.scalar_one_or_none()
    if not it:
        raise HTTPException(status_code=404, detail="Item not found")

    p = dict(it.payload or {})
    p["is_hidden"] = True
    it.payload = p
    it.status = "rejected"
    it.updated_at = datetime.now(timezone.utc)

    await _write_audit_log(
        db=db,
        tenant_id=tenant_id,
        kb_id=kb_id,
        actor=actor,
        action="hide",
        item_key=item_key,
    )
    await db.commit()
    return {"status": "hidden", "item_key": item_key}


@router.post("/items/{item_key:path}/resolve-conflict", summary="Resolve Item Conflict")
async def resolve_conflict(
    kb_id: uuid.UUID,
    item_key: str,
    body: ResolveConflictRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id, actor = _get_tenant_and_actor(request)
    stmt = select(KB2KnowledgeItem).where(
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
        KB2KnowledgeItem.item_key == item_key,
    )
    res = await db.execute(stmt)
    it = res.scalar_one_or_none()
    if not it:
        raise HTTPException(status_code=404, detail="Item not found")

    if body.resolution == "accept_staged":
        if it.staged_payload:
            it.payload = it.staged_payload
        it.staged_payload = None
        it.status = "confirmed"
    elif body.resolution == "keep_current":
        it.staged_payload = None
        it.status = "confirmed"
    else:
        raise HTTPException(status_code=400, detail="Invalid resolution. Must be 'accept_staged' or 'keep_current'.")

    it.reviewed_at = datetime.now(timezone.utc)
    it.updated_at = datetime.now(timezone.utc)

    await _write_audit_log(
        db=db,
        tenant_id=tenant_id,
        kb_id=kb_id,
        actor=actor,
        action="resolve_conflict",
        item_key=item_key,
        after={"resolution": body.resolution},
    )
    await db.commit()
    return {"status": it.status, "resolution": body.resolution, "item_key": item_key}


@router.get("/conflicts", summary="List Conflicted Items")
async def list_conflicts(
    kb_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id, _ = _get_tenant_and_actor(request)
    stmt = (
        select(KB2KnowledgeItem)
        .where(
            KB2KnowledgeItem.tenant_id == tenant_id,
            KB2KnowledgeItem.db_knowledgebase_id == kb_id,
            KB2KnowledgeItem.status == "conflict",
        )
        .order_by(KB2KnowledgeItem.updated_at.desc())
    )
    res = await db.execute(stmt)
    items = res.scalars().all()
    return {
        "conflicts": [
            {
                "id": str(it.id),
                "item_type": it.item_type,
                "item_key": it.item_key,
                "payload": it.payload,
                "staged_payload": it.staged_payload,
                "updated_at": it.updated_at.isoformat() if it.updated_at else None,
            }
            for it in items
        ]
    }


@router.get("/stats", summary="Knowledge Items Summary Stats")
async def get_stats(
    kb_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    tenant_id, _ = _get_tenant_and_actor(request)
    stmt = (
        select(
            KB2KnowledgeItem.item_type,
            KB2KnowledgeItem.status,
            func.count(KB2KnowledgeItem.id),
        )
        .where(
            KB2KnowledgeItem.tenant_id == tenant_id,
            KB2KnowledgeItem.db_knowledgebase_id == kb_id,
        )
        .group_by(KB2KnowledgeItem.item_type, KB2KnowledgeItem.status)
    )
    res = await db.execute(stmt)
    rows = res.fetchall()

    breakdown = {}
    total = 0
    for r in rows:
        itype, istatus, cnt = r[0], r[1], int(r[2])
        total += cnt
        breakdown.setdefault(itype, {})[istatus] = cnt

    return {
        "total_items": total,
        "breakdown": breakdown,
    }


@router.get("/quality-report", summary="Knowledge Base Quality Report & Readiness")
async def get_quality_report(
    kb_id: uuid.UUID,
    request: Request,
    min_table_desc_pct: float = Query(80.0),
    min_column_meaning_pct: float = Query(70.0),
    min_confirmed_item_pct: float = Query(60.0),
    max_unmapped_coded_cols: int = Query(10),
    min_seed_examples: int = Query(10),
    db: AsyncSession = Depends(get_db),
):
    from ..quality.quality_report import generate_quality_report, QualityThresholds
    tenant_id, _ = _get_tenant_and_actor(request)
    thresholds = QualityThresholds(
        min_table_desc_pct=min_table_desc_pct,
        min_column_meaning_pct=min_column_meaning_pct,
        min_confirmed_item_pct=min_confirmed_item_pct,
        max_unmapped_coded_cols=max_unmapped_coded_cols,
        min_seed_examples=min_seed_examples,
    )
    report = await generate_quality_report(
        tenant_id=tenant_id,
        kb_id=kb_id,
        db_session=db,
        thresholds=thresholds,
    )
    return report.model_dump()


class RetrieveRequest(BaseModel):
    question: str
    reference_date: Optional[str] = None
    clarification_answers: Optional[Dict[str, Any]] = None
    debug: bool = False


@router.post("/retrieve", summary="Phase 3 Grounded Schema & Context Retrieval")
async def retrieve_knowledge_context(
    kb_id: uuid.UUID,
    body: RetrieveRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Executes Step 3.8 ContextPackBuilder pipeline returning grounded ContextPack."""
    from datetime import datetime
    from ..retrieval.context_pack import ContextPackBuilder

    tenant_id, _ = _get_tenant_and_actor(request)
    ref_d = None
    if body.reference_date:
        try:
            ref_d = datetime.strptime(body.reference_date, "%Y-%m-%d").date()
        except Exception:
            pass

    builder = ContextPackBuilder(db=db, tenant_id=tenant_id)
    pack = await builder.build(
        db_knowledgebase_id=kb_id,
        question=body.question,
        reference_date=ref_d,
        clarification_answers=body.clarification_answers,
    )

    resp = pack.model_dump()
    if not body.debug:
        resp.pop("timings_ms", None)
    return resp


@router.post("/pipeline/run", summary="Trigger Phase 2/3 Knowledge Pipeline manually")
async def run_pipeline_manual_endpoint(
    kb_id: uuid.UUID,
    request: Request,
    force_recompute: bool = Query(False, description="Re-run all stages ignoring previous successes"),
    run_inline: bool = Query(True, description="Run inline synchronously or background task"),
    db: AsyncSession = Depends(get_db),
):
    """Manually triggers the Phase 2/3 knowledge pipeline for this KB without Redis."""
    tenant_id, actor = _get_tenant_and_actor(request)
    from ..jobs.pipeline import run_pipeline_for_kb_local

    if run_inline:
        run_record = await run_pipeline_for_kb_local(
            kb_id=kb_id,
            tenant_id=tenant_id,
            force_recompute=force_recompute,
        )
        return run_record.model_dump(mode="json")
    else:
        import asyncio
        asyncio.create_task(
            run_pipeline_for_kb_local(
                kb_id=kb_id,
                tenant_id=tenant_id,
                force_recompute=force_recompute,
            )
        )
        return {"status": "enqueued_locally", "kb_id": str(kb_id), "force_recompute": force_recompute}



