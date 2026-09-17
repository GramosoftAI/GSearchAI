import asyncio
import logging
import sys, os

# Ensure the project root is on PYTHONPATH for absolute imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase
from app.modules.knowledge_bases.kb_summary import generate_kb_summary_embedding

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    async with AsyncSessionLocal() as session:
        # Find all KBs that haven't been backfilled yet
        stmt = select(KnowledgeBase.id).where(KnowledgeBase.summary_embedding.is_(None))
        result = await session.execute(stmt)
        kbs = result.scalars().all()
        
        logger.info(f"Found {len(kbs)} Knowledge Bases needing summary backfill.")
        
        for kb_id in kbs:
            try:
                await generate_kb_summary_embedding(str(kb_id), session)
            except Exception as e:
                logger.error(f"Failed to backfill KB {kb_id}: {e}")
                await session.rollback()

if __name__ == "__main__":
    asyncio.run(main())
