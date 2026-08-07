"""
WebSocket RAG routes - Streaming chat interface for GraphRAG
Phase 3: Real-time Conversational Retrieval + Long-term Episodic Memory
# Triggering uvicorn reload third time
"""

import os
import logging
import json
import sys
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status

import httpx

logger = logging.getLogger(__name__)
logger.info(f"DEBUG: sys.path is: {sys.path}")

from .service import RAGService
from ..knowledge_bases.repository import KnowledgeBaseRepository
from ...core.database import get_db_with_tenant
from ...core.security import verify_access_token

router = APIRouter(prefix="/ws", tags=["WebSocket RAG"])


def resolve_memory_api_base_url() -> str:
    """Resolve the memory API base URL for local dev, containers, and tests."""
    configured = os.getenv("MEMORY_API_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")

    env_host = os.getenv("MEMORY_API_HOST", "").strip()
    if env_host:
        return env_host.rstrip("/")

    return "http://127.0.0.1:8001"


async def call_memory_api(endpoint: str, json_data: dict, method: str = "POST", timeout: float = 5.0):
    MEMORY_API_URL = resolve_memory_api_base_url()
    candidate_urls = [
        f"{MEMORY_API_URL.rstrip('/')}{endpoint}",
        f"http://localhost:4917/api/v1/memory{endpoint}",
        f"http://127.0.0.1:4917/api/v1/memory{endpoint}",
        f"http://localhost:8002/api/v1/memory{endpoint}",
        f"http://memory-api:8001/api/v1/memory{endpoint}"
    ]


    urls = list(dict.fromkeys(candidate_urls))
    
    async with httpx.AsyncClient() as client:
        for url in urls:
            try:
                resp = await client.request(method, url, json=json_data, timeout=timeout)
                if resp.status_code == 200:
                    return resp
                logger.warning(f"Memory API {url} returned status {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.debug(f"Memory API {url} unreachable: {e}")
    return None

@router.websocket("/{agent_id}")
async def rag_websocket(
    websocket: WebSocket,
    agent_id: str,
    token: Optional[str] = Query(None),
):
    """
    WebSocket endpoint for real-time RAG chat with standalone memory API integration.
    """

    # 1. ACCEPT HANDSHAKE IMMEDIATELY
    await websocket.accept()

    # 2. VALIDATE TOKEN PRESENCE
    if not token or token in ("null", "undefined"):
        logger.warning(
            f"Rejected WS for agent={agent_id}: missing/invalid token param ('{token}')"
        )
        await websocket.send_text(
            json.dumps({"type": "error", "message": "Missing or invalid auth token"})
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 3. AUTHENTICATION
    try:
        payload = await verify_access_token(token)
        if not payload:
            raise ValueError("Token verification returned no payload")
        tenant_id = payload.tenant_id
        user_id = payload.user_id
    except Exception as auth_err:
        logger.warning(f"WebSocket auth failed for agent={agent_id}: {auth_err}")
        await websocket.send_text(
            json.dumps(
                {"type": "error", "message": "Unauthorized: invalid or expired token"}
            )
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    logger.info(
        f"WebSocket connected: Agent={agent_id}, Tenant={tenant_id}, User={user_id}"
    )

    # 4. INITIALIZE SERVICES
    async with get_db_with_tenant(tenant_id) as db:
        rag_service = RAGService(db=db, tenant_id=tenant_id)
        kb_repo = KnowledgeBaseRepository(db, tenant_id)

        try:
            kbs, _ = await kb_repo.list_by_agent(agent_id, limit=10)
            if not kbs:
                await websocket.send_text(json.dumps({"type": "error", "message": "Knowledge Base not found"}))
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected before initialization completed: Agent={agent_id}")
            return

        kb_ids = [str(kb.id) for kb in kbs]
        logger.info(f"Session ready: Agent={agent_id}, KBs={len(kb_ids)}")

        from ..chats.service import ChatService
        from ...core.query_rewriter import QueryRewriter

        chat_service = ChatService(db=db, tenant_id=tenant_id)
        query_rewriter = QueryRewriter()

        try:
            while True:
                # 5. WAIT FOR MESSAGE
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    query = msg.get("query", "").strip() if msg.get("query") else ""
                    session_id = msg.get("session_id")
                    enhance_prompt = msg.get("prompt_enhancer", False) or msg.get(
                        "enhance_prompt", False
                    )
                except json.JSONDecodeError:
                    await websocket.send_text(
                        json.dumps({"type": "error", "message": "Invalid JSON format"})
                    )
                    continue

                if not query:
                    continue

                # 6. RESOLVE OR CREATE CHAT SESSION
                session = None
                if session_id:
                    session = await chat_service.chat_repo.get_session_by_id(session_id)
                    if not session:
                        logger.warning(
                            f"Session {session_id} not found in WS, creating new"
                        )

                if session is None:
                    session = await chat_service.chat_repo.create_session(
                        agent_id=agent_id, user_id=user_id
                    )

                active_session_id = str(session.id)

                # ============================================================
                # DELEGATE TO CHAT PIPELINE
                # ============================================================
                from .stream.response_chunk import ChunkType
                from .chat_pipeline import ChatPipeline
                chat_pipeline = ChatPipeline(db=db, tenant_id=tenant_id)
                
                async for chunk in chat_pipeline.stream_response(
                    query=query,
                    session_id=active_session_id,
                    agent_id=agent_id,
                    user_id=user_id,
                    kb_ids=kb_ids,
                    enhance_prompt=enhance_prompt
                ):
                    try:
                        if chunk.type == ChunkType.CONTENT:
                            await websocket.send_text(chunk.text)
                        elif chunk.type == ChunkType.METADATA:
                            meta_payload = chunk.data.model_dump()
                            meta_payload["type"] = "metadata"
                            await websocket.send_text(json.dumps(meta_payload))
                        elif chunk.type == ChunkType.ERROR:
                            # The original route sometimes sent raw text for errors and sometimes JSON. 
                            # We send JSON here, or raw text if preferred, but JSON is safer.
                            await websocket.send_text(json.dumps({"type": "error", "message": chunk.text}))
                        elif chunk.type == ChunkType.STATUS:
                            await websocket.send_text(json.dumps({"type": "status", "message": chunk.text}))
                        elif chunk.type == ChunkType.DONE:
                            await websocket.send_text(json.dumps({"type": "done"}))
                    except Exception as ws_err:
                        logger.error(f"Failed to send chunk to websocket: {ws_err}")
                        break

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected: Agent={agent_id}")
        except Exception as e:
            logger.error(f"WebSocket session error: {e}", exc_info=True)
            try:
                await websocket.send_text(
                    json.dumps(
                        {"type": "error", "message": f"Session interrupted: {str(e)}"}
                    )
                )
            except Exception:
                pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass
            if db:
                await db.close()
