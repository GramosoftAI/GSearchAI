"""SuperAdmin Models: Complete Identity, MFA, Sessions, Roles, and Audit Trail.

CRITICAL ARCHITECTURAL PRINCIPLE:
SuperAdmin is a dedicated platform-level administration system.
SuperAdmin models are NOT tied to customer tenant accounts.
"""

import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    Integer,
    JSON,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.models.base import Base


class SuperAdminRole(str, enum.Enum):
    """Platform-level SuperAdmin Role Hierarchy."""
    SUPERADMIN_ROOT = "SUPERADMIN_ROOT"       # Complete platform-level control (all scopes, sensitive actions)
    SUPER_ADMIN = "SUPER_ADMIN"               # Standard platform administrator
    PLATFORM_OPERATOR = "PLATFORM_OPERATOR"   # Operations, monitoring, jobs, infrastructure
    SUPPORT_AUDITOR = "SUPPORT_AUDITOR"       # Read-only audit logs, customer support diagnostics
    BILLING_ADMIN = "BILLING_ADMIN"           # Usage, LLM costs, tenant tiers & quotas


class SuperAdminRoleDefinition(Base):
    """
    Configurable Role Definitions and Scopes.
    Allows platform owners to define custom roles and assign fine-grained permissions.
    """
    __tablename__ = "superadmin_roles"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    role_name = Column(String(100), unique=True, index=True, nullable=False)
    description = Column(String(500), nullable=True)
    is_system = Column(Boolean, default=False, nullable=False)  # System roles cannot be deleted
    permissions = Column(JSON, default=list, nullable=False)    # List of allowed scopes

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<SuperAdminRoleDefinition role_name={self.role_name}>"


class SuperAdminUser(Base):
    """
    Dedicated platform-level SuperAdmin user account.
    Independent of tenant-scoped customer accounts.
    """
    __tablename__ = "superadmin_users"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    email = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)

    role = Column(String(50), default=SuperAdminRole.SUPERADMIN_ROOT.value, nullable=False, index=True)
    permissions = Column(JSON, default=lambda: ["*"], nullable=False)  # Configurable scopes
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    # Multi-Factor Authentication (MFA)
    mfa_enabled = Column(Boolean, default=False, nullable=False, index=True)
    totp_secret = Column(String(255), nullable=True)
    totp_enabled = Column(Boolean, default=False, nullable=False)
    webauthn_enabled = Column(Boolean, default=False, nullable=False)
    backup_codes = Column(JSON, default=list, nullable=True)  # List of hashed recovery codes

    # Account Lockout & Attempt Tracking
    failed_login_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    last_failed_login_at = Column(DateTime(timezone=True), nullable=True)

    # Optional IP Allowlisting
    ip_allowlist_enabled = Column(Boolean, default=False, nullable=False)
    allowed_ips = Column(JSON, default=list, nullable=True)  # List of IPs or CIDRs

    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<SuperAdminUser id={self.id} email={self.email} role={self.role}>"


