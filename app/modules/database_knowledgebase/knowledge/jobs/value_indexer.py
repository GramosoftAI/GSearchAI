"""Phase 2 Knowledge Layer: Distinct Value Indexer Stage

Picks entity columns from profiler knowledge items:
- role in ('name', 'enum', 'code')
- not sensitive
- distinct count under configurable cap (default 50,000)
- incremental: re-index column only when stats were refreshed

Processing:
- sample / fetch values capped per column (e.g. up to 1,000 distinct values per column)
- normalize: unicodedata.normalize('NFKC', text), lowercase, strip, collapse spaces
- skip values longer than 255 chars
- bulk upsert through EntityValueRepository (setting frequency_count)
- prune_unseen for that run
- embeddings configurable, default ON only for role='name' columns, batched via EmbeddingGenerator
"""

import uuid
import re
import unicodedata
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import EmbeddingGenerator
from ..adapters.phase1_adapter import Phase1Adapter
from ..repositories.entity_value_repository import EntityValueRepository
from ..models.knowledge_items import KB2KnowledgeItem
from ..sensitivity import is_sensitive_column, is_sensitive_for_values

logger = logging.getLogger(__name__)


def normalize_value(val: str) -> str:
    """Normalize text value: NFKC, lowercase, strip, collapse whitespace."""
    if not val:
        return ""
    norm = unicodedata.normalize("NFKC", str(val))
    norm = norm.lower().strip()
    norm = re.sub(r"\s+", " ", norm)
    return norm


async def run_stage_value_index(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    schema_version: str,
    adapter: Phase1Adapter,
    db_session: AsyncSession,
    heartbeat_cb: Optional[Any] = None,
    distinct_count_cap: int = 50000,
    values_per_column_cap: int = 1000,
    enable_name_embeddings: bool = True,
    last_run_timestamp: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Execute Stage 3: Categorical / Entity Value Indexing."""
    logger.info(f"[Stage: Value Index] Starting for KB={kb_id}, schema_version={schema_version}")
    stage_start_time = datetime.now(timezone.utc)
    entity_repo = EntityValueRepository(db=db_session, tenant_id=tenant_id)

    # 1. Fetch column profiler items from kb2_knowledge_items
    stmt = select(KB2KnowledgeItem).where(
        KB2KnowledgeItem.tenant_id == tenant_id,
        KB2KnowledgeItem.db_knowledgebase_id == kb_id,
        KB2KnowledgeItem.item_type == "column",
    )
    res = await db_session.execute(stmt)
    column_items = res.scalars().all()

    candidate_columns = []
    for item in column_items:
        payload = item.payload or {}
        role = payload.get("role", "general")
        is_sens = item.is_sensitive or payload.get("is_sensitive", False)
        stats = payload.get("stats", {})
        distinct_count = stats.get("distinct_count", 0)

        # Skip non-candidate roles
        if role not in ("name", "enum", "code"):
            continue
        # Skip sensitive and PII columns
        col_n = payload.get("column_name", "")
        if is_sens or is_sensitive_column(col_n) or is_sensitive_for_values(col_n):
            continue
        # Check distinct count cap
        if distinct_count and distinct_count > distinct_count_cap:
            continue

        # Incremental check: re-index column only when stats were refreshed since last run
        stats_refreshed_str = stats.get("refreshed_at")
        if last_run_timestamp and stats_refreshed_str:
            try:
                stats_refreshed_dt = datetime.fromisoformat(stats_refreshed_str.replace("Z", "+00:00"))
                if stats_refreshed_dt < last_run_timestamp:
                    continue
            except Exception:
                pass

        candidate_columns.append({
            "table_name": payload.get("table_name"),
            "column_name": payload.get("column_name"),
            "role": role,
            "distinct_count": distinct_count,
        })

    logger.info(f"[Stage: Value Index] Found {len(candidate_columns)} candidate columns to index.")

    total_values_indexed = 0

    # 2. Extract values from customer database via Phase1Adapter
    for col_info in candidate_columns:
        if heartbeat_cb:
            await heartbeat_cb()

        tbl = col_info["table_name"]
        col = col_info["column_name"]
        role = col_info["role"]

        if not tbl or not col:
            continue

        if "." in tbl:
            parts = tbl.split(".", 1)
            quoted_tbl = f'"{parts[0]}"."{parts[1]}"'
        else:
            quoted_tbl = f'"{tbl}"'

        try:
            async with adapter.open_readonly_connection(tenant_id, kb_id) as conn:
                query = f"""
                    SELECT "{col}"::text AS raw_val, COUNT(*) AS freq
                    FROM {quoted_tbl}
                    WHERE "{col}" IS NOT NULL
                    GROUP BY "{col}"
                    ORDER BY freq DESC
                    LIMIT {values_per_column_cap};
                """
                rows = await conn.fetch(query)
        except Exception as exc:
            logger.warning(f"[Stage: Value Index] Failed to fetch values for {tbl}.{col}: {exc}")
            continue

        values_to_upsert: List[Dict[str, Any]] = []
        name_texts: List[str] = []
        name_val_indices: List[int] = []

        for r in rows:
            raw_v = r["raw_val"]
            if raw_v is None:
                continue

            raw_str = str(raw_v)
            norm_v = normalize_value(raw_str)
            if not norm_v or len(norm_v) > 255:
                continue

            entry = {
                "table_name": tbl,
                "column_name": col,
                "raw_value": raw_str,
                "normalized_value": norm_v,
                "frequency_count": int(r["freq"]),
                "embedding": None,
            }
            if role == "name" and enable_name_embeddings:
                name_texts.append(norm_v)
                name_val_indices.append(len(values_to_upsert))

            values_to_upsert.append(entry)

        # Batch generate embeddings for role='name'
        if name_texts:
            try:
                vectors = await EmbeddingGenerator.generate_embeddings_batch(name_texts)
                for idx, vec in zip(name_val_indices, vectors):
                    values_to_upsert[idx]["embedding"] = vec
            except Exception as emb_exc:
                logger.warning(f"[Stage: Value Index] Embedding generation failed for {tbl}.{col}: {emb_exc}")

        if values_to_upsert:
            count = await entity_repo.bulk_upsert_values(
                db_knowledgebase_id=kb_id,
                values=values_to_upsert,
            )
            total_values_indexed += len(values_to_upsert)

    # 3. Prune unseen values for this run
    pruned_count = await entity_repo.prune_unseen(
        db_knowledgebase_id=kb_id,
        before=stage_start_time,
    )

    await db_session.commit()

    logger.info(
        f"[Stage: Value Index] Complete. Indexed: {total_values_indexed}, Pruned: {pruned_count}"
    )
    return {
        "candidate_columns_indexed": len(candidate_columns),
        "values_indexed": total_values_indexed,
        "values_pruned": pruned_count,
    }
