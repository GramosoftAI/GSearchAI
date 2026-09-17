"""Background worker tasks for asynchronous Slack event processing."""

import logging
from typing import Optional, Dict, Any
from uuid import UUID
from sqlalchemy import select, and_

from app.core.database import AsyncSessionLocal
from app.modules.rag.service import execute_rag
from .client import SlackClient
from .security import decrypt_token
from .events import generate_slack_session_id, generate_slack_user_id, format_slack_response
from .models import SlackConnection

logger = logging.getLogger(__name__)


async def process_slack_event_task(
    tenant_id: str,
    agent_id: str,
    channel_id: str,
    query: str,
    team_id: str,
    thread_ts: Optional[str] = None,
    message_ts: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """
    Executes RAG pipeline for a Slack message and responds in the channel or thread.
    Can be run via FastAPI BackgroundTasks or ARQ worker.
    """
    logger.info("Processing Slack event for agent %s in channel %s (thread_ts=%s)", agent_id, channel_id, thread_ts)
    client = SlackClient()

    async with AsyncSessionLocal() as db:
        # 1. Fetch connection to obtain encrypted bot token
        stmt = select(SlackConnection).where(
            and_(
                SlackConnection.tenant_id == UUID(str(tenant_id)),
                SlackConnection.agent_id == UUID(str(agent_id)),
                SlackConnection.slack_team_id == team_id,
                SlackConnection.is_active == True,
            )
        )
        res = await db.execute(stmt)
        conn = res.scalars().first()
        if not conn:
            logger.error("No active Slack connection found for agent %s and team %s", agent_id, team_id)
            return

        bot_token = decrypt_token(conn.bot_access_token_encrypted)
        session_id = generate_slack_session_id(
            team_id=team_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            message_ts=message_ts,
        )
        valid_user_id = generate_slack_user_id(user_id)

        # 2. Execute RAG
        try:
            rag_result = await execute_rag(
                db=db,
                tenant_id=str(tenant_id),
                agent_id=str(agent_id),
                query=query,
                session_id=session_id,
                user_id=valid_user_id,
                source="slack",
                enable_memory=True,
            )

            answer = rag_result.get("answer", "")
            sources = rag_result.get("sources", [])
            formatted_text = format_slack_response(answer, sources)

            # If message was in a thread, reply in thread. If top-level, post directly to channel.
            target_thread = thread_ts

            await client.post_message(
                bot_token=bot_token,
                channel=channel_id,
                text=formatted_text,
                thread_ts=target_thread,
            )
            logger.info("Successfully posted Slack response to channel %s", channel_id)

        except Exception as e:
            logger.exception("Failed to execute RAG or post response to Slack: %s", e)
            try:
                target_thread = thread_ts
                await client.post_message(
                    bot_token=bot_token,
                    channel=channel_id,
                    text="I encountered an error while processing your request. Please try again later.",
                    thread_ts=target_thread,
                )
            except Exception as post_err:
                logger.error("Failed to post error message to Slack: %s", post_err)


async def slack_event_job(
    ctx: Dict[Any, Any],
    tenant_id: str,
    agent_id: str,
    channel_id: str,
    query: str,
    team_id: str,
    thread_ts: Optional[str] = None,
    message_ts: Optional[str] = None,
    user_id: Optional[str] = None,
) -> None:
    """ARQ Worker Job entrypoint."""
    await process_slack_event_task(
        tenant_id=tenant_id,
        agent_id=agent_id,
        channel_id=channel_id,
        query=query,
        team_id=team_id,
        thread_ts=thread_ts,
        message_ts=message_ts,
        user_id=user_id,
    )
