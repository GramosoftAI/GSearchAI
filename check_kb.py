import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text

async def check():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT id, name, description FROM knowledge_bases WHERE id = 'ed9eafd1-7bd8-409e-baac-d5317adab25d'"))
        kb = res.fetchone()
        print("KB:", kb)

        res2 = await db.execute(text("SELECT chunk_index, length(text), text FROM document_chunks WHERE kb_id = 'ed9eafd1-7bd8-409e-baac-d5317adab25d' AND text ILIKE '%picture%' ORDER BY chunk_index LIMIT 2"))
        chunks = res2.fetchall()
        for c in chunks:
            print("CHUNK INDEX:", c[0], "LEN:", c[1])
            print(c[2])
            print("="*60)

if __name__ == "__main__":
    asyncio.run(check())
