"""Schema Vector Indexer: Transforms and indexes Schema Documents into pgvector

Handles:
- Batch embedding generation via EmbeddingGenerator
- Version-pinned persistence in db_schema_embeddings
- Pruning/clean replacement of old schema version embeddings
- Atomic transactional consistency
"""

import uuid
import asyncio
import logging
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.core.embeddings import EmbeddingGenerator
from ..models.embeddings import DatabaseSchemaEmbedding
from ..models.database_knowledgebase import DatabaseKnowledgebase
from ..schemas.canonical import DatabaseSchema
from .document_generator import SchemaDocumentGenerator
from ..schemas.documents import BaseSchemaDocument

logger = logging.getLogger(__name__)

BATCH_SIZE = 25  # Concurrency window for batch embeddings


class SchemaIndexer:
    """
    Indexes canonical database schemas into dense vector embeddings stored in PostgreSQL.
    """

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID):
        self.session = session
        self.tenant_id = tenant_id

    async def index_schema(
        self,
        kb_id: uuid.UUID,
        schema: DatabaseSchema,
        database_description: str = "",
        prune_old_versions: bool = True,
    ) -> int:
        """
        Generate semantic documents from schema, compute vector embeddings in bounded batches,
        and persist version-pinned embeddings to db_schema_embeddings.

        Returns:
            Number of indexed documents.
        """
        schema_version = schema.fingerprint
        if not schema_version:
            from .fingerprint import SchemaFingerprinter
            schema_version = SchemaFingerprinter.generate_fingerprint(schema)
            schema.fingerprint = schema_version

        logger.info(
            f"Starting schema indexing for KB {kb_id}, tenant={self.tenant_id}, "
            f"version={schema_version[:8]}"
        )

        # 1. Generate semantic documents
        docs: List[BaseSchemaDocument] = SchemaDocumentGenerator.generate_all_documents(
            schema=schema,
            database_description=database_description,
        )

        if not docs:
            logger.warning(f"No schema documents generated for KB {kb_id}")
            return 0

        # 2. Check if this exact schema version is already indexed
        existing_stmt = select(DatabaseSchemaEmbedding.id).where(
            DatabaseSchemaEmbedding.tenant_id == self.tenant_id,
            DatabaseSchemaEmbedding.db_knowledgebase_id == kb_id,
            DatabaseSchemaEmbedding.schema_version == schema_version,
        ).limit(1)
        existing_res = await self.session.execute(existing_stmt)
        if existing_res.scalar_one_or_none():
            logger.info(
                f"Schema version {schema_version[:8]} already indexed for KB {kb_id}. "
                "Skipping re-embedding."
            )
            return len(docs)

        # 3. Generate embeddings in bounded concurrent batches
        embedding_records: List[DatabaseSchemaEmbedding] = []
        for i in range(0, len(docs), BATCH_SIZE):
            batch = docs[i : i + BATCH_SIZE]
            
            # Concurrent embedding generation for current batch
            tasks = [EmbeddingGenerator.generate_embedding(doc.embedding_text) for doc in batch]
            embeddings = await asyncio.gather(*tasks)

            for doc, emb in zip(batch, embeddings):
                record = DatabaseSchemaEmbedding(
                    id=uuid.uuid4(),
                    tenant_id=self.tenant_id,
                    db_knowledgebase_id=kb_id,
                    schema_version=schema_version,
                    entity_type=doc.document_type.value,
                    entity_key=doc.entity_key,
                    document_text=doc.embedding_text,
                    embedding=emb,
                    metadata_json=doc.model_dump(),
                )
                embedding_records.append(record)

        # 4. Optional: Clean up older schema version embeddings for this KB
        if prune_old_versions:
            delete_old_stmt = delete(DatabaseSchemaEmbedding).where(
                DatabaseSchemaEmbedding.tenant_id == self.tenant_id,
                DatabaseSchemaEmbedding.db_knowledgebase_id == kb_id,
                DatabaseSchemaEmbedding.schema_version != schema_version,
            )
            await self.session.execute(delete_old_stmt)

        # 5. Persist new embeddings
        self.session.add_all(embedding_records)

        # Update KB status to 'indexed'
        kb = await self.session.get(DatabaseKnowledgebase, kb_id)
        if kb:
            kb.status = "indexed"
            kb.schema_version = schema_version

        await self.session.commit()
        logger.info(f"Successfully indexed {len(embedding_records)} schema entities for KB {kb_id}")
        return len(embedding_records)
