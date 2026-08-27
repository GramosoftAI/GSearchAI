import logging
import uuid
from typing import Dict, Any, List
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import DocumentChunk
from app.core.embeddings import EmbeddingGenerator

logger = logging.getLogger(__name__)

async def embedding_job(ctx: Dict[Any, Any], kb_id: str, tenant_id: str, chunks: List[Dict[str, Any]]):
    logger.info(f"Starting embedding_job for {len(chunks)} chunks")
    redis = ctx.get('redis')
    
    if not chunks:
        return {"status": "success", "processed": 0}
        
    texts = [chunk["text"] for chunk in chunks]
    
    # Generate embeddings in batch
    embeddings = await EmbeddingGenerator.generate_embeddings_batch(texts)
    
    # Write to Vector Database (PostgreSQL)
    async with AsyncSessionLocal() as db:
        for i, chunk in enumerate(chunks):
            chunk_id = uuid.uuid4()
            chunk["chunk_id"] = str(chunk_id) # Save for graph update
            
            pg_chunk = DocumentChunk(
                id=chunk_id,
                tenant_id=uuid.UUID(tenant_id),
                kb_id=uuid.UUID(kb_id),
                text=chunk["text"],
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
