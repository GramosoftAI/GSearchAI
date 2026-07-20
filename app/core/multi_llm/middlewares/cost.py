import logging
from typing import Optional

from .registry import register_middleware
from ..types import LLMRequest, LLMResponse
from ..context import LLMExecutionContext
from ..cost.estimator import CostEstimator

log = logging.getLogger(__name__)

class CostMiddleware:
    def __init__(self, estimator: Optional[CostEstimator] = None, **kwargs):
        # Allow passing an explicit estimator for testing, otherwise it could be injected via kwargs or factory in a real app
        # For this prototype we expect it passed in or we can assume it's created externally.
        # The router usually passes `factory=factory` to middlewares. We might need the registry.
        # But per Phase 7B requirements, CostMiddleware takes an estimator.
        self._estimator = estimator

    async def after_response(self, request: LLMRequest, context: LLMExecutionContext, response: LLMResponse) -> LLMResponse:
        if not self._estimator:
            return response
            
        cost = self._estimator.estimate(
            provider=context.provider or context.route.provider, 
            model=context.model or context.route.model,
            prompt_tokens=getattr(response, "tokens_prompt", 0) or 0,
            completion_tokens=getattr(response, "tokens_completion", 0) or 0,
            cached_tokens=getattr(response, "cached_tokens", 0)
        )
        
        if cost is None:
            log.warning(f"cost_pricing_unavailable: provider={context.provider} model={context.model}")
            context.estimated_cost = None
        else:
            context.estimated_cost = cost
            
        return response

    async def on_exception(self, request: LLMRequest, context: LLMExecutionContext, exc: Exception) -> None:
        pass

register_middleware("cost", CostMiddleware, 450, mw_types=["response"])
