import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

async def check():
    engine = create_async_engine('postgresql+asyncpg://graphmind:graphmind_password@localhost:5433/graphmind')
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        res = await session.execute(text("""
            SELECT id, query, response_status, llm_input_tokens, llm_output_tokens, embedding_tokens, total_cost_usd, created_at
            FROM analytics_query_logs
            ORDER BY created_at DESC
            LIMIT 1
        """))
        row = res.fetchone()
        if row:
            print("Latest Query Log in DB:")
            print("ID:", row[0])
            print("Query:", row[1])
            print("Status:", row[2])
            print("LLM Input Tokens:", row[3])
            print("LLM Output Tokens:", row[4])
            print("Embedding Tokens:", row[5])
            print("Total Cost USD:", row[6])
            print("Created At:", row[7])
        else:
            print("No query logs found.")

asyncio.run(check())
