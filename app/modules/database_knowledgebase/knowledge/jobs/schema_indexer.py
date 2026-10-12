"""Schema Search Index Builder & Synchronization (Phase 3 Step 3.1)

Builds and indexes searchable schema documents into kb2_schema_docs:
- doc_types: table, column, metric, glossary
- Source data: kb2_knowledge_items
- Semantic fields:
  - description, meaning, aliases, unit, row_grain, domain, metric expression, glossary term.
- Security & privacy invariants:
  - NEVER include top_values.
  - Skip is_sensitive columns entirely.
  - Skip glossary terms that target sensitive columns entirely.
- Embeddings:
  - Batched via EmbeddingGenerator.generate_embeddings_batch.
  - Skips docs whose input hash (SHA-256) is unchanged.
- Idempotency & drift:
  - Upserts documents on (db_knowledgebase_id, doc_type, item_key).
  - Deletes docs for stale or dropped knowledge items.
"""

import uuid
import hashlib
import json
import logging
from typing import Optional, List, Dict, Any, Set, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import EmbeddingGenerator
from ..models.knowledge_items import KB2KnowledgeItem
from ..repositories.knowledge_item_repository import KnowledgeItemRepository
from ..repositories.schema_doc_repository import SchemaDocRepository
from ..sensitivity import is_sensitive_column

logger = logging.getLogger(__name__)

EMBEDDING_BATCH_SIZE = 50


def compute_doc_input_hash(title: str, body: str, aliases: List[str], unit: Optional[str], role: Optional[str]) -> str:
    """Compute deterministic SHA-256 hash of doc text and attributes to detect changes."""
    content = {
        "title": (title or "").strip(),
        "body": (body or "").strip(),
        "aliases": sorted(aliases or []),
        "unit": (unit or "").strip() if unit else None,
        "role": (role or "").strip() if role else None,
    }
    dumped = json.dumps(content, sort_keys=True)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


def _is_item_sensitive(item: KB2KnowledgeItem) -> bool:
    """Check if knowledge item is explicitly marked sensitive or is a sensitive column."""
    if item.is_sensitive:
        return True
    payload = item.payload or {}
    if payload.get("is_sensitive"):
        return True
    if item.item_type == "column":
        col_name = payload.get("column_name") or item.item_key.split(".")[-1]
        if is_sensitive_column(col_name):
            return True
    return False


