from typing import Protocol, Callable, Awaitable, Any, List, Optional
from ..types import LLMRequest, LLMResponse
from ..context import LLMExecutionContext

class RequestMiddleware(Protocol):
    """Runs before the provider call. May short-circuit."""
    async def before_request(
        self, request: LLMRequest, context: LLMExecutionContext,
    ) -> Optional[LLMResponse]: ...

class ResponseMiddleware(Protocol):
    """Runs after the provider call (or after a short-circuit)."""
    async def after_response(
        self, request: LLMRequest, context: LLMExecutionContext, response: LLMResponse,
    ) -> LLMResponse: ...

    async def on_exception(
        self, request: LLMRequest, context: LLMExecutionContext, exc: Exception,
    ) -> None: ...

class RetryRequested(Exception):
    """Signal raised by a ResponseMiddleware to trigger a retry loop in the pipeline runner."""
    pass

async def run_pipeline(
    request: LLMRequest, 
    context: LLMExecutionContext, 
    request_mw: List[RequestMiddleware], 
    response_mw: List[ResponseMiddleware], 
    provider_call: Callable[[LLMRequest, LLMExecutionContext], Awaitable[LLMResponse]]
) -> LLMResponse:
    
    # 1. Run Request Middlewares (Capability, Constraint, CircuitBreaker check)
    response = None
    for mw in request_mw:
        short_circuit = await mw.before_request(request, context)
        if short_circuit is not None:
            response = short_circuit
            break
            
    # 2. Run Provider with Retry loop support
    if response is None:
        while True:
            try:
                response = await provider_call(request, context)
                break
            except Exception as exc:
                context.exception = exc
                context.success = False
                
                retry_requested = False
                for mw in response_mw:
                    try:
                        await mw.on_exception(request, context, exc)
                    except RetryRequested:
                        retry_requested = True
                        
                if retry_requested:
                    continue  # Loop again to retry provider call
                raise

    # 3. Run Response Middlewares
    context.success = True
    for mw in response_mw:
        response = await mw.after_response(request, context, response)
        
    return response
