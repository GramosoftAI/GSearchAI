import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

async def check():
    engine = create_async_engine('postgresql+asyncpg://postgres:postgres%40docker@localhost:5433/graphmind')
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        res = await session.execute(text("SELECT tenant_id FROM agents WHERE id = '443a6edd-4117-4ba3-9d8c-2be0d091527b'"))
        agent = res.fetchone()
        print('Agent Tenant:', agent)

asyncio.run(check())
