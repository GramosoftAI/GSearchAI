from typing import Optional, Dict
from datetime import date
from decimal import Decimal

from .models import TokenPricing

class PricingRegistry:
    def __init__(self, pricing_table: dict, pricing_version: str):
        self._table = pricing_table
        self.pricing_version = pricing_version

    def lookup(self, provider: str, model: str, region: Optional[str] = None, as_of: Optional[date] = None) -> Optional[TokenPricing]:
        """Returns None if pricing is genuinely unavailable — never raises."""
        provider_data = self._table.get(provider, {})
        model_data = provider_data.get(model)
        
        if not model_data:
            return None
            
        return TokenPricing(
            prompt=Decimal(str(model_data.get("prompt", "0"))),
            completion=Decimal(str(model_data.get("completion", "0"))),
            currency=model_data.get("currency", "USD")
        )

    @classmethod
    def from_dict(cls, data: dict) -> "PricingRegistry":
        pricing_version = data.get("pricing_version", "unknown")
        providers = data.get("providers", {})
        return cls(pricing_table=providers, pricing_version=pricing_version)
