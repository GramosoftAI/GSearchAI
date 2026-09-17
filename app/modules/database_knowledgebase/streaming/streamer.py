"""Phase 3D SSE Stream Generator

Consumes events from DatabasePipelineEventSink and formats them as SSE frames.
Enforces:
- Active disconnect detection even when the event queue is idle (background watcher + heartbeat timeout).
- Immediate cancellation propagation to the underlying query task (LLM / asyncpg).
- Best-effort query.cancelled emission on client disconnect.
- Zero artificial delay on deterministic paths.
- SSE keepalive / heartbeat framing.
- Clean resource finalization and zero task or connection leaks.
"""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, AsyncGenerator, Optional
import uuid
from fastapi import Request

from .models import DatabaseStreamEvent, DatabaseStreamEventType
from .sink import DatabasePipelineEventSink

logger = logging.getLogger(__name__)

DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 15.0
DISCONNECT_POLL_INTERVAL_SECONDS = 0.2


async def stream_database_query(
    service: Any,
    kb_id: uuid.UUID,
    user_query: str,
    request: Request,
    top_k_tables: int = 5,
    top_k_columns_per_table: int = 25,
    use_llm: bool = True,
    execution_config: Optional[Any] = None,
    heartbeat_interval_seconds: float = DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
) -> AsyncGenerator[str, None]:
    """
    Asynchronously executes a database query and streams lifecycle events as SSE frames.
    """
    correlation_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
    query_id = str(uuid.uuid4())
    sink = DatabasePipelineEventSink(correlation_id=correlation_id, query_id=query_id)

    done_event = asyncio.Event()

    # 1. Start background query pipeline task
    async def _run_query_pipeline():
        try:
            await service.query_database(
                kb_id=kb_id,
                user_query=user_query,
                top_k_tables=top_k_tables,
                top_k_columns_per_table=top_k_columns_per_table,
                use_llm=use_llm,
                execution_config=execution_config,
                request_id=correlation_id,
                event_sink=sink,
            )
        except asyncio.CancelledError:
            logger.info(f"Query task cancelled for query {query_id}")
            raise
        except Exception as exc:
            logger.exception(f"Unhandled exception in streaming query pipeline: {exc}")
            if not sink.is_terminal:
                safe_code = StreamingSanitizer.resolve_safe_error_code(exc)
                safe_msg = StreamingSanitizer.resolve_safe_error_message(exc, "INTERNAL")
                await sink.emit(
                    DatabaseStreamEventType.QUERY_ERROR,
                    stage="INTERNAL",
                    status="error",
                    data={
                        "error_code": safe_code,
                        "stage": "INTERNAL",
                        "retryable": False,
                        "message": safe_msg,
                        "correlation_id": correlation_id,
                    },
                )
        finally:
            done_event.set()
            if not sink.is_terminal:
                await sink.queue.put(None)

    query_task = asyncio.create_task(_run_query_pipeline())

    # 2. Start dedicated disconnect watcher task (active polling even when event queue is idle)
    async def _watch_client_disconnect():
        try:
            while not done_event.is_set():
                if await request.is_disconnected():
                    logger.info(f"Active disconnect watcher detected client disconnect for query {query_id}")
                    sink.cancel("Client disconnected")
                    if not query_task.done():
                        query_task.cancel()
                    break
                await asyncio.sleep(DISCONNECT_POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            pass

    watcher_task = asyncio.create_task(_watch_client_disconnect())

    # 3. Stream SSE frames to client
    try:
        while True:
            # Check disconnect state before waiting (drain any enqueued terminal event first)
            if sink.is_cancelled and sink.queue.empty():
                break

            if done_event.is_set() and sink.queue.empty():
                break

            try:
                # Wait for next event or heartbeat timeout
                event = await asyncio.wait_for(
                    sink.queue.get(),
                    timeout=heartbeat_interval_seconds,
                )
            except asyncio.TimeoutError:
                # Queue was idle: check disconnect and emit keepalive
                if await request.is_disconnected():
                    logger.info(f"Idle timeout detected client disconnect for query {query_id}")
                    sink.cancel("Client disconnected during idle queue")
                    if not query_task.done():
                        query_task.cancel()
                    break

                # Emit keepalive frame to maintain intermediate proxy connections
                yield ": keepalive\n\n"
                continue

            # None is sentinel indicating stream complete
            if event is None:
                break

            # Yield SSE frame
            yield event.to_sse_frame()

    except (asyncio.CancelledError, GeneratorExit):
        logger.info(f"SSE generator cancelled/closed by client for query {query_id}")
        sink.cancel("Client connection closed")
        if not query_task.done():
            query_task.cancel()

    finally:
        # Stop watcher task
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass

        # If query task is still running, cancel and await it to guarantee resource cleanup
        if not query_task.done():
            query_task.cancel()
            try:
                await query_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.debug(f"Exception during query task cancellation: {exc}")

        # Best-effort attempt to emit query.cancelled if client requested cancellation
        # and socket might still be open (wrapped in try/except to tolerate already-closed sockets)
        if sink.is_cancelled and not sink.is_terminal:
            try:
                await sink.emit(
                    DatabaseStreamEventType.QUERY_CANCELLED,
                    stage="STREAM",
                    status="cancelled",
                    data={"stage": "STREAM", "reason": "Query cancelled by client"},
                )
                cancelled_event = await sink.queue.get()
                if cancelled_event is not None:
                    yield cancelled_event.to_sse_frame()
            except Exception as write_err:
                logger.debug(f"Best-effort query.cancelled write ignored on closed socket: {write_err}")
