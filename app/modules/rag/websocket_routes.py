"""

WebSocket RAG routes - Streaming chat interface for GraphRAG

Phase 3: Real-time Conversational Retrieval

"""



import logging

import json

import asyncio

from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status



from .service import RAGService

from ..knowledge_bases.repository import KnowledgeBaseRepository

from ...core.database import AsyncSessionLocal, get_db_with_tenant

from ...core.security import verify_access_token



logger = logging.getLogger(__name__)



router = APIRouter(prefix="/ws", tags=["WebSocket RAG"])





@router.websocket("/{agent_id}")

async def rag_websocket(

    websocket: WebSocket,

    agent_id: str,

    token: str = Query(...),

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

    """
    
    # 0. PREVENT INVALID TOKENS FROM OPENING CONNECTION
    if not token or token == "null" or token == "undefined":
        logger.warning(f"Frontend sent invalid token '{token}', rejecting connection.")
        # We must accept and then close with policy violation, or just close. 
        # FastAPI requires accept before sending close codes in some versions, but close() works.
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 1. ACCEPT CONNECTION IMMEDIATELY (Prevent handshake timeouts)
    await websocket.accept()
    
    # 2. AUTHENTICATION

    payload = await verify_access_token(token)

    if not payload:

        logger.warning(f"WebSocket auth failed for agent {agent_id}")

        await websocket.send_text(json.dumps({"error": "Unauthorized: Invalid or expired token"}))

        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)

        return



    tenant_id = payload.tenant_id

    user_id = payload.user_id

    

    logger.info(f" WebSocket connected: Agent={agent_id}, Tenant={tenant_id}")



    # 3. INITIALIZE SERVICE (Once per session for max speed)

    async with get_db_with_tenant(tenant_id) as db:

        rag_service = RAGService(db=db, tenant_id=tenant_id)

        kb_repo = KnowledgeBaseRepository(db, tenant_id)

        

        # AUTO-RESOLVE KBs (Cached for session duration)

        kbs, _ = await kb_repo.list_by_agent(agent_id, limit=10)

        if not kbs:

            await websocket.send_text(json.dumps({"error": "Knowledge Base not found"}))

            await websocket.close()

            return

        

        kb_ids = [str(kb.id) for kb in kbs]

        logger.info(f" Session ready: Agent={agent_id}, KBs={len(kb_ids)}")



        # Initialize ChatService for history persistence

        from ..chats.service import ChatService

        chat_service = ChatService(db=db, tenant_id=tenant_id)



        # Initialize QueryRewriter for Prompt Enhancement

        from ...core.query_rewriter import QueryRewriter

        query_rewriter = QueryRewriter()



        try:

            while True:

                # 4. WAIT FOR MESSAGE

                data = await websocket.receive_text()

                try:

                    msg = json.loads(data)

                    query = msg.get("query")

                    session_id = msg.get("session_id")

                    enhance_prompt = msg.get("prompt_enhancer", False) or msg.get("enhance_prompt", False)

                except:

                    await websocket.send_text(json.dumps({"error": "Invalid JSON format"}))

                    continue



                if not query:

                    continue



                # 5. RESOLVE OR CREATE CHAT SESSION

                if session_id:

                    session = await chat_service.chat_repo.get_session_by_id(session_id)

                    if not session:

                        logger.warning(f"Session {session_id} not found in WS, creating new")

                        session = await chat_service.chat_repo.create_session(

                            agent_id=agent_id,

                            user_id=user_id

                        )

                else:

                    session = await chat_service.chat_repo.create_session(

                        agent_id=agent_id,

                        user_id=user_id

                    )



                active_session_id = str(session.id)



                # 6. SAVE USER MESSAGE

                user_msg = await chat_service.chat_repo.add_message(

                    session_id=active_session_id,

                    role="user",

                    content=query

                )

                await db.commit()



                # 6.5 CHECK PROMPT ENHANCER / QUERY REWRITING

                enhanced_query = query

                is_enhanced = False

                if enhance_prompt:

                    try:

                        logger.info(f" Running Prompt Enhancer for: '{query}'")

                        rewritten = await query_rewriter.rewrite_query(query)

                        if rewritten and rewritten != query:

                            enhanced_query = rewritten

                            is_enhanced = True

                            logger.info(f" Enhanced Query: '{query}' -> '{enhanced_query}'")

                    except Exception as e:

                        logger.error(f" Prompt enhancement failed: {e}", exc_info=True)



                # 7. LOAD RECENT MEMORY (CONVERSATION HISTORY)

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

                        logger.warning(f" WebSocket Memory injection failed: {me}")



                logger.info(f" Raw Query: {query}")

                if is_enhanced:

                    logger.info(f" Enhanced RAG Query: {enhanced_query}")

                if memory_used:

                    logger.info(f" Augmented Query: \n{augmented_query}")



                # 8. STREAM RESPONSE & COLLECT CHUNKS FOR PERSISTENCE

                full_response_text = ""

                sources = []

                has_error = False



                async for chunk in rag_service.stream_rag_answer(

                    query=augmented_query,

                    agent_id=agent_id,

                    kb_id=kb_ids,

                    user_id=user_id

                ):

                    try:

                        # Extract metadata if it's the first JSON payload

                        parsed = json.loads(chunk)

                        if isinstance(parsed, dict):

                            if parsed.get("type") == "metadata":
                                parsed["session_id"] = active_session_id
                                if is_enhanced:
                                    parsed["is_enhanced"] = True
                                    parsed["enhanced_query"] = enhanced_query
                                sources = parsed.get("sources", [])
                                logger.info("=" * 50)
                                logger.info(f"SOURCES: {sources}")
                                logger.info("=" * 50)
                                await websocket.send_text(json.dumps(parsed))
                                continue

                                if is_enhanced:

                                    parsed["is_enhanced"] = True

                                    parsed["enhanced_query"] = enhanced_query

                                sources = parsed.get("sources", [])

                                await websocket.send_text(json.dumps(parsed))

                                continue

                            elif "error" in parsed:

                                await websocket.send_text(chunk)

                                full_response_text = parsed["error"]

                                has_error = True

                                break

                    except:

                        pass



                    # Forward stream chunk to client
                    # We skip logging every chunk to avoid log spam, but we track errors
                    try:
                        await websocket.send_text(chunk)
                    except Exception as ws_err:
                        logger.error(f"Failed to send chunk to websocket: {ws_err}")
                        has_error = True
                        break
                        
                    full_response_text += chunk



                # 9. SAVE ASSISTANT MESSAGE TO DB

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



                # 10. SIGNAL COMPLETION

                if not has_error:

                    await websocket.send_text(json.dumps({"type": "done"}))



        except WebSocketDisconnect:

            logger.info(f" WebSocket disconnected: Agent={agent_id}")

        except Exception as e:

            logger.error(f" WebSocket session error: {e}", exc_info=True)

            try:

                await websocket.send_text(json.dumps({"error": "Session interrupted"}))

            except:

                pass

