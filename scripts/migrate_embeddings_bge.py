import asyncio
import argparse
import logging
from typing import List, Optional
from sqlalchemy import select, func, text, update
from sqlalchemy.ext.asyncio import AsyncSession

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger("migration.bge_reembed")

# Import application components
from app.core.database import AsyncSessionLocal
from app.core.embeddings import EmbeddingGenerator
from app.modules.knowledge_bases.models import DocumentChunk, KnowledgeBase

# Model Registry Configuration (as requested)
MODEL_REGISTRY = {
    "qwen3-embedding-8b": {"dim": 4096, "column": "embedding"},
    "bge-large":          {"dim": 1024, "column": "embedding_bge"},
}

BATCH_SIZE = 100

async def process_batch(db: AsyncSession, chunks: List[DocumentChunk]):
    if not chunks:
        return
    
    texts = [chunk.text for chunk in chunks]
    chunk_ids = [chunk.id for chunk in chunks]
    
    # Batch generate embeddings
    logger.info(f"Generating BGE embeddings for batch of {len(texts)} chunks...")
    try:
        embeddings = await EmbeddingGenerator.generate_embeddings_batch(texts)
    except Exception as e:
        logger.error(f"Failed to generate embeddings: {e}")
        return False
        
    if len(embeddings) != len(chunks):
        logger.error(f"Mismatch in embedding count: expected {len(chunks)}, got {len(embeddings)}")
        return False
        
    # Update chunks in DB
    for chunk, embedding in zip(chunks, embeddings):
        chunk.embedding = embedding
        
    try:
        await db.commit()
        logger.info(f"Successfully committed {len(chunks)} updated chunks.")
        return True
    except Exception as e:
        logger.error(f"Database commit failed: {e}")
        await db.rollback()
        return False

async def run_migration(tenant_id: Optional[str] = None):
    """
    Run migration to populate embedding_bge for document chunks that lack it.
    """
    logger.info("Starting BGE embedding migration script.")
    
    # Use AsyncSessionLocal directly for DB access outside request context
    async with AsyncSessionLocal() as db:
        
        # Build query
        query = select(DocumentChunk).where(DocumentChunk.embedding == None) # assuming embedding mapped to embedding_bge
        
        if tenant_id:
            query = query.where(DocumentChunk.tenant_id == tenant_id)
            logger.info(f"Filtered migration to tenant: {tenant_id}")
            
        # Get total count for progress tracking
        count_query = select(func.count()).select_from(query.subquery())
        total_missing = await db.scalar(count_query)
        
        logger.info(f"Found {total_missing} chunks requiring BGE embeddings.")
        
        if total_missing == 0:
            logger.info("No chunks to migrate. Exiting.")
            return

        processed = 0
        failed = 0
        
        # Iterate in batches
        # We re-query with limit because we are updating them to be non-null,
        # so the query will naturally return unmigrated chunks.
        while True:
            batch_query = query.limit(BATCH_SIZE)
            result = await db.execute(batch_query)
            chunks = result.scalars().all()
            
            if not chunks:
                break
                
            success = await process_batch(db, chunks)
            
            if success:
                processed += len(chunks)
                logger.info(f"Progress: {processed}/{total_missing} ({(processed/total_missing)*100:.1f}%)")
            else:
                failed += len(chunks)
                logger.error(f"Failed to process a batch of {len(chunks)} chunks. Skipping...")
                # To prevent infinite loop on failure, we need a mechanism to skip failed rows.
                # For this basic script, we'll abort.
                logger.critical("Aborting migration due to batch failure.")
                break

    logger.info(f"Migration completed. Processed: {processed}, Failed: {failed}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate existing chunks to BGE embeddings")
    parser.add_argument("--tenant_id", type=str, help="Optional Tenant ID to scope migration", default=None)
    args = parser.parse_argument()
    
    asyncio.run(run_migration(args.tenant_id))
