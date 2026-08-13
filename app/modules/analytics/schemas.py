"""
Pydantic schemas for the Analytics Module.
"""

from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import List, Optional
from .models import ResponseStatus

class AnalyticsSummaryBase(BaseModel):
    session_id: Optional[UUID] = None
    total_queries: int = Field(0, ge=0)
    answered_queries: int = Field(0, ge=0)
    unanswered_queries: int = Field(0, ge=0)
    accuracy_score: float = Field(0.0, ge=0.0, le=100.0)
    avg_confidence: float = Field(0.0, ge=0.0, le=1.0)

class AnalyticsSummaryCreate(AnalyticsSummaryBase):
    pass

class AnalyticsSummaryUpdate(BaseModel):
    total_queries: Optional[int] = None
    answered_queries: Optional[int] = None
    unanswered_queries: Optional[int] = None
    accuracy_score: Optional[float] = None
    avg_confidence: Optional[float] = None

class AnalyticsSummaryResponse(AnalyticsSummaryBase):
    id: UUID
    tenant_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

class AnalyticsQueryLogBase(BaseModel):
    session_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    request_id: Optional[str] = None
    model_name: Optional[str] = None
    query: str
    response_status: ResponseStatus = ResponseStatus.SUCCESS
    confidence_score: float = Field(0.0, ge=0.0, le=1.0)
    latency_ms: float = Field(0.0, ge=0.0)
    llm_input_tokens: int = Field(0, ge=0)
    llm_output_tokens: int = Field(0, ge=0)
    embedding_tokens: int = Field(0, ge=0)
    total_tokens: int = Field(0, ge=0)
    llm_cost_usd: float = Field(0.0, ge=0.0)
    embedding_cost_usd: float = Field(0.0, ge=0.0)
    total_cost_usd: float = Field(0.0, ge=0.0)

class AnalyticsQueryLogCreate(AnalyticsQueryLogBase):
    pass

class AnalyticsQueryLogResponse(AnalyticsQueryLogBase):
    id: UUID
    tenant_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

# ================= TOKEN CONSUMPTION SCHEMAS =================

class TokenConsumptionItem(BaseModel):
    id: UUID
    tenant_id: UUID
    user_id: Optional[UUID] = None
    session_id: Optional[UUID] = None
    request_id: Optional[str] = None
    model_name: Optional[str] = None
    query: str
    response_status: str
    latency_ms: float
    llm_input_tokens: int
    llm_output_tokens: int
    embedding_tokens: int
    total_tokens: int
    llm_cost_usd: float
    embedding_cost_usd: float
    total_cost_usd: float
    created_at: datetime

    class Config:
        from_attributes = True

class TokenConsumptionSummary(BaseModel):
    total_input_tokens: int
    total_output_tokens: int
    total_embedding_tokens: int
    total_tokens: int
    total_cost_usd: float
    total_queries: int

class ModelTokenUsageBreakdown(BaseModel):
    model_name: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    total_cost_usd: float
    request_count: int
    purpose: Optional[str] = None
    model_type: Optional[str] = None
    status: Optional[str] = None
    provider: Optional[str] = None

class UserTokenUsageBreakdown(BaseModel):
    user_id: Optional[UUID] = None
    user_email: Optional[str] = None
    input_tokens: int
    output_tokens: int
    embedding_tokens: int
    total_tokens: int
    total_cost_usd: float
    request_count: int

class DailyTokenUsageItem(BaseModel):
    date: str
    input_tokens: int
    output_tokens: int
    embedding_tokens: int
    total_tokens: int
    total_cost_usd: float
    query_count: int

class TokenConsumptionResponse(BaseModel):
    summary: TokenConsumptionSummary
    by_model: List[ModelTokenUsageBreakdown]
    by_user: List[UserTokenUsageBreakdown]
    daily_trends: List[DailyTokenUsageItem]
    records: List[TokenConsumptionItem]
    total_records: int
    page: int
    limit: int

class DashboardMetrics(BaseModel):
    total_queries: int
    accuracy_percent: float
    unanswered_count: int
    avg_confidence: float
    trend_queries: List[dict] # {date: string, count: int}
    confidence_distribution: List[dict] # {bucket: string, count: int}

# ================= OPERATIONAL ANALYTICS =================

class OperationalDashboardResponse(BaseModel):
    system_health: str # HEALTHY, DEGRADED, CRITICAL
    slo_compliance_percent: float
    documents_processed: int
    failures: int
    retries: int
    fallbacks: int
    repair_rate: float
    avg_latency_ms: float
    p95_latency_ms: float

class OperationalTrendItem(BaseModel):
    date: str
    entities_per_chunk: float
    triplets_per_chunk: float
    fallback_rate: float
    nodes_created: int
    relationships_created: int

class OperationalTrendResponse(BaseModel):
    trends: List[OperationalTrendItem]

# ================= COST GOVERNANCE =================

class CostCategoryItem(BaseModel):
    document_category: str
    total_tokens: int
    estimated_cost_usd: float

class DailyTokenItem(BaseModel):
    date: str
    input_tokens: int
    output_tokens: int

class CostGovernanceResponse(BaseModel):
    total_tokens_30d: int
    total_cost_usd_30d: float
    total_tokens: Optional[int] = None
    total_cost_usd: Optional[float] = None
    category_breakdown: List[CostCategoryItem]
    daily_tokens: List[DailyTokenItem]

# ================= CAPACITY PLANNING =================

class CapacityProjection(BaseModel):
    current_daily_chunks: float
    projected_30d_daily_chunks: float
    projected_90d_daily_chunks: float
    avg_latency_ms: float
    p95_latency_ms: float
    documents_per_day: float

class CapacityGovernanceResponse(BaseModel):
    projection: CapacityProjection


from typing import Dict, Any


class AppErrorLogSchema(BaseModel):
    id: UUID
    tenant_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    module: str
    endpoint: Optional[str] = None
    error_type: str
    message: str
    stack_trace: Optional[str] = None
    request_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AppErrorLogsPaginatedResponse(BaseModel):
    success: bool = True
    data: List[AppErrorLogSchema]
    meta: Dict[str, Any] = Field(default_factory=dict)


class UserCostItem(BaseModel):
    user_id: UUID
    user_email: str
    total_tokens: int
    total_cost_usd: float
