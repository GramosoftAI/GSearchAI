"""Service layer for Widget Embed Configuration & Legacy Widget Customization business logic"""

from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional, List
import logging
import os
import uuid
import asyncio

from .repository import WidgetCustomizationRepository, WidgetEmbedConfigRepository, OptimisticLockError
from .schemas import WidgetCustomizationUpdate, WidgetEmbedConfigCreate
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

# ---------------------------------------------------------------------------
# NEW: Full embed config service
# ---------------------------------------------------------------------------

# Default values to return when no config is saved for an agent
_DEFAULT_CONFIG: Dict[str, Any] = {
    "theme_color": "#0fb5a1",
    "theme_text_color": "#ffffff",
    "btn_bg_color": "#0fb5a1",
    "btn_border_color": "#0fb5a1",
    "header_logo": None,
    "header_align": "center",
    "header_name": "Gsearch AI",
    "header_subtext": "The team can also help",
    "agent_label": "Agent",
    "bot_avatar": "chat",
    "chat_type": "icon",
    "position": "right",
    "placeholder_text": None,
    "button_icon": "chat",
    "button_align": "right",
    "show_button_text": True,
    "button_text": "Help",
    "initial_message": "Hi! I'm your AI Support Agent. How can I help you today?",
    "display_sources": True,
    "allow_downloads": False,
    "display_copy": True,
    "display_feedback": True,
    "link_safety": True,
    "lead_collection": False,
    "lead_fields": ["name", "email"],
    "lead_timing": "pre-chat",
    "escalation_enabled": False,
    "escalation_link": "",
    "show_in_header": True,
    "show_in_chat": True,
    "show_in_embed": False,
}


class WidgetEmbedConfigService:
    """
    Service class for full widget embed configuration CRUD.

    Responsibilities:
    - Validate agent ownership (agent must belong to the tenant)
    - Coordinate with WidgetEmbedConfigRepository for DB operations
    - Handle OCC version conflicts and translate to HTTP 409
    - Return structured dicts / ORM objects for routes to serialize
    """

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = tenant_id
        self.repository = WidgetEmbedConfigRepository(db, tenant_id)

    async def get_config(self, agent_id: str) -> Dict[str, Any]:
        """
        Fetch embed config for the (tenant_id, agent_id) pair.
        Returns safe defaults if no config has been saved yet.

        Used by both authenticated dashboard (full response) and
        public widget script (sanitized response — handled at route level).
        """
        config = await self.repository.get_by_agent(agent_id)
        if not config:
            logger.debug(
                "No embed config found; returning defaults",
                extra={"tenant_id": self.tenant_id, "agent_id": agent_id},
            )
            return {**_DEFAULT_CONFIG, "agent_id": agent_id, "exists": False}

        return self._config_to_dict(config, exists=True)

    async def list_configs(self) -> Dict[str, Any]:
        """List all embed configs for the tenant (dashboard listing)."""
        configs = await self.repository.list_all()
        return {
            "configs": [self._config_to_dict(c, exists=True) for c in configs],
            "total": len(configs),
        }

    async def save_config(
        self,
        user_id: str,
        data: WidgetEmbedConfigCreate,
    ) -> Dict[str, Any]:
        """
        Create or update widget embed config for (tenant_id, agent_id).

        Raises:
            ValueError: 422 — if data fails Pydantic validation (handled by FastAPI)
            HTTPException 409 — if expected_version doesn't match DB version (OCC conflict)
        """
        # Build the data dict from validated Pydantic model (exclude meta fields)
        config_data = data.model_dump(
            exclude={"agent_id", "expected_version", "change_reason"}
        )

        try:
            config = await self.repository.upsert(
                agent_id=data.agent_id,
                user_id=user_id,
                data=config_data,
                expected_version=data.expected_version,
                change_reason=data.change_reason,
            )
        except OptimisticLockError as e:
            # Re-raise with the OCC message — route will convert to HTTP 409
            raise OptimisticLockError(str(e))

        await self.db.commit()

        logger.info(
            "Embed config saved",
            extra={
                "tenant_id": self.tenant_id,
                "agent_id": data.agent_id,
                "user_id": user_id,
                "version": config.version,
            },
        )

        return {
            "success": True,
            "message": "Widget embed configuration saved successfully.",
            "config": self._config_to_dict(config, exists=True),
        }

    async def delete_config(
        self,
        agent_id: str,
        user_id: str,
        change_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Delete embed config for (tenant_id, agent_id).
        Returns success False if no config found (idempotent).
        """
        deleted = await self.repository.delete_by_agent(
            agent_id=agent_id,
            user_id=user_id,
            change_reason=change_reason,
        )
        if not deleted:
            logger.warning(
                "Delete attempted but no config found",
                extra={"tenant_id": self.tenant_id, "agent_id": agent_id},
            )
            return {"success": False, "message": "No configuration found for this agent.", "agent_id": agent_id}

        await self.db.commit()

        logger.info(
            "Embed config deleted",
            extra={"tenant_id": self.tenant_id, "agent_id": agent_id, "user_id": user_id},
        )

        return {
            "success": True,
            "message": "Widget embed configuration deleted successfully.",
            "agent_id": agent_id,
        }

    @staticmethod
    def _config_to_dict(config: Any, exists: bool = True) -> Dict[str, Any]:
        """Serialize a WidgetEmbedConfig ORM object to a plain dict."""
        return {
            "id": str(config.id),
            "tenant_id": str(config.tenant_id),
            "agent_id": str(config.agent_id),
            "user_id": str(config.user_id),
            "version": config.version,
            "config_schema_version": config.config_schema_version,
            "exists": exists,
            # Theme
            "theme_color": config.theme_color,
            "theme_text_color": config.theme_text_color,
            "btn_bg_color": config.btn_bg_color,
            "btn_border_color": config.btn_border_color,
            # Header
            "header_logo": config.header_logo,
            "header_align": config.header_align,
            "header_name": config.header_name,
            "header_subtext": config.header_subtext,
            # Bot Identity
            "agent_label": config.agent_label,
            "bot_avatar": config.bot_avatar,
            # Chat Type
            "chat_type": config.chat_type,
            "position": config.position,
            "placeholder_text": config.placeholder_text,
            # Button
            "button_icon": config.button_icon,
            "button_align": config.button_align,
            "show_button_text": config.show_button_text,
            "button_text": config.button_text,
            # Content
            "initial_message": config.initial_message,
            "display_sources": config.display_sources,
            "allow_downloads": config.allow_downloads,
            "display_copy": config.display_copy,
            "display_feedback": config.display_feedback,
            "link_safety": config.link_safety,
            # Lead
            "lead_collection": config.lead_collection,
            "lead_fields": config.lead_fields or ["name", "email"],
            "lead_timing": config.lead_timing,
            # Escalation
            "escalation_enabled": config.escalation_enabled,
            "escalation_link": config.escalation_link or "",
            # Legacy
            "show_in_header": config.show_in_header,
            "show_in_chat": config.show_in_chat,
            "show_in_embed": config.show_in_embed,
            # Metadata
            "created_at": config.created_at.isoformat() if config.created_at else None,
            "updated_at": config.updated_at.isoformat() if config.updated_at else None,
        }


# ---------------------------------------------------------------------------
# LEGACY: Logo-only service (backward compat)
# ---------------------------------------------------------------------------

class WidgetCustomizationService:
    """Service class for widget customization operations (legacy logo-only)"""


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
