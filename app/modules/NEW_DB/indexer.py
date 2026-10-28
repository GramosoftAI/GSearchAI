"""Vector Indexer for Table Documentation using PostgreSQL pgvector

Generates dense vector embeddings for table Markdown cheat sheets and stores them
in PostgreSQL pgvector for high-speed cosine similarity retrieval.
"""

import uuid
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.embeddings import EmbeddingGenerator
from app.modules.database_knowledgebase.models.embeddings import DatabaseSchemaEmbedding
from .schemas import TableInfo, CanonicalSchema

logger = logging.getLogger(__name__)


class TableDocIndexer:
    """Embeds table documentation and manages storage in PostgreSQL pgvector."""

    @classmethod
    async def index_canonical_schema_docs(
        cls,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        kb_id: uuid.UUID,
        schema: CanonicalSchema,
    ) -> int:
        """
        Embeds each table's Markdown documentation and stores in db_schema_embeddings.
        Returns the number of indexed table documents.
        """
        logger.info(f"[NEW_DB] Indexing {len(schema.tables)} table docs into pgvector for KB {kb_id}")

        # 1. Clean up old table_doc embeddings for this KB to prevent stale documents
        await session.execute(
            delete(DatabaseSchemaEmbedding).where(
                DatabaseSchemaEmbedding.tenant_id == tenant_id,
                DatabaseSchemaEmbedding.db_knowledgebase_id == kb_id,
                DatabaseSchemaEmbedding.entity_type == "table_doc",
            )
        )

        valid_tables = [t for t in schema.tables if t.markdown_doc]
        chunk_size = 32
        indexed_count = 0

        for i in range(0, len(valid_tables), chunk_size):
            chunk = valid_tables[i:i + chunk_size]
            docs = [t.markdown_doc for t in chunk]
            try:
                embeddings = await EmbeddingGenerator.generate_embeddings_batch(docs)
            except Exception as e:
                logger.error(f"[NEW_DB] Batch embedding failed for chunk {i}: {e}")
                embeddings = [[0.0] * 1024 for _ in chunk]

            for table, emb in zip(chunk, embeddings):
                entity_key = f"{table.schema_name}.{table.table_name}"
                col_names = [c.name for c in table.columns]
                meta_data = {
                    "source": f"{table.table_name}.md",
                    "title": f"Table: {entity_key}",
                    "schema_name": table.schema_name,
                    "table_name": table.table_name,
                    "column_names": col_names,
                    "primary_keys": table.primary_keys,
                    "foreign_keys_count": len(table.foreign_keys),
                }

                rec = DatabaseSchemaEmbedding(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    db_knowledgebase_id=kb_id,
                    schema_version=schema.fingerprint,
                    entity_type="table_doc",
                    entity_key=entity_key,
                    document_text=table.markdown_doc,
                    embedding=emb,
                    metadata_json=meta_data,
                )
                session.add(rec)
                indexed_count += 1

        await session.commit()
        logger.info(f"[NEW_DB] Successfully indexed {indexed_count} table documents into pgvector for KB {kb_id}")
        return indexed_count
