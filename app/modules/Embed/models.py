"""Widget Embed Configuration Models

Two tables:
  1. widget_embed_configs        — current config per (tenant_id, agent_id)
  2. widget_embed_config_history — immutable audit log of every change
  3. widget_customizations       — legacy logo-only table (kept for backward compat)

Design decisions:
  - Unique constraint on (tenant_id, agent_id) → one config per agent
  - `version` integer enables optimistic concurrency control (OCC)
  - `config_schema_version` allows forward-compatible schema evolution
  - `user_id` stored for audit only; NOT part of the uniqueness key
  - Individual columns (not JSONB blob) for fast indexed queries on key fields
  - History table records full snapshot + who/when/why changed it
"""

from sqlalchemy import (
    Column,
    String,
    Boolean,
    Integer,
    Text,
    ForeignKey,
    UniqueConstraint,
    Index,
    DateTime,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from ...models.base import BaseModel, Base
import uuid


# ---------------------------------------------------------------------------
# LEGACY: Logo-only table — kept for backward compatibility
# ---------------------------------------------------------------------------

class WidgetCustomization(BaseModel):
    """
    Legacy Widget Customization model - logo/branding flags only.
    Retained for backward compatibility with existing /embed/customization endpoints.
    New configurations should use WidgetEmbedConfig below.
    """

    __tablename__ = "widget_customizations"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    logo_url = Column(String, nullable=True)
    show_in_header = Column(Boolean, nullable=False, default=True)
    show_in_chat = Column(Boolean, nullable=False, default=True)
    show_in_embed = Column(Boolean, nullable=False, default=True)


# ---------------------------------------------------------------------------
# PRIMARY: Full embed configuration table
# ---------------------------------------------------------------------------

class WidgetEmbedConfig(BaseModel):
    """
    Full widget embed configuration keyed by (tenant_id, agent_id).

    Unique Constraint: (tenant_id, agent_id)
      -> Enforced at DB level for safe UPSERT with ON CONFLICT.
      -> user_id is audit-only, NOT part of the uniqueness key.

    Optimistic Concurrency:
      -> `version` is incremented on every update.
      -> Callers may pass their known `version`; a mismatch returns HTTP 409.

    Schema Evolution:
      -> `config_schema_version` allows future migrations of field semantics.
    """

    __tablename__ = "widget_embed_configs"

    # -- Ownership (audit-only — NOT part of unique key) -------------------
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # -- Agent Scoping (forms the uniqueness pair with tenant_id) ----------
    agent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # -- Optimistic Concurrency --------------------------------------------
    version = Column(Integer, nullable=False, default=1, server_default="1")
    config_schema_version = Column(Integer, nullable=False, default=1, server_default="1")

    # -- Theme & Colors ----------------------------------------------------
    theme_color = Column(String(20), nullable=False, default="#0fb5a1")
    theme_text_color = Column(String(20), nullable=False, default="#ffffff")
    btn_bg_color = Column(String(20), nullable=False, default="#0fb5a1")
    btn_border_color = Column(String(20), nullable=False, default="#0fb5a1")

    # -- Header ------------------------------------------------------------
    header_logo = Column(Text, nullable=True)
    header_align = Column(String(10), nullable=False, default="center")
    header_name = Column(String(200), nullable=False, default="Gsearch AI")
    header_subtext = Column(String(300), nullable=True, default="The team can also help")

    # -- Bot Identity ------------------------------------------------------
    agent_label = Column(String(100), nullable=False, default="Agent")
    bot_avatar = Column(String(200), nullable=False, default="chat")

    # -- Chat Widget Type & Layout -----------------------------------------
    chat_type = Column(String(20), nullable=False, default="icon")      # 'icon' | 'search'
    position = Column(String(20), nullable=False, default="right")      # 'left' | 'right' | 'center'
    placeholder_text = Column(String(300), nullable=True)

    # -- Entry Button ------------------------------------------------------
    button_icon = Column(String(200), nullable=False, default="chat")
    button_align = Column(String(10), nullable=False, default="right")
    show_button_text = Column(Boolean, nullable=False, default=True)
    button_text = Column(String(100), nullable=False, default="Help")

    # -- Content & Behavior Flags ------------------------------------------
    initial_message = Column(
        Text,
        nullable=True,
        default="Hi! I'm your AI Support Agent. How can I help you today?",
    )
    display_sources = Column(Boolean, nullable=False, default=True)
    allow_downloads = Column(Boolean, nullable=False, default=False)
    display_copy = Column(Boolean, nullable=False, default=True)
    display_feedback = Column(Boolean, nullable=False, default=True)
    link_safety = Column(Boolean, nullable=False, default=True)

    # -- Lead Capture ------------------------------------------------------
    lead_collection = Column(Boolean, nullable=False, default=False)
    # JSONB: ["name", "email"] — validated against allowed field names in service
    lead_fields = Column(JSONB, nullable=False, default=list, server_default='["name","email"]')
    lead_timing = Column(String(20), nullable=False, default="pre-chat")  # 'pre-chat'|'post-chat'

    # -- Support Escalation ------------------------------------------------
    escalation_enabled = Column(Boolean, nullable=False, default=False)
    escalation_link = Column(String(500), nullable=True, default="")

    # -- Logo Visibility (legacy-compat) -----------------------------------
    show_in_header = Column(Boolean, nullable=False, default=True)
    show_in_chat = Column(Boolean, nullable=False, default=True)
    show_in_embed = Column(Boolean, nullable=False, default=False)

    # -- DB-level Constraints & Indexes ------------------------------------
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_id", name="uq_embed_config_tenant_agent"),
        Index("ix_embed_config_tenant_agent", "tenant_id", "agent_id"),
    )


# ---------------------------------------------------------------------------
# AUDIT: Immutable history / version log table
# ---------------------------------------------------------------------------

class WidgetEmbedConfigHistory(Base):
    """
    Immutable snapshot of each embed config change.

    Every create or update to WidgetEmbedConfig inserts a row here with the
    full state at that point in time. This table is append-only.
    Rows are NEVER updated or deleted.
    """

    __tablename__ = "widget_embed_config_history"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    # Reference back to the live config row (nullable for deleted configs)
    config_id = Column(
        UUID(as_uuid=True),
        ForeignKey("widget_embed_configs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    tenant_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    agent_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Who made the change
    changed_by_user_id = Column(UUID(as_uuid=True), nullable=False, index=True)

    # Version at the time of this snapshot (matches config.version after update)
    version_snapshot = Column(Integer, nullable=False)

    # Operation type: 'create' | 'update' | 'delete'
    operation = Column(String(10), nullable=False, default="update")

    # Optional human-readable reason for the change
    change_reason = Column(String(500), nullable=True)

    # Full config snapshot stored as JSONB (compact, queryable, rollback-able)
    config_snapshot = Column(JSONB, nullable=False)

    # Immutable write timestamp (server-set)
    changed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    __table_args__ = (
        Index("ix_embed_history_config_id", "config_id"),
        Index("ix_embed_history_tenant_agent", "tenant_id", "agent_id"),
        Index("ix_embed_history_changed_at", "changed_at"),
    )
