import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase, DocumentChunk

async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(KnowledgeBase).filter(KnowledgeBase.name.ilike('%20071231X02009.pdf%')))
        kb = res.scalar_one_or_none()
        if not kb:
            print("KB not found.")
            return
            
        print(f"KB found: {kb.name} (Total chunks: {kb.total_chunks})")
        
        # Get unstructured chunks
        res = await db.execute(select(DocumentChunk).filter(
            DocumentChunk.kb_id == kb.id,
            DocumentChunk.chunk_index < 90000
        ))
        chunks = res.scalars().all()
        for c in chunks:
            print(f"--- Chunk {c.chunk_index} ---")
            print(c.text)

if __name__ == "__main__":
    asyncio.run(main())
