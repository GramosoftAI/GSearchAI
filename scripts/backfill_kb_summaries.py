import asyncio
import logging
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase
from app.modules.knowledge_bases.kb_summary import generate_kb_summary_embedding

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    async with AsyncSessionLocal() as session:
        # Find all KBs that haven't been backfilled yet
        stmt = select(KnowledgeBase).where(KnowledgeBase.summary_embedding.is_(None))
        result = await session.execute(stmt)
        kbs = result.scalars().all()
        
        logger.info(f"Found {len(kbs)} Knowledge Bases needing summary backfill.")
        
        for kb in kbs:
            try:
                await generate_kb_summary_embedding(str(kb.id), session)
            except Exception as e:
                logger.error(f"Failed to backfill KB {kb.id}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
