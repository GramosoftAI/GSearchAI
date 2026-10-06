"""Knowledge Item Repository for Phase 2 (kb2_knowledge_items)

Follows BaseRepository pattern:
- Strictly scoped by tenant_id on every operation.
- Supports RLS session setting.

Rules enforced on upsert:
- If is_locked_by_admin: never overwrite payload. If incoming object_hash differs,
  write to staged_payload and set status='conflict'.
- source='declared' items may be created as 'confirmed'; 'llm'/'inferred' always 'draft'.
- Methods:
  - upsert_item
  - get_item
  - list_items(filters)
  - mark_stale(item_keys)
  - bulk_upsert(items)
"""

import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_repository import BaseRepository
from ..models.knowledge_items import KB2KnowledgeItem


class KnowledgeItemRepository(BaseRepository):
    """Data access repository for kb2_knowledge_items."""

    def __init__(self, db: AsyncSession, tenant_id: str | uuid.UUID):
        super().__init__(db, str(tenant_id))

    async def get_item(
        self,
        db_knowledgebase_id: uuid.UUID,
        item_type: str,
        item_key: str,
        for_update: bool = False,
    ) -> Optional[KB2KnowledgeItem]:
        """Fetch item by unique natural key within tenant scope, optionally locking with FOR UPDATE."""
        stmt = select(KB2KnowledgeItem).where(
            KB2KnowledgeItem.tenant_id == self.tenant_id,
            KB2KnowledgeItem.db_knowledgebase_id == db_knowledgebase_id,
            KB2KnowledgeItem.item_type == item_type,
            KB2KnowledgeItem.item_key == item_key,
        )
        if for_update:
            stmt = stmt.with_for_update()
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def upsert_item(
        self,
        db_knowledgebase_id: uuid.UUID,
        item_type: str,
        item_key: str,
        valid_from_version: str,
        object_hash: str,
        source: str,
        payload: Dict[str, Any],
        confidence: float = 1.0,
        is_sensitive: bool = False,
        reviewed_by: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
    ) -> KB2KnowledgeItem:
        """Atomic upsert of a single knowledge item with admin lock & lifecycle status rules enforced."""
        now_utc = datetime.now(timezone.utc)

        # Concurrency-safe atomic upsert:
        # 1. First attempt to SELECT FOR UPDATE
        # 2. If row exists, update it according to governance rules
        # 3. If row does not exist, insert inside a nested SAVEPOINT
        #    If another concurrent transaction inserted the row first, catch UniqueViolation,
        #    rollback to savepoint, and perform SELECT FOR UPDATE + update.
        # This provides complete atomic concurrency without raw sql parameter typing issues.
        from sqlalchemy.exc import IntegrityError

        existing = await self.get_item(db_knowledgebase_id, item_type, item_key, for_update=True)

        if not existing:
            if source == "declared":
                target_status = status if status in ("draft", "confirmed") else "confirmed"
            else:
                target_status = "draft"

            item = KB2KnowledgeItem(
                id=uuid.uuid4(),
                tenant_id=self.tenant_id,
                db_knowledgebase_id=db_knowledgebase_id,
                item_type=item_type,
                item_key=item_key,
                valid_from_version=valid_from_version,
                object_hash=object_hash,
                source=source,
                status=target_status,
                is_locked_by_admin=False,
                is_sensitive=is_sensitive,
                confidence=confidence,
                payload=payload,
                staged_payload=None,
                reviewed_by=reviewed_by,
                reviewed_at=now_utc if reviewed_by else None,
                created_at=now_utc,
                updated_at=now_utc,
            )
            try:
                async with self.db.begin_nested():
                    self.db.add(item)
                    await self.db.flush()
                return item
            except IntegrityError:
                # Concurrent transaction won the race and inserted the row
                existing = await self.get_item(db_knowledgebase_id, item_type, item_key, for_update=True)

        # Update existing item
        if existing.is_locked_by_admin:
            if existing.object_hash != object_hash:
                existing.staged_payload = payload
                existing.status = "conflict"
            existing.valid_from_version = valid_from_version
            existing.updated_at = now_utc
            await self.db.flush()
            return existing

        # Unlocked lifecycle status rules
        if existing.status == "rejected":
            target_status = "rejected"
        elif existing.status == "confirmed" and existing.object_hash != object_hash:
            target_status = "draft"
        elif source == "declared":
            target_status = status if status in ("draft", "confirmed") else (existing.status or "confirmed")
        else:
            target_status = "draft" if source in ("llm", "inferred") else existing.status

        existing.valid_from_version = valid_from_version
        existing.object_hash = object_hash
        existing.source = source
        existing.payload = payload
        existing.confidence = confidence
        existing.is_sensitive = is_sensitive
        existing.staged_payload = None
        existing.status = target_status
        if reviewed_by:
            existing.reviewed_by = reviewed_by
            existing.reviewed_at = now_utc
        existing.updated_at = now_utc

        await self.db.flush()
        return existing



    async def list_items(
        self,
        db_knowledgebase_id: uuid.UUID,
        item_type: Optional[str] = None,
        status: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[KB2KnowledgeItem]:
        """List items matching filters within tenant scope."""
        conditions = [
            KB2KnowledgeItem.tenant_id == self.tenant_id,
            KB2KnowledgeItem.db_knowledgebase_id == db_knowledgebase_id,
        ]
        if item_type:
            conditions.append(KB2KnowledgeItem.item_type == item_type)
        if status:
            conditions.append(KB2KnowledgeItem.status == status)
        if source:
            conditions.append(KB2KnowledgeItem.source == source)

        stmt = (
            select(KB2KnowledgeItem)
            .where(and_(*conditions))
            .order_by(KB2KnowledgeItem.item_key)
            .limit(limit)
            .offset(offset)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def mark_stale(
        self,
        db_knowledgebase_id: uuid.UUID,
        item_keys: List[str],
    ) -> int:
        """Mark items as 'stale' (e.g. dropped tables/columns during schema drift).
        
        Admin-locked items are NOT marked stale directly to preserve auditability.
        """
        if not item_keys:
            return 0

        stmt = (
            update(KB2KnowledgeItem)
            .where(
                KB2KnowledgeItem.tenant_id == self.tenant_id,
                KB2KnowledgeItem.db_knowledgebase_id == db_knowledgebase_id,
                KB2KnowledgeItem.item_key.in_(item_keys),
                KB2KnowledgeItem.is_locked_by_admin == False,
            )
            .values(status="stale", updated_at=datetime.now(timezone.utc))
        )
        res = await self.db.execute(stmt)
        await self.db.flush()
        return res.rowcount

    async def bulk_upsert(
        self,
        items_data: List[Dict[str, Any]],
    ) -> List[KB2KnowledgeItem]:
        """Bulk upsert multiple knowledge items, honoring lock & status rules for each."""
        results = []
        for d in items_data:
            item = await self.upsert_item(
                db_knowledgebase_id=d["db_knowledgebase_id"],
                item_type=d["item_type"],
                item_key=d["item_key"],
                valid_from_version=d["valid_from_version"],
                object_hash=d["object_hash"],
                source=d["source"],
                payload=d.get("payload", {}),
                confidence=d.get("confidence", 1.0),
                is_sensitive=d.get("is_sensitive", False),
                reviewed_by=d.get("reviewed_by"),
                status=d.get("status"),
            )
            results.append(item)
        return results
