"""Asynchronous Slack Web API Client.

Handles:
- OAuth v2 access token exchange
- Channel listing with pagination
- Joining public channels
- Posting and updating messages (including thread support)
- Token revocation on disconnect
- Strict error checking on response `ok` flag
"""

import logging
from typing import Optional, List, Dict, Any
import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SLACK_API_BASE = "https://slack.com/api"


class SlackClient:
    """Async client for Slack Web API operations."""

    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    async def exchange_oauth_code(
        self,
        code: str,
        redirect_uri: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Exchange a temporary OAuth authorization code for a bot access token.
        POST https://slack.com/api/oauth.v2.access
        """
        settings = get_settings()
        c_id = client_id or getattr(settings, "slack_client_id", None)
        c_sec = client_secret or getattr(settings, "slack_client_secret", None)
        r_uri = redirect_uri or getattr(settings, "slack_redirect_uri", None)

        if not c_id or not c_sec:
            raise ValueError("Slack client_id or client_secret is not configured")

        data = {
            "client_id": c_id,
            "client_secret": c_sec,
            "code": code,
        }
        if r_uri:
            data["redirect_uri"] = r_uri

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(f"{SLACK_API_BASE}/oauth.v2.access", data=data)
            resp_data = resp.json()

            if not resp_data.get("ok"):
                error_msg = resp_data.get("error", "unknown_oauth_error")
                logger.error("Slack OAuth exchange failed: %s", error_msg)
                raise ValueError(f"Slack OAuth exchange failed: {error_msg}")

            team_info = resp_data.get("team", {})
            authed_user = resp_data.get("authed_user", {})

            return {
                "access_token": resp_data.get("access_token"),
                "token_type": resp_data.get("token_type"),
                "scope": resp_data.get("scope"),
                "bot_user_id": resp_data.get("bot_user_id"),
                "team_id": team_info.get("id"),
                "team_name": team_info.get("name"),
                "installed_by_user_id": authed_user.get("id"),
            }

    async def list_channels(
        self,
        bot_token: str,
        types: str = "public_channel,private_channel",
        max_channels: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        List conversations/channels in the workspace with pagination support.
        GET https://slack.com/api/conversations.list
        """
        headers = {"Authorization": f"Bearer {bot_token}"}
        channels: List[Dict[str, Any]] = []
        cursor = None

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            while len(channels) < max_channels:
                params: Dict[str, Any] = {
                    "types": types,
                    "exclude_archived": "true",
                    "limit": 100,
                }
                if cursor:
                    params["cursor"] = cursor

                resp = await client.get(
                    f"{SLACK_API_BASE}/conversations.list",
                    headers=headers,
                    params=params,
                )
                data = resp.json()

                if not data.get("ok"):
                    error_msg = data.get("error", "conversations_list_error")
                    logger.error("Failed to list Slack channels: %s", error_msg)
                    raise ValueError(f"Slack API error: {error_msg}")

                for ch in data.get("channels", []):
                    channels.append({
                        "id": ch.get("id"),
                        "name": ch.get("name"),
                        "is_private": ch.get("is_private", False),
                        "is_member": ch.get("is_member", False),
                    })

                cursor = data.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break

        return channels

    async def join_channel(self, bot_token: str, channel_id: str) -> bool:
        """
        Join a public channel.
        POST https://slack.com/api/conversations.join
        """
        headers = {"Authorization": f"Bearer {bot_token}"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{SLACK_API_BASE}/conversations.join",
                headers=headers,
                json={"channel": channel_id},
            )
            data = resp.json()
            if not data.get("ok"):
                err = data.get("error")
                # Already in channel or cannot join private channel is acceptable
                if err in ("already_in_channel", "method_not_supported_for_channel_type"):
                    return True
                logger.warning("Slack join channel %s returned error: %s", channel_id, err)
                return False
            return True

    async def post_message(
        self,
        bot_token: str,
        channel: str,
        text: str,
        thread_ts: Optional[str] = None,
        blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Post a message to a channel or thread.
        POST https://slack.com/api/chat.postMessage
        """
        headers = {"Authorization": f"Bearer {bot_token}"}
        payload: Dict[str, Any] = {
            "channel": channel,
            "text": text,
        }
        if thread_ts:
            payload["thread_ts"] = thread_ts
        if blocks:
            payload["blocks"] = blocks

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{SLACK_API_BASE}/chat.postMessage",
                headers=headers,
                json=payload,
            )
            data = resp.json()
            if not data.get("ok"):
                error_msg = data.get("error", "chat_postMessage_error")
                logger.error("Slack chat.postMessage failed: %s", error_msg)
                raise ValueError(f"Slack postMessage failed: {error_msg}")
            return data

    async def update_message(
        self,
        bot_token: str,
        channel: str,
        ts: str,
        text: str,
        blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Update an existing message.
        POST https://slack.com/api/chat.update
        """
        headers = {"Authorization": f"Bearer {bot_token}"}
        payload: Dict[str, Any] = {
            "channel": channel,
            "ts": ts,
            "text": text,
        }
        if blocks:
            payload["blocks"] = blocks

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{SLACK_API_BASE}/chat.update",
                headers=headers,
                json=payload,
            )
            data = resp.json()
            if not data.get("ok"):
                error_msg = data.get("error", "chat_update_error")
                logger.error("Slack chat.update failed: %s", error_msg)
                raise ValueError(f"Slack updateMessage failed: {error_msg}")
            return data

    async def revoke_token(self, bot_token: str) -> bool:
        """
        Revoke an OAuth token on disconnect.
        POST https://slack.com/api/auth.revoke
        """
        headers = {"Authorization": f"Bearer {bot_token}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{SLACK_API_BASE}/auth.revoke", headers=headers)
                data = resp.json()
                return bool(data.get("ok"))
        except Exception as e:
            logger.warning("Failed to revoke Slack token: %s", e)
            return False
