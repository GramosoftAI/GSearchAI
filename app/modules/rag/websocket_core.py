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

        turn_start_time = time.perf_counter()

        if not active_session_id and request.session_id:
            active_session_id = request.session_id

        if not active_session_id:
            try:
                new_session = await chat_service.chat_repo.create_session(
                    agent_id=agent_id,
                    user_id=user_id,
                    title="New Conversation"
                )
                active_session_id = str(new_session.id)
                await db.commit()
            except Exception as e:
                logger.error(f"Failed to auto-create session: {e}")

        if active_session_id:
            try:
                await chat_service.chat_repo.add_message(
                    session_id=active_session_id,
                    role="user",
                    content=request.query
                )
                await db.commit()
            except Exception as e:
                logger.error(f"Failed to persist user message: {e}")

        async def _forward_event(event: LoopEvent):
            await adapter.send(websocket, event)

        try:
            async def _fetch_chat_history():
                if active_session_id:
                    return await chat_service.chat_repo.get_recent_messages(
                        session_id=active_session_id, count=10
                    )
                return []
            
            # Await ONLY chat history synchronously
            history_messages = await _fetch_chat_history()

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
                
            if final_state.get("source_documents"):
                sources_payload = final_state["source_documents"]
            elif final_state.get("sources"):
                sources_payload = [{"source": s} for s in final_state["sources"]]
            else:
                sources_payload = []

            if sources_payload:
                collected_sources = sources_payload
                await adapter.send(websocket, LoopEvent(type="sources", sources=sources_payload, triplets=[]))


            full_response = "".join(response_buffer)

            if has_error:
                try:
                    from app.modules.analytics.repository import AnalyticsRepository
                    from app.modules.analytics.models import ResponseStatus
                    from app.modules.chats.repository import safe_uuid
                    from app.core.config import get_settings

                    t_uuid = safe_uuid(tenant_id)
                    u_uuid = safe_uuid(user_id)
                    s_uuid = safe_uuid(active_session_id)
                    latency_ms = (time.perf_counter() - turn_start_time) * 1000
                    settings = get_settings()
                    used_model_name = getattr(rag_service.llm_client, "model_answer", settings.model_answer) if hasattr(rag_service, "llm_client") else settings.model_answer

                    analytics_repo = AnalyticsRepository(db, tenant_id=t_uuid, user_id=u_uuid)
                    await analytics_repo.create_query_log({
                        "tenant_id": t_uuid,
                        "user_id": u_uuid,
                        "session_id": s_uuid,
                        "query": request.query,
                        "response_status": ResponseStatus.ERROR,
                        "confidence_score": 0.0,
                        "latency_ms": latency_ms,
                        "model_name": used_model_name,
                        "llm_input_tokens": max(1, len(request.query) // 4),
                        "llm_output_tokens": 0,
                        "embedding_tokens": max(1, len(request.query) // 4),
                        "total_tokens": max(1, len(request.query) // 4) * 2,
                        "llm_cost_usd": 0.0,
                        "embedding_cost_usd": 0.0,
                        "total_cost_usd": 0.0,
                    })
                    await db.commit()
                except Exception as log_err:
                    logger.warning(f"Failed to record error analytics log in WebSocket loop: {log_err}")

                await _persist_partial(db, chat_service, active_session_id, user_id, request.query, response_buffer, "rag_error")
                break

            # 5. Evaluate Human Support Escalation
            is_escalated = detect_escalation_intent(
                query=request.query,
                sources=collected_sources,
                response_text=full_response
            )

            # Persist response and send completion event
            if active_session_id:
                try:
                    await chat_service.chat_repo.add_message(
                        session_id=active_session_id,
                        role="assistant",
                        content=full_response,
                        metadata={
                            "sources": collected_sources,
                            "status": "complete",
                            "escalation_detected": is_escalated,
                            "channel": channel,
                        },
                    )
                    await db.commit()
                except Exception as e:
                    logger.error(f"Failed to persist response: {e}")

            # Record Analytics Query Log & Token Usage
            try:
                from app.modules.analytics.repository import AnalyticsRepository
                from app.modules.analytics.models import ResponseStatus
                from app.modules.chats.repository import safe_uuid
                from app.core.llm.pricing import calculate_token_cost
                from app.core.config import get_settings

                t_uuid = safe_uuid(tenant_id)
                u_uuid = safe_uuid(user_id)
                s_uuid = safe_uuid(active_session_id)
                latency_ms = (time.perf_counter() - turn_start_time) * 1000

                clean_ans = full_response.lower() if full_response else ""
                is_unanswered = (
                    has_error
                    or not full_response.strip()
                    or (not collected_sources and (
                        "don't have that specific information" in clean_ans
                        or "cannot find" in clean_ans
                        or "no relevant information" in clean_ans
                        or "i don't know" in clean_ans
                    ))
                )

                query_status = ResponseStatus.UNANSWERED if is_unanswered else ResponseStatus.SUCCESS
                confidence = 0.0 if is_unanswered else (0.95 if collected_sources else 0.88)

                settings = get_settings()
                used_model_name = getattr(rag_service.llm_client, "model_answer", settings.model_answer) if hasattr(rag_service, "llm_client") else settings.model_answer
                llm_inp = max(1, len(request.query) // 4 + sum(len(str(s)) // 4 for s in collected_sources))
                llm_out = max(1, len(full_response) // 4)
                emb_tok = max(1, len(request.query) // 4)
                llm_cost = calculate_token_cost(used_model_name, llm_inp, llm_out)
                emb_cost = calculate_token_cost(settings.model_embedding, emb_tok, 0)

                analytics_repo = AnalyticsRepository(db, tenant_id=t_uuid, user_id=u_uuid)
                await analytics_repo.create_query_log({
                    "tenant_id": t_uuid,
                    "user_id": u_uuid,
                    "session_id": s_uuid,
                    "query": request.query,
                    "response_status": query_status,
                    "confidence_score": confidence,
                    "latency_ms": latency_ms,
                    "model_name": used_model_name,
                    "llm_input_tokens": llm_inp,
                    "llm_output_tokens": llm_out,
                    "embedding_tokens": emb_tok,
                    "total_tokens": llm_inp + llm_out + emb_tok,
                    "llm_cost_usd": llm_cost,
                    "embedding_cost_usd": emb_cost,
                    "total_cost_usd": llm_cost + emb_cost,
                })
                await analytics_repo.log_usage(
                    tenant_id=t_uuid,
                    user_id=u_uuid,
                    model_name=used_model_name,
                    query_text=request.query,
                    input_tokens=llm_inp,
                    output_tokens=llm_out,
                    task_name="chat_response"
                )
                await db.commit()
            except Exception as log_err:
                logger.warning(f"Failed to record analytics log in WebSocket loop: {log_err}")

            await adapter.send(websocket, LoopEvent(type="done", escalation_detected=is_escalated))

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

