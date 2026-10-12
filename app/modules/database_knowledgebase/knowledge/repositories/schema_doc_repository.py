"""Schema Doc Repository for Phase 3 (kb2_schema_docs)

Follows BaseRepository pattern:
- Strictly scoped by tenant_id on every operation.
- Supports RLS session setting.
- Provides:
  - bulk_upsert: upsert documents by (db_knowledgebase_id, doc_type, item_key)
  - delete_missing: remove stale docs for dropped or removed items
  - search_fts: full-text search against generated tsvector 'tsv' column with ranking
  - search_vector: semantic vector cosine similarity search via pgvector HNSW index
"""

import uuid
import re
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy import select, delete, and_, func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_repository import BaseRepository
from ..models.knowledge_items import KB2SchemaDoc


class SchemaDocRepository(BaseRepository):
    """Data access repository for kb2_schema_docs."""

    def __init__(self, db: AsyncSession, tenant_id: str | uuid.UUID):
        super().__init__(db, str(tenant_id))

    async def bulk_upsert(
        self,
        docs_data: List[Dict[str, Any]],
    ) -> List[KB2SchemaDoc]:
        """Bulk upsert schema docs on (db_knowledgebase_id, doc_type, item_key).
        
        Preserves existing embedding if not provided in incoming doc update.
        Updates title, body, aliases, unit, role, status, source, schema_version, and updated_at.
        """
        if not docs_data:
            return []

        # Deduplicate incoming docs by unique constraint key
        deduped: Dict[tuple, Dict[str, Any]] = {}
        for d in docs_data:
            key = (str(d["db_knowledgebase_id"]), str(d["doc_type"]), str(d["item_key"]))
            deduped[key] = d

        items = list(deduped.values())
        now_utc = datetime.now(timezone.utc)

        rows_to_insert = []
        for d in items:
            row = {
                "id": d.get("id") or uuid.uuid4(),
                "tenant_id": uuid.UUID(str(self.tenant_id)),
                "db_knowledgebase_id": uuid.UUID(str(d["db_knowledgebase_id"])),
                "doc_type": d["doc_type"],
                "item_key": d["item_key"],
                "title": d["title"],
                "body": d["body"],
                "aliases": d.get("aliases") or [],
                "unit": d.get("unit"),
                "role": d.get("role"),
                "status": d.get("status", "draft"),
                "source": d.get("source", "inferred"),
                "schema_version": d["schema_version"],
                "input_hash": d.get("input_hash"),
                "embedding": d.get("embedding"),
                "created_at": now_utc,
                "updated_at": now_utc,
            }
            rows_to_insert.append(row)

        stmt = pg_insert(KB2SchemaDoc).values(rows_to_insert)
        update_cols = {
            "title": stmt.excluded.title,
            "body": stmt.excluded.body,
            "aliases": stmt.excluded.aliases,
            "unit": stmt.excluded.unit,
            "role": stmt.excluded.role,
            "status": stmt.excluded.status,
            "source": stmt.excluded.source,
            "schema_version": stmt.excluded.schema_version,
            "input_hash": stmt.excluded.input_hash,
            "updated_at": stmt.excluded.updated_at,
        }
        # Update embedding only if new embedding is provided, else keep existing
        update_cols["embedding"] = func.coalesce(stmt.excluded.embedding, KB2SchemaDoc.embedding)

        stmt = stmt.on_conflict_do_update(
            constraint="uq_kb2_schema_docs_kb_type_key",
            set_=update_cols,
        ).returning(KB2SchemaDoc)

        res = await self.db.execute(stmt)
        await self.db.flush()
        return list(res.scalars().all())

    async def get_existing_docs(
        self,
        db_knowledgebase_id: uuid.UUID,
        item_keys: Optional[List[str]] = None,
    ) -> Dict[str, KB2SchemaDoc]:
        """Fetch existing schema docs mapped by (doc_type, item_key) or item_key."""
        conditions = [
            KB2SchemaDoc.tenant_id == self.tenant_id,
            KB2SchemaDoc.db_knowledgebase_id == db_knowledgebase_id,
        ]
        if item_keys:
            conditions.append(KB2SchemaDoc.item_key.in_(item_keys))

        stmt = select(KB2SchemaDoc).where(and_(*conditions))
        res = await self.db.execute(stmt)
        docs = res.scalars().all()
        return {f"{d.doc_type}:{d.item_key}": d for d in docs}

    async def delete_missing(
        self,
        db_knowledgebase_id: uuid.UUID,
        active_keys: List[str],
        doc_types: Optional[List[str]] = None,
    ) -> int:
        """Delete documents whose item_keys are not in active_keys for this KB."""
        conditions = [
            KB2SchemaDoc.tenant_id == self.tenant_id,
            KB2SchemaDoc.db_knowledgebase_id == db_knowledgebase_id,
        ]
        if doc_types:
            conditions.append(KB2SchemaDoc.doc_type.in_(doc_types))
        if active_keys is not None:
            conditions.append(~KB2SchemaDoc.item_key.in_(active_keys))

        stmt = delete(KB2SchemaDoc).where(and_(*conditions))
        res = await self.db.execute(stmt)
        await self.db.flush()
        return res.rowcount

    async def search_fts(
        self,
        db_knowledgebase_id: uuid.UUID,
        query: str,
        doc_types: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Full-text search querying generated 'tsv' column with GIN index."""
        clean_query = (query or "").strip()
        if not clean_query:
            return []

        # Sanitize tokens for prefix matching fallback on 'simple' configuration
        tokens = [re.sub(r"[^a-zA-Z0-9_]", "", t) for t in clean_query.split()]
        tokens = [t for t in tokens if t]
        
        # Primary: plainto_tsquery, Secondary fallback: prefix tsquery
        if tokens:
            prefix_expr = " | ".join(f"{t}:*" for t in tokens)
            tsquery_sql = func.coalesce(
                func.nullif(func.plainto_tsquery(text("'simple'"), clean_query), func.to_tsquery(text("'simple'"), text("''"))),
                func.to_tsquery(text("'simple'"), prefix_expr)
            )
            # Use query with prefix match fallback
            match_clause = KB2SchemaDoc.tsv.op("@@")(
                func.to_tsquery(text("'simple'"), prefix_expr)
            )
            rank_query = func.to_tsquery(text("'simple'"), prefix_expr)
        else:
            match_clause = KB2SchemaDoc.tsv.op("@@")(func.plainto_tsquery(text("'simple'"), clean_query))
            rank_query = func.plainto_tsquery(text("'simple'"), clean_query)

        conditions = [
            KB2SchemaDoc.tenant_id == self.tenant_id,
            KB2SchemaDoc.db_knowledgebase_id == db_knowledgebase_id,
            match_clause,
        ]
        if doc_types:
            conditions.append(KB2SchemaDoc.doc_type.in_(doc_types))

        rank_expr = func.ts_rank(KB2SchemaDoc.tsv, rank_query).label("rank")

        stmt = (
            select(KB2SchemaDoc, rank_expr)
            .where(and_(*conditions))
            .order_by(rank_expr.desc())
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        rows = res.all()

        results = []
        for doc, rank in rows:
            results.append({
                "id": str(doc.id),
                "doc_type": doc.doc_type,
                "item_key": doc.item_key,
                "title": doc.title,
                "body": doc.body,
                "aliases": doc.aliases or [],
                "unit": doc.unit,
                "role": doc.role,
                "status": doc.status,
                "source": doc.source,
                "schema_version": doc.schema_version,
                "score": float(rank),
            })
        return results

    async def search_vector(
        self,
        db_knowledgebase_id: uuid.UUID,
        embedding: List[float],
        doc_types: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Vector cosine similarity search using pgvector HNSW index."""
        if not embedding:
            return []

        conditions = [
            KB2SchemaDoc.tenant_id == self.tenant_id,
            KB2SchemaDoc.db_knowledgebase_id == db_knowledgebase_id,
            KB2SchemaDoc.embedding.isnot(None),
        ]
        if doc_types:
            conditions.append(KB2SchemaDoc.doc_type.in_(doc_types))

        dist_expr = KB2SchemaDoc.embedding.cosine_distance(embedding).label("distance")

        stmt = (
            select(KB2SchemaDoc, dist_expr)
            .where(and_(*conditions))
            .order_by(dist_expr)
            .limit(limit)
        )
        res = await self.db.execute(stmt)
        rows = res.all()

        results = []
        for doc, dist in rows:
            sim = 1.0 - float(dist) if dist is not None else 0.0
            results.append({
                "id": str(doc.id),
                "doc_type": doc.doc_type,
                "item_key": doc.item_key,
                "title": doc.title,
                "body": doc.body,
                "aliases": doc.aliases or [],
                "unit": doc.unit,
                "role": doc.role,
                "status": doc.status,
                "source": doc.source,
                "schema_version": doc.schema_version,
                "score": sim,
                "distance": float(dist) if dist is not None else None,
            })
        return results