def build_schema_doc_data(
    item: KB2KnowledgeItem,
    sensitive_column_keys: Set[str],
) -> Optional[Dict[str, Any]]:
    """Build document representation from a knowledge item.
    
    Returns None if item is sensitive, targets a sensitive column, or is not an indexable doc_type.
    """
    if item.item_type not in ("table", "column", "metric", "glossary"):
        return None

    # Skip sensitive items
    if _is_item_sensitive(item):
        return None

    payload = item.payload or {}
    semantic = payload.get("semantic") or {}

    doc_type = item.item_type
    item_key = item.item_key
    schema_version = item.valid_from_version or "v1"
    status = item.status or "draft"
    source = item.source or "inferred"

    title = ""
    body = ""
    aliases: List[str] = []
    unit: Optional[str] = None
    role: Optional[str] = None

    if doc_type == "table":
        table_name = payload.get("table_name") or item_key.split(".")[-1]
        domain = semantic.get("domain") or payload.get("domain") or ""
        row_grain = semantic.get("row_grain") or ""
        description = semantic.get("description") or payload.get("comment") or ""
        aliases = semantic.get("aliases") or []

        title = f"Table {table_name}"
        body_parts = []
        if domain:
            body_parts.append(f"Domain: {domain}")
        if row_grain:
            body_parts.append(f"Row Grain: {row_grain}")
        if description:
            body_parts.append(f"Description: {description}")
        body = ". ".join(body_parts) if body_parts else f"Table {table_name}"

    elif doc_type == "column":
        col_name = payload.get("column_name") or item_key.split(".")[-1]
        table_name = payload.get("table_name") or ".".join(item_key.split(".")[:-1])
        meaning = semantic.get("meaning") or payload.get("comment") or ""
        usage_note = semantic.get("usage_note") or ""
        aliases = semantic.get("aliases") or []
        unit = semantic.get("unit") or payload.get("unit_hint")
        role = payload.get("role")

        title = f"Column {table_name}.{col_name}"
        body_parts = []
        if role:
            body_parts.append(f"Role: {role}")
        if unit:
            body_parts.append(f"Unit: {unit}")
        if meaning:
            body_parts.append(f"Meaning: {meaning}")
        if usage_note:
            body_parts.append(f"Usage: {usage_note}")
        body = ". ".join(body_parts) if body_parts else f"Column {col_name}"

    elif doc_type == "metric":
        metric_name = payload.get("name") or semantic.get("name") or item_key.replace("metric:", "").replace("_", " ").title()
        expression = payload.get("expression") or semantic.get("expression") or ""
        grain = payload.get("grain") or semantic.get("grain") or ""
        description = payload.get("description") or semantic.get("description") or ""
        aliases = payload.get("aliases") or semantic.get("aliases") or []
        unit = payload.get("unit") or semantic.get("unit")
        depends_on = payload.get("depends_on") or []

        # If metric depends exclusively on sensitive columns, skip
        if depends_on and all(dep in sensitive_column_keys for dep in depends_on):
            return None

        title = f"Metric {metric_name}"
        body_parts = []
        if expression:
            body_parts.append(f"Expression: {expression}")
        if grain:
            body_parts.append(f"Grain: {grain}")
        if unit:
            body_parts.append(f"Unit: {unit}")
        if description:
            body_parts.append(f"Description: {description}")
        body = ". ".join(body_parts) if body_parts else f"Metric {metric_name}"

    elif doc_type == "glossary":
        term = payload.get("term") or semantic.get("term") or item_key.replace("glossary:", "").replace("_", " ").title()
        target = payload.get("target") or "table"
        target_key = payload.get("target_key") or ""
        description = payload.get("description") or semantic.get("description") or ""
        aliases = payload.get("aliases") or semantic.get("aliases") or []

        # Check if target is a sensitive column
        if target == "column" and target_key in sensitive_column_keys:
            return None
        # Also check if target_key ends with any sensitive column name or matches sensitive column token
        if target == "column" and any(target_key == sk or target_key.endswith(f".{sk.split('.')[-1]}") for sk in sensitive_column_keys):
            return None

        title = f"Glossary Term {term}"
        body_parts = []
        if target_key:
            body_parts.append(f"Target ({target}): {target_key}")
        if description:
            body_parts.append(f"Definition: {description}")
        body = ". ".join(body_parts) if body_parts else f"Term {term}"

    # Compute deterministic input hash
    input_hash = compute_doc_input_hash(title, body, aliases, unit, role)

    return {
        "db_knowledgebase_id": item.db_knowledgebase_id,
        "doc_type": doc_type,
        "item_key": item_key,
        "title": title,
        "body": body,
        "aliases": aliases,
        "unit": unit,
        "role": role,
        "status": status,
        "source": source,
        "schema_version": schema_version,
        "input_hash": input_hash,
    }


