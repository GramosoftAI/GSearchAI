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

async def _persist_partial(db, chat_service, session_id, user_id, query, response_buffer, reason: str, channel: str = "websocket") -> None:
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
                "channel": channel,
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
                return LoopEvent(
                    type="clarification_needed", 
                    text=parsed.get("plain_text_fallback"), 
                    clarification=parsed,
                    candidates=parsed.get("candidates")
                )
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
            async def _fetch_chat_history():
                if session.message_count > 1:
                    return await chat_service.chat_repo.get_recent_messages(
                        session_id=active_session_id, count=10
                    )
                return []
            
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


            # 4. LangGraph Execution & Streaming
            has_error = False
            msg_metadata = {"status": "complete"}
            response_buffer = []
            collected_sources = []
            
            from app.modules.rag.graph.workflow import build_rag_graph
            import asyncio
            
            stream_queue = asyncio.Queue()
            
            initial_state = {
                "query": original_query,
                "original_query": original_query,
                "tenant_id": tenant_id,
                "agent_id": agent_id,
                "session_id": active_session_id,
                "user_id": user_id,
                "kb_ids": kb_ids,
                "chat_history": chat_history_str,
                "skip_search": False,
                "top_k": request.top_k,
                "max_depth": request.max_depth,
                "stream_queue": stream_queue
            }
            
            # Fetch target_kb_id if explicitly requested
            if getattr(request, "target_kb_id", None):
                initial_state["target_kb_id"] = request.target_kb_id
                
            graph = build_rag_graph().compile()
            graph_task = asyncio.create_task(graph.ainvoke(initial_state))
            
            # Watchdog: ensure sentinel None is queued if graph_task dies prematurely
            def _on_graph_done(t):
                if t.cancelled() or t.exception():
                    try:
                        stream_queue.put_nowait(None)
                    except Exception:
                        pass
            graph_task.add_done_callback(_on_graph_done)

            # Consumer Loop for LLM Tokens with watchdog protection
            final_state = {}
            while True:
                if stream_queue.empty() and graph_task.done():
                    break

                get_task = asyncio.create_task(stream_queue.get())
                done, _ = await asyncio.wait(
                    [graph_task, get_task],
                    return_when=asyncio.FIRST_COMPLETED
                )

                if get_task in done:
                    chunk = get_task.result()
                    if chunk is None:
                        break
                    response_buffer.append(chunk)
                    await adapter.send(websocket, LoopEvent(type="token", text=chunk))
                elif graph_task in done:
                    get_task.cancel()
                    # Drain any tokens that were already pushed to the queue
                    while not stream_queue.empty():
                        chunk = stream_queue.get_nowait()
                        if chunk is None:
                            break
                        response_buffer.append(chunk)
                        await adapter.send(websocket, LoopEvent(type="token", text=chunk))
                    break
                
            try:
                final_state = await graph_task
            except Exception as e:
                has_error = True
                logger.error(f"[LANGGRAPH] Execution failed: {e}", exc_info=True)
                await adapter.send_error(websocket, str(e))
                final_state = {}
                
            if final_state.get("requires_clarification"):
                parsed = final_state["clarification_payload"]
                plain_fallback = parsed.get("message", "Please choose a file.")
                response_buffer.append(plain_fallback)
                msg_metadata["clarification"] = parsed
                await adapter.send(
                    websocket, 
                    LoopEvent(
                        type="clarification_needed", 
                        text=plain_fallback, 
                        clarification=parsed,
                        candidates=parsed.get("candidates")
                    )
                )
                
            if final_state.get("sources"):
                sources_payload = [{"source": s} for s in final_state["sources"]]
                collected_sources = sources_payload
                await adapter.send(websocket, LoopEvent(type="sources", sources=sources_payload, triplets=[]))

            full_response = "".join(response_buffer)

            if has_error:
                await _persist_partial(db, chat_service, active_session_id, user_id, request.query, response_buffer, "rag_error")
                break

            # 5. Evaluate Human Support Escalation
            is_escalated = detect_escalation_intent(
                query=request.query,
                sources=collected_sources,
                response_text=full_response
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

