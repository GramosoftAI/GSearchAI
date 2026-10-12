"""Entity Value Repository for Phase 2 (kb2_entity_values)

Follows BaseRepository pattern:
- Strictly scoped by tenant_id on every operation.
- Every write path (single and bulk) MUST call validate_not_sensitive on column_name.
- Methods:
  - bulk_upsert_values (ON CONFLICT DO UPDATE last_seen_at/frequency_count)
  - prune_unseen(before=timestamp)
  - search_exact(db_kb_id, table_name, column_name, value)
  - search_fuzzy(db_kb_id, query_text, limit, min_similarity) via pg_trgm similarity
  - search_fts(db_kb_id, query_text, limit) via PostgreSQL full-text search ('simple' dictionary)
"""

import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy import select, delete, func, text, and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_repository import BaseRepository
from ..models.knowledge_items import KB2EntityValue
from ..sensitivity import validate_not_sensitive


class EntityValueRepository(BaseRepository):
    """Data access repository for kb2_entity_values."""

    def __init__(self, db: AsyncSession, tenant_id: str | uuid.UUID):
        super().__init__(db, str(tenant_id))

    async def bulk_upsert_values(
        self,
        db_knowledgebase_id: uuid.UUID,
        values: List[Dict[str, Any]],
    ) -> int:
        """Bulk upsert distinct entity values.
        
        CRITICAL: Validates that NO column_name is sensitive before executing write.
        On conflict on (db_knowledgebase_id, table_name, column_name, normalized_value):
        - updates last_seen_at = now()
        - updates frequency_count = COALESCE(existing + 1, frequency_count)
        """
        if not values:
            return 0

        # Enforce write-time sensitivity guard across all records
        now_utc = datetime.now(timezone.utc)
        
        # Deduplicate and aggregate across the same batch by unique constraint key
        # (db_knowledgebase_id, table_name, column_name, normalized_value)
        # to avoid PostgreSQL CardinalityViolationError on duplicate constrained values in one INSERT.
        deduped_rows: dict[tuple[str, str, str], dict] = {}
        for val in values:
            col_name = val["column_name"]
            validate_not_sensitive(col_name)

            norm_val = val["normalized_value"].strip()
            if len(norm_val) > 255:
                norm_val = norm_val[:255]

            key = (val["table_name"], col_name, norm_val)
            freq = val.get("frequency_count", 1)

            if key in deduped_rows:
                deduped_rows[key]["frequency_count"] += freq
                # Keep embedding if not already set
                if not deduped_rows[key].get("embedding") and val.get("embedding"):
                    deduped_rows[key]["embedding"] = val.get("embedding")
            else:
                deduped_rows[key] = {
                    "id": val.get("id") or uuid.uuid4(),
                    "tenant_id": self.tenant_id,
                    "db_knowledgebase_id": db_knowledgebase_id,
                    "table_name": val["table_name"],
                    "column_name": col_name,
                    "raw_value": val["raw_value"],
                    "normalized_value": norm_val,
                    "frequency_count": freq,
                    "embedding": val.get("embedding"),
                    "last_seen_at": now_utc,
                    "created_at": now_utc,
                }

        insert_rows = list(deduped_rows.values())
        if not insert_rows:
            return 0

        stmt = pg_insert(KB2EntityValue).values(insert_rows)
        upsert_stmt = stmt.on_conflict_do_update(
            constraint="uq_kb2_entity_val",
            set_={
                "last_seen_at": stmt.excluded.last_seen_at,
                "frequency_count": stmt.excluded.frequency_count,
            },
        )
        res = await self.db.execute(upsert_stmt)
        await self.db.flush()
        return res.rowcount

    async def prune_unseen(
        self,
        db_knowledgebase_id: uuid.UUID,
        before: datetime,
    ) -> int:
        """Prune entity values that have not been observed since `before` timestamp."""
        stmt = delete(KB2EntityValue).where(
            KB2EntityValue.tenant_id == self.tenant_id,
            KB2EntityValue.db_knowledgebase_id == db_knowledgebase_id,
            KB2EntityValue.last_seen_at < before,
        )
        res = await self.db.execute(stmt)
        await self.db.flush()
        return res.rowcount

    async def search_exact(
        self,
        db_knowledgebase_id: uuid.UUID,
        table_name: str,
        column_name: str,
        value: str,
    ) -> Optional[KB2EntityValue]:
        """Exact normalized lookup within tenant scope."""
        stmt = select(KB2EntityValue).where(
            KB2EntityValue.tenant_id == self.tenant_id,
            KB2EntityValue.db_knowledgebase_id == db_knowledgebase_id,
            KB2EntityValue.table_name == table_name,
            KB2EntityValue.column_name == column_name,
            KB2EntityValue.normalized_value == value.strip().lower(),
        )
        res = await self.db.execute(stmt)
        return res.scalar_one_or_none()

    async def search_fuzzy(
        self,
        db_knowledgebase_id: uuid.UUID,
        query_text: str,
        table_name: Optional[str] = None,
        column_name: Optional[str] = None,
        limit: int = 10,
        min_similarity: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """Fuzzy search using pg_trgm % operator with similarity threshold to leverage GIN index.
        
        Optional filtering by table_name and column_name.
        """
        clean_query = query_text.strip().lower()
        if not clean_query:
            return []

        async with self.db.begin_nested():
            # Set similarity limit for session/transaction so % operator utilizes threshold and GIN index
            try:
                async with self.db.begin_nested():
                    await self.db.execute(text("SELECT set_limit(CAST(:lim AS real));"), {"lim": float(min_similarity)})
            except Exception:
                try:
                    async with self.db.begin_nested():
                        await self.db.execute(text("SELECT set_config('pg_trgm.similarity_threshold', :lim, true);"), {"lim": str(min_similarity)})
                except Exception as lim_err:
                    logger.debug(f"Could not set pg_trgm similarity limit: {lim_err}")

            conditions = [
                "tenant_id = :tenant_id",
                "db_knowledgebase_id = :db_kb_id",
                "normalized_value % :q",
            ]
            params = {
                "tenant_id": str(self.tenant_id),
                "db_kb_id": str(db_knowledgebase_id),
                "q": clean_query,
                "limit": limit,
            }

            if table_name:
                conditions.append("table_name = :t_name")
                params["t_name"] = table_name
            if column_name:
                conditions.append("column_name = :c_name")
                params["c_name"] = column_name

            where_clause = " AND ".join(conditions)
            sql = f"""
                SELECT id, table_name, column_name, raw_value, normalized_value, frequency_count,
                       similarity(normalized_value, :q) AS sim_score
                FROM kb2_entity_values
                WHERE {where_clause}
                ORDER BY similarity(normalized_value, :q) DESC, frequency_count DESC NULLS LAST
                LIMIT :limit;
            """
            res = await self.db.execute(text(sql), params)
            rows = res.fetchall()
            return [
                {
                    "id": r[0],
                    "table_name": r[1],
                    "column_name": r[2],
                    "raw_value": r[3],
                    "normalized_value": r[4],
                    "frequency_count": r[5],
                    "similarity": float(r[6]),
                }
                for r in rows
            ]

    async def search_fts(
        self,
        db_knowledgebase_id: uuid.UUID,
        query_text: str,
        table_name: Optional[str] = None,
        column_name: Optional[str] = None,
        limit: int = 10,
    ) -> List[KB2EntityValue]:
        """Full-text search querying stored tsv_value column directly with GIN index."""
        clean_query = query_text.strip()
        if not clean_query:
            return []

        conditions = [
            KB2EntityValue.tenant_id == self.tenant_id,
            KB2EntityValue.db_knowledgebase_id == db_knowledgebase_id,
            KB2EntityValue.tsv_value.op("@@")(
                func.plainto_tsquery(text("'simple'"), clean_query)
            ),
        ]
        if table_name:
            conditions.append(KB2EntityValue.table_name == table_name)
        if column_name:
            conditions.append(KB2EntityValue.column_name == column_name)

        stmt = (
            select(KB2EntityValue)
            .where(and_(*conditions))
            .order_by(KB2EntityValue.frequency_count.desc().nullslast())
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        return list(res.scalars().all())
