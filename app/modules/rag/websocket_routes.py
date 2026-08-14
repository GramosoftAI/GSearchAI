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
    print("----------------------------------rag websocket called",token,"----------------------------------------------------------------------")
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

        chat_service = ChatService(db=db, tenant_id=tenant_id)

        try:
            from .adapters import DashboardAdapter
            from .websocket_core import run_unified_rag_websocket_loop

            await run_unified_rag_websocket_loop(
                websocket=websocket,
                db=db,
                agent_id=agent_id,
                tenant_id=tenant_id,
                user_id=user_id,
                kb_ids=kb_ids,
                adapter=DashboardAdapter(),
                chat_service=chat_service,
                rag_service=rag_service,
            )

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
