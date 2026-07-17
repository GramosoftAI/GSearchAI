import logging
from typing import Optional

from ..types import LLMRequest, LLMResponse
from ..context import LLMExecutionContext
from .registry import register_middleware
from ..telemetry.factory import TelemetryEventFactory
from ..telemetry.sinks import TelemetrySink, NoOpSink

log = logging.getLogger(__name__)

class TelemetryMiddleware:
    def __init__(self, factory: Optional[TelemetryEventFactory] = None, sink: Optional[TelemetrySink] = None, **kwargs):
        self._factory = factory or TelemetryEventFactory()
        self._sink = sink or NoOpSink()

    async def after_response(self, request: LLMRequest, context: LLMExecutionContext, response: LLMResponse) -> LLMResponse:
        try:
            for event in self._factory.build_completion_events(context, response):
                await self._sink.emit(event)
        except Exception:
            log.warning("telemetry_emit_failed", exc_info=True)
        return response

    async def on_exception(self, request: LLMRequest, context: LLMExecutionContext, exc: Exception) -> None:
        try:
            event = self._factory.build_failure_event(context, exc)
            await self._sink.emit(event)
        except Exception:
            log.warning("telemetry_emit_failed", exc_info=True)

register_middleware("telemetry", TelemetryMiddleware, 500, mw_types=["response"])
