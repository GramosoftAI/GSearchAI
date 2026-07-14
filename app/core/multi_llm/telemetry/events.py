from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID

from ..cost.models import EstimatedCost

class TelemetryEvent(BaseModel):
    schema_version: str = "1.0"
    event_name: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    request_id: UUID
    tenant_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    task_type: str
    provider: Optional[str] = None
    model: Optional[str] = None
    route_attempt: int
    fallback_depth: int
    retry_count: int
    latency_ms: Optional[int] = None
    success: Optional[bool] = None
    exception_type: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class RequestStartedEvent(TelemetryEvent):
    event_name: str = "RequestStarted"

class RouteResolvedEvent(TelemetryEvent):
    event_name: str = "RouteResolved"
    resolved_route: str

class ProviderAttemptEvent(TelemetryEvent):
    event_name: str = "ProviderAttempt"

class ProviderRetryEvent(TelemetryEvent):
    event_name: str = "ProviderRetry"
    attempt: int
    retry_reason: str

class ProviderFailedEvent(TelemetryEvent):
    event_name: str = "ProviderFailed"
    error_detail: str

class CircuitOpenedEvent(TelemetryEvent):
    event_name: str = "CircuitOpened"

class CircuitRecoveredEvent(TelemetryEvent):
    event_name: str = "CircuitRecovered"

class FallbackTriggeredEvent(TelemetryEvent):
    event_name: str = "FallbackTriggered"
    from_step: str
    to_step: str

class RequestCompletedEvent(TelemetryEvent):
    event_name: str = "RequestCompleted"
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int = 0
    estimated_cost: Optional[EstimatedCost] = None
    currency: str = "USD"
    finish_reason: Optional[str] = None
