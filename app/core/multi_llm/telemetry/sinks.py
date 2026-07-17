import logging
from typing import Protocol

from .events import TelemetryEvent

log = logging.getLogger("multi_llm.telemetry")

class TelemetrySink(Protocol):
    async def emit(self, event: TelemetryEvent) -> None:
        ...

class StructuredLogSink(TelemetrySink):
    """Emits telemetry events as structured JSON logs."""
    async def emit(self, event: TelemetryEvent) -> None:
        # Uses model_dump_json for structured logging
        log.info(event.model_dump_json())

class NoOpSink(TelemetrySink):
    """A sink that does nothing; useful for testing or disabling telemetry."""
    async def emit(self, event: TelemetryEvent) -> None:
        pass
