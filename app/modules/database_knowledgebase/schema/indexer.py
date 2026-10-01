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
from app.modules.knowledge_bases.models import DocumentChunk, KnowledgeBase
from ..models.database_knowledgebase import DatabaseKnowledgebase
from ..schemas.canonical import DatabaseSchema, TableSchema
from ..schemas.canonical import StructuredSchemaDocument, StructuredSchemaDocumentColumn, StructuredSchemaDocumentRelationship

logger = logging.getLogger(__name__)

BATCH_SIZE = 25  # Concurrency window for batch embeddings


class SchemaIndexer:
    """
    Phase 1 Schema Vector Indexer: Transforms canonical DatabaseSchema into 
    StructuredSchemaDocuments and indexes them into document_chunks.embedding_bge.
    """

    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID):
        self.session = session
        self.tenant_id = tenant_id

    def _build_semantic_content(self, table: TableSchema) -> str:
        """Generates rich semantic text for vector retrieval."""
        lines = [f"Table: {table.table_name}\n"]
        
        if table.comment:
            lines.append("Purpose:")
            lines.append(f"{table.comment}\n")
            
        lines.append("Columns:")
        for col_name, col in table.columns.items():
            pk_str = ", primary key" if col.is_primary_key else ""
            fk_str = ", foreign key" if col.is_foreign_key else ""
            comment_str = f": {col.comment}" if col.comment else ""
            lines.append(f"- {col_name}: {col.data_type.lower()}{pk_str}{fk_str}{comment_str}")
            
        if table.relationships or table.foreign_keys:
            lines.append("\nRelationships:")
            # Use computed relationships if available, else fallback to FKs
            if table.relationships:
                for rel in table.relationships:
                    src_cols = ", ".join(rel.source_columns)
                    tgt_cols = ", ".join(rel.target_columns)
                    lines.append(f"- {table.table_name}.{src_cols} -> {rel.target_table}.{tgt_cols} ({rel.relationship_type.value})")
            else:
                for fk in table.foreign_keys:
                    src_cols = ", ".join(fk.constrained_columns)
                    tgt_cols = ", ".join(fk.referred_columns)
                    lines.append(f"- {table.table_name}.{src_cols} -> {fk.referred_table}.{tgt_cols}")
                    
        return "\n".join(lines)

    async def index_schema(
        self,
        kb_id: uuid.UUID,
        schema: DatabaseSchema,
        database_description: str = "",
        prune_old_versions: bool = True,
    ) -> int:
        """
        Builds StructuredSchemaDocuments for each table, computes BGE embeddings,
        and upserts into document_chunks.
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
        
        # 1. Fetch DB KB to get connection_id (using KB ID as connection reference)
        # Note: DatabaseConnection is 1:1 with KnowledgeBase for databases
        kb = await self.session.get(DatabaseKnowledgebase, kb_id)
        if not kb:
            logger.warning(f"KB {kb_id} not found.")
            return 0

        # 2. Check if this exact schema version is already indexed in document_chunks
        existing_stmt = select(DocumentChunk.id).where(
            DocumentChunk.tenant_id == self.tenant_id,
            DocumentChunk.kb_id == kb_id,
            DocumentChunk.metadata_json.op("->>")("schema_hash") == schema_version
        ).limit(1)
        existing_res = await self.session.execute(existing_stmt)
        if existing_res.scalar_one_or_none():
            logger.info(f"Schema version {schema_version[:8]} already indexed. Skipping.")
            return 0

        # 3. Build StructuredSchemaDocuments
        docs: List[StructuredSchemaDocument] = []
        for table in schema.all_tables:
            # Build columns
            columns = [
                StructuredSchemaDocumentColumn(
                    name=c.name,
                    data_type=c.data_type.value,
                    is_primary_key=c.is_primary_key
                ) for c in table.columns.values()
            ]
            
            # Build relationships
            relationships = []
            for fk in table.foreign_keys:
                if fk.constrained_columns and fk.referred_columns:
                    relationships.append(StructuredSchemaDocumentRelationship(
                        column=fk.constrained_columns[0],
                        referenced_table=fk.referred_table,
                        referenced_column=fk.referred_columns[0]
                    ))
            
            # Semantic text
            content = self._build_semantic_content(table)
            
            doc = StructuredSchemaDocument(
                document_type="TABLE",
                document_version="v1.0",
                tenant_id=str(self.tenant_id),
                connection_id=str(kb_id),
                database_id=str(kb_id),
                schema_name=table.schema_name,
                table_name=table.table_name,
                content=content,
                columns=columns,
                relationships=relationships,
                schema_hash=schema_version
            )
            docs.append(doc)

        if not docs:
            return 0

        # 4. Generate embeddings and create DocumentChunks
        embedding_records = []
        for i in range(0, len(docs), BATCH_SIZE):
            batch = docs[i : i + BATCH_SIZE]
            
            # Concurrent embedding generation for current batch
            tasks = [EmbeddingGenerator.generate_embedding(doc.content) for doc in batch]
            embeddings = await asyncio.gather(*tasks)

            for doc_idx, (doc, emb) in enumerate(zip(batch, embeddings)):
                # Inject indexing metadata into metadata_json
                meta = doc.model_dump()
                meta.update({
                    "embedding_model": "BAAI/bge-large-en-v1.5",
                    "embedding_dimension": 1024,
                    "index_version": "1.0",
                    "is_schema_document": True
                })
                
                record = DocumentChunk(
                    id=uuid.uuid4(),
                    tenant_id=self.tenant_id,
                    kb_id=kb_id,
                    text=doc.content,
                    chunk_index=i + doc_idx,
                    section="SCHEMA_INDEX",
                    embedding_bge=emb,
                    metadata_json=meta
                )
                embedding_records.append(record)

        # 5. Prune old versions (clean replacement)
        if prune_old_versions:
            delete_old_stmt = delete(DocumentChunk).where(
                DocumentChunk.tenant_id == self.tenant_id,
                DocumentChunk.kb_id == kb_id,
                DocumentChunk.section == "SCHEMA_INDEX",
                DocumentChunk.metadata_json.op("->>")("schema_hash") != schema_version
            )
            await self.session.execute(delete_old_stmt)

        # 6. Persist new embeddings
        self.session.add_all(embedding_records)

        # Update KB status
        if kb:
            kb.status = "indexed"
            kb.schema_version = schema_version

        await self.session.commit()
        logger.info(f"Successfully indexed {len(embedding_records)} schema entities into document_chunks for KB {kb_id}")
        return len(embedding_records)
