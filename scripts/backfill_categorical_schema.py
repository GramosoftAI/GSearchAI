import os
import sys
import asyncio
import polars as pl
import logging

# Add project root to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase
from sqlalchemy import select, update
from app.core.parquet_ingester import ParquetIngester

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def backfill():
    async with AsyncSessionLocal() as db:
        # We need to find all KBs that have a parquet file (description="excel_parquet")
        stmt = select(KnowledgeBase).where(KnowledgeBase.description == "excel_parquet")
        result = await db.execute(stmt)
        kbs = result.scalars().all()
        
        updated_count = 0
        for kb in kbs:
            try:
                dataset_name = getattr(kb, "parsed_path", None)
                if not dataset_name:
                    continue
                    
                parquet_path = ParquetIngester.get_active_dataset(dataset_name)
                if not parquet_path or not os.path.exists(parquet_path):
                    logger.warning(f"Parquet file not found for KB {kb.id} ({kb.name})")
                    continue
                    
                df = pl.read_parquet(parquet_path)
                
                categorical_registry = {}
                for col in df.columns:
                    if df[col].dtype == pl.String or df[col].dtype == pl.Utf8:
                        unique_vals = df[col].drop_nulls().unique().to_list()
                        if len(unique_vals) < 50:
                            categorical_registry[col] = unique_vals
                            
                if categorical_registry:
                    await db.execute(
                        update(KnowledgeBase)
                        .where(KnowledgeBase.id == kb.id)
                        .values(categorical_values=categorical_registry)
                    )
                    updated_count += 1
                    logger.info(f"Updated KB {kb.id} ({kb.name}) with {len(categorical_registry)} categorical columns")
                    
            except Exception as e:
                logger.error(f"Error processing KB {kb.id}: {e}")
                
        await db.commit()
        logger.info(f"Backfill complete. Updated {updated_count} KBs.")

if __name__ == "__main__":
    asyncio.run(backfill())
