"""add_widget_embed_configs_and_history

Creates two new tables:
  - widget_embed_configs        : Full per-agent embed configuration
  - widget_embed_config_history : Immutable audit log

Revision ID: e32c19c5a944
Create Date: 2026-08-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e32c19c5a944"
down_revision = "a2089ae9aacb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widget_embed_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("config_schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("theme_color", sa.String(20), nullable=False, server_default="#0fb5a1"),
        sa.Column("theme_text_color", sa.String(20), nullable=False, server_default="#ffffff"),
        sa.Column("btn_bg_color", sa.String(20), nullable=False, server_default="#0fb5a1"),
        sa.Column("btn_border_color", sa.String(20), nullable=False, server_default="#0fb5a1"),
        sa.Column("header_logo", sa.Text(), nullable=True),
        sa.Column("header_align", sa.String(10), nullable=False, server_default="center"),
        sa.Column("header_name", sa.String(200), nullable=False, server_default="Gsearch AI"),
        sa.Column("header_subtext", sa.String(300), nullable=True, server_default="The team can also help"),
        sa.Column("agent_label", sa.String(100), nullable=False, server_default="Agent"),
        sa.Column("bot_avatar", sa.String(200), nullable=False, server_default="chat"),
        sa.Column("chat_type", sa.String(20), nullable=False, server_default="icon"),
        sa.Column("position", sa.String(20), nullable=False, server_default="right"),
        sa.Column("placeholder_text", sa.String(300), nullable=True),
        sa.Column("button_icon", sa.String(200), nullable=False, server_default="chat"),
        sa.Column("button_align", sa.String(10), nullable=False, server_default="right"),
        sa.Column("show_button_text", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("button_text", sa.String(100), nullable=False, server_default="Help"),
        sa.Column("initial_message", sa.Text(), nullable=True),
        sa.Column("display_sources", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("allow_downloads", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("display_copy", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("display_feedback", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("link_safety", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("lead_collection", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("lead_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='["name","email"]'),
        sa.Column("lead_timing", sa.String(20), nullable=False, server_default="pre-chat"),
        sa.Column("escalation_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("escalation_link", sa.String(500), nullable=True, server_default=""),
        sa.Column("show_in_header", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("show_in_chat", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("show_in_embed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "agent_id", name="uq_embed_config_tenant_agent"),
    )
    op.create_index("ix_embed_config_tenant_agent", "widget_embed_configs", ["tenant_id", "agent_id"])
    op.create_index("ix_embed_config_tenant_id", "widget_embed_configs", ["tenant_id"])
    op.create_index("ix_embed_config_agent_id", "widget_embed_configs", ["agent_id"])
    op.create_index("ix_embed_config_updated_at", "widget_embed_configs", ["updated_at"])

    op.create_table(
        "widget_embed_config_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("config_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("changed_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_snapshot", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(10), nullable=False),
        sa.Column("change_reason", sa.String(500), nullable=True),
        sa.Column("config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["config_id"], ["widget_embed_configs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_embed_history_config_id", "widget_embed_config_history", ["config_id"])
    op.create_index("ix_embed_history_tenant_agent", "widget_embed_config_history", ["tenant_id", "agent_id"])
    op.create_index("ix_embed_history_changed_at", "widget_embed_config_history", ["changed_at"])


def downgrade() -> None:
    op.drop_index("ix_embed_history_changed_at", table_name="widget_embed_config_history")
    op.drop_index("ix_embed_history_tenant_agent", table_name="widget_embed_config_history")
    op.drop_index("ix_embed_history_config_id", table_name="widget_embed_config_history")
    op.drop_table("widget_embed_config_history")

    op.drop_index("ix_embed_config_updated_at", table_name="widget_embed_configs")
    op.drop_index("ix_embed_config_agent_id", table_name="widget_embed_configs")
    op.drop_index("ix_embed_config_tenant_id", table_name="widget_embed_configs")
    op.drop_index("ix_embed_config_tenant_agent", table_name="widget_embed_configs")
    op.drop_table("widget_embed_configs")
