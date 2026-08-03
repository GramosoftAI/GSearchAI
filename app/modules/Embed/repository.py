"""Repository layer for Widget Customization"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import uuid
import logging
from .models import WidgetCustomization

logger = logging.getLogger(__name__)


class WidgetCustomizationRepository:
    """Repository handling CRUD operations for widget customizations"""

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id

    async def get_by_tenant_id(self) -> Optional[WidgetCustomization]:
        """Retrieve widget customization for current tenant"""
        query = select(WidgetCustomization).where(
            WidgetCustomization.tenant_id == self.tenant_id
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def create_or_update(
        self,
        user_id: str,
        logo_url: Optional[str],
        show_in_header: bool,
        show_in_chat: bool,
        show_in_embed: bool
    ) -> WidgetCustomization:
        """Create new widget customization or update existing record for tenant"""
        user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        existing = await self.get_by_tenant_id()

        if existing:
            existing.user_id = user_uuid
            existing.logo_url = logo_url
            existing.show_in_header = show_in_header
            existing.show_in_chat = show_in_chat
            existing.show_in_embed = show_in_embed
            await self.db.flush()
            await self.db.refresh(existing)
            return existing
        else:
            customization = WidgetCustomization(
                tenant_id=self.tenant_id,
                user_id=user_uuid,
                logo_url=logo_url,
                show_in_header=show_in_header,
                show_in_chat=show_in_chat,
                show_in_embed=show_in_embed
            )
            self.db.add(customization)
            await self.db.flush()
            await self.db.refresh(customization)
            return customization
