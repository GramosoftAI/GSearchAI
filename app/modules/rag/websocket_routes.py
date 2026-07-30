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

MEMORY_API_BASE_URL = os.getenv("MEMORY_API_BASE_URL", "http://memory-api:8001").rstrip("/")
MEMORY_API_URL = f"{MEMORY_API_BASE_URL}/api/v1/memory"


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
                # MEMORY-API STEP 1: TRIAGE + RECALL (Scoped by Agent, User, Tenant)
                # ============================================================
                episodic_guidance = ""
                is_feedback_only = False
                is_history_query = False
                router_category = None

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
                            timeout=8.0
                        )
                        if mem_resp.status_code == 200:
                            mem_data = mem_resp.json()
                            episodic_guidance = mem_data.get("guidance_context") or ""
                            is_feedback_only = mem_data.get("is_feedback_only", False)
                            is_history_query = mem_data.get("is_history_query", False)
                            # Forwarded to /save-turn so the background ingest step reuses
                            # this exact classification instead of re-running the router
                            # and potentially disagreeing with it.
                            router_category = mem_data.get("category")
                        else:
                            logger.warning(f"memory-api process-turn status={mem_resp.status_code}: {mem_resp.text}")
                    except Exception as e:
                        logger.warning(f"memory-api process-turn unreachable, continuing without memory: {e}")

                # 7. SAVE USER MESSAGE TO CHAT DB
                user_msg = await chat_service.chat_repo.add_message(
                    session_id=active_session_id,
                    role="user",
                    content=query
                )
                await db.commit()

                # Handle feedback-only turns
                # If the memory API returned stored preferences (episodic_guidance is set),
                # it means the query may need an answer from memory (e.g., "what is my name?"
                # was mis-classified as PREFERENCE_UPDATE). Fall through to the RAG path so
                # the AI can answer using that memory context.
                # Only short-circuit when there is truly nothing to recall.
                if is_feedback_only:
                    acknowledgment = "Understood! I've updated your preferences and saved them to my long-term memory."
                    async with httpx.AsyncClient() as client:
                        try:
                            await client.post(
                                f"{MEMORY_API_URL}/save-turn",
                                json={
                                    "query": query,
                                    "ai_response": acknowledgment,
                                    "session_id": active_session_id,
                                    "agent_id": agent_id,
                                    "user_id": user_id,
                                    "tenant_id": tenant_id,
                                    "is_feedback_only": True,
                                    "metadata": {"router_category": router_category}
                                },
                                timeout=3.0
                            )
                        except Exception as e:
                            logger.warning(f"memory-api save-turn (feedback) failed: {e}")

                    await chat_service.chat_repo.add_message(
                        session_id=active_session_id,
                        role="assistant",
                        content=acknowledgment,
                        metadata={"feedback_turn": True}
                    )
                    await db.commit()

                    await websocket.send_text(json.dumps({
                        "type": "status",
                        "message": "Preferences recorded successfully."
                    }))
                    await websocket.send_text(json.dumps({"type": "done"}))
                    continue
                # If is_feedback_only but episodic_guidance exists, fall through to RAG
                # so the AI can answer using stored preferences.

                # ============================================================
                # META-HISTORY SHORT-CIRCUIT (COGNEE STRUCTURAL RECALL)
                # If asking "What did we discuss?", bypass Document RAG entirely.
                # ============================================================
                if is_history_query:
                    history_prompt = (
                        "You are a helpful assistant. The user is asking about past chat history.\n"
                        "Answer their question using ONLY the provided conversation context and graph facts below.\n\n"
                        f"{episodic_guidance if episodic_guidance else 'No previous chat history found for this user.'}\n\n"
                        f"User Question: {query}\n\n"
                        "Provide a clear, concise summary of what was discussed:"
                    )

                    full_response_text = ""
                    history_stream_error = None
                    try:
                        full_response_text = await rag_service.llm_client.generate_cloud(prompt=history_prompt)
                        await websocket.send_text(full_response_text)
                    except Exception as direct_err:
                        # Log the FULL traceback + prompt size, not just str(err) —
                        # a bare message hides whether this was a timeout, an
                        # oversized prompt, a bad response shape, etc.
                        logger.error(
                            f"Direct memory streaming failed: {type(direct_err).__name__}: {direct_err} | "
                            f"history_prompt_chars={len(history_prompt)} | "
                            f"episodic_guidance_chars={len(episodic_guidance)}",
                            exc_info=True,
                        )
                        history_stream_error = f"{type(direct_err).__name__}: {direct_err}"
                        full_response_text = "I attempted to review our past chats, but ran into an error processing the summaries."
                        await websocket.send_text(full_response_text)

                    # Save Assistant Turn & Memory
                    await chat_service.chat_repo.add_message(
                        session_id=active_session_id,
                        role="assistant",
                        content=full_response_text,
                        metadata={
                            "memory_used": True,
                            "direct_history_recall": True,
                            "error": history_stream_error,
                        }
                    )
                    await db.commit()

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
                                    "metadata": {"router_category": router_category}
                                },
                                timeout=3.0
                            )
                        except Exception as e:
                            logger.warning(f"memory-api save-turn failed: {e}")

                    await websocket.send_text(json.dumps({"type": "done"}))
                    continue
                # 8. FETCH RECENT HISTORY
                history_messages = []
                conversation_turns = 0
                if session.message_count > 1:
                    try:
                        memory_messages = await chat_service.chat_repo.get_recent_messages(
                            session_id=active_session_id,
                            count=10
                        )
                        history_messages = [m for m in memory_messages if str(m.id) != str(user_msg.id)]
                        conversation_turns = sum(1 for m in history_messages if m.role == "user")
                    except Exception as me:
                        logger.warning(f"Failed to fetch recent memory messages: {me}")

                # 9. PROMPT ENHANCER / QUERY REWRITING
                enhanced_query = query
                is_enhanced = False
                if enhance_prompt or history_messages:
                    try:
                        rewritten = await query_rewriter.rewrite_query(query, history=history_messages)
                        if rewritten and rewritten != query:
                            enhanced_query = rewritten
                            is_enhanced = True
                    except Exception as e:
                        logger.error(f"Prompt enhancement failed: {e}", exc_info=True)

                # 10. PREPARE CONTEXT FOR FINAL LLM GENERATION
                chat_history_str = None
                memory_used = False
                if history_messages:
                    chat_history_str = chat_service._format_memory_context(
                        history=history_messages,
                        current_query=enhanced_query
                    )
                    memory_used = True

                if episodic_guidance:
                    guidance_block = (
                        "### MANDATORY USER PREFERENCES & MEMORY DIRECTIVES\n"
                        f"{episodic_guidance}\n"
                    )
                    chat_history_str = guidance_block + ("\n" + chat_history_str if chat_history_str else "")
                    memory_used = True

                skip_search = False
                if enhanced_query.startswith("[HISTORY_FILTER]"):
                    skip_search = True
                    enhanced_query = enhanced_query.replace("[HISTORY_FILTER]", "").strip()

                # 11. STREAM RAG ANSWER FROM KNOWLEDGE BASE
                full_response_text = ""
                sources = []
                has_error = False

                token_usage = {}
                def capture_usage(usage_dict):
                    token_usage.update(usage_dict)
                async for chunk in rag_service.stream_rag_answer(
                    query=enhanced_query,
                    agent_id=agent_id,
                    kb_id=kb_ids,
                    user_id=user_id,
                    session_id=active_session_id,
                    on_usage_callback=capture_usage,
                    chat_history=chat_history_str,
                    skip_search=skip_search,
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

                # 11. PERSIST ASSISTANT MESSAGE
                assistant_metadata = {
                    "sources": sources,
                    "memory_used": memory_used,
                    "conversation_turns": conversation_turns
                }
                if has_error:
                    assistant_metadata["error"] = True

                if token_usage:
                    assistant_metadata["stats"] = {
                        "llm_input_tokens": token_usage.get("prompt_tokens", 0),
                        "llm_output_tokens": token_usage.get("completion_tokens", 0),
                        "total_tokens": token_usage.get("total_tokens", 0),
                        "model": "Qwen/Qwen3.5-9B",
                    }
                await chat_service.chat_repo.add_message(
                    session_id=active_session_id,
                    role="assistant",
                    content=full_response_text,
                    metadata=assistant_metadata
                )
                await db.commit()

                # 12. SAVE TURN TO MEMORY API
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
                                    "metadata": {
                                        "source_doc_count": len(sources),
                                        "router_category": router_category
                                    }
                                },
                                timeout=3.0
                            )
                        except Exception as e:
                            logger.warning(f"memory-api save-turn failed: {e}")

                # 13. SIGNAL COMPLETION
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
