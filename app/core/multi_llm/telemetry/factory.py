from typing import List, Optional

from ..context import LLMExecutionContext
from ..types import LLMResponse
from ..exceptions import ProviderTimeoutError, ProviderUnavailableError
from .events import (
    TelemetryEvent,
    RequestCompletedEvent,
    ProviderFailedEvent,
    ProviderRetryEvent
)

class TelemetryEventFactory:
    """Builds typed telemetry events from the LLMExecutionContext."""
    
    def _base_kwargs(self, context: LLMExecutionContext) -> dict:
        return {
            "request_id": context.request_id,
            "tenant_id": context.tenant_id,
            "session_id": context.session_id,
            "user_id": context.user_id,
            "task_type": context.task_type,
            "provider": context.provider or context.route.provider,
            "model": context.model or context.route.model,
            "route_attempt": context.route_attempt,
            "fallback_depth": context.fallback_depth,
            "retry_count": context.retry_count,
            "latency_ms": context.latency_ms,
            "success": context.success,
            "exception_type": type(context.exception).__name__ if context.exception else None,
            "metadata": context.metadata.copy(),
        }

    def build_completion_events(self, context: LLMExecutionContext, response: LLMResponse) -> List[TelemetryEvent]:
        events: List[TelemetryEvent] = []
        
        # A request has completed successfully if we reached this point
        # (Though TelemetryMiddleware runs after_response, we only emit completion here)
        completion_event = RequestCompletedEvent(
            **self._base_kwargs(context),
            prompt_tokens=context.prompt_tokens,
            completion_tokens=context.completion_tokens,
            cached_tokens=context.cached_tokens,
            estimated_cost=context.estimated_cost,
            currency=context.currency,
            finish_reason=context.finish_reason
        )
        events.append(completion_event)
        return events

    def build_failure_event(self, context: LLMExecutionContext, exc: Exception) -> TelemetryEvent:
        # In a real system we might emit a ProviderRetryEvent if the context indicates a retry is happening.
        # But we don't know if a retry WILL happen unless the RetryRequested signal is used.
        # For simplicity, we just emit a ProviderFailedEvent containing the error details.
        
        return ProviderFailedEvent(
            **self._base_kwargs(context),
            error_detail=str(exc)
        )
