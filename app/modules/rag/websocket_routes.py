"""
WebSocket RAG routes - Streaming chat interface for GraphRAG
Phase 3: Real-time Conversational Retrieval + Long-term Episodic Memory
"""

import os
import logging
import json
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status

import httpx

from .service import RAGService
from ..knowledge_bases.repository import KnowledgeBaseRepository
from ...core.database import get_db_with_tenant
from ...core.security import verify_access_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["WebSocket RAG"])

# Internal Docker hostname — NOT localhost. "memory-api" is the compose service
# name, resolved via the graphmind-network. Configurable via env for non-Docker
# environments (falls back to the value the main `api` service already gets
# from docker-compose.yml: MEMORY_API_BASE_URL=http://memory-api:8001).
MEMORY_API_BASE_URL = os.getenv("MEMORY_API_BASE_URL", "http://memory-api:8001").rstrip("/")
MEMORY_API_URL = f"{MEMORY_API_BASE_URL}/api/v1/memory"


@router.websocket("/{agent_id}")
async def rag_websocket(
    websocket: WebSocket,
    agent_id: str,
    token: Optional[str] = Query(None),
):
    """
    WebSocket endpoint for real-time RAG chat.

    SECURITY:
    1. Authenticates via token in query params (standard for WS)
    2. Enforces tenant isolation from JWT payload
    3. Validates agent ownership in every request

    PROTOCOL:
    - Client sends: {"query": "message"}
    - Server sends (metadata): {"type": "metadata", "sources": [...]}
    - Server sends (chunk): "text chunk"
    - Server sends (done): {"type": "done"}

    IMPORTANT: `accept()` is always called FIRST, before any validation.
    Closing a websocket before it has been accepted causes the ASGI server
    (uvicorn) to reject the handshake with an HTTP 403 instead of performing
    a clean WS close with a proper close code.
    """

    # 1. ACCEPT HANDSHAKE IMMEDIATELY
    await websocket.accept()

    # 2. VALIDATE TOKEN PRESENCE
    if not token or token in ("null", "undefined"):
        logger.warning(f"Rejected WS for agent={agent_id}: missing/invalid token param ('{token}')")
        await websocket.send_text(json.dumps({"type": "error", "message": "Missing or invalid auth token"}))
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
        await websocket.send_text(json.dumps({"type": "error", "message": "Unauthorized: invalid or expired token"}))
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    logger.info(f"WebSocket connected: Agent={agent_id}, Tenant={tenant_id}, User={user_id}")

    # 4. INITIALIZE SERVICE (once per session)
    async with get_db_with_tenant(tenant_id) as db:
        rag_service = RAGService(db=db, tenant_id=tenant_id)
        kb_repo = KnowledgeBaseRepository(db, tenant_id)

        kbs, _ = await kb_repo.list_by_agent(agent_id, limit=10)
        if not kbs:
            await websocket.send_text(json.dumps({"type": "error", "message": "Knowledge Base not found"}))
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
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
                    enhance_prompt = msg.get("prompt_enhancer", False) or msg.get("enhance_prompt", False)
                except json.JSONDecodeError:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Invalid JSON format"}))
                    continue

                if not query:
                    continue

                # 6. RESOLVE OR CREATE CHAT SESSION
                session = None
                if session_id:
                    session = await chat_service.chat_repo.get_session_by_id(session_id)
                    if not session:
                        logger.warning(f"Session {session_id} not found in WS, creating new")

                if session is None:
                    session = await chat_service.chat_repo.create_session(
                        agent_id=agent_id,
                        user_id=user_id
                    )

                active_session_id = str(session.id)

                # ============================================================
                # MEMORY-API STEP 1: TRIAGE + LONG-TERM EPISODIC GUIDANCE
                # ============================================================
                episodic_guidance = ""
                is_feedback_only = False

                async with httpx.AsyncClient() as client:
                    try:
                        mem_resp = await client.post(
                            f"{MEMORY_API_URL}/process-turn",
                            json={
                                "query": query,
                                "session_id": active_session_id,
                                "agent_id": agent_id,
                                "user_id": user_id,
                                "tenant_id": tenant_id
                            },
                            timeout=8.0  # Kept robust 8s timeout for vector + graph parsing
                        )
                        if mem_resp.status_code == 200:
                            mem_data = mem_resp.json()
                            episodic_guidance = mem_data.get("guidance_context") or ""
                            is_feedback_only = mem_data.get("is_feedback_only", False)
                        else:
                            logger.warning(f"memory-api process-turn returned {mem_resp.status_code}: {mem_resp.text}")
                    except Exception as e:
                        # Memory-api being down should never break core RAG chat
                        logger.warning(f"memory-api process-turn unreachable, continuing without it: {e}")

                # 7. SAVE USER MESSAGE
                user_msg = await chat_service.chat_repo.add_message(
                    session_id=active_session_id,
                    role="user",
                    content=query
                )
                await db.commit()

                # If the message was pure corrective feedback, record it and skip RAG execution
                if is_feedback_only:
                    async with httpx.AsyncClient() as client:
                        try:
                            await client.post(
                                f"{MEMORY_API_URL}/save-turn",
                                json={
                                    "query": query,
                                    "ai_response": "Acknowledged and updated rules.",
                                    "session_id": active_session_id,
                                    "agent_id": agent_id,
                                    "user_id": user_id,
                                    "tenant_id": tenant_id
                                },
                                timeout=3.0
                            )
                        except Exception as e:
                            logger.warning(f"memory-api save-turn (feedback) failed: {e}")

                    await websocket.send_text(json.dumps({
                        "type": "status",
                        "message": "Feedback captured and rules updated."
                    }))
                    await websocket.send_text(json.dumps({"type": "done"}))
                    continue

                # 8. PROMPT ENHANCER / QUERY REWRITING
                enhanced_query = query
                is_enhanced = False
                if enhance_prompt:
                    try:
                        logger.info(f"Running Prompt Enhancer for: '{query}'")
                        rewritten = await query_rewriter.rewrite_query(query)
                        if rewritten and rewritten != query:
                            enhanced_query = rewritten
                            is_enhanced = True
                            logger.info(f"Enhanced Query: '{query}' -> '{enhanced_query}'")
                    except Exception as e:
                        logger.error(f"Prompt enhancement failed: {e}", exc_info=True)

                # 9. TIER 3 RECALL: LOAD RECENT MEMORY (SAME-SESSION HISTORY)
                augmented_query = enhanced_query
                memory_used = False
                conversation_turns = 0

                if session.message_count > 1:
                    try:
                        memory_messages = await chat_service.chat_repo.get_recent_messages(
                            session_id=active_session_id,
                            count=10
                        )
                        history_messages = [m for m in memory_messages if str(m.id) != str(user_msg.id)]
                        if history_messages:
                            augmented_query = chat_service._format_memory_context(
                                history=history_messages,
                                current_query=enhanced_query
                            )
                            memory_used = True
                            conversation_turns = sum(1 for m in history_messages if m.role == "user")
                    except Exception as me:
                        logger.warning(f"WebSocket same-session memory injection failed: {me}")

                # TIER 1 & 2 RECALL: Merge Long-term episodic vector & graph context
                # Prepend with a clean markdown block header as requested to bundle seamlessly
                if episodic_guidance:
                    augmented_query = f"{episodic_guidance}\n\n## CURRENT USER QUERY FOCUS\n{augmented_query}"
                    memory_used = True

                logger.info(f"Raw Query: {query}")
                if is_enhanced:
                    logger.info(f"Enhanced RAG Query: {enhanced_query}")
                if memory_used:
                    logger.info(f"Augmented Query:\n{augmented_query}")

                # 10. STREAM RESPONSE & COLLECT CHUNKS FOR PERSISTENCE (TIER 3: Core Doc RAG)
                full_response_text = ""
                sources = []
                has_error = False

                async for chunk in rag_service.stream_rag_answer(
                    query=augmented_query,
                    agent_id=agent_id,
                    kb_id=kb_ids,
                    user_id=user_id
                ):
                    is_control_frame = False
                    try:
                        parsed = json.loads(chunk)
                        if isinstance(parsed, dict):
                            if parsed.get("type") == "metadata":
                                parsed["session_id"] = active_session_id
                                if is_enhanced:
                                    parsed["is_enhanced"] = True
                                    parsed["enhanced_query"] = enhanced_query
                                sources = parsed.get("sources", [])
                                logger.info(f"SOURCES: {sources}")
                                await websocket.send_text(json.dumps(parsed))
                                is_control_frame = True

                            elif "error" in parsed:
                                await websocket.send_text(chunk)
                                full_response_text = parsed["error"]
                                has_error = True
                                break
                    except (json.JSONDecodeError, TypeError):
                        pass

                    if is_control_frame:
                        continue

                    try:
                        await websocket.send_text(chunk)
                    except Exception as ws_err:
                        logger.error(f"Failed to send chunk to websocket: {ws_err}")
                        has_error = True
                        break

                    full_response_text += chunk

                # 11. SAVE ASSISTANT MESSAGE TO DB
                assistant_metadata = {
                    "sources": sources,
                    "memory_used": memory_used,
                    "conversation_turns": conversation_turns
                }
                if has_error:
                    assistant_metadata["error"] = True

                await chat_service.chat_repo.add_message(
                    session_id=active_session_id,
                    role="assistant",
                    content=full_response_text,
                    metadata=assistant_metadata
                )
                await db.commit()

                # ============================================================
                # MEMORY-API STEP 2: PERSIST TURN TO DUAL VECTOR & GRAPH SCHEMA
                # ============================================================
                if not has_error and full_response_text:
                    async with httpx.AsyncClient() as client:
                        try:
                            await client.post(
                                f"{MEMORY_API_URL}/save-turn",
                                json={
                                    "query": query,
                                    "ai_response": full_response_text,
                                    "session_id": active_session_id,
                                    "agent_id": agent_id,
                                    "user_id": user_id,
                                    "tenant_id": tenant_id,
                                    "metadata": {"source_doc_count": len(sources)}
                                },
                                timeout=3.0
                            )
                        except Exception as e:
                            # Fire-and-forget by design; a failed save here should
                            # never break the chat response the user already got.
                            logger.warning(f"memory-api save-turn failed: {e}")

                # 12. SIGNAL COMPLETION
                if not has_error:
                    await websocket.send_text(json.dumps({"type": "done"}))

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected: Agent={agent_id}")
        except Exception as e:
            logger.error(f"WebSocket session error: {e}", exc_info=True)
            try:
                await websocket.send_text(json.dumps({"type": "error", "message": f"Session interrupted: {str(e)}"}))
            except Exception:
                pass
