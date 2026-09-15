import logging
from typing import Dict, Any, List, Optional
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.service import KnowledgeBaseService

logger = logging.getLogger(__name__)

async def google_drive_sync_job(
    ctx: Dict[Any, Any],
    kb_id: str,
    tenant_id: str,
    credentials: Dict[str, Any],
    folder_urls: Optional[List[str]] = None,
    file_ids: Optional[List[str]] = None,
    folder_ids: Optional[List[str]] = None,
    user_email: Optional[str] = None
) -> dict:
    """
    Background worker job to synchronize Google Drive files to PostgreSQL & Neo4j.
    """
    logger.info(f"Starting background google_drive_sync_job for KB {kb_id}, tenant {tenant_id}")
    try:
        import importlib
        import app.modules.knowledge_bases.service as kb_service_mod
        importlib.reload(kb_service_mod)
        async with AsyncSessionLocal() as db:
            service = kb_service_mod.KnowledgeBaseService(db, tenant_id)
            res = await service.sync_google_drive_source(
                kb_id=kb_id,
                credentials_dict=credentials,
                folder_urls=folder_urls,
                file_ids=file_ids,
                folder_ids=folder_ids,
                user_email=user_email
            )
            logger.info(f"Finished google_drive_sync_job for KB {kb_id}: {res}")
            return res
    except Exception as e:
        logger.error(f"google_drive_sync_job failed for KB {kb_id}: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
