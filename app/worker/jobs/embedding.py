import logging
import uuid
from typing import Dict, Any, List
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import DocumentChunk, KnowledgeBase
from app.core.embeddings import EmbeddingGenerator

logger = logging.getLogger(__name__)

async def embedding_job(ctx: Dict[Any, Any], kb_id: str, tenant_id: str, chunks: List[Dict[str, Any]]):
    logger.info(f"Starting embedding_job for {len(chunks)} chunks")
    redis = ctx.get('redis')
    
    if not chunks:
        return {"status": "success", "processed": 0}
        
    context_header = ""
    # Write to Vector Database (PostgreSQL)
    async with AsyncSessionLocal() as db:
        # Fetch KB to get its name and global_identifiers
        res = await db.execute(select(KnowledgeBase).filter(KnowledgeBase.id == uuid.UUID(kb_id)))
        kb = res.scalar_one_or_none()
        
        if kb:
            kb_name = kb.name or "Unknown Document"
            global_identifiers = (kb.metadata_json or {}).get("global_identifiers", [])
            
            context_parts = [f"[Document Title: {kb_name}]"]
            if global_identifiers:
                context_parts.append(f"[Document Context: {', '.join(global_identifiers)}]")
            context_header = "\n".join(context_parts)

        texts_for_embedding = []
        for chunk in chunks:
            # Check explicit chunk type first, otherwise fallback to the chunk_index boundary for table chunks
            is_unstructured = chunk.get("chunk_type") == "unstructured" or (
                "chunk_type" not in chunk and chunk.get("chunk_index", 0) < 90000
            )
            
            if is_unstructured and context_header:
                augmented_text = f"{context_header}\n{chunk['text']}"
                texts_for_embedding.append(augmented_text)
            else:
                texts_for_embedding.append(chunk["text"])

        # Generate embeddings in batch
        embeddings = await EmbeddingGenerator.generate_embeddings_batch(texts_for_embedding)
        
        for i, chunk in enumerate(chunks):
            chunk_id = uuid.uuid4()
            chunk["chunk_id"] = str(chunk_id) # Save for graph update
            
            pg_chunk = DocumentChunk(
                id=chunk_id,
                tenant_id=uuid.UUID(tenant_id),
                kb_id=uuid.UUID(kb_id),
                text=chunk["text"],  # Store the ORIGINAL, unaugmented text in the DB
                chunk_index=chunk["chunk_index"],
                embedding=embeddings[i],
                metadata_json=chunk.get("metadata") or {}
            )
            db.add(pg_chunk)
            
        await db.commit()
        logger.info(f"Successfully saved {len(chunks)} embedded chunks to Postgres")
        
    # Enqueue Graph Update Job
    await redis.enqueue_job(
        'graph_update_job',
        kb_id,
        tenant_id,
        chunks
    )
    
    return {"status": "success", "embedded_chunks": len(chunks)}
