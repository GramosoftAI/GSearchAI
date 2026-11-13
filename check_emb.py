import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase, DocumentChunk

async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(KnowledgeBase).filter(KnowledgeBase.name.ilike('%20071231X02009.pdf%')))
        kb = res.scalar_one_or_none()
        
        # Get unstructured chunks
        res = await db.execute(select(DocumentChunk).filter(
            DocumentChunk.kb_id == kb.id,
            DocumentChunk.chunk_index == 0
        ))
        c = res.scalar_one_or_none()
        if c:
            if c.embedding is None:
                print("Chunk 0 embedding is NONE!")
            else:
                print(f"Chunk 0 embedding length: {len(c.embedding)}")
        else:
            print("Chunk 0 not found.")

if __name__ == "__main__":
    asyncio.run(main())
