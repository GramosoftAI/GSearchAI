import uuid
import logging
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.knowledge_bases.models import DocumentChunk
from app.core.embeddings import EmbeddingGenerator
from ..domain.pipeline_context import PipelineContext

logger = logging.getLogger(__name__)

class PostgresWriter:
    def __init__(self, db: AsyncSession):
        self.db = db
        
    async def write(self, context: PipelineContext) -> PipelineContext:
        objects = [obj for obj in context.business_object_store.get_all() if not obj.state.value == "QUARANTINED"]
        total_chunks = len(objects)
        
        if total_chunks == 0:
            return context
            
        chunk_texts = []
        chunk_metadatas = []
        
        for obj in objects:
            semantic_parts = [f"{obj.entity_type}: {obj.id}"]
            for k, v in obj.attributes.items():
                semantic_parts.append(f"{k}: {v}")
            for rel in obj.relationships:
                semantic_parts.append(f"{rel.predicate} ({rel.target_type}): {rel.target_id}")
                
            chunk_texts.append(" | ".join(semantic_parts))
            chunk_metadatas.append({
                "chunk_type": "business_object",
                "object_id": obj.id,
                "entity_type": obj.entity_type,
                "provenance": obj.provenance,
                "raw_data": obj.attributes
            })

        logger.info(f"Generating embeddings for {total_chunks} Business Objects...")
        embeddings = await EmbeddingGenerator.generate_embeddings_batch(chunk_texts)

        chunk_ids = [str(uuid.uuid4()) for _ in range(total_chunks)]
        
        for idx in range(total_chunks):
            pg_chunk = DocumentChunk(
                id=uuid.UUID(chunk_ids[idx]),
                tenant_id=uuid.UUID(context.tenant_id),
                kb_id=uuid.UUID(context.kb_id),
                text=chunk_texts[idx],
                chunk_index=idx,
                embedding=embeddings[idx],
                metadata_json=chunk_metadatas[idx]
            )
            self.db.add(pg_chunk)
            
        context.log(f"Staged {total_chunks} Business Objects in PostgreSQL")
        return context