async def build_and_index_schema_docs(
    tenant_id: uuid.UUID,
    kb_id: uuid.UUID,
    schema_version: str,
    db_session: AsyncSession,
) -> Dict[str, Any]:
    """Execute schema search index synchronization for a knowledgebase.
    
    1. Loads all candidate knowledge items (table, column, metric, glossary).
    2. Identifies sensitive columns to filter out and to prune targeted glossary terms.
    3. Builds doc representations skipping sensitive data and top_values.
    4. Compares input_hash with existing docs in kb2_schema_docs to skip unchanged embeddings.
    5. Generates embeddings in batches for new or modified docs.
    6. Bulk upserts docs into kb2_schema_docs.
    7. Deletes docs for dropped or stale items.
    """
    item_repo = KnowledgeItemRepository(db=db_session, tenant_id=tenant_id)
    doc_repo = SchemaDocRepository(db=db_session, tenant_id=tenant_id)

    # 1. Fetch all items for this KB
    all_items = await item_repo.list_items(db_knowledgebase_id=kb_id, limit=2000)

    # 2. Identify sensitive column keys
    sensitive_column_keys: Set[str] = set()
    for it in all_items:
        if it.item_type == "column" and _is_item_sensitive(it):
            sensitive_column_keys.add(it.item_key)
            col_leaf = it.item_key.split(".")[-1]
            sensitive_column_keys.add(col_leaf)

    # 3. Build candidate docs
    candidate_docs: List[Dict[str, Any]] = []
    active_keys: List[str] = []

    for it in all_items:
        # Ignore items marked stale or rejected
        if it.status in ("stale", "rejected"):
            continue

        doc = build_schema_doc_data(it, sensitive_column_keys)
        if doc is not None:
            candidate_docs.append(doc)
            active_keys.append(doc["item_key"])

    # 4. Fetch existing docs to compare input_hash
    existing_docs = await doc_repo.get_existing_docs(db_knowledgebase_id=kb_id)

    # 5. Determine which docs need embedding generation
    docs_to_embed: List[Dict[str, Any]] = []
    embed_texts: List[str] = []

    for doc in candidate_docs:
        key = f"{doc['doc_type']}:{doc['item_key']}"
        existing = existing_docs.get(key)

        # Re-embed if doc is new, input_hash changed, or existing doc has no embedding
        if not existing or existing.input_hash != doc["input_hash"] or existing.embedding is None:
            doc_text = f"{doc['title']}. {doc['body']}"
            if doc.get("aliases"):
                doc_text += f" Aliases: {', '.join(doc['aliases'])}"
            docs_to_embed.append(doc)
            embed_texts.append(doc_text)
        else:
            # Reuse existing embedding
            doc["embedding"] = existing.embedding

    # 6. Batch generate embeddings for new/modified docs
    embeddings_generated = 0
    if docs_to_embed:
        logger.info(f"[Schema Index Builder] Generating embeddings for {len(docs_to_embed)} docs (batch size: {EMBEDDING_BATCH_SIZE})")
        for i in range(0, len(docs_to_embed), EMBEDDING_BATCH_SIZE):
            batch_slice = docs_to_embed[i : i + EMBEDDING_BATCH_SIZE]
            text_slice = embed_texts[i : i + EMBEDDING_BATCH_SIZE]
            try:
                batch_vectors = await EmbeddingGenerator.generate_embeddings_batch(text_slice)
                for doc_obj, vec in zip(batch_slice, batch_vectors):
                    doc_obj["embedding"] = vec
                embeddings_generated += len(batch_vectors)
            except Exception as emb_exc:
                logger.error(f"[Schema Index Builder] Batch embedding generation error: {emb_exc}")
                for doc_obj in batch_slice:
                    doc_obj["embedding"] = None

    # 7. Bulk upsert docs
    upserted = await doc_repo.bulk_upsert(candidate_docs)

    # 8. Delete missing docs for stale or dropped items
    deleted_count = await doc_repo.delete_missing(
        db_knowledgebase_id=kb_id,
        active_keys=active_keys,
        doc_types=["table", "column", "metric", "glossary"],
    )

    doc_counts_by_type: Dict[str, int] = {}
    for d in candidate_docs:
        t = d["doc_type"]
        doc_counts_by_type[t] = doc_counts_by_type.get(t, 0) + 1

    return {
        "total_candidate_docs": len(candidate_docs),
        "docs_upserted": len(upserted),
        "embeddings_generated": embeddings_generated,
        "embeddings_reused": len(candidate_docs) - len(docs_to_embed),
        "stale_docs_deleted": deleted_count,
        "counts_by_type": doc_counts_by_type,
    }
