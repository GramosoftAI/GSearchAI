"""Service layer for Widget Customization business logic"""

from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional
import logging
import os
import uuid
import asyncio

from .repository import WidgetCustomizationRepository
from .schemas import WidgetCustomizationUpdate
from ...core.s3 import S3StorageService
from ...core.config import get_settings

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".webp"}
ALLOWED_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/svg+xml",
    "image/webp"
}
MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB


class WidgetCustomizationService:
    """Service class for widget customization operations"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.repository = WidgetCustomizationRepository(db, tenant_id)

    async def get_customization(self) -> Dict[str, Any]:
        """Fetch widget customization for tenant or return defaults if non-existent"""
        customization = await self.repository.get_by_tenant_id()
        if customization:
            return {
                "logo_url": customization.logo_url,
                "show_in_header": customization.show_in_header,
                "show_in_chat": customization.show_in_chat,
                "show_in_embed": customization.show_in_embed
            }

        # Default response required if no customization exists
        return {
            "logo_url": None,
            "show_in_header": True,
            "show_in_chat": True,
            "show_in_embed": True
        }

    async def save_customization(
        self,
        user_id: str,
        data: WidgetCustomizationUpdate
    ) -> Dict[str, Any]:
        """Create or update widget customization settings for tenant"""
        await self.repository.create_or_update(
            user_id=user_id,
            logo_url=data.logo_url,
            show_in_header=data.show_in_header,
            show_in_chat=data.show_in_chat,
            show_in_embed=data.show_in_embed
        )
        await self.db.commit()
        return {
            "success": True,
            "message": "Widget customization saved successfully."
        }

    async def upload_logo(
        self,
        filename: str,
        content_type: str,
        file_bytes: bytes
    ) -> Dict[str, Any]:
        """Validate and upload logo image file to AWS S3 storage"""
        # 1. Validate file size (max 2 MB)
        if len(file_bytes) > MAX_FILE_SIZE:
            return {
                "success": False,
                "status_code": 400,
                "error": f"File size exceeds maximum allowed limit of 2 MB. File size: {len(file_bytes)/(1024*1024):.2f} MB"
            }

        # 2. Validate allowed file format
        file_ext = os.path.splitext(filename.lower())[1]
        if file_ext not in ALLOWED_IMAGE_EXTENSIONS and (not content_type or content_type.lower() not in ALLOWED_MIME_TYPES):
            return {
                "success": False,
                "status_code": 400,
                "error": f"Invalid file type '{file_ext}'. Allowed formats: PNG, JPG, JPEG, SVG, WEBP."
            }

        # 3. Upload file to AWS S3 storage
        s3_service = S3StorageService()
        if not s3_service.client:
            return {
                "success": False,
                "status_code": 500,
                "error": "AWS S3 cloud storage is not configured on the server."
            }

        unique_name = f"logo_{uuid.uuid4().hex[:8]}{file_ext}"
        bucket_val = get_settings().aws_s3_bucket or "default-bucket"
        bucket_parts = bucket_val.split('/', 1)
        base_prefix = bucket_parts[1] + '/' if len(bucket_parts) > 1 else ''
        s3_key = f"{base_prefix}logos/{self.tenant_id}/{unique_name}"

        try:
            def _upload():
                try:
                    s3_service.client.put_object(
                        Bucket=s3_service.bucket_name,
                        Key=s3_key,
                        Body=file_bytes,
                        ContentType=content_type or "image/png",
                        ACL='public-read'
                    )
                except Exception:
                    s3_service.client.put_object(
                        Bucket=s3_service.bucket_name,
                        Key=s3_key,
                        Body=file_bytes,
                        ContentType=content_type or "image/png"
                    )
            await asyncio.to_thread(_upload)

            region = get_settings().aws_region or "us-east-1"
            logo_url = f"https://{s3_service.bucket_name}.s3.{region}.amazonaws.com/{s3_key}"

            return {
                "success": True,
                "logo_url": logo_url
            }
        except Exception as e:
            logger.error(f"S3 logo upload failed for tenant {self.tenant_id}: {e}", exc_info=True)
            return {
                "success": False,
                "status_code": 500,
                "error": "Failed to upload logo image to S3 cloud storage."
            }
