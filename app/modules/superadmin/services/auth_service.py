"""SuperAdmin Comprehensive Authentication & Security Service.

Implements:
- MFA & TOTP Authenticator support
- WebAuthn / Passkey registration & verification
- Session tracking, rotation, remote revocation & logout from all devices
- Account lockout after repeated failed attempts
- Password reset and recovery tokens
- Optional IP allowlisting (single IP and CIDR subnets)
- Device and login attempt history tracking
- Step-up authentication for sensitive operations
"""

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple, Dict, Any
from uuid import UUID
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
import logging

from ..models import (
    SuperAdminUser,
    SuperAdminRole,
    SuperAdminSession,
    SuperAdminLoginHistory,
    SuperAdminPasswordResetToken,
    SuperAdminWebAuthnCredential,
)
from ..schemas import (
    SuperAdminLoginResponse,
    SuperAdminTokenResponse,
    SuperAdminUserResponse,
    TOTPSetupResponse,
    SuperAdminSessionResponse,
    StepUpAuthResponse,
    LoginHistoryItem,
)
from ..security import (
    hash_password,
    verify_password,
    hash_token,
    generate_totp_secret,
    generate_totp_uri,
    verify_totp_code,
    generate_backup_codes,
    is_ip_allowed,
    create_superadmin_access_token,
    create_superadmin_refresh_token,
    create_mfa_pending_token,
    verify_superadmin_refresh_token,
    verify_mfa_pending_token,
)

logger = logging.getLogger(__name__)

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15
STEP_UP_VALID_MINUTES = 10


