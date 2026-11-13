import logging
from typing import Dict, Any, List, Optional
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.service import KnowledgeBaseService

logger = logging.getLogger(__name__)

async def onedrive_sync_job(
    ctx: Dict[Any, Any],
    kb_id: str,
    tenant_id: str,
    credentials: Dict[str, Any],
    file_ids: Optional[List[str]] = None,
    folder_ids: Optional[List[str]] = None,
) -> dict:
    """
    Background worker job to synchronize OneDrive files to PostgreSQL & Neo4j.
    """
    logger.info(f"Starting background onedrive_sync_job for KB {kb_id}, tenant {tenant_id}")
    try:
        async with AsyncSessionLocal() as db:
            service = KnowledgeBaseService(db, tenant_id)
            res = await service.sync_onedrive_source(
                kb_id=kb_id,
                credentials_dict=credentials,
                file_ids=file_ids,
                folder_ids=folder_ids,
            )
            logger.info(f"Finished onedrive_sync_job for KB {kb_id}: {res}")
            return res
    except Exception as e:
        logger.error(f"onedrive_sync_job failed for KB {kb_id}: {e}", exc_info=True)
        return {"success": False, "error": str(e)}

