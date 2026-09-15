import asyncio
import sys
import os
import logging
from sqlalchemy import select, delete, text

# Add the project root to the python path
sys.path.append('.')

from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase, DocumentChunk

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def migrate_csv_chunks():
    """
    Migration script to align previously ingested CSV/Excel KBs with the new
    unconditional DuckDB bypass architecture.
    
    Deletes all DocumentChunk records where chunk_index < 90000 (ESDIP semantic chunks)
    for KBs identified as datasets/spreadsheets.
    """
    logger.info("Starting CSV/Excel DocumentChunk migration...")
    
    async with AsyncSessionLocal() as db:
        try:
            # Find all KBs that are datasets/spreadsheets
            # We can identify them by checking document_category == 'dataset',
            # or by name/parsed_path ending in .csv, .xls, .xlsx
            stmt = select(KnowledgeBase.id, KnowledgeBase.name, KnowledgeBase.document_category, KnowledgeBase.parsed_path).where(
                (KnowledgeBase.document_category == 'dataset') |
                KnowledgeBase.name.ilike('%spreadsheet%') |
                KnowledgeBase.name.ilike('%.csv%') |
                KnowledgeBase.name.ilike('%.xlsx%') |
                KnowledgeBase.name.ilike('%.xls%') |
                (KnowledgeBase.parsed_path != None)
            )
            result = await db.execute(stmt)
            kbs = result.all()
            
            target_kb_ids = []
            for kb in kbs:
                # Be careful to only include CSV/Excel KBs, not PDFs that might have a parsed_path
                is_csv_kb = False
                name = kb.name.lower() if kb.name else ""
                path = kb.parsed_path.lower() if kb.parsed_path else ""
                
                if kb.document_category == 'dataset':
                    is_csv_kb = True
                elif "spreadsheet" in name or name.endswith((".csv", ".xls", ".xlsx")):
                    is_csv_kb = True
                elif path.endswith((".csv", ".xls", ".xlsx", ".parquet")):
                    is_csv_kb = True
                    
                if is_csv_kb:
                    target_kb_ids.append(kb.id)
            
            if not target_kb_ids:
                logger.info("No CSV/Excel KBs found. Nothing to migrate.")
                return

            logger.info(f"Found {len(target_kb_ids)} CSV/Excel KBs. Executing cleanup...")
            
            # Delete chunks for these KBs where chunk_index < 90000
            delete_stmt = delete(DocumentChunk).where(
                DocumentChunk.kb_id.in_(target_kb_ids),
                DocumentChunk.chunk_index < 90000
            )
            
            res = await db.execute(delete_stmt)
            deleted_count = res.rowcount
            await db.commit()
            
            logger.info(f"Migration complete. Deleted {deleted_count} old ESDIP chunks.")
            
        except Exception as e:
            logger.error(f"Migration failed: {e}")
            await db.rollback()

if __name__ == "__main__":
    asyncio.run(migrate_csv_chunks())
