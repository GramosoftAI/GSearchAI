"""Documentation Vector and Keyword Embedder

Embeds stored schema documentation elements (table docs, column docs, example questions)
into `schema_doc_embeddings` table:
- Batches of 32-64 texts, not one request per text
- Dimension and model equal to the query-time embedder (EmbeddingGenerator)
- Each embedded text strictly starts with the exact schema.table.column name
- Includes tsvector column for hybrid / keyword search
- Does NOT wire into retrieval yet (saved in schema_doc_embeddings)
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.embeddings import EmbeddingGenerator
from ..models.schema_doc import SchemaDocEmbedding

logger = logging.getLogger(__name__)

EMBEDDING_BATCH_SIZE = 32  # 32 to 64 batch size


class DocEmbeddingItem:
    """Item to embed."""
    def __init__(
        self,
        item_type: str,  # table_doc | column_doc | example_question
        item_key: str,
        exact_identifier: str,
        document_text: str,
        metadata_json: Optional[Dict[str, Any]] = None,
    ):
        self.item_type = item_type
        self.item_key = item_key
        self.exact_identifier = exact_identifier
        self.document_text = document_text
        self.metadata_json = metadata_json or {}


class SchemaDocEmbedder:
    """Manages batch embedding generation and persistence for schema cheat sheets."""

    @classmethod
    async def embed_and_store_items(
        cls,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        kb_id: uuid.UUID,
        schema_version: str,
        items: List[DocEmbeddingItem],
    ) -> int:
        """
        Embed items in batches of 32-64, ensuring exact schema.table[.column] prefix.
        Stores into schema_doc_embeddings.
        """
        if not items:
            return 0

        # Guarantee exact identifier prefix on document_text
        formatted_texts = []
        for item in items:
            prefix = f"[{item.exact_identifier}]"
            if not item.document_text.startswith(prefix):
                full_text = f"{prefix} {item.document_text}"
            else:
                full_text = item.document_text
            formatted_texts.append(full_text)

        # Batch embed using EmbeddingGenerator
        all_embeddings: List[List[float]] = []
        for i in range(0, len(formatted_texts), EMBEDDING_BATCH_SIZE):
            batch_slice = formatted_texts[i : i + EMBEDDING_BATCH_SIZE]
            batch_vectors = await EmbeddingGenerator.generate_embeddings_batch(batch_slice)
            all_embeddings.extend(batch_vectors)

        # Build ORM records
        records = []
        for item, full_text, emb in zip(items, formatted_texts, all_embeddings):
            rec = SchemaDocEmbedding(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                db_knowledgebase_id=kb_id,
                schema_version=schema_version,
                item_type=item.item_type,
                item_key=item.item_key,
                exact_identifier=item.exact_identifier,
                document_text=full_text,
                embedding=emb,
                metadata_json=item.metadata_json,
            )
            records.append(rec)

        session.add_all(records)
        await session.flush()
        logger.info(f"Persisted {len(records)} embeddings into schema_doc_embeddings for KB {kb_id}")
        return len(records)
