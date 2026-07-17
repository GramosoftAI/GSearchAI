import asyncio
import time
import logging
from enum import Enum
from typing import Dict, Tuple, Optional

from ..types import LLMRequest, LLMResponse
from ..context import LLMExecutionContext
from ..exceptions import ProviderTimeoutError, ProviderUnavailableError
from .base import RetryRequested
from .registry import register_middleware

log = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"

class CircuitBreaker:
    def __init__(self, max_failures: int = 3, reset_timeout: int = 30):
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.max_failures:
            self.state = CircuitState.OPEN
            log.warning("Circuit breaker tripped to OPEN state")

    def record_success(self):
        if self.state != CircuitState.CLOSED:
            log.info("Circuit breaker recovered to CLOSED state")
        self.state = CircuitState.CLOSED
        self.failure_count = 0

    def allow_request(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = CircuitState.HALF_OPEN
                log.info("Circuit breaker entering HALF_OPEN state")
                return True
            return False
        return True

class CircuitBreakerMiddleware:
    def __init__(self, **kwargs):
        self.breakers: Dict[Tuple[str, str], CircuitBreaker] = {}

    def _get_breaker(self, provider: str, model: str) -> CircuitBreaker:
        key = (provider, model)
        if key not in self.breakers:
            self.breakers[key] = CircuitBreaker()
        return self.breakers[key]

    async def before_request(self, request: LLMRequest, context: LLMExecutionContext) -> Optional[LLMResponse]:
        breaker = self._get_breaker(context.route.provider, context.route.model)
        context.circuit_state = breaker.state.value
        
        if not breaker.allow_request():
            raise ProviderUnavailableError(
                f"Circuit breaker OPEN for {context.route.provider}/{context.route.model}", 
                provider=context.route.provider
            )
        return None
        
    async def after_response(self, request: LLMRequest, context: LLMExecutionContext, response: LLMResponse) -> LLMResponse:
        breaker = self._get_breaker(context.route.provider, context.route.model)
        breaker.record_success()
        context.circuit_state = breaker.state.value
        return response

    async def on_exception(self, request: LLMRequest, context: LLMExecutionContext, exc: Exception) -> None:
        if isinstance(exc, (ProviderTimeoutError, ProviderUnavailableError)):
            breaker = self._get_breaker(context.route.provider, context.route.model)
            breaker.record_failure()
            context.circuit_state = breaker.state.value

class RetryMiddleware:
    def __init__(self, max_retries: int = 3, **kwargs):
        self.max_retries = max_retries
        
    async def before_request(self, request: LLMRequest, context: LLMExecutionContext) -> Optional[LLMResponse]:
        context.retry_count = 0
        return None
        
    async def after_response(self, request: LLMRequest, context: LLMExecutionContext, response: LLMResponse) -> LLMResponse:
        return response
        
    async def on_exception(self, request: LLMRequest, context: LLMExecutionContext, exc: Exception) -> None:
        if isinstance(exc, (ProviderTimeoutError, ProviderUnavailableError)):
            if context.retry_count < self.max_retries:
                context.retry_count += 1
                sleep_time = (2 ** context.retry_count) + 0.1
                log.info(f"Retrying request for {context.route.provider}/{context.route.model} in {sleep_time}s (Attempt {context.retry_count}/{self.max_retries})")
                await asyncio.sleep(sleep_time)
                raise RetryRequested()
            else:
                log.warning(f"Max retries reached for {context.route.provider}/{context.route.model}")

register_middleware("circuit_breaker", CircuitBreakerMiddleware, 300, mw_types=["request", "response"])
register_middleware("retry", RetryMiddleware, 400, mw_types=["response"])
