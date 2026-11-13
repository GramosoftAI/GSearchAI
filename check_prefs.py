import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

async def check():
    engine = create_async_engine('postgresql+asyncpg://graphmind:graphmind_password@localhost:5433/graphmind')
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        res = await session.execute(text("""
            SELECT id, tenant_id, user_id, agent_id, preference_key, preference_value, raw_statement, updated_at
            FROM user_preferences
            ORDER BY updated_at DESC
        """))
        rows = res.fetchall()
        print(f"Found {len(rows)} preferences:")
        for row in rows:
            print("ID:", row[0])
            print("Tenant:", row[1])
            print("User:", row[2])
            print("Agent:", row[3])
            print("Key:", row[4])
            print("Value:", row[5])
            print("Statement:", row[6])
            print("Updated At:", row[7])
            print("-" * 40)

asyncio.run(check())
