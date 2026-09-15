"""FastAPI REST routes for Slack Multi-Tenant Integration."""

import logging
import json
from uuid import UUID
from typing import Optional

from fastapi import (
    APIRouter,
    Request,
    Response,
    HTTPException,
    status,
    BackgroundTasks,
    Query,
    Body,
)
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse

from app.core.database import AsyncSessionLocal
from app.core.config import get_settings
from app.utils.formatters import format_success, format_error
from .service import SlackService
from .security import verify_slack_signature
from .events import clean_slack_text, is_bot_event
from .worker import process_slack_event_task
from .schemas import (
    SlackConnectResponse,
    SlackChannelInfo,
    SlackSetChannelRequest,
    SlackConnectionResponse,
    SlackDisconnectRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/slack", tags=["Slack Integration"])


def _get_tenant_id(request: Request) -> str:
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tenant context required",
        )
    return str(tenant_id)


@router.get("/connect", response_model=SlackConnectResponse)
async def connect_slack(
    request: Request,
    agent_id: str = Query(..., description="Agent UUID to connect to Slack"),
    redirect_uri: Optional[str] = Query(None, description="Optional custom OAuth redirect URI"),
):
    """
    Generate Slack OAuth authorization URL.
    Cryptographically binds tenant_id and agent_id in a signed JWT state.
    Requires Tenant JWT authentication.
    """
    tenant_id = _get_tenant_id(request)
    async with AsyncSessionLocal() as db:
        service = SlackService(db, tenant_id)
        return await service.get_authorization_url(agent_id=agent_id, redirect_uri=redirect_uri)


@router.get("/callback")
async def slack_oauth_callback(
    code: str = Query(..., description="Temporary OAuth code from Slack"),
    state: str = Query(..., description="Signed JWT state parameter"),
):
    """
    Handle OAuth callback redirect from Slack.
    Exchanges code for encrypted bot token, persists connection, and redirects to frontend dashboard.
    Public endpoint (state is cryptographically validated via HMAC-SHA256).
    """
    settings = get_settings()
    frontend_url = (getattr(settings, "FRONTEND_URL", None) or "http://localhost:3000").rstrip("/")

    async with AsyncSessionLocal() as db:
        service = SlackService(db)
        try:
            conn = await service.handle_oauth_callback(code, state)
            redirect_url = f"{frontend_url}/dashboard/integrations?slack=connected&agent_id={conn.agent_id}"
            logger.info("Slack OAuth successful for team %s; redirecting to %s", conn.slack_team_name or conn.slack_team_id, redirect_url)
            return RedirectResponse(url=redirect_url, status_code=302)
        except Exception as e:
            logger.error("Slack OAuth callback failed: %s", e)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to complete Slack OAuth: {str(e)}",
            )


@router.get("/channels", response_model=list[SlackChannelInfo])
async def list_slack_channels(
    request: Request,
    agent_id: str = Query(..., description="Agent UUID"),
):
    """
    List channels available in the connected Slack workspace.
    Requires Tenant JWT authentication.
    """
    tenant_id = _get_tenant_id(request)
    async with AsyncSessionLocal() as db:
        service = SlackService(db, tenant_id)
        return await service.list_channels_for_agent(agent_id)


@router.post("/set-channel", response_model=SlackConnectionResponse)
async def set_slack_channel(
    request: Request,
    body: SlackSetChannelRequest,
):
    """
    Assign an active agent to a specific Slack channel.
    Enforces one active agent per Slack channel in a workspace.
    Requires Tenant JWT authentication.
    """
    tenant_id = _get_tenant_id(request)
    async with AsyncSessionLocal() as db:
        service = SlackService(db, tenant_id)
        conn = await service.set_active_channel(
            agent_id=str(body.agent_id),
            channel_id=body.channel_id,
            slack_team_id=body.slack_team_id,
            channel_name=body.channel_name,
        )
        return conn


@router.api_route("/disconnect", methods=["POST", "DELETE"])
async def disconnect_slack(
    request: Request,
    agent_id: Optional[UUID] = Query(None, description="Agent UUID to disconnect"),
    slack_team_id: Optional[str] = Query(None, description="Optional Slack team ID"),
    body: Optional[SlackDisconnectRequest] = Body(None),
):
    """
    Disconnect Slack workspace from an agent and revoke tokens.
    Supports both POST (JSON body) and DELETE (query params or body).
    Requires Tenant JWT authentication.
    """
    tenant_id = _get_tenant_id(request)

    resolved_agent_id = None
    resolved_team_id = slack_team_id

    if body and body.agent_id:
        resolved_agent_id = str(body.agent_id)
        if body.slack_team_id:
            resolved_team_id = body.slack_team_id
    elif agent_id:
        resolved_agent_id = str(agent_id)

    if not resolved_agent_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="agent_id is required either as query parameter or request body",
        )

    async with AsyncSessionLocal() as db:
        service = SlackService(db, tenant_id)
        success = await service.disconnect(
            agent_id=resolved_agent_id,
            slack_team_id=resolved_team_id,
        )
        return {"status": "disconnected", "success": success}


