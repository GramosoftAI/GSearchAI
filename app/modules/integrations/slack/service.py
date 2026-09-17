
"""Slack Integration Service - Core business logic for OAuth, channels, deduplication, and connection management."""

import logging
from typing import Optional, List, Dict, Any
from uuid import UUID
from urllib.parse import urlencode

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from app.core.config import get_settings
from app.modules.agents.repository import AgentRepository
from .models import SlackConnection, SlackEvent
from .client import SlackClient
from .security import (
    encrypt_token,
    decrypt_token,
    create_oauth_state,
    verify_oauth_state,
)
from .schemas import (
    SlackConnectResponse,
    SlackChannelInfo,
    SlackConnectionResponse,
)

logger = logging.getLogger(__name__)

# Standard OAuth Scopes required for bot operation
SLACK_BOT_SCOPES = [
    "app_mentions:read",
    "channels:history",
    "channels:read",
    "channels:join",
    "chat:write",
    "groups:history",
    "groups:read",
    "im:history",
    "im:read",
    "mpim:history",
    "mpim:read",
]


class SlackService:
    """Service managing Slack connections, channels, and event lifecycle."""

    def __init__(self, db: AsyncSession, tenant_id: Optional[str] = None):
        self.db = db
        self.tenant_id = tenant_id
        self.client = SlackClient()

    async def get_authorization_url(
        self,
        agent_id: str,
        redirect_uri: Optional[str] = None,
    ) -> SlackConnectResponse:
        """
        Generate Slack OAuth v2 authorization URL with signed JWT state.
        Validates agent ownership under current tenant.
        """
        if not self.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tenant context required",
            )

        agent_repo = AgentRepository(self.db, self.tenant_id)
        agent = await agent_repo.get_by_id(agent_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found",
            )

        settings = get_settings()
        client_id = getattr(settings, "slack_client_id", None)
        if not client_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Slack client_id is not configured",
            )

        target_redirect = redirect_uri or getattr(settings, "slack_redirect_uri", None)
        state = create_oauth_state(
            tenant_id=self.tenant_id,
            agent_id=agent_id,
            redirect_uri=target_redirect,
        )

        params = {
            "client_id": client_id,
            "scope": ",".join(SLACK_BOT_SCOPES),
            "state": state,
        }
        if target_redirect:
            params["redirect_uri"] = target_redirect

        auth_url = f"https://slack.com/oauth/v2/authorize?{urlencode(params)}"
        return SlackConnectResponse(authorization_url=auth_url, state=state)

    async def handle_oauth_callback(
        self,
        code: str,
        state: str,
    ) -> SlackConnection:
        """
        Exchange code for bot access token, encrypt token, and persist SlackConnection.
        Binds to tenant_id and agent_id verified from signed JWT state.
        """
        payload = verify_oauth_state(state)
        tenant_id = UUID(payload["tenant_id"])
        agent_id = UUID(payload["agent_id"])
        redirect_uri = payload.get("redirect_uri")

        # Exchange OAuth code
        oauth_data = await self.client.exchange_oauth_code(code, redirect_uri=redirect_uri)

        raw_token = oauth_data["access_token"]
        encrypted_token = encrypt_token(raw_token)
        team_id = oauth_data["team_id"]
        team_name = oauth_data.get("team_name")
        bot_user_id = oauth_data.get("bot_user_id")
        scopes = oauth_data.get("scope")
        installed_by = oauth_data.get("installed_by_user_id")

        # Look for existing connection
        stmt = select(SlackConnection).where(
            and_(
                SlackConnection.tenant_id == tenant_id,
                SlackConnection.agent_id == agent_id,
                SlackConnection.slack_team_id == team_id,
            )
        )
        res = await self.db.execute(stmt)
        conn = res.scalars().first()

        if conn:
            conn.bot_access_token_encrypted = encrypted_token
            conn.slack_team_name = team_name
            conn.bot_user_id = bot_user_id
            conn.scopes = scopes
            conn.installed_by_user_id = installed_by
            conn.is_active = True
        else:
            conn = SlackConnection(
                tenant_id=tenant_id,
                agent_id=agent_id,
                slack_team_id=team_id,
                slack_team_name=team_name,
                bot_user_id=bot_user_id,
                bot_access_token_encrypted=encrypted_token,
                scopes=scopes,
                installed_by_user_id=installed_by,
                is_active=True,
            )
            self.db.add(conn)

        await self.db.commit()
        await self.db.refresh(conn)
        logger.info("Successfully connected Slack team %s for agent %s (tenant %s)", team_id, agent_id, tenant_id)
        return conn

    async def get_connection_for_agent(self, agent_id: str) -> Optional[SlackConnection]:
        """Fetch the active SlackConnection for an agent."""
        if not self.tenant_id:
            return None
        stmt = select(SlackConnection).where(
            and_(
                SlackConnection.tenant_id == UUID(self.tenant_id),
                SlackConnection.agent_id == UUID(agent_id),
                SlackConnection.is_active == True,
            )
        )
        res = await self.db.execute(stmt)
        return res.scalars().first()

    async def list_channels_for_agent(self, agent_id: str) -> List[SlackChannelInfo]:
        """List channels available in the Slack workspace connected to an agent."""
        conn = await self.get_connection_for_agent(agent_id)
        if not conn:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No active Slack connection found for agent {agent_id}",
            )

        bot_token = decrypt_token(conn.bot_access_token_encrypted)
        channels_raw = await self.client.list_channels(bot_token)
        return [
            SlackChannelInfo(
                id=c["id"],
                name=c["name"],
                is_private=c["is_private"],
                is_member=c["is_member"],
            )
            for c in channels_raw
        ]

    async def set_active_channel(
        self,
        agent_id: str,
        channel_id: str,
        slack_team_id: Optional[str] = None,
        channel_name: Optional[str] = None,
    ) -> SlackConnection:
        """
        Map an agent to a specific Slack channel.
        Enforces one active agent per Slack channel in a team.
        """
        if not self.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tenant context required",
            )

        # 1. Fetch connection
        conditions = [
            SlackConnection.tenant_id == UUID(self.tenant_id),
            SlackConnection.agent_id == UUID(agent_id),
            SlackConnection.is_active == True,
        ]
        if slack_team_id:
            conditions.append(SlackConnection.slack_team_id == slack_team_id)

        stmt = select(SlackConnection).where(and_(*conditions))
        res = await self.db.execute(stmt)
        conn = res.scalars().first()
        if not conn:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active Slack connection found for this agent",
            )

        resolved_team_id = conn.slack_team_id

        # 2. Check if another active connection is already using this channel
        conflict_stmt = select(SlackConnection).where(
            and_(
                SlackConnection.slack_team_id == resolved_team_id,
                SlackConnection.slack_channel_id == channel_id,
                SlackConnection.is_active == True,
                SlackConnection.id != conn.id,
            )
        )
        conflict_res = await self.db.execute(conflict_stmt)
        if conflict_res.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Slack channel {channel_id} is already mapped to another active agent",
            )

        # 3. Join the channel with bot token
        bot_token = decrypt_token(conn.bot_access_token_encrypted)
        await self.client.join_channel(bot_token, channel_id)

        # 4. Update connection
        conn.slack_channel_id = channel_id
        if channel_name:
            conn.slack_channel_name = channel_name

        await self.db.commit()
        await self.db.refresh(conn)
        return conn

    async def disconnect(
        self,
        agent_id: str,
        slack_team_id: Optional[str] = None,
    ) -> bool:
        """Disconnect Slack workspace, revoke bot token, and mark connection inactive."""
        if not self.tenant_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Tenant context required",
            )

        conditions = [
            SlackConnection.tenant_id == UUID(self.tenant_id),
            SlackConnection.agent_id == UUID(agent_id),
            SlackConnection.is_active == True,
        ]
        if slack_team_id:
            conditions.append(SlackConnection.slack_team_id == slack_team_id)

        stmt = select(SlackConnection).where(and_(*conditions))
        res = await self.db.execute(stmt)
        connections = res.scalars().all()

        if not connections:
            return False

        for conn in connections:
            try:
                bot_token = decrypt_token(conn.bot_access_token_encrypted)
                await self.client.revoke_token(bot_token)
            except Exception as e:
                logger.warning("Revoking Slack token during disconnect failed: %s", e)

            conn.is_active = False
            conn.slack_channel_id = None

        await self.db.commit()
        return True

    async def record_event_dedup(
        self,
        event_id: str,
        slack_team_id: str,
        channel_id: Optional[str],
        event_type: str,
        tenant_id: Optional[UUID] = None,
    ) -> bool:
        """
        Record Slack event ID for distributed deduplication.
        Returns True if event is new and recorded.
        Returns False if event was already processed (duplicate).
        """
        ev = SlackEvent(
            event_id=event_id,
            slack_team_id=slack_team_id,
            channel_id=channel_id,
            event_type=event_type,
            tenant_id=tenant_id,
        )
        self.db.add(ev)
        try:
            await self.db.commit()
            return True
        except IntegrityError:
            await self.db.rollback()
            logger.info("Deduplicated repeated Slack event %s (team %s)", event_id, slack_team_id)
            return False

    async def get_connection_for_event(
        self,
        slack_team_id: str,
        channel_id: Optional[str] = None,
    ) -> Optional[SlackConnection]:
        """
        Lookup the active SlackConnection matching an incoming webhook event.
        - Exact channel mapping: If channel matches slack_channel_id, returns that agent.
        - Direct Messages (DMs, starts with 'D'): Falls back to the team's active connection.
        - Unassigned connection: If an agent has no channel configured yet (slack_channel_id is None), it can respond.
        - Strict isolation: If an agent has a specific channel configured, it will NOT respond in other channels.
        """
        if channel_id:
            # 1. Exact channel match
            stmt = select(SlackConnection).where(
                and_(
                    SlackConnection.slack_team_id == slack_team_id,
                    SlackConnection.slack_channel_id == channel_id,
                    SlackConnection.is_active == True,
                )
            )
            res = await self.db.execute(stmt)
            conn = res.scalars().first()
            if conn:
                return conn

        # 2. Direct Messages (DMs) fallback
        is_dm = bool(channel_id and channel_id.startswith("D"))
        if is_dm or not channel_id:
            stmt_fallback = select(SlackConnection).where(
                and_(
                    SlackConnection.slack_team_id == slack_team_id,
                    SlackConnection.is_active == True,
                )
            )
            res = await self.db.execute(stmt_fallback)
            return res.scalars().first()

        # 3. Channel fallback only for connections without an assigned channel (slack_channel_id is None)
        stmt_unassigned = select(SlackConnection).where(
            and_(
                SlackConnection.slack_team_id == slack_team_id,
                SlackConnection.slack_channel_id == None,
                SlackConnection.is_active == True,
            )
        )
        res = await self.db.execute(stmt_unassigned)
        return res.scalars().first()
