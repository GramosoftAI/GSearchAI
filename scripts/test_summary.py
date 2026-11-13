import asyncio
import sys
import logging
from uuid import UUID
from sqlalchemy import select

# Add the project root to the python path
sys.path.append('.')

from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.kb_summary import generate_kb_summary_embedding
from app.modules.knowledge_bases.models import KnowledgeBase

logging.basicConfig(level=logging.INFO)

async def test_summary():
    kb_id = "b45107ec-b88c-46a9-86c7-67d041af3073" # From previous logs
    async with AsyncSessionLocal() as db:
        stmt = select(KnowledgeBase).where(KnowledgeBase.id == UUID(kb_id))
        res = await db.execute(stmt)
        kb = res.scalar_one_or_none()
        if not kb:
            print(f"KB {kb_id} not found.")
            return
            
        print("--- BEFORE RE-GENERATING ---")
        print("Schema:", kb.dataset_schema)
        
        print("\n--- RE-GENERATING SUMMARY ---")
        await generate_kb_summary_embedding(kb_id, db)
        
if __name__ == "__main__":
    asyncio.run(test_summary())
