from pydantic import BaseModel
from decimal import Decimal
from typing import Optional
from datetime import date

class TokenPricing(BaseModel):
    prompt: Decimal
    completion: Decimal
    currency: str = "USD"
    effective_date: Optional[date] = None
    region: Optional[str] = None

class EstimatedCost(BaseModel):
    prompt_cost: Decimal
    completion_cost: Decimal
    cache_discount: Decimal
    total_cost: Decimal
    currency: str
    pricing_version: str
