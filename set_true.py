import asyncio
from sqlalchemy import text
from app.core.database import AsyncSessionLocal

async def alter_db():
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(text("UPDATE widget_embed_configs SET search_mobile_icon = TRUE WHERE agent_id = '784642d3-5170-4140-bc81-281bc15456df';"))
            print("Set search_mobile_icon = TRUE for agent 784642d3-5170-4140-bc81-281bc15456df")
        except Exception as e:
            print(e)
        await db.commit()

if __name__ == "__main__":
    asyncio.run(alter_db())
