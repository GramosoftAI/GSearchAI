import json
import logging
import httpx
import os
import time
from uuid import UUID
from fastapi import WebSocket, WebSocketDisconnect
from .schemas import UnifiedChatRequest
from .events import LoopEvent
from .adapters import ChannelAdapter
from .escalation import detect_escalation_intent

logger = logging.getLogger(__name__)

def resolve_memory_api_base_url() -> str:
    configured = os.getenv("MEMORY_API_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    env_host = os.getenv("MEMORY_API_HOST", "").strip()
    if env_host:
        return env_host.rstrip("/")
    return "http://127.0.0.1:4917"

async def _persist_partial(db, chat_service, session_id, user_id, query, response_buffer, reason: str) -> None:
    try:
        try:
            await db.rollback()
        except Exception:
            pass
        await chat_service.chat_repo.add_message(
            session_id=session_id,
            role="assistant",
            content="".join(response_buffer),
            metadata={
                "sources": [],
                "status": "partial_failure",
                "failure_reason": reason,
            },
        )
        await db.commit()
    except Exception as e:
        logger.error(f"Failed to persist partial response: {e}")

def _rag_chunk_to_loop_event(chunk: str) -> LoopEvent:
    # RAGService yields chunks. If it's a JSON string with type "metadata", it's sources.
    # Otherwise it's a content token.
    try:
        if chunk.startswith("{") and ("type" in chunk or "error" in chunk):
            parsed = json.loads(chunk)
            if parsed.get("type") == "metadata":
                return LoopEvent(type="sources", sources=parsed.get("sources", []), triplets=parsed.get("triplets", []))
            elif parsed.get("type") == "clarification_needed":
                return LoopEvent(type="clarification_needed", text=parsed.get("plain_text_fallback"), clarification=parsed)
            elif "error" in parsed:
                return LoopEvent(type="error", error_detail=parsed["error"])
    except (json.JSONDecodeError, TypeError):
        pass
    
    return LoopEvent(type="token", text=chunk)

async def run_unified_rag_websocket_loop(
    websocket: WebSocket,
    db,
    agent_id: str,
    tenant_id: str,
    user_id: str,
    kb_ids: list,
    adapter: ChannelAdapter,
    chat_service,
    rag_service,
    session_id: str = None,
    enable_memory: bool = True
) -> None:
    """
    Channel-agnostic execution core for WebSockets.
    """
    from .service import execute_rag

    channel = getattr(adapter, "channel", "websocket")
    active_session_id = session_id

    while True:
        try:
            raw_payload = await adapter.receive(websocket)
        except WebSocketDisconnect:
            return

        try:
            request = UnifiedChatRequest.from_raw(raw_payload)
        except ValueError as e:
            await adapter.send_error(websocket, str(e))
            continue

        if not active_session_id and request.session_id:
            active_session_id = request.session_id

        async def _forward_event(event: LoopEvent):
            await adapter.send(websocket, event)

        try:
            result = await execute_rag(
                db=db,
                tenant_id=tenant_id,
                agent_id=agent_id,
                query=request.query,
                session_id=active_session_id,
                user_id=user_id,
                source=channel,
                enable_memory=enable_memory,
                top_k=request.top_k,
                max_depth=request.max_depth,
                target_kb_id=request.target_kb_id,
                kb_ids=kb_ids,
                on_event=_forward_event,
            )
            active_session_id = result.get("session_id", active_session_id)
            await adapter.send(
                websocket,
                LoopEvent(
                    type="done",
                    escalation_detected=result.get("escalation_detected", False),
                ),
            )
        except WebSocketDisconnect:
            return
        except Exception as e:
            logger.exception("unified_rag_loop_failure", extra={"tenant_id": tenant_id, "agent_id": agent_id})
            try:
                await adapter.send_error(websocket, "internal_error")
            except Exception:
                pass
            try:
                await adapter.send(websocket, LoopEvent(type="done", escalation_detected=False))
            except Exception:
                pass

