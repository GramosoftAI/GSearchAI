import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from uuid import UUID
from app.modules.rag.pipeline import RAGPipeline
import logging
import sys

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

async def check():
    engine = create_async_engine('postgresql+asyncpg://postgres:postgres%40docker@localhost:5433/graphmind')
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    tenant_id = 'fd06d2c3-c7c8-4a6e-a155-40870a062310'
    kb_id = 'c936905e-68c6-471f-9395-62b39692a12e'
    agent_id = '443a6edd-4117-4ba3-9d8c-2be0d091527b'
    query = "Which movie was released on 24-11-2021, and what is its Vote_Average compared to The King's Man?"

    async with async_session() as session:
        pipeline = RAGPipeline(tenant_id=tenant_id, db=session)
        context = await pipeline.query(
            query=query,
            agent_id=agent_id,
            kb_id=[kb_id],
            top_k=5,
            max_depth=0
        )
        print("Final chunks:", len(context.chunks))
        for c in context.chunks:
            print("Chunk:", c.chunk_id)

asyncio.run(check())
