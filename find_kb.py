import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from app.core.config import get_settings

async def find_kb():
    s = get_settings()
    db_url = f'postgresql+asyncpg://{s.postgres_user}:{s.postgres_password}@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}'
    engine = create_async_engine(db_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        res = await session.execute(text("SELECT kb_id, COUNT(*) as c FROM document_chunks GROUP BY kb_id ORDER BY c DESC LIMIT 1"))
        row = res.fetchone()
        if not row:
            print("No chunks found in DB!")
            return
        kb_id = str(row.kb_id)
        
        res = await session.execute(text("SELECT agent_id, tenant_id FROM knowledge_bases WHERE id = :kb_id"), {"kb_id": kb_id})
        k_row = res.fetchone()
        
        print(f"tenant_id = '{k_row.tenant_id}'")
        print(f"kb_id = '{kb_id}'")
        print(f"agent_id = '{k_row.agent_id}'")

asyncio.run(find_kb())
