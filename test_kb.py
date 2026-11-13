import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase
from sqlalchemy import select

async def run():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(KnowledgeBase).where(KnowledgeBase.name.like('%Attrition%')))
        kb = res.scalars().first()
        if kb:
            print("Found KB:", kb.name)
            print("Categorical Values:", kb.categorical_values)
        else:
            print("Not found")

if __name__ == "__main__":
    asyncio.run(run())
