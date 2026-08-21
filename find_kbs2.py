import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import sys

load_dotenv('e:/graphmind/graphmind/.env')
sys.path.append('e:/graphmind/graphmind')
from app.core.config import get_settings

async def main():
    s = get_settings()
    engine = create_async_engine(f'postgresql+asyncpg://{s.postgres_user}:{s.postgres_password}@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}')
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as db:
        res = await db.execute(text("SELECT id, name, tenant_id FROM knowledge_bases LIMIT 10"))
        print(res.fetchall())
        
        # Also let's try to find exactly the one the user meant.
        # "46-URL / 157-chunk website ingestion"
        res = await db.execute(text("SELECT kb_id, count(id) FROM document_chunks GROUP BY kb_id HAVING count(id) = 157"))
        print("\nKBs with exactly 157 chunks:")
        print(res.fetchall())

asyncio.run(main())
