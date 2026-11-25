"""Admin Module Pydantic Schemas"""

from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from datetime import datetime


class ServiceHealthItem(BaseModel):
    name: str
    status: str  # "healthy", "operational", "degraded", "standby", "offline"
    latency_ms: Optional[float] = None
    message: Optional[str] = None


class SystemHealthDetails(BaseModel):
    score: float = Field(..., description="System health score percentage (e.g. 99.4)")
    status: str = Field(..., description="Overall status: healthy, optimal, or degraded")
    uptime_seconds: int = Field(default=86400)
    last_checked: str
    services: Dict[str, ServiceHealthItem]


class OverviewMetrics(BaseModel):
    total_users: int = Field(..., description="Total valid registered users in tenant")
    total_agents: int = Field(default=0, description="Total active AI agents")
    total_tenants: int = Field(default=0, description="Total active organizations/tenants")
    files_processed: int = Field(default=0, description="Total files and documents processed")
    active_endpoints: int = Field(..., description="Total active API & service endpoints")
    system_health: float = Field(..., description="System health score in percentage")
    total_knowledgebases: int = Field(..., description="Total document & database knowledgebases")


class OverviewBreakdown(BaseModel):
    document_knowledgebases: int = 0
    database_knowledgebases: int = 0
    active_agents: int = 0
    total_tenants: int = 0
    files_processed: int = 0
    total_conversations: int = 0
    total_chunks: int = 0
    total_users_active: int = 0
    api_routes_count: int = 0
    agent_endpoints_count: int = 0
    system_health_details: SystemHealthDetails


class EndpointItem(BaseModel):
    path: str
    method: str
    name: str
    tag: str
    status: str = "active"


class AnnouncementCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    message: str = Field(..., min_length=1)
    priority: str = Field(default="info", description="info, warning, critical, success")
    is_active: bool = True


class AnnouncementUpdate(BaseModel):
    title: Optional[str] = None
    message: Optional[str] = None
    priority: Optional[str] = None
    is_active: Optional[bool] = None


class AnnouncementResponse(BaseModel):
    id: str
    title: str
    message: str
    priority: str
    is_active: bool
    created_at: str
    updated_at: str


class AdminOverviewResponse(BaseModel):
    success: bool = True
    metrics: OverviewMetrics
    breakdown: OverviewBreakdown
    announcements: List[AnnouncementResponse] = []
    last_updated: str

