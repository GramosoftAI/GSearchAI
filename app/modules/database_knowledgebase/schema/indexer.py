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
from ..models.database_knowledgebase import DatabaseKnowledgebase
from ..models.embeddings import DatabaseSchemaEmbedding
from ..schemas.canonical import DatabaseSchema
from .document_generator import SchemaDocumentGenerator

logger = logging.getLogger(__name__)

BATCH_SIZE = 25  # Concurrency window for batch embeddings


class SchemaIndexer:
    """
    Phase 1 Schema Vector Indexer: Transforms canonical DatabaseSchema into 
    Schema Documents and indexes them into db_schema_embeddings.
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
        Builds semantic documents for database, schema, table, column, and relationships,
        computes embeddings, and upserts into db_schema_embeddings.
        """
        schema_version = schema.fingerprint
        if not schema_version:
            from .fingerprint import SchemaFingerprinter
            schema_version = SchemaFingerprinter.generate_fingerprint(schema)
            schema.fingerprint = schema_version

        logger.info(
            f"Phase 1: Indexing schema for KB {kb_id}, tenant={self.tenant_id}, "
            f"version={schema_version[:8]}"
        )
        
        kb = await self.session.get(DatabaseKnowledgebase, kb_id)
        if not kb:
            logger.warning(f"KB {kb_id} not found.")
            return 0

        # Check if this exact schema version is already indexed
        existing_stmt = select(DatabaseSchemaEmbedding.id).where(
            DatabaseSchemaEmbedding.tenant_id == self.tenant_id,
            DatabaseSchemaEmbedding.db_knowledgebase_id == kb_id,
            DatabaseSchemaEmbedding.schema_version == schema_version
        ).limit(1)
        existing_res = await self.session.execute(existing_stmt)
        if existing_res.scalar_one_or_none():
            logger.info(f"Schema version {schema_version[:8]} already indexed. Skipping.")
            return 0

        # Build semantic documents
        docs = SchemaDocumentGenerator.generate_all_documents(
            schema=schema,
            database_description=database_description,
            glossary_entries=None
        )

        if not docs:
            return 0

        # Generate embeddings and create DatabaseSchemaEmbedding records
        embedding_records = []
        for i in range(0, len(docs), BATCH_SIZE):
            batch = docs[i : i + BATCH_SIZE]
            
            # Concurrent embedding generation for current batch
            tasks = [EmbeddingGenerator.generate_embedding(doc.embedding_text) for doc in batch]
            embeddings = await asyncio.gather(*tasks)

            for doc, emb in zip(batch, embeddings):
                meta = doc.model_dump()
                record = DatabaseSchemaEmbedding(
                    id=uuid.uuid4(),
                    tenant_id=self.tenant_id,
                    db_knowledgebase_id=kb_id,
                    schema_version=schema_version,
                    entity_type=doc.document_type.value,
                    entity_key=doc.entity_key,
                    document_text=doc.embedding_text,
                    embedding=emb,
                    metadata_json=meta
                )
                embedding_records.append(record)

        # Prune old versions (clean replacement)
        if prune_old_versions:
            delete_old_stmt = delete(DatabaseSchemaEmbedding).where(
                DatabaseSchemaEmbedding.tenant_id == self.tenant_id,
                DatabaseSchemaEmbedding.db_knowledgebase_id == kb_id,
                DatabaseSchemaEmbedding.schema_version != schema_version
            )
            await self.session.execute(delete_old_stmt)

        # Persist new embeddings
        self.session.add_all(embedding_records)

        # Update KB status
        if kb:
            kb.status = "indexed"
            kb.schema_version = schema_version

        await self.session.commit()
        logger.info(f"Successfully indexed {len(embedding_records)} schema entities into db_schema_embeddings for KB {kb_id}")
        return len(embedding_records)
