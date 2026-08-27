"""Authentication models: User, Tenant, APIKey"""

from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Index, text, Integer
from sqlalchemy.sql import func
import uuid
from datetime import datetime
from sqlalchemy import UUID

# Use the shared Base from models package (ensures proper metadata registration)
from ...models.base import Base


class User(Base):
    """
    User model - stored in PostgreSQL.

    CRITICAL: Every user belongs to exactly one tenant.
    tenant_id is used for RLS filtering.
    """

    __tablename__ = "users"

    # ============= PRIMARY KEY =============
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    # ============= MULTI-TENANCY =============
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,  # RLS filtering
    )

    # ============= USER FIELDS =============
    email = Column(String(255), unique=True, index=True, nullable=False)

    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)

    hashed_password = Column(String(255), nullable=False)

    # ============= PREFERENCES =============
    preferred_llm_model = Column(String(255), nullable=True)

    # ============= STATUS =============
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    is_admin = Column(Boolean, default=False, nullable=False)

    # ============= TIMESTAMPS =============
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ============= INDEXES =============
    __table_args__ = (
        Index("ix_users_tenant_email", "tenant_id", "email"),  # Composite for RLS
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} tenant_id={self.tenant_id}>"

    @property
    def username(self) -> str:
        return self.email

    @property
    def role(self) -> str:
        return "admin" if self.is_admin else "user"

    @role.setter
    def role(self, value: str):
        self.is_admin = (value == "admin")


class Tenant(Base):
    """
    Tenant model - represents a customer/organization.

    Every user, API key, agent, knowledge base belongs to one tenant.
    """

    __tablename__ = "tenants"

    # ============= PRIMARY KEY =============
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    # ============= TENANT FIELDS =============
    name = Column(String(255), unique=True, nullable=False, index=True)
    slug = Column(String(255), unique=True, nullable=False, index=True)

    description = Column(String(1000), nullable=True)

    # ============= STATUS =============
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    # ============= TIMESTAMPS =============
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
        return f"<Tenant id={self.id} name={self.name}>"


class APIKey(Base):
    """
    API Key model - for programmatic access.

    Each API key is tied to a specific user and tenant.
    Keys are hashed before storage (never store plaintext).
    """

    __tablename__ = "api_keys"

    # ============= PRIMARY KEY =============
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    # ============= OWNER =============
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ============= KEY DATA =============
    key_hash = Column(String(255), unique=True, nullable=False, index=True)

    name = Column(String(255), nullable=True)  # For human reference

    # ============= STATUS =============
    is_active = Column(Boolean, default=True, nullable=False, index=True)

    # ============= TRACKING =============
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (Index("ix_api_keys_tenant_user", "tenant_id", "user_id"),)

    def __repr__(self) -> str:
        return (
            f"<APIKey id={self.id} tenant_id={self.tenant_id} active={self.is_active}>"
        )


class TokenBlacklist(Base):
    """
    Token Blacklist for revocation (logout, compromised tokens).

    When a user logs out or a token is compromised, it's added here.
    Before verifying JWT, check if token's jti is in blacklist.

    CRITICAL: Add JWT 'jti' (JWT ID) claim to track individual tokens.
    """

    __tablename__ = "token_blacklist"

    # ============= PRIMARY KEY =============
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    # ============= MULTI-TENANCY =============
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ============= TOKEN INFO =============
    jti = Column(String(255), unique=True, index=True, nullable=False)  # JWT ID
    token_type = Column(String(50), nullable=False)  # 'access' or 'refresh'

    # ============= TRACKING =============
    reason = Column(
        String(255), nullable=True
    )  # 'logout', 'compromised', 'password_changed', etc.

    # Token expiration (use to auto-clean old entries)
    expires_at = Column(DateTime(timezone=True), nullable=False)  # Same as token exp

    blacklisted_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_token_blacklist_tenant_user", "tenant_id", "user_id"),
        Index("ix_token_blacklist_expires", "expires_at"),  # For cleanup
    )

class PasswordResetToken(Base):
    """
    Password Reset Token model.
    Stores hashed tokens for secure password recovery.
    """

    __tablename__ = "password_reset_tokens"

    # ============= PRIMARY KEY =============
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    # ============= OWNER =============
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ============= TOKEN DATA =============
    token_hash = Column(String(255), unique=True, nullable=False, index=True)
    is_used = Column(Boolean, default=False, nullable=False)

    # ============= STATUS =============
    expires_at = Column(DateTime(timezone=True), nullable=False)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_password_reset_tokens_tenant_user", "tenant_id", "user_id"),
        Index("ix_password_reset_tokens_expires", "expires_at"),  # For cleanup
    )

    def __repr__(self) -> str:
        return f"<PasswordResetToken user={self.user_id} used={self.is_used}>"


class RegistrationOTP(Base):
    """
    Registration OTP model.
    Stores hashed OTPs for secure email validation during registration.
    """

    __tablename__ = "registration_otps"

    # ============= PRIMARY KEY =============
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    # ============= OTP DATA =============
    email = Column(String(255), nullable=False)
    otp_hash = Column(String(255), nullable=False)
    is_used = Column(Boolean, default=False, nullable=False)
    failed_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)

    # ============= STATUS =============
    expires_at = Column(DateTime(timezone=True), nullable=False)

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    ) 

    __table_args__ = (
        Index("ix_registration_otps_email", "email"),
        Index("ix_registration_otps_expires", "expires_at"),  # For cleanup
    )

    def __repr__(self) -> str:
        return f"<RegistrationOTP email={self.email} used={self.is_used}>"

