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
            
        print(f"KB found: {kb.name} (ID: {kb.id})")
        
        # Get all chunks
        res = await db.execute(select(DocumentChunk).filter(DocumentChunk.kb_id == kb.id))
        chunks = res.scalars().all()
        
        print(f"Total chunks: {len(chunks)}")
        
        found = False
        for c in chunks:
            if "probable cause" in c.text.lower():
                print(f"--- Chunk {c.chunk_index} ---")
                print(f"Contains 'probable cause': YES")
                print(f"Text snippet: {c.text[:200]}...")
                found = True
                
        if not found:
            print("ERROR: 'probable cause' NOT FOUND IN ANY CHUNK!")

if __name__ == "__main__":
    asyncio.run(main())
