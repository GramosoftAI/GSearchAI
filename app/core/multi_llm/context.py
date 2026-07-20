from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID

from .config.schema import RouteStep
from .cost.models import EstimatedCost

class LLMExecutionContext(BaseModel):
    request_id: UUID

    tenant_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None

    task_type: str

    route: RouteStep
    route_attempt: int = 1
    fallback_depth: int = 0

    provider: Optional[str] = None
    model: Optional[str] = None

    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    retry_count: int = 0
    circuit_state: Optional[str] = None

    latency_ms: Optional[int] = None
    queue_time_ms: Optional[int] = None

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    estimated_cost: Optional[EstimatedCost] = None
    currency: str = "USD"

    finish_reason: Optional[str] = None
    success: Optional[bool] = None
    
    # Use Any for exception to avoid pydantic validation issues with arbitrary Exception types,
    # or skip validation via Config.
    exception: Optional[Any] = None

    deadline: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    class Config:
        arbitrary_types_allowed = True