class SuperAdminSession(Base):
    """
    Active SuperAdmin Sessions for multi-device management,
    token rotation, step-up authentication, and remote revocation.
    """
    __tablename__ = "superadmin_sessions"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    admin_id = Column(
        UUID(as_uuid=True),
        ForeignKey("superadmin_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    session_token_hash = Column(String(255), unique=True, index=True, nullable=False)
    refresh_token_hash = Column(String(255), unique=True, index=True, nullable=True)

    ip_address = Column(String(100), nullable=True)
    user_agent = Column(String(500), nullable=True)
    device_name = Column(String(255), nullable=True)

    is_revoked = Column(Boolean, default=False, nullable=False, index=True)
    step_up_until = Column(DateTime(timezone=True), nullable=True)  # Valid window for sensitive operations
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    last_active_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<SuperAdminSession id={self.id} admin_id={self.admin_id} active={not self.is_revoked}>"


class SuperAdminLoginHistory(Base):
    """
    Device, IP, and authentication attempt tracking.
    """
    __tablename__ = "superadmin_login_history"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    admin_id = Column(
        UUID(as_uuid=True),
        ForeignKey("superadmin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    email = Column(String(255), nullable=False, index=True)
    ip_address = Column(String(100), nullable=True)
    user_agent = Column(String(500), nullable=True)
    device_info = Column(String(255), nullable=True)

    status = Column(String(50), nullable=False)  # SUCCESS, FAILED, LOCKED, MFA_CHALLENGED, BLOCKED_IP
    failure_reason = Column(String(255), nullable=True)
    created_at = Column(
        DateTime(timezone=True), default=func.now(), nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<SuperAdminLoginHistory email={self.email} status={self.status} at={self.created_at}>"


class SuperAdminPasswordResetToken(Base):
    """
    Hashed, time-limited password recovery tokens for SuperAdmins.
    """
    __tablename__ = "superadmin_password_reset_tokens"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    admin_id = Column(
        UUID(as_uuid=True),
        ForeignKey("superadmin_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash = Column(String(255), unique=True, index=True, nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)


class SuperAdminWebAuthnCredential(Base):
    """
    Registered WebAuthn / FIDO2 / Passkey security credentials for SuperAdmin MFA.
    """
    __tablename__ = "superadmin_webauthn_credentials"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    admin_id = Column(
        UUID(as_uuid=True),
        ForeignKey("superadmin_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    credential_id = Column(String(500), unique=True, index=True, nullable=False)
    public_key = Column(Text, nullable=False)
    credential_name = Column(String(255), default="Security Key / Passkey", nullable=False)
    sign_count = Column(Integer, default=0, nullable=False)
    aaguid = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)


class SuperAdminAuditLog(Base):
    """
    Centralized, immutable audit trail for platform-level administrative actions.
    Records who did what, when, against which resource or customer tenant.
    """
    __tablename__ = "superadmin_audit_logs"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    admin_id = Column(
        UUID(as_uuid=True),
        ForeignKey("superadmin_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    admin_email = Column(String(255), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)         # e.g., SUPERADMIN_LOGIN, STEP_UP_AUTH
    resource_type = Column(String(100), nullable=False, index=True)  # e.g., auth, session, tenant
    resource_id = Column(String(255), nullable=True)
    target_tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)

    status = Column(String(50), default="SUCCESS", nullable=False)  # SUCCESS, FAILED, WARNING
    details = Column(JSON, nullable=True)
    ip_address = Column(String(100), nullable=True)
    user_agent = Column(String(500), nullable=True)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (
        Index("ix_superadmin_audit_logs_action_created", "action", "created_at"),
        Index("ix_superadmin_audit_logs_admin_created", "admin_email", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<SuperAdminAuditLog id={self.id} action={self.action} admin={self.admin_email}>"


class SuperAdminDashboardWidget(Base):
    """
    Configurable Dashboard Widgets / Saved Operational Metric Views.
    Allows SuperAdmins to customize, save, reorder, and CRUD their dashboard widgets.
    """
    __tablename__ = "superadmin_dashboard_widgets"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    name = Column(String(255), nullable=False)
    widget_type = Column(String(100), default="METRIC_CARD", nullable=False)  # METRIC_CARD, CHART, LIST, HEALTH
    metric_key = Column(String(100), nullable=False, index=True)              # e.g., organizations, users, etc.
    title = Column(String(255), nullable=False)
    description = Column(String(500), nullable=True)

    layout_row = Column(Integer, default=0, nullable=False)
    layout_col = Column(Integer, default=0, nullable=False)
    layout_width = Column(Integer, default=1, nullable=False)
    layout_height = Column(Integer, default=1, nullable=False)

    is_visible = Column(Boolean, default=True, nullable=False, index=True)
    config = Column(JSON, default=dict, nullable=True)

    created_by_admin_id = Column(
        UUID(as_uuid=True),
        ForeignKey("superadmin_users.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<SuperAdminDashboardWidget id={self.id} metric_key={self.metric_key} title={self.title}>"
