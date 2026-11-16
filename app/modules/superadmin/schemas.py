"""SuperAdmin Pydantic Schemas.

Comprehensive request/response models for:
- Authentication & Sessions (Tokens, MFA, TOTP, WebAuthn, Step-up)
- Security Governance (Account Lockout, Password Reset, IP Allowlisting, History)
- Role Hierarchy & Scope Management (SUPERADMIN_ROOT, Configurable Scopes)
- Consolidated Dashboard & Platform Overview (MVP)
- Dashboard Widgets CRUD & Audit Logging
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field, EmailStr
from .models import SuperAdminRole


# ============================================================================
# 1. AUTHENTICATION, TOKENS & MFA SCHEMAS
# ============================================================================

class SuperAdminLoginRequest(BaseModel):
    email: EmailStr
    password: str
    device_name: Optional[str] = Field("Web Browser", description="Friendly device identifier")


class SuperAdminTokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    session_id: Optional[str] = None
    token_type: str = "bearer"
    expires_in_minutes: int
    admin_id: str
    email: str
    role: str
    permissions: List[str] = Field(default_factory=list)


class SuperAdminUserResponse(BaseModel):
    id: UUID
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    permissions: List[str] = Field(default_factory=list)
    is_active: bool
    mfa_enabled: bool = False
    totp_enabled: bool = False
    webauthn_enabled: bool = False
    ip_allowlist_enabled: bool = False
    allowed_ips: List[str] = Field(default_factory=list)
    last_login_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SuperAdminLoginResponse(BaseModel):
    """Returned from login endpoint; indicates whether MFA challenge is required."""
    mfa_required: bool = False
    mfa_token: Optional[str] = None
    allowed_methods: List[str] = Field(default_factory=list)  # ["totp", "webauthn", "backup_code"]
    tokens: Optional[SuperAdminTokenResponse] = None
    admin: Optional[SuperAdminUserResponse] = None
    message: Optional[str] = None


class SuperAdminRefreshTokenRequest(BaseModel):
    refresh_token: str


# ============================================================================
# 2. MFA: TOTP & BACKUP CODES
# ============================================================================

class TOTPSetupResponse(BaseModel):
    secret: str
    otpauth_url: str
    backup_codes: List[str]
    message: str = "Scan QR code or enter secret into your authenticator app, then verify."


class TOTPVerifyRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class MFAVerifyRequest(BaseModel):
    mfa_token: str
    method: str = Field("totp", description="'totp', 'backup_code', or 'webauthn'")
    code: Optional[str] = Field(None, description="6-digit TOTP code or backup code")
    device_name: Optional[str] = "Web Browser"


# ============================================================================
# 3. WEBAUTHN / PASSKEY SCHEMAS
# ============================================================================

class WebAuthnRegisterOptionsResponse(BaseModel):
    challenge: str
    rp: Dict[str, Any]
    user: Dict[str, Any]
    pubKeyCredParams: List[Dict[str, Any]]
    timeout: int = 60000
    attestation: str = "none"


class WebAuthnRegisterVerifyRequest(BaseModel):
    credential_name: str = Field("Security Key / Passkey", max_length=255)
    credential_id: str
    public_key: str
    client_data_json: Optional[str] = None
    attestation_object: Optional[str] = None


class WebAuthnLoginOptionsResponse(BaseModel):
    challenge: str
    allowCredentials: List[Dict[str, Any]] = Field(default_factory=list)
    timeout: int = 60000


class WebAuthnLoginVerifyRequest(BaseModel):
    mfa_token: Optional[str] = None
    credential_id: str
    authenticator_data: Optional[str] = None
    client_data_json: Optional[str] = None
    signature: Optional[str] = None
    device_name: Optional[str] = "Web Browser"


class WebAuthnCredentialResponse(BaseModel):
    id: UUID
    credential_name: str
    credential_id: str
    sign_count: int
    created_at: datetime
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================================================
# 4. SESSIONS & STEP-UP AUTHENTICATION SCHEMAS
# ============================================================================

class SuperAdminSessionResponse(BaseModel):
    id: UUID
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    device_name: Optional[str] = None
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime
    is_current: bool = False
    step_up_active: bool = False

    class Config:
        from_attributes = True


class StepUpAuthRequest(BaseModel):
    password: Optional[str] = None
    totp_code: Optional[str] = None


class StepUpAuthResponse(BaseModel):
    success: bool
    step_up_valid_until: datetime
    message: str


# ============================================================================
# 5. PASSWORD RESET & IP ALLOWLISTING SCHEMAS
# ============================================================================

class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str = Field(..., min_length=8)


class IPAllowlistUpdateRequest(BaseModel):
    ip_allowlist_enabled: bool
    allowed_ips: List[str] = Field(default_factory=list)


class LoginHistoryItem(BaseModel):
    id: UUID
    email: str
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    device_info: Optional[str] = None
    status: str
    failure_reason: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# 6. CONFIGURABLE ROLES & PERMISSIONS SCHEMAS
# ============================================================================

class PermissionScopeItem(BaseModel):
    scope: str
    category: str
    description: str


class RoleDefinitionCreate(BaseModel):
    role_name: str = Field(..., max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    permissions: List[str] = Field(default_factory=list)


class RoleDefinitionUpdate(BaseModel):
    description: Optional[str] = None
    permissions: Optional[List[str]] = None


class RoleDefinitionResponse(BaseModel):
    id: UUID
    role_name: str
    description: Optional[str] = None
    is_system: bool
    permissions: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# 7. SUPERADMIN STAFF MANAGEMENT SCHEMAS
# ============================================================================

class SuperAdminCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str = SuperAdminRole.SUPERADMIN_ROOT.value
    permissions: List[str] = Field(default_factory=lambda: ["*"])
    ip_allowlist_enabled: bool = False
    allowed_ips: List[str] = Field(default_factory=list)


class SuperAdminUpdateRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[str] = None
    permissions: Optional[List[str]] = None
    is_active: Optional[bool] = None
    ip_allowlist_enabled: Optional[bool] = None
    allowed_ips: Optional[List[str]] = None
    password: Optional[str] = Field(None, min_length=8)


class SuperAdminChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=8)


# ============================================================================
# 8. DASHBOARD OVERVIEW & METRICS SCHEMAS
# ============================================================================

class OrganizationsMetric(BaseModel):
    total: int = 0
    active: int = 0
    suspended: int = 0
    inactive: int = 0
    new_last_30_days: int = 0


class UsersMetric(BaseModel):
    total: int = 0
    active: int = 0
    inactive: int = 0
    tenant_admins: int = 0
    standard_users: int = 0
    new_last_30_days: int = 0


class AgentsMetric(BaseModel):
    total: int = 0
    platform_agents: int = 0
    integrated_agents: int = 0
    active_agents: int = 0


class KnowledgeBasesMetric(BaseModel):
    total: int = 0
    document_kbs: int = 0
    database_kbs: int = 0
    total_chunks: int = 0


class IntegrationsMetric(BaseModel):
    total_connected: int = 0
    google_drive: int = 0
    gmail: int = 0
    slack: int = 0
    sharepoint: int = 0


class DocumentsAndJobsMetric(BaseModel):
    total_documents: int = 0
    total_chunks: int = 0
    total_jobs: int = 0
    queued_jobs: int = 0
    processing_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0


class ApiStatisticsMetric(BaseModel):
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    error_rate_pct: float = 0.0
    total_tokens: int = 0
    total_llm_tokens: int = 0
    total_embedding_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0


class ServiceHealthItem(BaseModel):
    service_name: str
    status: str  # "healthy", "degraded", "down", "not_configured"
    response_time_ms: float = 0.0
    last_checked: datetime = Field(default_factory=datetime.utcnow)
    message: Optional[str] = None


class SystemHealthMetric(BaseModel):
    overall_status: str  # "healthy", "degraded", "down"
    services: List[ServiceHealthItem] = Field(default_factory=list)


class AuditActivitySummaryItem(BaseModel):
    id: UUID
    admin_email: str
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    target_tenant_id: Optional[UUID] = None
    status: str
    details: Optional[Dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DashboardOverviewResponse(BaseModel):
    """The master consolidated SuperAdmin dashboard response."""
    organizations: OrganizationsMetric
    users: UsersMetric
    agents: AgentsMetric
    knowledge_bases: KnowledgeBasesMetric
    integrations: IntegrationsMetric
    documents_and_jobs: DocumentsAndJobsMetric
    api_statistics: ApiStatisticsMetric
    system_health: SystemHealthMetric
    recent_activities: List[AuditActivitySummaryItem] = Field(default_factory=list)
    filters_applied: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================================
# 9. USAGE SUMMARY & TIME-SERIES BREAKDOWNS
# ============================================================================

class DailyUsagePoint(BaseModel):
    date: str
    requests: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    error_count: int = 0


class ModelUsageBreakdown(BaseModel):
    model_name: str
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class TenantUsageBreakdown(BaseModel):
    tenant_id: UUID
    tenant_name: str
    requests: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class UsageSummaryResponse(BaseModel):
    summary: ApiStatisticsMetric
    daily_trend: List[DailyUsagePoint] = Field(default_factory=list)
    model_breakdown: List[ModelUsageBreakdown] = Field(default_factory=list)
    top_tenants: List[TenantUsageBreakdown] = Field(default_factory=list)


# ============================================================================
# 10. DASHBOARD WIDGETS CRUD SCHEMAS
# ============================================================================

class SuperAdminDashboardWidgetCreate(BaseModel):
    name: str = Field(..., max_length=255)
    widget_type: str = Field("METRIC_CARD", description="METRIC_CARD, CHART, LIST, HEALTH")
    metric_key: str = Field(..., max_length=100, description="organizations, users, agents, etc.")
    title: str = Field(..., max_length=255)
    description: Optional[str] = Field(None, max_length=500)
    layout_row: int = 0
    layout_col: int = 0
    layout_width: int = 1
    layout_height: int = 1
    is_visible: bool = True
    config: Optional[Dict[str, Any]] = Field(default_factory=dict)


class SuperAdminDashboardWidgetUpdate(BaseModel):
    name: Optional[str] = None
    widget_type: Optional[str] = None
    metric_key: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    layout_row: Optional[int] = None
    layout_col: Optional[int] = None
    layout_width: Optional[int] = None
    layout_height: Optional[int] = None
    is_visible: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None


class SuperAdminDashboardWidgetResponse(BaseModel):
    id: UUID
    name: str
    widget_type: str
    metric_key: str
    title: str
    description: Optional[str] = None
    layout_row: int
    layout_col: int
    layout_width: int
    layout_height: int
    is_visible: bool
    config: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# 11. AUDIT LOG SCHEMAS
# ============================================================================

class AuditLogCreateRequest(BaseModel):
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    target_tenant_id: Optional[UUID] = None
    status: str = "SUCCESS"
    details: Optional[Dict[str, Any]] = None


class AuditLogResponse(BaseModel):
    id: UUID
    admin_id: Optional[UUID] = None
    admin_email: str
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    target_tenant_id: Optional[UUID] = None
    status: str
    details: Optional[Dict[str, Any]] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogPaginatedResponse(BaseModel):
    items: List[AuditLogResponse]
    total: int
    limit: int
    offset: int


# ============================================================================
# 12. CUSTOMER TENANT USERS MANAGEMENT SCHEMAS
# ============================================================================

class CustomerUserListItem(BaseModel):
    id: UUID
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    is_active: bool
    is_locked: bool = False
    locked_until: Optional[datetime] = None
    lock_reason: Optional[str] = None
    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    preferred_llm_model: Optional[str] = None
    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CustomerUserStats(BaseModel):
    total_chat_sessions: int = 0
    total_messages: int = 0
    total_queries: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    active_api_keys_count: int = 0


class CustomerUserProfileResponse(BaseModel):
    id: UUID
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    is_active: bool
    is_locked: bool = False
    locked_until: Optional[datetime] = None
    lock_reason: Optional[str] = None
    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    tenant_is_active: bool
    preferred_llm_model: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime] = None
    stats: CustomerUserStats


class CustomerUserStatusUpdateRequest(BaseModel):
    is_active: bool
    reason: str = Field(..., min_length=3, description="Mandatory reason for audit trail")


class CustomerUserLockRequest(BaseModel):
    duration_hours: Optional[int] = Field(24, ge=1, le=8760, description="Lock duration in hours (default 24h)")
    lock_until: Optional[datetime] = Field(None, description="Exact timestamp until locked")
    reason: str = Field(..., min_length=3, description="Mandatory reason for audit trail")


class CustomerUserUnlockRequest(BaseModel):
    reason: str = Field(..., min_length=3, description="Mandatory reason for audit trail")


class CustomerUserRoleUpdateRequest(BaseModel):
    role: str = Field(..., description="'admin' or 'user'")
    reason: str = Field(..., min_length=3, description="Mandatory reason for audit trail")


class CustomerUserTransferTenantRequest(BaseModel):
    target_tenant_id: UUID
    authorization_reference: str = Field(..., min_length=3, description="Authorization ticket or approved reference")
    reason: str = Field(..., min_length=3, description="Mandatory reason for audit trail")


class CustomerUserPasswordResetTriggerRequest(BaseModel):
    reason: str = Field(..., min_length=3, description="Mandatory reason for audit trail")


class CustomerUserSessionRevokeRequest(BaseModel):
    reason: str = Field(..., min_length=3, description="Mandatory reason for audit trail")


class CustomerUserAIUsageResponse(BaseModel):
    user_id: UUID
    email: str
    tenant_id: UUID
    tenant_name: str
    total_queries: int = 0
    total_tokens: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    embedding_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    model_breakdown: List[ModelUsageBreakdown] = Field(default_factory=list)


class CustomerUserActivityItem(BaseModel):
    id: str
    activity_type: str  # "QUERY", "CHAT_SESSION", "SUPERADMIN_ACTION"
    title: str
    description: str
    details: Optional[Dict[str, Any]] = None
    created_at: datetime


class CustomerUserActivityResponse(BaseModel):
    user_id: UUID
    activities: List[CustomerUserActivityItem] = Field(default_factory=list)
    total: int


# ============================================================================
# 13. FEATURE 6: AI AGENTS AND KNOWLEDGEBASE ADMINISTRATION SCHEMAS
# ============================================================================

class SuperAdminAgentKBItem(BaseModel):
    id: UUID
    name: str
    source: str
    total_chunks: int = 0
    is_active: bool
    created_at: datetime


class SuperAdminAgentListItem(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    personality: Optional[str] = None
    agent_type: str = "platform"
    is_active: bool
    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    user_id: UUID
    user_email: str
    knowledgebase_count: int = 0
    total_queries: int = 0
    error_count_24h: int = 0
    health_status: str = "HEALTHY"  # HEALTHY, WARNING, CRITICAL
    created_at: datetime
    updated_at: datetime


class SuperAdminAgentListResponse(BaseModel):
    agents: List[SuperAdminAgentListItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    total_pages: int


class SuperAdminAgentDetailResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    personality: Optional[str] = None
    personality_id: Optional[UUID] = None
    system_prompt: Optional[str] = None
    agent_type: str
    organization_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    website_url: Optional[str] = None
    fallback_message_enabled: bool = True
    brand_persona: Optional[str] = None
    is_active: bool
    tenant_id: UUID
    tenant_name: str
    tenant_slug: str
    user_id: UUID
    user_email: str
    knowledgebases: List[SuperAdminAgentKBItem] = Field(default_factory=list)
    database_knowledgebases: List[Dict[str, Any]] = Field(default_factory=list)
    total_sessions: int = 0
    total_queries: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0
    error_count_24h: int = 0
    health_status: str = "HEALTHY"
    created_at: datetime
    updated_at: datetime


class AgentStatusUpdateRequest(BaseModel):
    is_active: bool
    reason: str = Field(..., min_length=3, description="Mandatory reason for audit log")


class AgentTransferOwnerRequest(BaseModel):
    new_user_id: UUID
    target_tenant_id: Optional[UUID] = None
    reason: str = Field(..., min_length=3, description="Mandatory reason for audit log")
    authorization_reference: str = Field(..., min_length=3, description="Authorization ticket or approved reference")


class AgentErrorItem(BaseModel):
    id: UUID
    module: str
    endpoint: Optional[str] = None
    error_type: str
    message: str
    stack_trace: Optional[str] = None
    created_at: datetime


class AgentHealthResponse(BaseModel):
    agent_id: UUID
    name: str
    tenant_id: UUID
    tenant_name: str
    health_status: str  # HEALTHY, WARNING, CRITICAL
    success_rate: float
    total_queries_24h: int
    error_count_24h: int
    error_count_7d: int
    last_error_at: Optional[datetime] = None
    recent_errors: List[AgentErrorItem] = Field(default_factory=list)


class AgentUsageResponse(BaseModel):
    agent_id: UUID
    name: str
    tenant_id: UUID
    tenant_name: str
    total_sessions: int = 0
    total_queries: int = 0
    total_tokens: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    embedding_tokens: int = 0
    total_cost_usd: float = 0.0
    avg_latency_ms: float = 0.0


class FailingAgentItem(BaseModel):
    agent_id: UUID
    name: str
    tenant_id: UUID
    tenant_name: str
    owner_email: str
    error_count_24h: int
    total_queries_24h: int
    failure_rate_percent: float
    last_error_message: Optional[str] = None
    last_error_at: Optional[datetime] = None
    primary_error_types: List[str] = Field(default_factory=list)


# --- KNOWLEDGEBASE SCHEMAS ---

class SuperAdminKBListItem(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    canonical_name: Optional[str] = None
    kb_type: str = "document"  # "document" or "database"
    source: str
    total_chunks: int = 0
    is_active: bool
    tenant_id: UUID
    tenant_name: str
    user_id: UUID
    user_email: str
    agent_id: Optional[UUID] = None
    agent_name: Optional[str] = None
    last_ingestion_status: Optional[str] = None
    last_ingestion_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class SuperAdminKBListResponse(BaseModel):
    knowledgebases: List[SuperAdminKBListItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    total_pages: int


class SuperAdminKBDetailResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    canonical_name: Optional[str] = None
    kb_type: str = "document"
    source: str
    total_chunks: int = 0
    is_active: bool
    tenant_id: UUID
    tenant_name: str
    user_id: UUID
    user_email: str
    agent_id: Optional[UUID] = None
    agent_name: Optional[str] = None
    s3_path: Optional[str] = None
    parsed_path: Optional[str] = None
    file_hash: Optional[str] = None
    aliases: Optional[List[str]] = None
    dataset_schema: Optional[Dict[str, Any]] = None
    storage_stats: Dict[str, int] = Field(default_factory=dict)
    db_connection: Optional[Dict[str, Any]] = None
    recent_ingestion_runs: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class KBContentItem(BaseModel):
    id: UUID
    content_type: str  # "chunk", "table_row", "entity", "section"
    index_or_page: Optional[int] = None
    section: Optional[str] = None
    preview_text: str
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime


class KBContentResponse(BaseModel):
    kb_id: UUID
    kb_name: str
    tenant_id: UUID
    tenant_name: str
    content_type: str
    total_items: int
    page: int
    page_size: int
    items: List[KBContentItem] = Field(default_factory=list)
    audit_warning: str = "Viewing customer knowledgebase content has been logged in the platform security audit trail."


class KBIngestionRunItem(BaseModel):
    id: UUID
    document_id: UUID
    kb_name: Optional[str] = None
    tenant_id: UUID
    tenant_name: Optional[str] = None
    status: str
    chunk_count: int = 0
    entity_count: int = 0
    triplet_count: int = 0
    repair_count: int = 0
    retry_count: int = 0
    llm_calls: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    embedding_tokens: int = 0
    embedding_cost_usd: float = 0.0
    total_duration_ms: int = 0
    error_message: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None


class KBProcessingJobItem(BaseModel):
    id: UUID
    tenant_id: UUID
    tenant_name: Optional[str] = None
    user_id: UUID
    kb_id: Optional[UUID] = None
    kb_name: Optional[str] = None
    job_type: str
    status: str
    progress: int = 0
    current_step: Optional[str] = None
    error_message: Optional[str] = None
    file_name: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class KBJobActionRequest(BaseModel):
    reason: str = Field(..., min_length=3, description="Mandatory reason for audit log")


class KBMaintenanceRequest(BaseModel):
    operation: str = Field(..., description="'generate_noisy_words', 'cleanup_orphaned_chunks', 'refresh_summary_embedding', 'purge_failed_runs'")
    reason: str = Field(..., min_length=3, description="Mandatory reason for audit log")


class KBDeleteRequest(BaseModel):
    reason: str = Field(..., min_length=3, description="Mandatory reason for audit log")
    hard_delete: bool = False


class KBReassignRequest(BaseModel):
    new_agent_id: Optional[UUID] = None
    new_user_id: Optional[UUID] = None
    reason: str = Field(..., min_length=3, description="Mandatory reason for audit log")
    authorization_reference: str = Field(..., min_length=3, description="Authorization ticket or approved reference")


class KBStorageAnalyticsResponse(BaseModel):
    total_knowledgebases: int
    total_document_kbs: int
    total_database_kbs: int
    total_chunks: int
    total_table_rows: int
    total_entities: int
    total_sections: int
    top_tenants_by_storage: List[Dict[str, Any]] = Field(default_factory=list)


