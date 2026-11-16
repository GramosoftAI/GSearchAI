"""SuperAdmin API Routes.

Consolidated administration interface:
- Dedicated Authentication, Sessions & Token Management
- MFA (TOTP Authenticator, Backup Codes, WebAuthn / Passkeys)
- Account Lockout, Password Reset, IP Allowlisting, Login History
- Step-Up Authentication for Sensitive Operations
- Role Hierarchy (SUPERADMIN_ROOT) & Configurable Scopes (CRUD)
- Master Dashboard & Platform Overview (MVP)
- Standalone Health & Usage Analytics
- Dashboard Widgets (CRUD)
- Platform Administrative Audit Logs (CRUD & search)
- SuperAdmin Staff Management (CRUD)
"""

from typing import Optional, List
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, Query, Request, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.utils.formatters import format_success, format_paginated
from .models import SuperAdminUser, SuperAdminRole
from .schemas import (
    SuperAdminLoginRequest,
    SuperAdminLoginResponse,
    SuperAdminRefreshTokenRequest,
    SuperAdminTokenResponse,
    SuperAdminUserResponse,
    SuperAdminCreateRequest,
    SuperAdminUpdateRequest,
    SuperAdminChangePasswordRequest,
    TOTPSetupResponse,
    TOTPVerifyRequest,
    MFAVerifyRequest,
    WebAuthnRegisterOptionsResponse,
    WebAuthnRegisterVerifyRequest,
    WebAuthnLoginOptionsResponse,
    WebAuthnLoginVerifyRequest,
    WebAuthnCredentialResponse,
    SuperAdminSessionResponse,
    StepUpAuthRequest,
    StepUpAuthResponse,
    PasswordResetRequest,
    PasswordResetConfirmRequest,
    IPAllowlistUpdateRequest,
    LoginHistoryItem,
    RoleDefinitionCreate,
    RoleDefinitionUpdate,
    RoleDefinitionResponse,
    PermissionScopeItem,
    DashboardOverviewResponse,
    SystemHealthMetric,
    UsageSummaryResponse,
    SuperAdminDashboardWidgetCreate,
    SuperAdminDashboardWidgetUpdate,
    SuperAdminDashboardWidgetResponse,
    AuditLogCreateRequest,
    AuditLogResponse,
    CustomerUserListItem,
    CustomerUserProfileResponse,
    CustomerUserStatusUpdateRequest,
    CustomerUserLockRequest,
    CustomerUserUnlockRequest,
    CustomerUserRoleUpdateRequest,
    CustomerUserTransferTenantRequest,
    CustomerUserPasswordResetTriggerRequest,
    CustomerUserSessionRevokeRequest,
    CustomerUserAIUsageResponse,
    CustomerUserActivityResponse,
    AgentStatusUpdateRequest,
    AgentTransferOwnerRequest,
    SuperAdminAgentListResponse,
    SuperAdminAgentDetailResponse,
    AgentHealthResponse,
    AgentUsageResponse,
    FailingAgentItem,
    SuperAdminKBListResponse,
    SuperAdminKBDetailResponse,
    KBContentResponse,
    KBIngestionRunItem,
    KBProcessingJobItem,
    KBJobActionRequest,
    KBMaintenanceRequest,
    KBDeleteRequest,
    KBReassignRequest,
    KBStorageAnalyticsResponse,
)
from .dependencies import (
    get_superadmin_db,
    get_current_superadmin,
    require_superadmin_role,
    require_permission,
    require_step_up_auth,
    log_admin_activity,
)
from .security import verify_superadmin_access_token
from .services import (
    DashboardService,
    WidgetService,
    AdminService,
    AuditService,
    SuperAdminAuthService,
    WebAuthnService,
    RoleService,
    CustomerUserService,
    AgentGovernanceService,
    KnowledgebaseGovernanceService,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/superadmin", tags=["SuperAdmin"])


# ============================================================================
# 1. SUPERADMIN DEDICATED AUTHENTICATION & SESSIONS
# ============================================================================

@router.post("/auth/login", status_code=status.HTTP_200_OK)
async def superadmin_login(
    req: SuperAdminLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Dedicated SuperAdmin authentication endpoint.
    - Secure bcrypt password verification
    - IP allowlist enforcement
    - Attempt tracking & account lockout after repeated failures
    - Issues MFA challenge if multi-factor authentication is enabled
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    resp = await SuperAdminAuthService.login(
        email=req.email,
        password=req.password,
        client_ip=client_ip,
        user_agent=user_agent,
        device_name=req.device_name,
        db=db,
    )
    return format_success(data=resp.dict())


@router.post("/auth/mfa/verify", status_code=status.HTTP_200_OK)
async def verify_mfa_login(
    req: MFAVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Verify second factor (TOTP or backup recovery code) and issue active session tokens."""
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    resp = await SuperAdminAuthService.verify_mfa_and_login(
        mfa_token=req.mfa_token,
        method=req.method,
        code=req.code,
        client_ip=client_ip,
        user_agent=user_agent,
        device_name=req.device_name,
        db=db,
    )
    return format_success(data=resp.dict())


@router.post("/auth/refresh", status_code=status.HTTP_200_OK)
async def refresh_access_token(
    req: SuperAdminRefreshTokenRequest,
    request: Request,
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Rotate and refresh access token using valid refresh token and active session."""
    client_ip = request.client.host if request.client else None
    tokens = await SuperAdminAuthService.refresh_access_token(
        refresh_token_str=req.refresh_token,
        client_ip=client_ip,
        db=db,
    )
    return format_success(data=tokens.dict())


@router.get("/auth/me", status_code=status.HTTP_200_OK)
async def superadmin_get_me(
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
):
    """Get profile and permissions of the currently authenticated SuperAdmin."""
    admin_data = SuperAdminUserResponse.from_orm(current_admin)
    return format_success(data=admin_data.dict())


@router.post("/auth/logout", status_code=status.HTTP_200_OK)
async def superadmin_logout(
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Revoke current administrative session."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    payload = verify_superadmin_access_token(token)
    session_id = payload.get("session_id") if payload else None

    if session_id:
        try:
            await SuperAdminAuthService.revoke_session(UUID(session_id), current_admin.id, db)
        except Exception:
            pass

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="LOGOUT",
        resource_type="auth",
        resource_id=session_id,
        status_val="SUCCESS",
        request=request,
    )
    return format_success(meta={"message": "Logged out successfully"})


@router.post("/auth/logout-all", status_code=status.HTTP_200_OK)
async def superadmin_logout_all(
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Revoke all active sessions for current SuperAdmin across all devices."""
    count = await SuperAdminAuthService.logout_all_devices(current_admin.id, db)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="LOGOUT_ALL_DEVICES",
        resource_type="auth",
        resource_id=str(current_admin.id),
        details={"revoked_sessions_count": count},
        status_val="SUCCESS",
        request=request,
    )
    return format_success(meta={"message": f"Successfully revoked {count} active session(s) across all devices"})


@router.post("/auth/change-password", status_code=status.HTTP_200_OK)
async def superadmin_change_password(
    req: SuperAdminChangePasswordRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Change current SuperAdmin password."""
    await AdminService.change_password(db, current_admin, req.old_password, req.new_password)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="CHANGE_PASSWORD",
        resource_type="auth",
        resource_id=str(current_admin.id),
        details={"email": current_admin.email},
        status_val="SUCCESS",
        request=request,
    )
    return format_success(meta={"message": "Password changed successfully"})


# ============================================================================
# 2. SESSION LISTING & REMOTE REVOCATION (CRUD)
# ============================================================================

@router.get("/auth/sessions", status_code=status.HTTP_200_OK)
async def list_active_sessions(
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """List all active sessions and connected devices for current SuperAdmin."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    payload = verify_superadmin_access_token(token)
    current_session_id = payload.get("session_id") if payload else None

    sessions = await SuperAdminAuthService.list_active_sessions(
        admin_id=current_admin.id,
        current_session_id=current_session_id,
        db=db,
    )
    return format_success(data=[s.dict() for s in sessions], meta={"total": len(sessions)})


@router.delete("/auth/sessions/{session_id}", status_code=status.HTTP_200_OK)
async def revoke_session_by_id(
    session_id: UUID,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Revoke a specific active administrative session (remote device logout)."""
    await SuperAdminAuthService.revoke_session(session_id, current_admin.id, db)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="REVOKE_SESSION",
        resource_type="session",
        resource_id=str(session_id),
        status_val="SUCCESS",
        request=request,
    )
    return format_success(meta={"message": f"Session {session_id} revoked successfully"})


# ============================================================================
# 3. STEP-UP AUTHENTICATION FOR SENSITIVE OPERATIONS
# ============================================================================

@router.post("/auth/step-up", status_code=status.HTTP_200_OK)
async def step_up_authenticate(
    req: StepUpAuthRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Elevate privileges for sensitive operations.
    Requires password or active TOTP authenticator code.
    Grants a 10-minute elevated privilege window.
    """
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    payload = verify_superadmin_access_token(token)
    session_id = payload.get("session_id") if payload else None

    resp = await SuperAdminAuthService.step_up_authenticate(
        admin=current_admin,
        session_id=session_id,
        password=req.password,
        totp_code=req.totp_code,
        db=db,
    )

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="STEP_UP_AUTH",
        resource_type="auth",
        resource_id=str(current_admin.id),
        details={"valid_until": resp.step_up_valid_until.isoformat()},
        status_val="SUCCESS",
        request=request,
    )
    return format_success(data=resp.dict())


# ============================================================================
# 4. MULTI-FACTOR AUTHENTICATION: TOTP & BACKUP CODES
# ============================================================================

@router.post("/auth/mfa/totp/setup", status_code=status.HTTP_200_OK)
async def setup_totp(
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Initialize TOTP Authenticator: generates secret, QR URI, and backup recovery codes."""
    setup_data = await SuperAdminAuthService.setup_totp(current_admin, db)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="SETUP_TOTP_MFA",
        resource_type="mfa",
        resource_id=str(current_admin.id),
        status_val="SUCCESS",
        request=request,
    )
    return format_success(data=setup_data.dict())


@router.post("/auth/mfa/totp/enable", status_code=status.HTTP_200_OK)
async def enable_totp(
    req: TOTPVerifyRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Verify 6-digit code and activate TOTP multi-factor authentication."""
    await SuperAdminAuthService.enable_totp(current_admin, req.code, db)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="ENABLE_TOTP_MFA",
        resource_type="mfa",
        resource_id=str(current_admin.id),
        status_val="SUCCESS",
        request=request,
    )
    return format_success(meta={"message": "TOTP multi-factor authentication successfully enabled"})


@router.post("/auth/mfa/totp/disable", status_code=status.HTTP_200_OK)
async def disable_totp(
    password: str = Query(..., description="Current password to confirm disabling MFA"),
    request: Request = None,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Disable TOTP multi-factor authentication (requires password verification)."""
    await SuperAdminAuthService.disable_totp(current_admin, password, db)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="DISABLE_TOTP_MFA",
        resource_type="mfa",
        resource_id=str(current_admin.id),
        status_val="SUCCESS",
        request=request,
    )
    return format_success(meta={"message": "TOTP multi-factor authentication disabled"})


# ============================================================================
# 5. WEBAUTHN / PASSKEY AUTHENTICATION (CRUD)
# ============================================================================

@router.post("/auth/webauthn/register/options", status_code=status.HTTP_200_OK)
async def webauthn_register_options(
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
):
    """Generate WebAuthn PublicKeyCredentialCreationOptions for Passkey registration."""
    opts = await WebAuthnService.generate_registration_options(current_admin)
    return format_success(data=opts.dict())


@router.post("/auth/webauthn/register/verify", status_code=status.HTTP_201_CREATED)
async def webauthn_register_verify(
    req: WebAuthnRegisterVerifyRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Verify and register a new Passkey / Security Key."""
    cred = await WebAuthnService.verify_registration(
        admin=current_admin,
        credential_name=req.credential_name,
        credential_id=req.credential_id,
        public_key=req.public_key,
        db=db,
    )

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="REGISTER_WEBAUTHN_KEY",
        resource_type="webauthn",
        resource_id=req.credential_id,
        details={"name": req.credential_name},
        status_val="SUCCESS",
        request=request,
    )
    return format_success(data=cred.dict(), meta={"message": "Passkey registered successfully"})


@router.post("/auth/webauthn/login/options", status_code=status.HTTP_200_OK)
async def webauthn_login_options(
    email: str = Query(..., description="SuperAdmin email"),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Generate PublicKeyCredentialRequestOptions for Passkey authentication challenge."""
    opts = await WebAuthnService.generate_login_options(email=email, db=db)
    return format_success(data=opts.dict())


@router.post("/auth/webauthn/login/verify", status_code=status.HTTP_200_OK)
async def webauthn_login_verify(
    req: WebAuthnLoginVerifyRequest,
    request: Request,
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Verify Passkey assertion and authenticate SuperAdmin."""
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    resp = await WebAuthnService.verify_login(
        mfa_token=req.mfa_token,
        credential_id=req.credential_id,
        client_ip=client_ip,
        user_agent=user_agent,
        device_name=req.device_name,
        db=db,
    )
    return format_success(data=resp.dict())


@router.get("/auth/webauthn/credentials", status_code=status.HTTP_200_OK)
async def list_webauthn_credentials(
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """List registered Passkeys and Security Keys for current SuperAdmin."""
    creds = await WebAuthnService.list_credentials(current_admin.id, db)
    return format_success(data=[c.dict() for c in creds], meta={"total": len(creds)})


@router.delete("/auth/webauthn/credentials/{credential_id}", status_code=status.HTTP_200_OK)
async def delete_webauthn_credential(
    credential_id: str,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Revoke a registered Passkey."""
    await WebAuthnService.delete_credential(credential_id, current_admin.id, db)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="REVOKE_WEBAUTHN_KEY",
        resource_type="webauthn",
        resource_id=credential_id,
        status_val="SUCCESS",
        request=request,
    )
    return format_success(meta={"message": "Passkey credential revoked successfully"})


# ============================================================================
# 6. PASSWORD RESET & RECOVERY
# ============================================================================

@router.post("/auth/password-reset/request", status_code=status.HTTP_200_OK)
async def request_password_reset(
    req: PasswordResetRequest,
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Request a secure password recovery token (valid for 15 minutes)."""
    token_or_msg = await SuperAdminAuthService.request_password_reset(req.email, db)
    return format_success(
        data={"reset_token": token_or_msg},
        meta={"message": "Password recovery request processed."}
    )


@router.post("/auth/password-reset/confirm", status_code=status.HTTP_200_OK)
async def confirm_password_reset(
    req: PasswordResetConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Verify reset token, update password, and revoke all active sessions."""
    await SuperAdminAuthService.confirm_password_reset(req.token, req.new_password, db)
    return format_success(meta={"message": "Password reset successfully. All active sessions revoked."})


# ============================================================================
# 7. IP ALLOWLISTING & LOGIN HISTORY TRACKING
# ============================================================================

@router.put("/auth/ip-allowlist", status_code=status.HTTP_200_OK)
async def update_ip_allowlist(
    req: IPAllowlistUpdateRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Configure allowed IP addresses or CIDR subnets (e.g., 10.0.0.0/8, 192.168.1.50)."""
    await SuperAdminAuthService.update_ip_allowlist(
        admin=current_admin,
        enabled=req.ip_allowlist_enabled,
        allowed_ips=req.allowed_ips,
        db=db,
    )

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="UPDATE_IP_ALLOWLIST",
        resource_type="security",
        resource_id=str(current_admin.id),
        details={"enabled": req.ip_allowlist_enabled, "allowed_ips": req.allowed_ips},
        status_val="SUCCESS",
        request=request,
    )
    return format_success(meta={"message": "IP allowlist configuration updated successfully"})


@router.get("/auth/login-history", status_code=status.HTTP_200_OK)
async def get_login_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """View device and authentication history, IP logs, and attempt tracking."""
    items, total = await SuperAdminAuthService.list_login_history(
        admin_id=current_admin.id,
        limit=limit,
        offset=skip,
        db=db,
    )
    formatted = [LoginHistoryItem.from_orm(h).dict() for h in items]
    return format_paginated(items=formatted, total=total, skip=skip, limit=limit)


# ============================================================================
# 8. SUPERADMIN ROLE HIERARCHY & CONFIGURABLE SCOPES (FULL CRUD)
# ============================================================================

@router.get("/roles/permissions", status_code=status.HTTP_200_OK)
async def get_permissions_catalog(
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
):
    """Catalog of all fine-grained platform permission scopes."""
    scopes = RoleService.get_permissions_catalog()
    return format_success(data=[s.dict() for s in scopes], meta={"total": len(scopes)})


@router.get("/roles", status_code=status.HTTP_200_OK)
async def list_roles(
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """List all platform roles (system roles + custom roles with assigned scopes)."""
    roles = await RoleService.list_roles(db)
    data = [RoleDefinitionResponse.from_orm(r).dict() for r in roles]
    return format_success(data=data, meta={"total": len(data)})


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(
    req: RoleDefinitionCreate,
    request: Request,
    current_admin: SuperAdminUser = Depends(require_superadmin_role([SuperAdminRole.SUPERADMIN_ROOT.value])),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Create a new custom administrative role with assigned permission scopes."""
    role = await RoleService.create_role(req, db)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="CREATE_ROLE",
        resource_type="role",
        resource_id=str(role.id),
        details={"role_name": role.role_name, "permissions": role.permissions},
        status_val="SUCCESS",
        request=request,
    )
    return format_success(data=RoleDefinitionResponse.from_orm(role).dict(), meta={"message": "Role created successfully"})


@router.get("/roles/{role_id}", status_code=status.HTTP_200_OK)
async def get_role_by_id(
    role_id: UUID,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Get details and permission scopes of a specific role."""
    role = await RoleService.get_role(role_id, db)
    return format_success(data=RoleDefinitionResponse.from_orm(role).dict())


@router.put("/roles/{role_id}", status_code=status.HTTP_200_OK)
async def update_role(
    role_id: UUID,
    req: RoleDefinitionUpdate,
    request: Request,
    current_admin: SuperAdminUser = Depends(require_superadmin_role([SuperAdminRole.SUPERADMIN_ROOT.value])),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Update description or configurable permission scopes of a role."""
    role = await RoleService.update_role(role_id, req, db)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="UPDATE_ROLE",
        resource_type="role",
        resource_id=str(role.id),
        details={"role_name": role.role_name, "permissions": role.permissions},
        status_val="SUCCESS",
        request=request,
    )
    return format_success(data=RoleDefinitionResponse.from_orm(role).dict(), meta={"message": "Role updated successfully"})


@router.delete("/roles/{role_id}", status_code=status.HTTP_200_OK)
async def delete_role(
    role_id: UUID,
    request: Request,
    current_admin: SuperAdminUser = Depends(require_superadmin_role([SuperAdminRole.SUPERADMIN_ROOT.value])),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Delete a custom administrative role (system roles cannot be deleted)."""
    await RoleService.delete_role(role_id, db)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="DELETE_ROLE",
        resource_type="role",
        resource_id=str(role_id),
        status_val="SUCCESS",
        request=request,
    )
    return format_success(meta={"message": f"Role {role_id} deleted successfully"})


# ============================================================================
# 9. CONSOLIDATED DASHBOARD & PLATFORM OVERVIEW (MVP REQUIREMENT)
# ============================================================================

@router.get("/dashboard/overview", status_code=status.HTTP_200_OK)
async def get_dashboard_overview(
    start_date: Optional[datetime] = Query(None, description="Filter metrics starting from (ISO 8601)"),
    end_date: Optional[datetime] = Query(None, description="Filter metrics ending at (ISO 8601)"),
    tenant_id: Optional[UUID] = Query(None, description="Optional organization filter for drilldown"),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Consolidated SuperAdmin Dashboard & Platform Overview."""
    overview = await DashboardService.get_overview(
        db=db,
        start_date=start_date,
        end_date=end_date,
        tenant_id=tenant_id,
    )
    return format_success(data=overview.dict())


@router.get("/dashboard/health", status_code=status.HTTP_200_OK)
async def get_system_health(
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Standalone live health diagnostic for Postgres, Neo4j, Redis, and Embedding APIs."""
    health = await DashboardService.check_system_health(db)
    return format_success(data=health.dict())


@router.get("/dashboard/usage-summary", status_code=status.HTTP_200_OK)
async def get_usage_summary(
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    tenant_id: Optional[UUID] = Query(None, description="Optional tenant ID filter"),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Time-series usage trend, LLM model consumption breakdown, and top tenants by spend."""
    usage = await DashboardService.get_usage_summary(
        db=db,
        start_date=start_date,
        end_date=end_date,
        tenant_id=tenant_id,
    )
    return format_success(data=usage.dict())


# ============================================================================
# 10. DASHBOARD WIDGETS (FULL CRUD)
# ============================================================================

@router.post("/dashboard/widgets", status_code=status.HTTP_201_CREATED)
async def create_dashboard_widget(
    req: SuperAdminDashboardWidgetCreate,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Create a new custom dashboard widget / saved metric view."""
    widget = await WidgetService.create_widget(db, req, creator=current_admin)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="CREATE_DASHBOARD_WIDGET",
        resource_type="widget",
        resource_id=str(widget.id),
        details={"name": widget.name, "metric_key": widget.metric_key},
        status_val="SUCCESS",
        request=request,
    )

    data = SuperAdminDashboardWidgetResponse.from_orm(widget)
    return format_success(data=data.dict(), meta={"message": "Dashboard widget created"})


@router.get("/dashboard/widgets", status_code=status.HTTP_200_OK)
async def list_dashboard_widgets(
    only_visible: bool = Query(False, description="Filter only visible widgets"),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """List all dashboard widgets (automatically seeds standard widgets if empty)."""
    widgets = await WidgetService.list_widgets(db, only_visible=only_visible)
    data = [SuperAdminDashboardWidgetResponse.from_orm(w).dict() for w in widgets]
    return format_success(data=data, meta={"total": len(data)})


@router.get("/dashboard/widgets/{widget_id}", status_code=status.HTTP_200_OK)
async def get_dashboard_widget(
    widget_id: UUID,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Get a specific dashboard widget by ID."""
    widget = await WidgetService.get_widget(db, widget_id)
    data = SuperAdminDashboardWidgetResponse.from_orm(widget)
    return format_success(data=data.dict())


@router.put("/dashboard/widgets/{widget_id}", status_code=status.HTTP_200_OK)
async def update_dashboard_widget(
    widget_id: UUID,
    req: SuperAdminDashboardWidgetUpdate,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Update layout, title, config, or visibility of a dashboard widget."""
    widget = await WidgetService.update_widget(db, widget_id, req)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="UPDATE_DASHBOARD_WIDGET",
        resource_type="widget",
        resource_id=str(widget.id),
        details={"name": widget.name, "updated_fields": list(req.dict(exclude_unset=True).keys())},
        status_val="SUCCESS",
        request=request,
    )

    data = SuperAdminDashboardWidgetResponse.from_orm(widget)
    return format_success(data=data.dict(), meta={"message": "Dashboard widget updated"})


@router.delete("/dashboard/widgets/{widget_id}", status_code=status.HTTP_200_OK)
async def delete_dashboard_widget(
    widget_id: UUID,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Delete a dashboard widget."""
    await WidgetService.delete_widget(db, widget_id)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="DELETE_DASHBOARD_WIDGET",
        resource_type="widget",
        resource_id=str(widget_id),
        status_val="SUCCESS",
        request=request,
    )
    return format_success(meta={"message": f"Widget {widget_id} deleted successfully"})


# ============================================================================
# 11. ADMINISTRATIVE AUDIT LOGS (SEARCH & CRUD)
# ============================================================================

@router.get("/audit-logs", status_code=status.HTTP_200_OK)
async def list_audit_logs(
    start_date: Optional[datetime] = Query(None, description="Start date filter"),
    end_date: Optional[datetime] = Query(None, description="End date filter"),
    action: Optional[str] = Query(None, description="Action filter (e.g., SUPERADMIN_LOGIN)"),
    resource_type: Optional[str] = Query(None, description="Resource type filter"),
    admin_email: Optional[str] = Query(None, description="Admin email filter"),
    target_tenant_id: Optional[UUID] = Query(None, description="Target tenant ID filter"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Query, search, and paginate immutable platform administrative audit logs."""
    items, total = await AuditService.list_logs(
        db=db,
        start_date=start_date,
        end_date=end_date,
        action=action,
        resource_type=resource_type,
        admin_email=admin_email,
        target_tenant_id=target_tenant_id,
        limit=limit,
        offset=skip,
    )
    formatted_items = [AuditLogResponse.from_orm(i).dict() for i in items]
    return format_paginated(items=formatted_items, total=total, skip=skip, limit=limit)


@router.post("/audit-logs", status_code=status.HTTP_201_CREATED)
async def record_audit_log(
    req: AuditLogCreateRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Record a custom administrative event or operational note."""
    entry = await AuditService.record_log(
        db=db,
        admin=current_admin,
        req=req,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    data = AuditLogResponse.from_orm(entry)
    return format_success(data=data.dict(), meta={"message": "Audit log recorded"})


@router.get("/audit-logs/{log_id}", status_code=status.HTTP_200_OK)
async def get_audit_log_entry(
    log_id: UUID,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Get single audit log entry by UUID."""
    entry = await AuditService.get_log(db, log_id)
    data = AuditLogResponse.from_orm(entry)
    return format_success(data=data.dict())


# ============================================================================
# 12. SUPERADMIN STAFF MANAGEMENT (FULL CRUD WITH STEP-UP GUARD)
# ============================================================================

@router.post("/admins", status_code=status.HTTP_201_CREATED)
async def create_superadmin(
    req: SuperAdminCreateRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(require_superadmin_role([SuperAdminRole.SUPERADMIN_ROOT.value])),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Create a new platform SuperAdmin staff account (Requires SUPERADMIN_ROOT role)."""
    new_admin = await AdminService.create_admin(db, req)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="CREATE_SUPERADMIN",
        resource_type="superadmin_user",
        resource_id=str(new_admin.id),
        details={"created_email": new_admin.email, "role": new_admin.role},
        status_val="SUCCESS",
        request=request,
    )

    data = SuperAdminUserResponse.from_orm(new_admin)
    return format_success(data=data.dict(), meta={"message": "SuperAdmin account created"})


@router.get("/admins", status_code=status.HTTP_200_OK)
async def list_superadmins(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """List platform SuperAdmin staff accounts with pagination."""
    admins = await AdminService.list_admins(db, limit=limit, offset=skip)
    data = [SuperAdminUserResponse.from_orm(a).dict() for a in admins]
    return format_paginated(items=data, total=len(data), skip=skip, limit=limit)


@router.get("/admins/{admin_id}", status_code=status.HTTP_200_OK)
async def get_superadmin_by_id(
    admin_id: UUID,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Get SuperAdmin staff account details by UUID."""
    admin = await AdminService.get_admin_by_id(db, admin_id)
    data = SuperAdminUserResponse.from_orm(admin)
    return format_success(data=data.dict())


@router.put("/admins/{admin_id}", status_code=status.HTTP_200_OK)
async def update_superadmin(
    admin_id: UUID,
    req: SuperAdminUpdateRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(require_superadmin_role([SuperAdminRole.SUPERADMIN_ROOT.value])),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Update a SuperAdmin staff account role, permissions, or active status."""
    updated = await AdminService.update_admin(db, admin_id, req)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="UPDATE_SUPERADMIN",
        resource_type="superadmin_user",
        resource_id=str(updated.id),
        details={"updated_email": updated.email, "changes": list(req.dict(exclude_unset=True).keys())},
        status_val="SUCCESS",
        request=request,
    )

    data = SuperAdminUserResponse.from_orm(updated)
    return format_success(data=data.dict(), meta={"message": "SuperAdmin account updated"})


@router.delete("/admins/{admin_id}", status_code=status.HTTP_200_OK)
async def delete_superadmin(
    admin_id: UUID,
    request: Request,
    current_admin: SuperAdminUser = Depends(require_superadmin_role([SuperAdminRole.SUPERADMIN_ROOT.value])),
    step_up_verified: SuperAdminUser = Depends(require_step_up_auth),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Delete a SuperAdmin staff account.
    CRITICAL: Requires SUPERADMIN_ROOT role AND Step-Up Authentication.
    """
    if current_admin.id == admin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot delete your own active administrative account.",
        )

    await AdminService.delete_admin(db, admin_id)

    await log_admin_activity(
        db=db,
        admin=current_admin,
        action="DELETE_SUPERADMIN",
        resource_type="superadmin_user",
        resource_id=str(admin_id),
        status_val="SUCCESS",
        request=request,
    )
    return format_success(meta={"message": f"SuperAdmin account {admin_id} deleted successfully"})


# ============================================================================
# 13. CUSTOMER USER MANAGEMENT ACROSS ALL TENANTS (FEATURE 4)
# ============================================================================

@router.get("/users", status_code=status.HTTP_200_OK)
async def list_customer_users(
    search: Optional[str] = Query(None, description="Search by email, name, user ID, or organization name"),
    tenant_id: Optional[UUID] = Query(None, description="Filter by customer organization"),
    role: Optional[str] = Query(None, description="Filter by tenant role ('admin' or 'user')"),
    status: Optional[str] = Query(None, description="Filter by status ('active', 'inactive', 'locked')"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Global directory of customer users across all tenants.
    Supports multi-field search and filtering by organization, role, and active/lock status.
    """
    items, total = await CustomerUserService.list_users(
        db=db,
        search=search,
        tenant_id=tenant_id,
        role=role,
        status_filter=status,
        skip=skip,
        limit=limit,
    )
    return format_paginated(items=[i.dict() for i in items], total=total, skip=skip, limit=limit)


@router.get("/users/{user_id}", status_code=status.HTTP_200_OK)
async def get_customer_user_profile(
    user_id: UUID,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Complete profile for a specific customer user.
    Includes organization details, account creation, last-login, lock status,
    and cross-system activity statistics.
    """
    profile = await CustomerUserService.get_user_profile(user_id=user_id, db=db)
    return format_success(data=profile.dict())


@router.post("/users/{user_id}/status", status_code=status.HTTP_200_OK)
async def update_customer_user_status(
    user_id: UUID,
    req: CustomerUserStatusUpdateRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("users:write")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Activate or deactivate a customer user account across the platform.
    Requires mandatory administrative reason recorded in audit log.
    """
    await CustomerUserService.update_user_status(
        user_id=user_id,
        is_active=req.is_active,
        reason=req.reason,
        admin=current_admin,
        request=request,
        db=db,
    )
    status_label = "activated" if req.is_active else "deactivated"
    return format_success(meta={"message": f"User {user_id} successfully {status_label}"})


@router.post("/users/{user_id}/lock", status_code=status.HTTP_200_OK)
async def lock_customer_user(
    user_id: UUID,
    req: CustomerUserLockRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("users:write")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Temporarily lock a customer user account and revoke active tokens.
    Requires mandatory administrative reason.
    """
    locked_until = await CustomerUserService.lock_user_account(
        user_id=user_id,
        duration_hours=req.duration_hours,
        lock_until=req.lock_until,
        reason=req.reason,
        admin=current_admin,
        request=request,
        db=db,
    )
    return format_success(
        data={"locked_until": locked_until.isoformat()},
        meta={"message": f"User {user_id} locked until {locked_until.isoformat()}"}
    )


@router.post("/users/{user_id}/unlock", status_code=status.HTTP_200_OK)
async def unlock_customer_user(
    user_id: UUID,
    req: CustomerUserUnlockRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("users:write")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Unlock a temporarily locked customer user account.
    Requires mandatory administrative reason.
    """
    await CustomerUserService.unlock_user_account(
        user_id=user_id,
        reason=req.reason,
        admin=current_admin,
        request=request,
        db=db,
    )
    return format_success(meta={"message": f"User {user_id} unlocked successfully"})


@router.post("/users/{user_id}/password-reset", status_code=status.HTTP_200_OK)
async def trigger_customer_user_password_reset(
    user_id: UUID,
    req: CustomerUserPasswordResetTriggerRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("users:write")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Trigger password-reset workflow for a customer user.
    Generates a secure recovery token, invalidates active sessions, and audits the action.
    """
    reset_token = await CustomerUserService.trigger_password_reset(
        user_id=user_id,
        reason=req.reason,
        admin=current_admin,
        request=request,
        db=db,
    )
    return format_success(
        data={"reset_token": reset_token},
        meta={"message": f"Password reset workflow initiated for user {user_id}"}
    )


@router.post("/users/{user_id}/revoke-sessions", status_code=status.HTTP_200_OK)
async def revoke_customer_user_sessions(
    user_id: UUID,
    req: CustomerUserSessionRevokeRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("users:write")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Revoke all active sessions, JWT tokens, and API keys for a customer user.
    Requires mandatory administrative reason.
    """
    await CustomerUserService.revoke_user_sessions(
        user_id=user_id,
        reason=req.reason,
        admin=current_admin,
        request=request,
        db=db,
    )
    return format_success(meta={"message": f"All active sessions and tokens revoked for user {user_id}"})


@router.put("/users/{user_id}/role", status_code=status.HTTP_200_OK)
async def update_customer_user_role(
    user_id: UUID,
    req: CustomerUserRoleUpdateRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("users:write")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Change user role within their tenant organization ('admin' or 'user').
    Requires mandatory administrative reason.
    """
    await CustomerUserService.change_user_role(
        user_id=user_id,
        new_role=req.role,
        reason=req.reason,
        admin=current_admin,
        request=request,
        db=db,
    )
    return format_success(meta={"message": f"Role for user {user_id} updated to '{req.role}'"})


@router.post("/users/{user_id}/transfer-tenant", status_code=status.HTTP_200_OK)
async def transfer_customer_user_tenant(
    user_id: UUID,
    req: CustomerUserTransferTenantRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(require_superadmin_role([SuperAdminRole.SUPERADMIN_ROOT.value])),
    step_up_verified: SuperAdminUser = Depends(require_step_up_auth),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Move a customer user between organizations.
    CRITICAL: Requires SUPERADMIN_ROOT, Step-Up Authentication, and mandatory Authorization Reference.
    Revokes previous tenant sessions and tokens to prevent cross-tenant data leakage.
    """
    await CustomerUserService.transfer_user_tenant(
        user_id=user_id,
        target_tenant_id=req.target_tenant_id,
        authorization_reference=req.authorization_reference,
        reason=req.reason,
        admin=current_admin,
        request=request,
        db=db,
    )
    return format_success(meta={"message": f"User {user_id} successfully transferred to organization {req.target_tenant_id}"})


@router.get("/users/{user_id}/usage", status_code=status.HTTP_200_OK)
async def get_customer_user_ai_usage(
    user_id: UUID,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("usage:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """View user-specific AI usage metrics, token throughput, costs in USD, and model breakdowns."""
    usage = await CustomerUserService.get_user_ai_usage(user_id=user_id, db=db)
    return format_success(data=usage.dict())


@router.get("/users/{user_id}/activity", status_code=status.HTTP_200_OK)
async def get_customer_user_activity(
    user_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("users:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """View user activity timeline, query history, chat sessions, and administrative interventions."""
    activity = await CustomerUserService.get_user_activity(user_id=user_id, limit=limit, db=db)
    return format_success(data=activity.dict())


# ============================================================================
# 14. FEATURE 6: AI AGENTS GOVERNANCE ROUTES
# ============================================================================

@router.get("/agents", status_code=status.HTTP_200_OK, tags=["SuperAdmin AI Agents"])
async def list_agents(
    search: Optional[str] = Query(None, description="Search by name, description, personality, brand"),
    tenant_id: Optional[UUID] = Query(None, description="Filter by customer tenant ID"),
    user_id: Optional[UUID] = Query(None, description="Filter by owner user ID"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    agent_type: Optional[str] = Query(None, description="Filter by 'platform' or 'integrated'"),
    has_errors: Optional[bool] = Query(None, description="Filter for agents with errors in last 24h"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("agents:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """View all AI agents across organizations with search, tenant filter, and operational health status."""
    service = AgentGovernanceService(db)
    res = await service.list_agents(
        search=search,
        tenant_id=tenant_id,
        user_id=user_id,
        is_active=is_active,
        agent_type=agent_type,
        has_errors=has_errors,
        page=page,
        page_size=page_size,
    )
    return format_success(data=res.dict())


@router.get("/agents/analytics/failing", status_code=status.HTTP_200_OK, tags=["SuperAdmin AI Agents"])
async def get_failing_agents(
    threshold: int = Query(3, ge=1, description="Minimum error count threshold"),
    timeframe_hours: int = Query(24, ge=1, le=168, description="Inspection timeframe in hours"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("agents:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Identify AI agents across the platform with repeated failures and high error rates."""
    service = AgentGovernanceService(db)
    failing = await service.get_failing_agents(
        threshold=threshold,
        timeframe_hours=timeframe_hours,
        page=page,
        page_size=page_size,
    )
    return format_success(data=[item.dict() for item in failing])


@router.get("/agents/{agent_id}", status_code=status.HTTP_200_OK, tags=["SuperAdmin AI Agents"])
async def get_agent_detail(
    agent_id: UUID,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("agents:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """View complete agent configuration, prompts, tenant, owner, and associated knowledgebases."""
    service = AgentGovernanceService(db)
    detail = await service.get_agent_detail(agent_id=agent_id)
    return format_success(data=detail.dict())


@router.put("/agents/{agent_id}/status", status_code=status.HTTP_200_OK, tags=["SuperAdmin AI Agents"])
async def update_agent_status(
    agent_id: UUID,
    req: AgentStatusUpdateRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("agents:write")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Activate or deactivate an AI agent with mandatory audit logging."""
    service = AgentGovernanceService(db)
    res = await service.update_agent_status(
        agent_id=agent_id,
        is_active=req.is_active,
        reason=req.reason,
        admin=current_admin,
        request=request,
    )
    return format_success(data=res)


@router.get("/agents/{agent_id}/health", status_code=status.HTTP_200_OK, tags=["SuperAdmin AI Agents"])
async def get_agent_health(
    agent_id: UUID,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("agents:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Inspect agent operational health, failure rates, recent error stack traces, and diagnostics."""
    service = AgentGovernanceService(db)
    health = await service.get_agent_health(agent_id=agent_id)
    return format_success(data=health.dict())


@router.get("/agents/{agent_id}/usage", status_code=status.HTTP_200_OK, tags=["SuperAdmin AI Agents"])
async def get_agent_usage(
    agent_id: UUID,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("agents:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """View agent usage telemetry, session count, query volume, tokens consumed, and cost attribution."""
    service = AgentGovernanceService(db)
    usage = await service.get_agent_usage(agent_id=agent_id)
    return format_success(data=usage.dict())


@router.put("/agents/{agent_id}/transfer-owner", status_code=status.HTTP_200_OK, tags=["SuperAdmin AI Agents"])
async def transfer_agent_ownership(
    agent_id: UUID,
    req: AgentTransferOwnerRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("agents:transfer")),
    step_up_verified: SuperAdminUser = Depends(require_step_up_auth),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Manage agent ownership under authorized policies.
    Requires 'agents:transfer' permission, Step-Up Authentication, and mandatory Authorization Reference.
    """
    service = AgentGovernanceService(db)
    res = await service.transfer_agent_ownership(
        agent_id=agent_id,
        new_user_id=req.new_user_id,
        target_tenant_id=req.target_tenant_id,
        reason=req.reason,
        authorization_reference=req.authorization_reference,
        admin=current_admin,
        request=request,
    )
    return format_success(data=res)


# ============================================================================
# 15. FEATURE 6: KNOWLEDGEBASE GOVERNANCE ROUTES
# ============================================================================

@router.get("/knowledgebases", status_code=status.HTTP_200_OK, tags=["SuperAdmin Knowledgebases"])
async def list_knowledgebases(
    search: Optional[str] = Query(None, description="Search by name, description, or canonical name"),
    tenant_id: Optional[UUID] = Query(None, description="Filter by tenant ID"),
    agent_id: Optional[UUID] = Query(None, description="Filter by associated agent ID"),
    kb_type: Optional[str] = Query(None, description="Filter by 'document' or 'database'"),
    source: Optional[str] = Query(None, description="Filter by source type"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("kb:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """View all customer knowledgebases across organizations with ownership, source, and ingestion status."""
    service = KnowledgebaseGovernanceService(db)
    res = await service.list_knowledgebases(
        search=search,
        tenant_id=tenant_id,
        agent_id=agent_id,
        kb_type=kb_type,
        source=source,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )
    return format_success(data=res.dict())


@router.get("/knowledgebases/analytics/storage", status_code=status.HTTP_200_OK, tags=["SuperAdmin Knowledgebases"])
async def get_kb_storage_analytics(
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("kb:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Monitor platform storage consumption, total chunks, tables, entities, and top tenants by storage."""
    service = KnowledgebaseGovernanceService(db)
    analytics = await service.get_storage_analytics()
    return format_success(data=analytics.dict())


@router.get("/knowledgebases/jobs", status_code=status.HTTP_200_OK, tags=["SuperAdmin Knowledgebases"])
async def list_kb_processing_jobs(
    tenant_id: Optional[UUID] = Query(None, description="Filter by tenant ID"),
    kb_id: Optional[UUID] = Query(None, description="Filter by KB ID"),
    status_filter: Optional[str] = Query(None, description="Filter by status ('queued', 'processing', 'completed', 'failed')"),
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("kb:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Inspect knowledgebase asynchronous processing jobs across all tenants."""
    service = KnowledgebaseGovernanceService(db)
    jobs = await service.list_processing_jobs(
        tenant_id=tenant_id,
        kb_id=kb_id,
        status_filter=status_filter,
        job_type=job_type,
        page=page,
        page_size=page_size,
    )
    return format_success(data=[j.dict() for j in jobs])


@router.get("/knowledgebases/ingestion-runs", status_code=status.HTTP_200_OK, tags=["SuperAdmin Knowledgebases"])
async def list_kb_ingestion_runs(
    kb_id: Optional[UUID] = Query(None, description="Filter by KB ID"),
    tenant_id: Optional[UUID] = Query(None, description="Filter by tenant ID"),
    status_filter: Optional[str] = Query(None, description="Filter by status ('COMPLETED', 'FAILED', 'IN_PROGRESS')"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("kb:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """View synchronization history, extraction telemetry, and document ingestion runs across all tenants."""
    service = KnowledgebaseGovernanceService(db)
    runs = await service.list_ingestion_runs(
        kb_id=kb_id,
        tenant_id=tenant_id,
        status_filter=status_filter,
        page=page,
        page_size=page_size,
    )
    return format_success(data=[r.dict() for r in runs])


@router.get("/knowledgebases/ingestion-runs/failures", status_code=status.HTTP_200_OK, tags=["SuperAdmin Knowledgebases"])
async def list_kb_ingestion_failures(
    tenant_id: Optional[UUID] = Query(None, description="Filter by tenant ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("kb:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Monitor ingestion failures and pipeline anomalies across customer organizations."""
    service = KnowledgebaseGovernanceService(db)
    failures = await service.list_ingestion_runs(
        tenant_id=tenant_id,
        status_filter="FAILED",
        page=page,
        page_size=page_size,
    )
    return format_success(data=[f.dict() for f in failures])


@router.get("/knowledgebases/{kb_id}", status_code=status.HTTP_200_OK, tags=["SuperAdmin Knowledgebases"])
async def get_knowledgebase_detail(
    kb_id: UUID,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("kb:read")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """View knowledgebase ownership, associated agents, document counts, schema, and storage metrics."""
    service = KnowledgebaseGovernanceService(db)
    detail = await service.get_knowledgebase_detail(kb_id=kb_id)
    return format_success(data=detail.dict())


@router.get("/knowledgebases/{kb_id}/content", status_code=status.HTTP_200_OK, tags=["SuperAdmin Knowledgebases"])
async def get_knowledgebase_content(
    kb_id: UUID,
    content_type: str = Query("chunks", description="'chunks', 'tables', 'entities', or 'sections'"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    request: Request = None,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("kb:read_content")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    PERMISSION-CONTROLLED AND AUDITED raw content inspection.
    Customer document content and knowledge data are strictly restricted and require 'kb:read_content'.
    Every access is logged to the platform security audit trail.
    """
    service = KnowledgebaseGovernanceService(db)
    content = await service.get_knowledgebase_content(
        kb_id=kb_id,
        content_type=content_type,
        page=page,
        page_size=page_size,
        admin=current_admin,
        request=request,
    )
    return format_success(data=content.dict())


@router.post("/knowledgebases/jobs/{job_id}/retry", status_code=status.HTTP_200_OK, tags=["SuperAdmin Knowledgebases"])
async def retry_failed_job(
    job_id: UUID,
    req: KBJobActionRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Retry a failed ingestion or processing job with audit logging."""
    service = KnowledgebaseGovernanceService(db)
    res = await service.retry_failed_job(
        job_id=job_id,
        reason=req.reason,
        admin=current_admin,
        request=request,
    )
    return format_success(data=res)


@router.post("/knowledgebases/jobs/{job_id}/cancel", status_code=status.HTTP_200_OK, tags=["SuperAdmin Knowledgebases"])
async def cancel_job(
    job_id: UUID,
    req: KBJobActionRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("kb:write")),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """Cancel a stuck or unwanted background processing job with audit logging."""
    service = KnowledgebaseGovernanceService(db)
    res = await service.cancel_job(
        job_id=job_id,
        reason=req.reason,
        admin=current_admin,
        request=request,
    )
    return format_success(data=res)


@router.post("/knowledgebases/{kb_id}/maintenance", status_code=status.HTTP_200_OK, tags=["SuperAdmin Knowledgebases"])
async def execute_kb_maintenance(
    kb_id: UUID,
    req: KBMaintenanceRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("kb:maintenance")),
    step_up_verified: SuperAdminUser = Depends(require_step_up_auth),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Trigger authorized maintenance or cleanup operations on a knowledgebase.
    Operations: 'generate_noisy_words', 'cleanup_orphaned_chunks', 'purge_failed_runs'.
    Requires 'kb:maintenance' permission and Step-Up Authentication.
    """
    service = KnowledgebaseGovernanceService(db)
    res = await service.execute_maintenance(
        kb_id=kb_id,
        operation=req.operation,
        reason=req.reason,
        admin=current_admin,
        request=request,
    )
    return format_success(data=res)


@router.delete("/knowledgebases/{kb_id}", status_code=status.HTTP_200_OK, tags=["SuperAdmin Knowledgebases"])
async def delete_knowledgebase(
    kb_id: UUID,
    req: KBDeleteRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("kb:delete")),
    step_up_verified: SuperAdminUser = Depends(require_step_up_auth),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Soft-deactivate or permanently purge a knowledgebase under authorized policies.
    Requires 'kb:delete' permission and Step-Up Authentication.
    """
    service = KnowledgebaseGovernanceService(db)
    res = await service.delete_knowledgebase(
        kb_id=kb_id,
        reason=req.reason,
        hard_delete=req.hard_delete,
        admin=current_admin,
        request=request,
    )
    return format_success(data=res)


@router.put("/knowledgebases/{kb_id}/reassign", status_code=status.HTTP_200_OK, tags=["SuperAdmin Knowledgebases"])
async def reassign_knowledgebase(
    kb_id: UUID,
    req: KBReassignRequest,
    request: Request,
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    perm_check: SuperAdminUser = Depends(require_permission("kb:write")),
    step_up_verified: SuperAdminUser = Depends(require_step_up_auth),
    db: AsyncSession = Depends(get_superadmin_db),
):
    """
    Reassign knowledgebase ownership or associated AI agent under authorized policies.
    Requires 'kb:write' permission, Step-Up Authentication, and mandatory Authorization Reference.
    """
    service = KnowledgebaseGovernanceService(db)
    res = await service.reassign_knowledgebase(
        kb_id=kb_id,
        new_agent_id=req.new_agent_id,
        new_user_id=req.new_user_id,
        reason=req.reason,
        authorization_reference=req.authorization_reference,
        admin=current_admin,
        request=request,
    )
    return format_success(data=res)

