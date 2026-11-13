"""Pydantic schemas for Slack Integration endpoints."""

from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class SlackConnectResponse(BaseModel):
    """OAuth URL response to initiate Slack app installation."""
    authorization_url: str
    state: str


class SlackChannelInfo(BaseModel):
    """Information about a Slack channel available to the bot."""
    id: str
    name: str
    is_private: bool = False
    is_member: bool = False


class SlackSetChannelRequest(BaseModel):
    """Request to assign an agent to a specific Slack channel."""
    agent_id: UUID
    channel_id: str
    slack_team_id: Optional[str] = None
    channel_name: Optional[str] = None


class SlackConnectionResponse(BaseModel):
    """Details of an active Slack workspace connection."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    agent_id: UUID
    slack_team_id: str
    slack_team_name: Optional[str] = None
    slack_channel_id: Optional[str] = None
    slack_channel_name: Optional[str] = None
    bot_user_id: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SlackDisconnectRequest(BaseModel):
    """Request to disconnect a Slack workspace from an agent."""
    agent_id: UUID
    slack_team_id: Optional[str] = None
