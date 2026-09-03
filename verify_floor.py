import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.modules.rag.scoring.term_frequency import get_kb_doc_frequency, idf_discount
import os

async def main():
    db_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/gsearch_db")
    engine = create_async_engine(db_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as db:
        # We need the kb_id for 2021ESG.pdf. Let's find it.
        result = await db.execute(text("SELECT id, name FROM knowledge_bases WHERE name ILIKE '%2021ESG%' LIMIT 1"))
        row = result.fetchone()
        if not row:
            print("Could not find KB 2021ESG.pdf")
            return
            
        kb_id = str(row[0])
        print(f"Found KB {row[1]} with ID {kb_id}")
        
        doc_freq = await get_kb_doc_frequency(kb_id, db)
        
        print(f"Total chunks: {doc_freq.get('_total_chunks')}")
        for term in ['2021', 'total', 'revenue', 'the', 'and', 'sugarcane']:
            df = doc_freq.get(term, 0)
            idf = idf_discount(term, doc_freq)
            print(f"Term '{term}': df={df}, idf={idf:.3f}")

if __name__ == "__main__":
    asyncio.run(main())
