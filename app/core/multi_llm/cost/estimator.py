from decimal import Decimal
from typing import Optional

from .models import EstimatedCost
from .registry import PricingRegistry

class CostEstimator:
    def __init__(self, pricing: PricingRegistry):
        self._pricing = pricing

    def estimate(self, provider: str, model: str,
                 prompt_tokens: int, completion_tokens: int,
                 cached_tokens: int = 0) -> Optional[EstimatedCost]:
        pricing = self._pricing.lookup(provider, model)
        if pricing is None:
            return None
            
        # Prices in pricing.yaml are per 1M tokens
        MILLION = Decimal(1_000_000)
        
        prompt_cost = (Decimal(prompt_tokens) * pricing.prompt) / MILLION
        completion_cost = (Decimal(completion_tokens) * pricing.completion) / MILLION
        cache_discount = (Decimal(cached_tokens) * pricing.prompt) / MILLION
        total = prompt_cost + completion_cost - cache_discount

        return EstimatedCost(
            prompt_cost=prompt_cost, 
            completion_cost=completion_cost,
            cache_discount=cache_discount, 
            total_cost=total,
            currency=pricing.currency, 
            pricing_version=self._pricing.pricing_version
        )
