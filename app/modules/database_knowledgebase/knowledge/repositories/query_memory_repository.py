"""Query Memory Repository for Phase 2 (kb2_query_memory)

Follows BaseRepository pattern:
- Strictly scoped by tenant_id on every operation.
- Supports RLS session setting.
- Stores verified NL-to-SQL query plans with embeddings, referenced items, and execution stats.
- Methods:
  - upsert_query_memory
  - get_query_memory
  - list_suggested_questions (for UI suggestions)
  - search_similar (via pgvector)
"""

import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy import select, update, and_, desc, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_repository import BaseRepository
from ..models.knowledge_items import KB2QueryMemory


class QueryMemoryRepository(BaseRepository):
    """Data access repository for kb2_query_memory."""

    def __init__(self, db: AsyncSession, tenant_id: str | uuid.UUID):
        super().__init__(db, str(tenant_id))

    async def upsert_query_memory(
        self,
        db_knowledgebase_id: uuid.UUID,
        schema_version: str,
        natural_query: str,
        compiled_sql: str,
        plan_ir: Dict[str, Any],
        referenced_items: List[str],
        execution_stats: Dict[str, Any],
        embedding: Optional[List[float]] = None,
        status: str = "verified",
    ) -> KB2QueryMemory:
        """Upsert a verified query execution into query memory."""
        now_utc = datetime.now(timezone.utc)
        norm_query = " ".join(natural_query.strip().lower().split())

        stmt = (
            select(KB2QueryMemory)
            .where(
                KB2QueryMemory.tenant_id == self.tenant_id,
                KB2QueryMemory.db_knowledgebase_id == db_knowledgebase_id,
                KB2QueryMemory.schema_version == schema_version,
                KB2QueryMemory.normalized_query == norm_query,
            )
            .with_for_update()
        )
        res = await self.db.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing:
            if not existing.is_locked_by_admin:
                existing.compiled_sql = compiled_sql
                existing.plan_ir = plan_ir
                existing.referenced_items = referenced_items
                existing.execution_stats = execution_stats
                if embedding:
                    existing.embedding = embedding
                existing.status = status
            existing.last_used_at = now_utc
            await self.db.flush()
            return existing

        item = KB2QueryMemory(
            id=uuid.uuid4(),
            tenant_id=self.tenant_id,
            db_knowledgebase_id=db_knowledgebase_id,
            schema_version=schema_version,
            natural_query=natural_query.strip(),
            normalized_query=norm_query,
            compiled_sql=compiled_sql.strip(),
            plan_ir=plan_ir,
            execution_stats=execution_stats,
            status=status,
            is_locked_by_admin=False,
            referenced_items=referenced_items,
            embedding=embedding,
            created_at=now_utc,
            last_used_at=now_utc,
        )
        self.db.add(item)
        await self.db.flush()
        return item

    async def list_suggested_questions(
        self,
        db_knowledgebase_id: uuid.UUID,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Return curated or high-quality seed questions for UI suggestion."""
        stmt = (
            select(KB2QueryMemory)
            .where(
                KB2QueryMemory.tenant_id == self.tenant_id,
                KB2QueryMemory.db_knowledgebase_id == db_knowledgebase_id,
                KB2QueryMemory.status == "verified",
            )
            .order_by(desc(KB2QueryMemory.created_at))
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        items = res.scalars().all()
        return [
            {
                "id": str(it.id),
                "question": it.natural_query,
                "sql": it.compiled_sql,
                "category": (it.plan_ir or {}).get("category", "general"),
                "provenance": (it.execution_stats or {}).get("provenance", "user"),
            }
            for it in items
        ]

    async def search_similar(
        self,
        db_knowledgebase_id: uuid.UUID,
        query_embedding: List[float],
        schema_version: Optional[str] = None,
        limit: int = 5,
    ) -> List[KB2QueryMemory]:
        """Cosine similarity search using pgvector."""
        conditions = [
            KB2QueryMemory.tenant_id == self.tenant_id,
            KB2QueryMemory.db_knowledgebase_id == db_knowledgebase_id,
            KB2QueryMemory.status == "verified",
            KB2QueryMemory.embedding.isnot(None),
        ]
        if schema_version:
            conditions.append(KB2QueryMemory.schema_version == schema_version)

        stmt = (
            select(KB2QueryMemory)
            .where(and_(*conditions))
            .order_by(KB2QueryMemory.embedding.cosine_distance(query_embedding))
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())
