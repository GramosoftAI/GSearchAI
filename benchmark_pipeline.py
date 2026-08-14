import asyncio
import time
import logging
import sys
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.modules.rag.service import RAGService
from dotenv import load_dotenv

from app.core.config import get_settings

logging.basicConfig(level=logging.WARNING, stream=sys.stdout)
load_dotenv('.env')

async def benchmark():
    s = get_settings()
    db_url = f'postgresql+asyncpg://{s.postgres_user}:{s.postgres_password}@{s.postgres_host}:{s.postgres_port}/{s.postgres_db}'
    engine = create_async_engine(db_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    tenant_id = 'd113ef9e-bcb5-4626-af1d-6c995bbfe4d0'
    kb_id = '2b9b7f57-3d46-4329-bb55-80605d43aa0e'
    agent_id = '9ad488ce-9b58-4943-b909-ab4791638bf9'
    query = "Which movie was released on 24-11-2021?"

    async with async_session() as session:
        service = RAGService(db=session, tenant_id=tenant_id)
        
        start_time = time.time()
        first_token_time = None
        
        print(f"Starting RAG stream benchmark for query: '{query}'")
        
        async for chunk in service.stream_rag_answer(
            query=query,
            agent_id=agent_id,
            kb_id=kb_id,
            top_k=5,
            max_depth=0
        ):
            if first_token_time is None:
                first_token_time = time.time()
                print(f"Time to First Token/Metadata (TTFT): {(first_token_time - start_time)*1000:.2f} ms")
                
        end_time = time.time()
        print(f"Total Response Time: {(end_time - start_time)*1000:.2f} ms")

asyncio.run(benchmark())
