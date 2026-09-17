"""Health and Diagnostics API Schemas for Phase 3B

Provides structured health check and diagnostic models for target databases.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, ConfigDict, Field


class DatabaseKnowledgebaseHealth(BaseModel):
    """Health status and diagnostic metrics for target database knowledgebase."""
    model_config = ConfigDict(extra="ignore")

    status: str = Field(description="HEALTHY, DEGRADED, or UNHEALTHY")
    database_connectivity: bool = Field(description="Whether the target database responded to ping")
    database_ping_ms: float = Field(description="Latency of the SELECT 1 ping in ms")
    read_only_enforced: bool = Field(description="Whether read-only privilege is actively verified")
    schema_version: str = Field(description="Active schema fingerprint")
    schema_freshness_status: str = Field(description="CURRENT or OUTDATED")
    metrics_summary: Dict[str, Any] = Field(description="Operational summary from metrics registry")
    error: Optional[str] = Field(default=None, description="Diagnostic error if connection degraded")
