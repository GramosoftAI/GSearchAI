import asyncio
import sys

from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase
from sqlalchemy import update, select

async def main():
    async with AsyncSessionLocal() as session:
        # Check current data
        result = await session.execute(select(KnowledgeBase))
        kbs = result.scalars().all()
        print("--- Current KBs ---")
        for kb in kbs:
            print(f"Name: {kb.name} | Canonical: {kb.canonical_name} | Aliases: {kb.aliases}")
        
        # Patch Hikers PA
        print("\n--- Patching HikersPaFAQ.pdf ---")
        stmt1 = (
            update(KnowledgeBase)
            .where(KnowledgeBase.name.ilike("%Hikers%"))
            .values(
                canonical_name="Hikers PA",
                aliases=["Hikers PA plan", "Hikers Personal Accident"]
            )
        )
        await session.execute(stmt1)

        # Patch BicycleFAQ
        print("\n--- Patching BicycleFAQ.pdf ---")
        stmt2 = (
            update(KnowledgeBase)
            .where(KnowledgeBase.name.ilike("%BicycleFAQ%"))
            .values(
                canonical_name="Bicycle FAQ",
                aliases=["bicycle insurance", "bicycle plan", "bicycle claim", "bicycle"]
            )
        )
        await session.execute(stmt2)

        await session.commit()
        print("Done! Database updated.")

if __name__ == "__main__":
    asyncio.run(main())
