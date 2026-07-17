import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

async def get_agent_id():
    engine = create_async_engine('postgresql+asyncpg://postgres:postgres%40docker@localhost:5433/graphmind')
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        res = await session.execute(text("SELECT agent_id FROM knowledge_bases WHERE id = 'c936905e-68c6-471f-9395-62b39692a12e'"))
        kbs = res.fetchall()
        print('Agent ID:', kbs)

asyncio.run(get_agent_id())
