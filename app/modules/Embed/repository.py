"""Repository layer for Widget Embed Configuration & Legacy Widget Customization"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from typing import Optional, List, Dict, Any
import uuid
import logging

from .models import WidgetCustomization, WidgetEmbedConfig, WidgetEmbedConfigHistory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NEW: Full embed configuration repository
# ---------------------------------------------------------------------------

class WidgetEmbedConfigRepository:
    """
    Repository handling CRUD operations for WidgetEmbedConfig.

    Key design decisions:
    - Atomic PostgreSQL UPSERT using INSERT ... ON CONFLICT DO UPDATE
      → Eliminates race conditions from a separate SELECT then INSERT/UPDATE
    - version is incremented atomically in SQL (not Python) to prevent lost updates
    - Every write appends an immutable row to WidgetEmbedConfigHistory
    - All queries are scoped to tenant_id for Row-Level Security enforcement
    """

    def __init__(self, db: AsyncSession, tenant_id: str):
        self.db = db
        self.tenant_id = uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id

    # ── READ ────────────────────────────────────────────────────────────────

    async def get_by_agent(self, agent_id: str) -> Optional[WidgetEmbedConfig]:
        """Retrieve embed config for (tenant_id, agent_id). Returns None if not found."""
        agent_uuid = uuid.UUID(agent_id) if isinstance(agent_id, str) else agent_id
        query = select(WidgetEmbedConfig).where(
            WidgetEmbedConfig.tenant_id == self.tenant_id,
            WidgetEmbedConfig.agent_id == agent_uuid,
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_all(self) -> List[WidgetEmbedConfig]:
        """List all embed configs for a tenant, newest first."""
        query = (
            select(WidgetEmbedConfig)
            .where(WidgetEmbedConfig.tenant_id == self.tenant_id)
            .order_by(WidgetEmbedConfig.updated_at.desc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    # ── UPSERT (atomic) ─────────────────────────────────────────────────────

    async def upsert(
        self,
        agent_id: str,
        user_id: str,
        data: Dict[str, Any],
        expected_version: Optional[int] = None,
        change_reason: Optional[str] = None,
    ) -> WidgetEmbedConfig:
        """
        Atomically create or update a widget embed config.

        Uses PostgreSQL's INSERT ... ON CONFLICT (tenant_id, agent_id) DO UPDATE
        to eliminate the read-modify-write race condition.

        Optimistic Concurrency Control:
          - If expected_version is provided, the UPDATE only fires when the
            current DB version matches. If it doesn't, the row is NOT updated
            and we raise a 409 Conflict in the service layer.

        History:
          - After every successful upsert, an immutable history row is appended.

        Args:
            agent_id: UUID of the agent
            user_id: UUID of the user making the change (audit)
            data: Dict of config fields to persist (all 25+ attributes)
            expected_version: Optional version for OCC; None = first-write-wins
            change_reason: Optional audit note

        Returns:
            The refreshed WidgetEmbedConfig ORM instance
        """
        agent_uuid = uuid.UUID(agent_id) if isinstance(agent_id, str) else agent_id
        user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
        config_id = uuid.uuid4()

        # Build the insert payload (all columns)
        insert_values = {
            "id": config_id,
            "tenant_id": self.tenant_id,
            "agent_id": agent_uuid,
            "user_id": user_uuid,
            "version": 1,
            "config_schema_version": 1,
            **data,
        }

        # Build the ON CONFLICT update payload — all fields except identity columns
        update_values = {
            k: v for k, v in data.items()
        }
        update_values["user_id"] = user_uuid
        # Increment version atomically in SQL (avoids stale Python read)
        # We use a raw expression via the excluded pseudo-table
        from sqlalchemy import text as sql_text

        stmt = pg_insert(WidgetEmbedConfig).values(**insert_values)

        if expected_version is not None:
            # Conditional update: only fires when version matches expected
            stmt = stmt.on_conflict_do_update(
                constraint="uq_embed_config_tenant_agent",
                set_={
                    **update_values,
                    "version": WidgetEmbedConfig.version + 1,
                },
                where=WidgetEmbedConfig.version == expected_version,
            )
        else:
            # Unconditional update (first-write-wins)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_embed_config_tenant_agent",
                set_={
                    **update_values,
                    "version": WidgetEmbedConfig.version + 1,
                },
            )

        # Execute UPSERT — returns the id of the affected row
        stmt = stmt.returning(WidgetEmbedConfig.id, WidgetEmbedConfig.version)
        result = await self.db.execute(stmt)
        row = result.fetchone()

        if row is None:
            # ON CONFLICT WHERE clause didn't match → version mismatch (OCC failure)
            raise OptimisticLockError(
                f"Version conflict: expected version {expected_version} but DB has a different version. "
                "Refresh and retry."
            )

        returned_id = row[0]
        new_version = row[1]

        # Fetch the full ORM object for the history snapshot and return value
        fetch_result = await self.db.execute(
            select(WidgetEmbedConfig).where(WidgetEmbedConfig.id == returned_id)
        )
        config = fetch_result.scalar_one()

        # Append immutable history record
        operation = "create" if new_version == 1 else "update"
        await self._append_history(
            config=config,
            changed_by_user_id=user_uuid,
            operation=operation,
            change_reason=change_reason,
        )

        logger.info(
            "Embed config upserted",
            extra={
                "tenant_id": str(self.tenant_id),
                "agent_id": agent_id,
                "user_id": user_id,
                "operation": operation,
                "version": new_version,
            },
        )

        return config

    # ── DELETE ──────────────────────────────────────────────────────────────

    async def delete_by_agent(
        self,
        agent_id: str,
        user_id: str,
        change_reason: Optional[str] = None,
    ) -> bool:
        """
        Hard-delete the embed config for (tenant_id, agent_id).

        Appends a 'delete' history record before deletion so the last known
        config is preserved in the audit log.

        Returns True if a row was deleted, False if none found.
        """
        agent_uuid = uuid.UUID(agent_id) if isinstance(agent_id, str) else agent_id
        user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id

        # Fetch existing record for history snapshot
        existing = await self.get_by_agent(agent_id)
        if not existing:
            return False

        # Write deletion event to history BEFORE deleting (config_id → SET NULL post-delete)
        await self._append_history(
            config=existing,
            changed_by_user_id=user_uuid,
            operation="delete",
            change_reason=change_reason,
        )

        # Hard delete
        await self.db.execute(
            delete(WidgetEmbedConfig).where(
                WidgetEmbedConfig.tenant_id == self.tenant_id,
                WidgetEmbedConfig.agent_id == agent_uuid,
            )
        )

        logger.info(
            "Embed config deleted",
            extra={
                "tenant_id": str(self.tenant_id),
                "agent_id": agent_id,
                "user_id": user_id,
            },
        )

        return True

    # ── HISTORY (private helper) ─────────────────────────────────────────────

    async def _append_history(
        self,
        config: WidgetEmbedConfig,
        changed_by_user_id: uuid.UUID,
        operation: str,
        change_reason: Optional[str],
    ) -> None:
        """Append an immutable snapshot row to the history table."""
        snapshot = {
            "theme_color": config.theme_color,
            "theme_text_color": config.theme_text_color,
            "btn_bg_color": config.btn_bg_color,
            "btn_border_color": config.btn_border_color,
            "header_logo": config.header_logo,
            "header_align": config.header_align,
            "header_name": config.header_name,
            "header_subtext": config.header_subtext,
            "agent_label": config.agent_label,
            "bot_avatar": config.bot_avatar,
            "chat_type": config.chat_type,
            "position": config.position,
            "placeholder_text": config.placeholder_text,
            "button_icon": config.button_icon,
            "button_align": config.button_align,
            "show_button_text": config.show_button_text,
            "button_text": config.button_text,
            "initial_message": config.initial_message,
            "display_sources": config.display_sources,
            "allow_downloads": config.allow_downloads,
            "display_copy": config.display_copy,
            "display_feedback": config.display_feedback,
            "link_safety": config.link_safety,
            "lead_collection": config.lead_collection,
            "lead_fields": config.lead_fields,
            "lead_timing": config.lead_timing,
            "escalation_enabled": config.escalation_enabled,
            "escalation_link": config.escalation_link,
            "show_in_header": config.show_in_header,
            "show_in_chat": config.show_in_chat,
            "show_in_embed": config.show_in_embed,
        }
        history_row = WidgetEmbedConfigHistory(
            config_id=config.id,
            tenant_id=config.tenant_id,
            agent_id=config.agent_id,
            changed_by_user_id=changed_by_user_id,
            version_snapshot=config.version,
            operation=operation,
            change_reason=change_reason,
            config_snapshot=snapshot,
        )
        self.db.add(history_row)


class OptimisticLockError(Exception):
    """Raised when an UPSERT is blocked by an optimistic concurrency version mismatch."""
    pass


# ---------------------------------------------------------------------------
# LEGACY: Logo-only repository (backward compat)
# ---------------------------------------------------------------------------

class WidgetCustomizationRepository:
    """Repository handling CRUD operations for widget customizations (legacy logo-only)"""

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