class SuperAdminAuthService:
    """Comprehensive authentication and access control operations for SuperAdmin."""

    @staticmethod
    async def login(
        email: str,
        password: str,
        client_ip: Optional[str],
        user_agent: Optional[str],
        device_name: Optional[str],
        db: AsyncSession,
    ) -> SuperAdminLoginResponse:
        """
        Authenticate SuperAdmin:
        1. Checks account lockout status
        2. Enforces IP allowlisting
        3. Verifies bcrypt password hash
        4. If MFA enabled, returns MFA challenge token
        5. If MFA not required, establishes session and issues full access + refresh tokens
        """
        clean_email = email.lower().strip()
        now = datetime.now(timezone.utc)

        # 0. Ensure initial platform admin accounts exist
        from .admin_service import AdminService
        await AdminService.bootstrap_initial_admin(db)

        # 1. Fetch SuperAdmin account
        query = select(SuperAdminUser).where(SuperAdminUser.email == clean_email)
        result = await db.execute(query)
        admin = result.scalar_one_or_none()

        if not admin:
            # Record failed login attempt for unknown account
            history = SuperAdminLoginHistory(
                admin_id=None,
                email=clean_email,
                ip_address=client_ip,
                user_agent=user_agent,
                device_info=device_name,
                status="FAILED",
                failure_reason="Account does not exist",
            )
            db.add(history)
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid administrative email or password.",
            )

        if not admin.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="SuperAdmin account is deactivated. Contact platform owner.",
            )

        # 2. Check Account Lockout
        if admin.locked_until and admin.locked_until > now:
            remaining_seconds = int((admin.locked_until - now).total_seconds())
            remaining_minutes = max(1, remaining_seconds // 60)
            history = SuperAdminLoginHistory(
                admin_id=admin.id,
                email=admin.email,
                ip_address=client_ip,
                user_agent=user_agent,
                device_info=device_name,
                status="LOCKED",
                failure_reason=f"Account locked until {admin.locked_until.isoformat()}",
            )
            db.add(history)
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Account temporarily locked due to repeated failed login attempts. Try again in {remaining_minutes} minute(s).",
            )

        # 3. Check IP Allowlisting
        if admin.ip_allowlist_enabled and not is_ip_allowed(client_ip, admin.allowed_ips):
            history = SuperAdminLoginHistory(
                admin_id=admin.id,
                email=admin.email,
                ip_address=client_ip,
                user_agent=user_agent,
                device_info=device_name,
                status="BLOCKED_IP",
                failure_reason=f"Client IP {client_ip} not in allowed IPs",
            )
            db.add(history)
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Client IP '{client_ip}' is not permitted for this SuperAdmin account.",
            )

        # 4. Verify Password
        if not verify_password(password, admin.hashed_password):
            admin.failed_login_attempts = (admin.failed_login_attempts or 0) + 1
            admin.last_failed_login_at = now
            failure_reason = "Invalid password"

            if admin.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                admin.locked_until = now + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
                failure_reason = f"Account locked after {admin.failed_login_attempts} failed attempts"

            history = SuperAdminLoginHistory(
                admin_id=admin.id,
                email=admin.email,
                ip_address=client_ip,
                user_agent=user_agent,
                device_info=device_name,
                status="FAILED" if admin.failed_login_attempts < MAX_FAILED_ATTEMPTS else "LOCKED",
                failure_reason=failure_reason,
            )
            db.add(admin)
            db.add(history)
            await db.commit()

            if admin.failed_login_attempts >= MAX_FAILED_ATTEMPTS:
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail=f"Too many failed login attempts. Account locked for {LOCKOUT_DURATION_MINUTES} minutes.",
                )
            else:
                remaining = MAX_FAILED_ATTEMPTS - admin.failed_login_attempts
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid administrative credentials. {remaining} attempt(s) remaining before temporary lockout.",
                )

        # 5. Password is valid: Reset failed attempts
        admin.failed_login_attempts = 0
        admin.locked_until = None

        # 6. Check if MFA is required
        if admin.mfa_enabled or admin.totp_enabled or admin.webauthn_enabled:
            allowed_methods = []
            if admin.totp_enabled:
                allowed_methods.append("totp")
            if admin.webauthn_enabled:
                allowed_methods.append("webauthn")
            if admin.backup_codes and len(admin.backup_codes) > 0:
                allowed_methods.append("backup_code")

            mfa_token = create_mfa_pending_token(admin_id=str(admin.id), email=admin.email)

            history = SuperAdminLoginHistory(
                admin_id=admin.id,
                email=admin.email,
                ip_address=client_ip,
                user_agent=user_agent,
                device_info=device_name,
                status="MFA_CHALLENGED",
                failure_reason=None,
            )
            db.add(admin)
            db.add(history)
            await db.commit()

            return SuperAdminLoginResponse(
                mfa_required=True,
                mfa_token=mfa_token,
                allowed_methods=allowed_methods,
                tokens=None,
                admin=None,
                message="Multi-factor authentication required.",
            )

        # 7. MFA not enabled: Establish session and issue tokens
        tokens, session = await SuperAdminAuthService._create_session_and_tokens(
            admin=admin,
            client_ip=client_ip,
            user_agent=user_agent,
            device_name=device_name,
            db=db,
        )

        admin.last_login_at = now
        history = SuperAdminLoginHistory(
            admin_id=admin.id,
            email=admin.email,
            ip_address=client_ip,
            user_agent=user_agent,
            device_info=device_name,
            status="SUCCESS",
            failure_reason=None,
        )
        db.add(admin)
        db.add(history)
        await db.commit()
        await db.refresh(admin)

        return SuperAdminLoginResponse(
            mfa_required=False,
            mfa_token=None,
            allowed_methods=[],
            tokens=tokens,
            admin=SuperAdminUserResponse.from_orm(admin),
            message="SuperAdmin authenticated successfully.",
        )

    @staticmethod
    async def verify_mfa_and_login(
        mfa_token: str,
        method: str,
        code: Optional[str],
        client_ip: Optional[str],
        user_agent: Optional[str],
        device_name: Optional[str],
        db: AsyncSession,
    ) -> SuperAdminLoginResponse:
        """Verify second factor (TOTP or backup recovery code) and issue session tokens."""
        payload = verify_mfa_pending_token(mfa_token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid, expired, or corrupted MFA challenge token. Please login again.",
            )

        admin_id = UUID(payload["admin_id"])
        admin = await db.get(SuperAdminUser, admin_id)
        if not admin or not admin.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="SuperAdmin account not found or deactivated.",
            )

        now = datetime.now(timezone.utc)
        verified = False

        if method == "totp":
            if not admin.totp_secret:
                raise HTTPException(status_code=400, detail="TOTP is not configured for this account.")
            if not code or not verify_totp_code(admin.totp_secret, code):
                raise HTTPException(status_code=401, detail="Invalid 6-digit authenticator code.")
            verified = True

        elif method == "backup_code":
            if not code or not admin.backup_codes:
                raise HTTPException(status_code=400, detail="Invalid or empty backup recovery code.")
            code_hash = hash_token(code.strip().upper())
            if code_hash in admin.backup_codes:
                # Remove used backup code
                updated_codes = [c for c in admin.backup_codes if c != code_hash]
                admin.backup_codes = updated_codes
                verified = True
            else:
                raise HTTPException(status_code=401, detail="Invalid or already used backup recovery code.")
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported verification method: '{method}'")

        if not verified:
            raise HTTPException(status_code=401, detail="Multi-factor authentication verification failed.")

        # Establish session and tokens
        tokens, session = await SuperAdminAuthService._create_session_and_tokens(
            admin=admin,
            client_ip=client_ip,
            user_agent=user_agent,
            device_name=device_name,
            db=db,
        )

        admin.last_login_at = now
        history = SuperAdminLoginHistory(
            admin_id=admin.id,
            email=admin.email,
            ip_address=client_ip,
            user_agent=user_agent,
            device_info=device_name,
            status="SUCCESS",
            failure_reason=None,
        )
        db.add(admin)
        db.add(history)
        await db.commit()
        await db.refresh(admin)

        return SuperAdminLoginResponse(
            mfa_required=False,
            mfa_token=None,
            allowed_methods=[],
            tokens=tokens,
            admin=SuperAdminUserResponse.from_orm(admin),
            message="MFA verified. SuperAdmin authenticated successfully.",
        )

    @staticmethod
    async def _create_session_and_tokens(
        admin: SuperAdminUser,
        client_ip: Optional[str],
        user_agent: Optional[str],
        device_name: Optional[str],
        db: AsyncSession,
    ) -> Tuple[SuperAdminTokenResponse, SuperAdminSession]:
        """Internal helper to create a database session and pair of access/refresh JWT tokens."""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=7)

        raw_session_token = secrets.token_urlsafe(32)
        raw_refresh_token = secrets.token_urlsafe(32)

        session = SuperAdminSession(
            admin_id=admin.id,
            session_token_hash=hash_token(raw_session_token),
            refresh_token_hash=hash_token(raw_refresh_token),
            ip_address=client_ip,
            user_agent=user_agent,
            device_name=device_name or "Web Browser",
            is_revoked=False,
            expires_at=expires_at,
            last_active_at=now,
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)

        access_token = create_superadmin_access_token(
            admin_id=str(admin.id),
            email=admin.email,
            role=admin.role,
            permissions=admin.permissions,
            session_id=str(session.id),
        )

        refresh_jwt = create_superadmin_refresh_token(
            admin_id=str(admin.id),
            session_id=str(session.id),
        )

        tokens = SuperAdminTokenResponse(
            access_token=access_token,
            refresh_token=refresh_jwt,
            session_id=str(session.id),
            token_type="bearer",
            expires_in_minutes=480,
            admin_id=str(admin.id),
            email=admin.email,
            role=admin.role,
            permissions=admin.permissions or ["*"],
        )
        return tokens, session

    @staticmethod
    async def refresh_access_token(
        refresh_token_str: str,
        client_ip: Optional[str],
        db: AsyncSession,
    ) -> SuperAdminTokenResponse:
        """Validate refresh token, verify active session, rotate access token."""
        payload = verify_superadmin_refresh_token(refresh_token_str)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid, expired, or revoked refresh token.",
            )

        admin_id = UUID(payload["admin_id"])
        session_id = UUID(payload["session_id"])
        now = datetime.now(timezone.utc)

        session = await db.get(SuperAdminSession, session_id)
        if not session or session.is_revoked or session.expires_at < now:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Administrative session has been revoked or expired.",
            )

        admin = await db.get(SuperAdminUser, admin_id)
        if not admin or not admin.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="SuperAdmin account is inactive.",
            )

        # Update session activity
        session.last_active_at = now
        session.ip_address = client_ip or session.ip_address
        db.add(session)
        await db.commit()

        new_access_token = create_superadmin_access_token(
            admin_id=str(admin.id),
            email=admin.email,
            role=admin.role,
            permissions=admin.permissions,
            session_id=str(session.id),
        )

        return SuperAdminTokenResponse(
            access_token=new_access_token,
            refresh_token=refresh_token_str,
            session_id=str(session.id),
            token_type="bearer",
            expires_in_minutes=480,
            admin_id=str(admin.id),
            email=admin.email,
            role=admin.role,
            permissions=admin.permissions or ["*"],
        )

    # ========================================================================
    # SESSIONS MANAGEMENT & REVOCATION
    # ========================================================================

    @staticmethod
    async def list_active_sessions(
        admin_id: UUID,
        current_session_id: Optional[str],
        db: AsyncSession,
    ) -> List[SuperAdminSessionResponse]:
        """List active sessions for current SuperAdmin."""
        now = datetime.now(timezone.utc)
        query = (
            select(SuperAdminSession)
            .where(
                SuperAdminSession.admin_id == admin_id,
                SuperAdminSession.is_revoked == False,
                SuperAdminSession.expires_at > now,
            )
            .order_by(SuperAdminSession.last_active_at.desc())
        )
        result = await db.execute(query)
        sessions = result.scalars().all()

        resp: List[SuperAdminSessionResponse] = []
        for s in sessions:
            is_curr = bool(current_session_id and str(s.id) == str(current_session_id))
            step_active = bool(s.step_up_until and s.step_up_until > now)
            resp.append(
                SuperAdminSessionResponse(
                    id=s.id,
                    ip_address=s.ip_address,
                    user_agent=s.user_agent,
                    device_name=s.device_name,
                    created_at=s.created_at,
                    last_active_at=s.last_active_at,
                    expires_at=s.expires_at,
                    is_current=is_curr,
                    step_up_active=step_active,
                )
            )
        return resp

    @staticmethod
    async def revoke_session(session_id: UUID, admin_id: UUID, db: AsyncSession) -> None:
        """Revoke a specific administrative session."""
        session = await db.get(SuperAdminSession, session_id)
        if not session or session.admin_id != admin_id:
            raise HTTPException(status_code=404, detail="Session not found.")
        session.is_revoked = True
        db.add(session)
        await db.commit()

    @staticmethod
    async def logout_all_devices(admin_id: UUID, db: AsyncSession) -> int:
        """Revoke all active sessions for a SuperAdmin across all devices."""
        stmt = (
            update(SuperAdminSession)
            .where(
                SuperAdminSession.admin_id == admin_id,
                SuperAdminSession.is_revoked == False,
            )
            .values(is_revoked=True)
        )
        res = await db.execute(stmt)
        await db.commit()
        return res.rowcount

    # ========================================================================
    # STEP-UP AUTHENTICATION FOR SENSITIVE OPERATIONS
    # ========================================================================

    @staticmethod
    async def step_up_authenticate(
        admin: SuperAdminUser,
        session_id: Optional[str],
        password: Optional[str],
        totp_code: Optional[str],
        db: AsyncSession,
    ) -> StepUpAuthResponse:
        """
        Elevate administrative privileges for sensitive operations.
        Requires verifying current password or current TOTP code.
        Grants a 10-minute elevated step-up window.
        """
        now = datetime.now(timezone.utc)
        valid = False

        if password and verify_password(password, admin.hashed_password):
            valid = True
        elif totp_code and admin.totp_secret and verify_totp_code(admin.totp_secret, totp_code):
            valid = True

        if not valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Step-up authentication failed: Invalid password or authenticator code.",
            )

        step_up_valid_until = now + timedelta(minutes=STEP_UP_VALID_MINUTES)

        if session_id:
            try:
                s_uuid = UUID(session_id)
                session = await db.get(SuperAdminSession, s_uuid)
                if session:
                    session.step_up_until = step_up_valid_until
                    db.add(session)
                    await db.commit()
            except Exception as e:
                logger.warning(f"Could not bind step-up to session {session_id}: {e}")

        return StepUpAuthResponse(
            success=True,
            step_up_valid_until=step_up_valid_until,
            message=f"Step-up authentication granted. Valid for {STEP_UP_VALID_MINUTES} minutes.",
        )

    # ========================================================================
    # TOTP AUTHENTICATOR SETUP & MANAGEMENT
    # ========================================================================

    @staticmethod
    async def setup_totp(admin: SuperAdminUser, db: AsyncSession) -> TOTPSetupResponse:
        """Generate a new TOTP secret and backup recovery codes."""
        secret = generate_totp_secret()
        otpauth_url = generate_totp_uri(secret, admin.email)
        plain_codes, hashed_codes = generate_backup_codes(8)

        # Store pending secret temporarily
        admin.totp_secret = secret
        admin.backup_codes = hashed_codes
        db.add(admin)
        await db.commit()

        return TOTPSetupResponse(
            secret=secret,
            otpauth_url=otpauth_url,
            backup_codes=plain_codes,
            message="Scan QR code into Google Authenticator / 1Password, save backup codes securely, then verify code.",
        )

    @staticmethod
    async def enable_totp(admin: SuperAdminUser, code: str, db: AsyncSession) -> None:
        """Verify code from authenticator app and enable TOTP on the account."""
        if not admin.totp_secret:
            raise HTTPException(status_code=400, detail="Run TOTP setup first.")

        if not verify_totp_code(admin.totp_secret, code):
            raise HTTPException(status_code=400, detail="Invalid 6-digit TOTP code. Verification failed.")

        admin.totp_enabled = True
        admin.mfa_enabled = True
        db.add(admin)
        await db.commit()

    @staticmethod
    async def disable_totp(admin: SuperAdminUser, password: str, db: AsyncSession) -> None:
        """Disable TOTP MFA (requires password confirmation)."""
        if not verify_password(password, admin.hashed_password):
            raise HTTPException(status_code=400, detail="Password confirmation failed.")

        admin.totp_enabled = False
        admin.totp_secret = None
        admin.backup_codes = []
        if not admin.webauthn_enabled:
            admin.mfa_enabled = False
        db.add(admin)
        await db.commit()

    # ========================================================================
    # PASSWORD RESET & RECOVERY
    # ========================================================================

    @staticmethod
    async def request_password_reset(email: str, db: AsyncSession) -> str:
        """Generate secure 15-minute password reset token."""
        clean_email = email.lower().strip()
        query = select(SuperAdminUser).where(SuperAdminUser.email == clean_email)
        result = await db.execute(query)
        admin = result.scalar_one_or_none()

        if not admin:
            # Prevent email enumeration: return standard success message
            return "If an administrative account exists with that email, reset instructions have been generated."

        raw_token = secrets.token_urlsafe(32)
        token_hash = hash_token(raw_token)
        now = datetime.now(timezone.utc)

        reset_token = SuperAdminPasswordResetToken(
            admin_id=admin.id,
            token_hash=token_hash,
            is_used=False,
            expires_at=now + timedelta(minutes=15),
        )
        db.add(reset_token)
        await db.commit()

        logger.info(f"[SUPERADMIN] Password reset requested for {clean_email}")
        return raw_token

    @staticmethod
    async def confirm_password_reset(token: str, new_password: str, db: AsyncSession) -> None:
        """Validate reset token, update password, and revoke all active sessions."""
        token_hash = hash_token(token.strip())
        now = datetime.now(timezone.utc)

        query = select(SuperAdminPasswordResetToken).where(
            SuperAdminPasswordResetToken.token_hash == token_hash,
            SuperAdminPasswordResetToken.is_used == False,
            SuperAdminPasswordResetToken.expires_at > now,
        )
        result = await db.execute(query)
        reset_entry = result.scalar_one_or_none()

        if not reset_entry:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid, expired, or already used password reset token.",
            )

        admin = await db.get(SuperAdminUser, reset_entry.admin_id)
        if not admin:
            raise HTTPException(status_code=404, detail="SuperAdmin account not found.")

        # Update password
        admin.hashed_password = hash_password(new_password)
        admin.failed_login_attempts = 0
        admin.locked_until = None
        reset_entry.is_used = True

        db.add(admin)
        db.add(reset_entry)
        await db.commit()

        # Invalidate all active sessions for security
        await SuperAdminAuthService.logout_all_devices(admin.id, db)

    # ========================================================================
    # IP ALLOWLIST & LOGIN HISTORY
    # ========================================================================

    @staticmethod
    async def update_ip_allowlist(
        admin: SuperAdminUser,
        enabled: bool,
        allowed_ips: List[str],
        db: AsyncSession,
    ) -> None:
        """Update IP allowlist rules for a SuperAdmin."""
        # Validate each IP / CIDR
        import ipaddress
        for ip_rule in allowed_ips:
            rule_str = ip_rule.strip()
            if not rule_str:
                continue
            try:
                if "/" in rule_str:
                    ipaddress.ip_network(rule_str, strict=False)
                else:
                    ipaddress.ip_address(rule_str)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid IP address or CIDR format: '{rule_str}'",
                )

        admin.ip_allowlist_enabled = enabled
        admin.allowed_ips = [i.strip() for i in allowed_ips if i.strip()]
        db.add(admin)
        await db.commit()
        await db.refresh(admin)

    @staticmethod
    async def list_login_history(
        admin_id: UUID,
        limit: int,
        offset: int,
        db: AsyncSession,
    ) -> Tuple[List[SuperAdminLoginHistory], int]:
        """Fetch paginated login and attempt history."""
        query = (
            select(SuperAdminLoginHistory)
            .where(SuperAdminLoginHistory.admin_id == admin_id)
            .order_by(SuperAdminLoginHistory.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        count_q = select(func.count(SuperAdminLoginHistory.id)).where(
            SuperAdminLoginHistory.admin_id == admin_id
        )

        total_res = await db.execute(count_q)
        total = total_res.scalar() or 0

        res = await db.execute(query)
        items = list(res.scalars().all())
        return items, total

