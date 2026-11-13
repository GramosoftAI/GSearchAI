import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase, DocumentChunk

async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(KnowledgeBase).filter(KnowledgeBase.name.ilike('%20071231X02009.pdf%')))
        kb = res.scalar_one_or_none()
        res = await db.execute(select(DocumentChunk).filter(DocumentChunk.kb_id == kb.id))
        chunks = res.scalars().all()
        for c in chunks:
            if c.chunk_index < 5:
                print(f"Chunk {c.chunk_index}: section={c.section}")

if __name__ == "__main__":
    asyncio.run(main())
