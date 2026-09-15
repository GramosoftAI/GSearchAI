"""SQLAlchemy ORM models for Slack Multi-Tenant Integration"""

import uuid
from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UUID as SQLAlchemyUUID,
)
from sqlalchemy.sql import func
from app.models.base import Base


class SlackConnection(Base):
    """
    Slack workspace integration for a tenant agent.

    A tenant connects a specific Agent to a Slack workspace (team).
    Once installed, the bot can be assigned to an active channel.
    Channel mapping ensures only one active agent is mapped per Slack channel.
    """
    __tablename__ = "slack_connections"

    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slack_team_id = Column(String(64), nullable=False, index=True)
    slack_team_name = Column(String(255), nullable=True)
    slack_channel_id = Column(String(64), nullable=True, index=True)
    slack_channel_name = Column(String(255), nullable=True)
    bot_user_id = Column(String(64), nullable=True)
    bot_access_token_encrypted = Column(Text, nullable=False)
    scopes = Column(Text, nullable=True)
    installed_by_user_id = Column(String(64), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        index=True,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        Index(
            "uq_slack_team_channel_active",
            "slack_team_id",
            "slack_channel_id",
            unique=True,
            postgresql_where=(
                (is_active == True) & (slack_channel_id != None)
            ),
        ),
        Index("ix_slack_connections_tenant_agent", "tenant_id", "agent_id"),
    )


class SlackEvent(Base):
    """
    Records processed Slack webhook events for distributed deduplication.
    Prevents duplicate processing on Slack webhook retries.
    """
    __tablename__ = "slack_events"

    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    event_id = Column(String(128), nullable=False, unique=True, index=True)
    slack_team_id = Column(String(64), nullable=False, index=True)
    channel_id = Column(String(64), nullable=True, index=True)
    event_type = Column(String(64), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        index=True,
    )
