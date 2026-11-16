"""SuperAdmin Dependencies: Auth Guards, Role Checks, Step-up Auth, and Platform DB Session."""

from typing import List, Optional, Callable
from uuid import UUID
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.core.database import AsyncSessionLocal
from .models import SuperAdminUser, SuperAdminRole, SuperAdminAuditLog, SuperAdminSession
from .security import verify_superadmin_access_token

logger = logging.getLogger(__name__)
security_scheme = HTTPBearer(auto_error=True)


# ============================================================================
# DATABASE SESSION FOR PLATFORM-LEVEL ACCESS (CROSS-TENANT)
# ============================================================================

async def get_superadmin_db() -> AsyncSession:
    """
    FastAPI dependency yielding a database session for SuperAdmin operations.
    Sets app.is_superadmin = true in PostgreSQL session so platform queries
    can bypass single-tenant RLS restrictions safely.
    """
    async with AsyncSessionLocal() as session:
        try:
            await session.execute(text("SELECT set_config('app.is_superadmin', 'true', false)"))
            yield session
            await session.commit()
        except BaseException as e:
            await session.rollback()
            logger.error(f"SuperAdmin DB session error: {e}")
            raise
        finally:
            await session.close()


# ============================================================================
# CURRENT SUPERADMIN AUTHENTICATION DEPENDENCY
# ============================================================================

async def get_current_superadmin(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_superadmin_db),
) -> SuperAdminUser:
    """
    Validates SuperAdmin JWT token:
    1. Checks token signature & claims (is_superadmin=True)
    2. Checks database for SuperAdminUser existence & active state
    3. If session_id is in token, checks superadmin_sessions table for revocation
    4. Checks account lockout
    """
    token = credentials.credentials
    payload = verify_superadmin_access_token(token)

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid, expired, or non-superadmin token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    admin_id = payload.get("admin_id")
    try:
        admin_uuid = UUID(admin_id)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed administrative user identifier in token.",
        )

    admin = await db.get(SuperAdminUser, admin_uuid)

    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SuperAdmin account not found or has been revoked.",
        )

    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SuperAdmin account is deactivated. Contact platform owner.",
        )

    now = datetime.now(timezone.utc)
    if admin.locked_until and admin.locked_until > now:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account is temporarily locked until {admin.locked_until.isoformat()}.",
        )

    # Check session revocation if session_id present
    session_id_str = payload.get("session_id")
    if session_id_str:
        try:
            s_uuid = UUID(session_id_str)
            session_rec = await db.get(SuperAdminSession, s_uuid)
            if session_rec:
                if session_rec.is_revoked or session_rec.expires_at < now:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Administrative session has been revoked or expired.",
                    )
                # Update last active
                session_rec.last_active_at = now
                db.add(session_rec)
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Session check error: {e}")

    return admin


# ============================================================================
# ROLE AND PERMISSION GUARDS
# ============================================================================

def require_superadmin_role(allowed_roles: List[str]) -> Callable:
    """
    Dependency factory restricting endpoints to specific SuperAdmin roles.
    SUPERADMIN_ROOT always bypasses role checks.
    """
    async def role_checker(
        current_admin: SuperAdminUser = Depends(get_current_superadmin)
    ) -> SuperAdminUser:
        # SUPERADMIN_ROOT has unrestricted platform authority
        if current_admin.role == SuperAdminRole.SUPERADMIN_ROOT.value:
            return current_admin

        allowed_values = [r.value if isinstance(r, SuperAdminRole) else str(r) for r in allowed_roles]
        if current_admin.role not in allowed_values:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Required role in {allowed_values}. Current role: {current_admin.role}",
            )
        return current_admin
    return role_checker


def require_permission(required_perm: str) -> Callable:
    """
    Dependency factory ensuring current SuperAdmin has a required permission scope.
    Wildcard '*' or SUPERADMIN_ROOT grants universal permission.
    """
    async def perm_checker(
        current_admin: SuperAdminUser = Depends(get_current_superadmin),
        db: AsyncSession = Depends(get_superadmin_db),
    ) -> SuperAdminUser:
        if current_admin.role == SuperAdminRole.SUPERADMIN_ROOT.value:
            return current_admin

        perms = current_admin.permissions or []
        if "*" in perms or required_perm in perms:
            return current_admin

        # Prefix match (e.g. 'orgs:*' matches 'orgs:read')
        prefix = required_perm.split(":")[0] + ":*"
        if prefix in perms:
            return current_admin

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Missing required platform permission scope '{required_perm}'.",
        )
    return perm_checker


# ============================================================================
# STEP-UP AUTHENTICATION GUARD
# ============================================================================

async def require_step_up_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    current_admin: SuperAdminUser = Depends(get_current_superadmin),
    db: AsyncSession = Depends(get_superadmin_db),
) -> SuperAdminUser:
    """
    Guards high-risk administrative operations (account deletion, credentials wipe, root overrides).
    Requires that the caller has performed step-up authentication within the last 10 minutes.
    """
    token = credentials.credentials
    payload = verify_superadmin_access_token(token)
    session_id_str = payload.get("session_id") if payload else None

    now = datetime.now(timezone.utc)
    step_up_active = False

    if session_id_str:
        try:
            session = await db.get(SuperAdminSession, UUID(session_id_str))
            if session and session.step_up_until and session.step_up_until > now:
                step_up_active = True
        except Exception:
            pass

    if not step_up_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Step-up authentication required for this sensitive operation. Please call POST /api/v1/superadmin/auth/step-up first.",
            headers={"X-Step-Up-Required": "true"},
        )

    return current_admin


# ============================================================================
# AUDIT LOGGING HELPER
# ============================================================================

async def log_admin_activity(
    db: AsyncSession,
    admin: SuperAdminUser,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    target_tenant_id: Optional[UUID] = None,
    details: Optional[dict] = None,
    status_val: str = "SUCCESS",
    request: Optional[Request] = None,
) -> SuperAdminAuditLog:
    """Record an administrative action into the immutable audit trail."""
    ip_addr = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None

    entry = SuperAdminAuditLog(
        admin_id=admin.id,
        admin_email=admin.email,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        target_tenant_id=target_tenant_id,
        status=status_val,
        details=details or {},
        ip_address=ip_addr,
        user_agent=user_agent,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry
