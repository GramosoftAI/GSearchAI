import json
import logging
import httpx
import os
from fastapi import WebSocket, WebSocketDisconnect
from .schemas import UnifiedChatRequest
from .events import LoopEvent
from .adapters import ChannelAdapter

logger = logging.getLogger(__name__)

def resolve_memory_api_base_url() -> str:
    configured = os.getenv("MEMORY_API_BASE_URL", "").strip()
    if configured:
        return configured.rstrip("/")
    env_host = os.getenv("MEMORY_API_HOST", "").strip()
    if env_host:
        return env_host.rstrip("/")
    return "http://127.0.0.1:8001"

async def _persist_partial(db, chat_service, session_id, user_id, query, response_buffer, reason: str) -> None:
    try:
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
    Channel-agnostic execution core.
    """
    memory_api_url = f"{resolve_memory_api_base_url()}/api/v1/memory"
    
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
        session = None
        if active_session_id:
            session = await chat_service.chat_repo.get_session_by_id(active_session_id)
            
        if not session:
            session = await chat_service.chat_repo.create_session(
                agent_id=agent_id, user_id=user_id
            )
            active_session_id = str(session.id)
            
        # Send session start if needed? The widget expects a session_id back.
        # It's better if we just proceed. Embed formatters don't typically send session_id in the loop event,
        # but widget js might need it. We will handle session initialization outside this loop if required.

        user_msg = await chat_service.chat_repo.add_message(
            session_id=active_session_id, role="user", content=request.query
        )
        await db.commit()

        response_buffer = []
        collected_sources = []
        
        episodic_guidance = ""
        is_feedback_only = False
        is_history_query = False
        router_category = None
        
        # 0. Fast-path for greetings
        import re
        import random
        clean_query = request.query.strip().lower()
        if re.fullmatch(r"hi|hello|hey|good morning|good evening|good afternoon|greetings|howdy|what's up", clean_query):
            greetings = [
                "Hello! How can I assist you today?",
                "Hi there! What can I help you with?",
                "Greetings! How may I be of service?",
                "Hello! It's nice to meet you. Is there something I can help you with or would you like to know more about our services?",
                "Hi! I'm here to help. What's on your mind?"
            ]
            ack = random.choice(greetings)
            await chat_service.chat_repo.add_message(
                session_id=active_session_id, role="assistant", content=ack, metadata={"is_greeting": True}
            )
            await db.commit()
            await adapter.send(websocket, LoopEvent(type="token", text=ack))
            await adapter.send(websocket, LoopEvent(type="done"))
            continue

        try:
            # 1. Memory API Triage & Chat History Fetching (Parallel)
            async def _fetch_memory_triage():
                if enable_memory:
                    async with httpx.AsyncClient() as client:
                        try:
                            resp = await client.post(
                                f"{memory_api_url}/process-turn",
                                json={
                                    "query": request.query,
                                    "session_id": active_session_id,
                                    "agent_id": agent_id,
                                    "user_id": user_id,
                                    "tenant_id": tenant_id,
                                },
                                timeout=8.0,
                            )
                            if resp.status_code == 200:
                                return resp.json()
                        except Exception as e:
                            logger.warning(f"memory-api process-turn unreachable: {e}")
                return {}

            async def _fetch_chat_history():
                if session.message_count > 1:
                    return await chat_service.chat_repo.get_recent_messages(
                        session_id=active_session_id, count=10
                    )
                return []

            import asyncio
            # START MEMORY TASK IN BACKGROUND CONCURRENTLY
            memory_task = asyncio.create_task(_fetch_memory_triage())
            
            # Await ONLY chat history synchronously
            memory_messages = await _fetch_chat_history()

            # 2. Chat History for Memory Context (used only as context, never to rewrite the query)
            history_messages = [m for m in memory_messages if str(m.id) != str(user_msg.id)]

            # Original query is immutable from this point forward
            original_query = request.query
            logger.info("QUERY_FIDELITY | original=%r | rewriter=removed", original_query)

            # 3. Graph Memory Context Formatting
            chat_history_str = None
            if history_messages:
                chat_history_str = chat_service._format_memory_context(
                    history=history_messages, current_query=original_query
                )


            # 4. RAG Streamer -> internal LoopEvents
            has_error = False
            msg_metadata = {"status": "complete"}
            async for chunk in rag_service.stream_rag_answer(
                query=original_query,
                agent_id=agent_id,
                kb_id=kb_ids,
                user_id=user_id,
                session_id=active_session_id,
                chat_history=chat_history_str,
                skip_search=False,
                top_k=request.top_k,
                max_depth=request.max_depth,
                memory_task=memory_task
            ):
                if chunk.startswith("{"):
                    try:
                        parsed = json.loads(chunk)
                        if parsed.get("type") == "feedback_bypass":
                            ack = parsed["ack"]
                            router_category = parsed.get("router_category")
                            async with httpx.AsyncClient() as client:
                                try:
                                    await client.post(
                                        f"{memory_api_url}/save-turn",
                                        json={
                                            "query": request.query,
                                            "ai_response": ack,
                                            "session_id": active_session_id,
                                            "agent_id": agent_id,
                                            "user_id": user_id,
                                            "tenant_id": tenant_id,
                                            "is_feedback_only": True,
                                            "metadata": {"router_category": router_category},
                                        },
                                        timeout=3.0,
                                    )
                                except Exception:
                                    pass
                            response_buffer.append(ack)
                            msg_metadata["feedback_turn"] = True
                            await adapter.send(websocket, LoopEvent(type="token", text=ack))
                            break
                        elif parsed.get("type") == "history_bypass":
                            history_prompt = parsed["history_prompt"]
                            try:
                                full_response_text = await rag_service.llm_client.generate_cloud(prompt=history_prompt)
                                response_buffer.append(full_response_text)
                                msg_metadata.update({"memory_used": True, "direct_history_recall": True})
                                await adapter.send(websocket, LoopEvent(type="token", text=full_response_text))
                                break
                            except Exception as e:
                                has_error = True
                                await adapter.send_error(websocket, str(e))
                                break
                    except (json.JSONDecodeError, TypeError):
                        pass

                event = _rag_chunk_to_loop_event(chunk)
                if event.type == "token":
                    response_buffer.append(event.text)
                elif event.type == "sources":
                    collected_sources = event.sources
                elif event.type == "error":
                    has_error = True
                    await adapter.send_error(websocket, event.error_detail)
                    break
                await adapter.send(websocket, event)

            full_response = "".join(response_buffer)

            if has_error:
                await _persist_partial(db, chat_service, active_session_id, user_id, request.query, response_buffer, "rag_error")
                break

            # 5. DB Persistence
            msg_metadata["sources"] = collected_sources
            await chat_service.chat_repo.add_message(
                session_id=active_session_id,
                role="assistant",
                content=full_response,
                metadata=msg_metadata,
            )
            await db.commit()

            # 6. Memory API Persistence
            if enable_memory:
                async with httpx.AsyncClient() as client:
                    try:
                        await client.post(
                            f"{memory_api_url}/save-turn",
                            json={
                                "query": request.query,
                                "ai_response": full_response,
                                "session_id": active_session_id,
                                "agent_id": agent_id,
                                "user_id": user_id,
                                "tenant_id": tenant_id,
                                "metadata": {"router_category": router_category},
                            },
                            timeout=3.0,
                        )
                    except Exception as e:
                        logger.warning(f"memory-api save-turn failed: {e}")

            # 7. Knowledge Flywheel Background Sync
            if enable_memory and collected_sources:
                top_chunk_id = collected_sources[0].get("chunk_id") if isinstance(collected_sources[0], dict) else getattr(collected_sources[0], "chunk_id", None)
                kb_id = kb_ids[0] if kb_ids else None
                if top_chunk_id and kb_id:
                    from ..chats.knowledge_service import ChatKnowledgeService
                    # It's an async method meant to be run in background tasks normally, but we can await it here or use asyncio.create_task
                    import asyncio
                    asyncio.create_task(ChatKnowledgeService.run_sync_background(
                        tenant_id=tenant_id,
                        session_id=active_session_id,
                        kb_id=kb_id,
                        chunk_id=top_chunk_id,
                        user_message=request.query,
                        assistant_message=full_response
                    ))

            await adapter.send(websocket, LoopEvent(type="done"))

        except WebSocketDisconnect:
            await _persist_partial(db, chat_service, active_session_id, user_id, request.query, response_buffer, "disconnect")
            return

        except Exception as e:
            await _persist_partial(db, chat_service, active_session_id, user_id, request.query, response_buffer, str(e))
            await adapter.send_error(websocket, "internal_error")
            logger.exception("unified_rag_loop_failure", extra={"tenant_id": tenant_id, "agent_id": agent_id})
