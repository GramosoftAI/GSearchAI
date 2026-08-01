import os
import logging
import urllib.parse
from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.database import AsyncSessionLocal
from app.core.s3 import S3StorageService
from app.modules.knowledge_bases.service import KnowledgeBaseService
from app.modules.knowledge_bases.routes import get_tenant_and_user

logger = logging.getLogger(__name__)

# Register a router without a module prefix to support /files/{file_id}/preview
router = APIRouter(tags=["Files"])

import uuid
from sqlalchemy import select
from app.modules.knowledge_bases.models import KnowledgeBase
from app.core.config import get_settings

CONTENT_TYPE_MAP = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".txt": "text/plain",
    ".html": "text/html",
    ".md": "text/markdown",
    ".json": "application/json"
}

@router.get("/files/{file_id}/preview")
@router.get("/api/v1/files/{file_id}/preview", include_in_schema=False)
async def preview_file(request: Request, file_id: str):
    """
    Securely preview or download files stored in private S3.
    Supports authenticated admin requests and unauthenticated embedded widget preview.
    """
    tenant_id, user_id = None, None
    try:
        tenant_id, user_id = get_tenant_and_user(request)
    except Exception:
        pass

    async with AsyncSessionLocal() as db:
        filename, s3_key = None, None
        
        if tenant_id and user_id:
            service = KnowledgeBaseService(db, tenant_id)
            result = await service.get_file_preview_metadata(file_id, user_id)
            if result.get("success"):
                data = result["data"]
                filename = data["filename"]
                s3_key = data["s3_key"]

        # Fallback for unauthenticated widget preview requests
        if not filename or not s3_key:
            try:
                file_uuid = uuid.UUID(file_id)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid file_id UUID format")
                
            query = select(KnowledgeBase).where(
                KnowledgeBase.id == file_uuid,
                KnowledgeBase.is_active == True
            )
            res = await db.execute(query)
            kb = res.scalar_one_or_none()
            
            if not kb:
                raise HTTPException(status_code=404, detail="File not found")
                
            filename = kb.name
            s3_service = S3StorageService()
            if kb.s3_path:
                s3_key = s3_service._parse_s3_key_from_url(kb.s3_path)
                if not s3_key and kb.s3_path.startswith("s3://"):
                    parts = kb.s3_path.split("/", 3)
                    if len(parts) >= 4:
                        s3_key = parts[3]
            if not s3_key:
                settings_cfg = get_settings()
                bucket_parts = (settings_cfg.aws_s3_bucket or "").split('/', 1)
                base_prefix = bucket_parts[1] + '/' if len(bucket_parts) > 1 else ''
                s3_key = f"{base_prefix}uploads/{kb.tenant_id}/{filename}"
        
        # Validation for allowed extensions
        file_ext = os.path.splitext(filename.lower())[1]
        content_type = CONTENT_TYPE_MAP.get(file_ext, "application/octet-stream")
        
        # Stream file from S3
        s3_service = S3StorageService()
        try:
            stream_body = s3_service.get_file_stream(s3_key)
        except ValueError as val_err:
            logger.error(f"S3 configuration error: {val_err}")
            raise HTTPException(status_code=500, detail="S3 storage is not configured properly.")
        except Exception as s3_err:
            logger.error(f"S3 fetch failed for key {s3_key}: {s3_err}")
            raise HTTPException(status_code=500, detail="Failed to fetch file from S3 storage.")

        encoded_filename = urllib.parse.quote(filename)
        headers = {
            "Content-Disposition": f'inline; filename="{filename}"; filename*=UTF-8\'\'{encoded_filename}'
        }
        
        return StreamingResponse(
            stream_body,
            media_type=content_type,
            headers=headers
        )


@router.get("/files/{file_id}/content")
@router.get("/api/v1/files/{file_id}/content", include_in_schema=False)
async def get_parsed_file_content(request: Request, file_id: str):
    """
    Securely retrieve the parsed text content of a file.
    """
    try:
        tenant_id, user_id = get_tenant_and_user(request)
    except HTTPException as e:
        raise e
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with AsyncSessionLocal() as db:
        service = KnowledgeBaseService(db, tenant_id)
        result = await service.get_parsed_content(file_id, user_id)
        
        if not result.get("success"):
            error_msg = result.get("error", "File not found")
            status_code = result.get("status_code", 404)
            raise HTTPException(status_code=status_code, detail=error_msg)

        return result