@router.post("/events")
async def slack_events_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Slack Event Webhook endpoint.
    Handles:
    - URL verification handshake (`url_verification`)
    - Event callbacks (`app_mention`, `message`)
    - HMAC-SHA256 signature verification & 300s replay window
    - Distributed DB event deduplication via `slack_events`
    - Channel-to-Agent routing and fast background worker dispatch (< 3s HTTP 200 response)
    """
    raw_body = await request.body()
    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    signature = request.headers.get("X-Slack-Signature")

    settings = get_settings()
    signing_secret = getattr(settings, "slack_signing_secret", None)

    # 1. Verify Signature
    if not verify_slack_signature(raw_body, timestamp, signature, signing_secret):
        logger.warning("Rejected Slack event: Invalid signature or timestamp drift")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": "Invalid signature or timestamp"},
        )

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as e:
        logger.error("Failed to parse Slack event JSON body: %s", e)
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Invalid JSON"},
        )

    # 2. Handle Slack URL Verification Handshake
    if payload.get("type") == "url_verification":
        logger.info("Responding to Slack url_verification challenge")
        return {"challenge": payload.get("challenge")}

    # 3. Handle Event Callback
    if payload.get("type") == "event_callback":
        event_id = payload.get("event_id")
        team_id = payload.get("team_id")
        event = payload.get("event", {})

        if not event_id or not team_id or not event:
            return {"status": "ignored_missing_data"}

        event_type = event.get("type")
        channel_id = event.get("channel")
        thread_ts = event.get("thread_ts")
        message_ts = event.get("ts")
        user_id = event.get("user")

        async with AsyncSessionLocal() as db:
            service = SlackService(db)

            # Check if this event was already processed (Distributed Deduplication)
            is_new = await service.record_event_dedup(
                event_id=event_id,
                slack_team_id=team_id,
                channel_id=channel_id,
                event_type=event_type or "unknown",
            )
            if not is_new:
                return {"status": "ignored_duplicate"}

            # Check bot events early without needing DB lookup
            if is_bot_event(event):
                return {"status": "ignored_bot_event"}

            # Resolve mapped connection
            conn = await service.get_connection_for_event(team_id, channel_id)
            if not conn or not conn.is_active:
                logger.info("No active agent mapped for Slack team %s, channel %s", team_id, channel_id)
                return {"status": "no_active_agent_mapped"}

            # Ignore bot messages matching this bot's user ID to prevent recursive loops
            if is_bot_event(event, bot_user_id=conn.bot_user_id):
                return {"status": "ignored_bot_event"}

            # Prevent double-triggering: If Slack sent both `message` and `app_mention` for a mention,
            # ignore the `message` event and let `app_mention` handle it.
            bot_user_id = conn.bot_user_id
            raw_text = event.get("text", "")
            channel_type = event.get("channel_type")
            is_im = channel_type == "im" or (channel_id and channel_id.startswith("D"))

            if event_type == "message":
                if not is_im:
                    # In channels/groups, ignore message events containing bot mention (app_mention handles them)
                    if bot_user_id and (f"<@{bot_user_id}>" in raw_text or bot_user_id in raw_text):
                        logger.info("Ignoring duplicate 'message' event with bot mention (handled by app_mention)")
                        return {"status": "ignored_duplicate_mention"}
                    # In channels/groups, ignore messages where the bot is NOT mentioned (only respond in DMs or on mention)
                    logger.debug("Ignoring unmentioned channel message")
                    return {"status": "ignored_unmentioned_channel_message"}

            clean_query = clean_slack_text(event.get("text", ""))
            if not clean_query:
                return {"status": "ignored_empty_text"}

            # Dispatch processing asynchronously in background to return HTTP 200 within 3 seconds
            background_tasks.add_task(
                process_slack_event_task,
                tenant_id=str(conn.tenant_id),
                agent_id=str(conn.agent_id),
                channel_id=channel_id,
                query=clean_query,
                team_id=team_id,
                thread_ts=thread_ts,
                message_ts=message_ts,
                user_id=user_id,
            )

            return {"status": "queued"}

    return {"status": "ignored_unknown_type"}
