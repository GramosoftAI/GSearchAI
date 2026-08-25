import asyncio
import logging
from uuid import UUID
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase, DocumentChunk
from app.core.embeddings import EmbeddingGenerator
from app.core.llm.deepinfra_llm import DeepInfraLLMClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def summarize_and_embed_kb(session, kb: KnowledgeBase):
    """Generates a summary for a KB based on its first few chunks, embeds it, and saves it."""
    # 1. Fetch the first few chunks to understand what the document is about
    stmt = select(DocumentChunk.text).where(
        DocumentChunk.kb_id == kb.id
    ).order_by(DocumentChunk.chunk_index.asc()).limit(5)
    
    result = await session.execute(stmt)
    chunks = result.scalars().all()
    
    if not chunks:
        logger.warning(f"KB {kb.id} ({kb.name}) has no chunks. Skipping.")
        return False
        
    document_text = "\n\n".join(chunks)
    
    # 2. Use a fast LLM call to summarize the document
    prompt = f"""
    You are an expert indexer. Summarize the following document accurately in 2-3 sentences.
    Focus strictly on the core topics, entities, and purpose of the document so a search engine can route queries to it.
    
    Title: {kb.name}
    Content Excerpt:
    {document_text[:4000]}
    
    Summary:
    """
    
    logger.info(f"Generating summary for KB: {kb.name} ({kb.id})")
    llm = DeepInfraLLMClient()
    summary = await llm.generate(prompt, temperature=0.0)
    
    logger.info(f"Generated Summary: {summary.strip()}")
    
    # 3. Generate the semantic centroid embedding
    logger.info(f"Generating embedding for KB summary...")
    embedding, _ = await EmbeddingGenerator.generate_embedding_with_usage(f"Title: {kb.name}\nSummary: {summary.strip()}")
    
    # 4. Save to DB
    kb.summary_embedding = embedding
    session.add(kb)
    await session.commit()
    logger.info(f"Successfully backfilled summary_embedding for KB: {kb.name}")
    return True


async def main():
    async with AsyncSessionLocal() as session:
        # Find all KBs that haven't been backfilled yet
        stmt = select(KnowledgeBase).where(KnowledgeBase.summary_embedding.is_(None))
        result = await session.execute(stmt)
        kbs = result.scalars().all()
        
        logger.info(f"Found {len(kbs)} Knowledge Bases needing summary backfill.")
        
        for kb in kbs:
            try:
                await summarize_and_embed_kb(session, kb)
            except Exception as e:
                logger.error(f"Failed to backfill KB {kb.id}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
