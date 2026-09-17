"""Phase 3D Decoupled Pipeline Event Sink

Provides the bridge between the service pipeline and the streaming transport.
Enforces:
- Monotonically increasing event sequence numbers starting at 1.
- Event-specific data allowlisting (zero arbitrary dictionaries).
- Exactly ONE terminal outcome per stream, completely preventing duplicate terminal events.
- Stage elapsed latency and total pipeline elapsed tracking.
- Client cancellation signaling and cooperative cancellation state.
"""

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, Optional

from .models import (
    DatabaseStreamEvent,
    DatabaseStreamEventType,
    EventDataFilter,
)

logger = logging.getLogger(__name__)

# Set of terminal events
TERMINAL_EVENT_TYPES = {
    DatabaseStreamEventType.STREAM_COMPLETED,
    DatabaseStreamEventType.QUERY_ERROR,
    DatabaseStreamEventType.QUERY_CANCELLED,
}


class DatabasePipelineEventSink:
    """
    Thread-safe and async-safe pipeline event sink.
    Decoupled from HTTP / SSE protocols.
    """

    def __init__(self, correlation_id: str, query_id: str):
        self.correlation_id = correlation_id
        self.query_id = query_id
        self.start_time = time.perf_counter()
        
        self._seq = 0
        self._seq_lock = asyncio.Lock()
        self._queue: asyncio.Queue[Optional[DatabaseStreamEvent]] = asyncio.Queue()
        
        self._terminal_event: Optional[DatabaseStreamEventType] = None
        self._is_cancelled = False
        self._cancellation_reason: Optional[str] = None
        
        self._stage_start_times: Dict[str, float] = {}

    @property
    def is_cancelled(self) -> bool:
        """Returns True if client cancellation has been signaled."""
        return self._is_cancelled

    @property
    def is_terminal(self) -> bool:
        """Returns True if a terminal event has already been emitted."""
        return self._terminal_event is not None

    @property
    def queue(self) -> asyncio.Queue[Optional[DatabaseStreamEvent]]:
        """Access event queue for consumer consumption."""
        return self._queue

    def cancel(self, reason: str = "Client disconnected or query cancelled") -> None:
        """Signals cooperative cancellation to the running pipeline."""
        if not self._is_cancelled:
            self._is_cancelled = True
            self._cancellation_reason = reason
            logger.info(f"PipelineEventSink cancelled for query {self.query_id}: {reason}")

    def start_stage(self, stage_name: str) -> None:
        """Records start timestamp of a pipeline stage."""
        self._stage_start_times[stage_name] = time.perf_counter()

    def get_stage_elapsed_ms(self, stage_name: str) -> Optional[float]:
        """Calculates elapsed duration in ms for a pipeline stage."""
        st = self._stage_start_times.get(stage_name)
        if st is not None:
            return round((time.perf_counter() - st) * 1000.0, 2)
        return None

    def get_total_elapsed_ms(self) -> float:
        """Calculates total pipeline duration since sink creation."""
        return round((time.perf_counter() - self.start_time) * 1000.0, 2)

    async def emit(
        self,
        event_type: DatabaseStreamEventType,
        stage: str,
        status: str = "in_progress",
        data: Optional[Dict[str, Any]] = None,
        elapsed_stage_ms: Optional[float] = None,
    ) -> bool:
        """
        Emits a typed lifecycle event.
        Guarantees:
        1. Monotonically increasing sequence number.
        2. Strict data allowlist filtering (anti-leakage).
        3. Exactly one terminal event: duplicate terminal events are silently ignored.
        """
        async with self._seq_lock:
            # Check terminal state invariant: exactly one terminal event allowed
            if self._terminal_event is not None:
                logger.debug(
                    f"Ignored emission of '{event_type.value}' because stream already "
                    f"terminated with '{self._terminal_event.value}'"
                )
                return False

            if event_type in TERMINAL_EVENT_TYPES:
                self._terminal_event = event_type

            self._seq += 1
            seq_num = self._seq

        # Filter data strictly against allowlist
        sanitized_data = EventDataFilter.filter_payload(event_type, data)

        # Calculate stage elapsed ms if not explicitly provided
        if elapsed_stage_ms is None and stage in self._stage_start_times:
            elapsed_stage_ms = self.get_stage_elapsed_ms(stage)

        event = DatabaseStreamEvent(
            sequence_number=seq_num,
            event=event_type,
            protocol_version="1.0",
            correlation_id=self.correlation_id,
            query_id=self.query_id,
            stage=stage,
            status=status,
            timestamp=datetime.now(timezone.utc),
            elapsed_stage_ms=elapsed_stage_ms,
            elapsed_total_ms=self.get_total_elapsed_ms(),
            data=sanitized_data,
        )

        await self._queue.put(event)

        # If terminal event emitted, put sentinel to terminate consumer stream
        if event_type in TERMINAL_EVENT_TYPES:
            await self._queue.put(None)

        return True

    async def emit_heartbeat(self) -> bool:
        """Emits an SSE heartbeat frame to keep idle proxies alive."""
        if self.is_terminal:
            return False

        async with self._seq_lock:
            self._seq += 1
            seq_num = self._seq

        hb_event = DatabaseStreamEvent(
            sequence_number=seq_num,
            event=DatabaseStreamEventType.HEARTBEAT,
            protocol_version="1.0",
            correlation_id=self.correlation_id,
            query_id=self.query_id,
            stage="STREAM",
            status="keepalive",
            timestamp=datetime.now(timezone.utc),
            elapsed_stage_ms=None,
            elapsed_total_ms=self.get_total_elapsed_ms(),
            data={"timestamp": datetime.now(timezone.utc).isoformat(), "sequence_number": seq_num},
        )
        await self._queue.put(hb_event)
        return True
