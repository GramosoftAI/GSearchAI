"""Authentication Pydantic schemas for request/response validation"""

from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional
from datetime import datetime
import uuid


# ============= REQUEST SCHEMAS =============
class SendRegistrationOTPRequest(BaseModel):
    """Request to send registration OTP"""
    email: EmailStr = Field(..., description="User email address")
    first_name: Optional[str] = Field(None, description="Optional user first name for personalized email greeting")
    tenant_name: Optional[str] = Field(None, description="Optional tenant name to check availability before sending OTP")
    password: Optional[str] = Field(None, description="Optional password to validate strength before sending OTP", min_length=8, max_length=128)

    @validator("password")
    def validate_password_strength(cls, v):
        """Validate password meets security requirements"""
        if v is None:
            return v
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain digit")
        return v


class RegisterRequest(BaseModel):
    """User registration request"""

    email: EmailStr = Field(..., description="User email address")
    otp: str = Field(..., description="6-digit OTP sent to email", min_length=6, max_length=6)
    first_name: str = Field(..., min_length=1, max_length=255)
    last_name: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    tenant_name: Optional[str] = Field(
        None, description="Create new tenant or join existing"
    )

    @validator("password")
    def validate_password_strength(cls, v):
        """Validate password meets security requirements"""
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain digit")
        return v


class LoginRequest(BaseModel):
    """User login request"""

    email: EmailStr = Field(..., description="User email")
    password: str = Field(..., description="User password")


class RefreshTokenRequest(BaseModel):
    """Refresh access token"""

    refresh_token: str = Field(..., description="Refresh token from previous login")


class CreateAPIKeyRequest(BaseModel):
    """Create new API key"""

    name: Optional[str] = Field(None, max_length=255)


class ForgotPasswordRequest(BaseModel):
    """Forgot password request"""

    email: EmailStr = Field(..., description="User email to send reset link to")


class ResetPasswordRequest(BaseModel):
    """Reset password request"""

    token: str = Field(..., description="The reset token received via email")
    new_password: str = Field(..., min_length=8, max_length=128)

    @validator("new_password")
    def validate_password_strength(cls, v):
        """Reuse the registration password strength check"""
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain digit")
        return v


class GoogleAuthRequest(BaseModel):
    """Google OAuth authentication request (via Google ID token)"""
    credential: str = Field(..., description="Google ID Token (JWT) from Google Identity Services")
    tenant_name: Optional[str] = Field(None, description="Optional tenant name if new user registration")


# ============= RESPONSE SCHEMAS =============
class TokenResponse(BaseModel):
    """Token response (access + refresh)"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Expiration in seconds")


class UserResponse(BaseModel):
    """User profile response"""

    id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    tenant_id: uuid.UUID
    is_active: bool
    is_admin: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TenantResponse(BaseModel):
    """Tenant response"""

    id: uuid.UUID
    name: str
    slug: str
    description: Optional[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class APIKeyResponse(BaseModel):
    """API Key response (public representation)"""

    id: uuid.UUID
    name: Optional[str]
    is_active: bool
    last_used_at: Optional[datetime]
    created_at: datetime

    # NOTE: key_hash is NOT included for security

    class Config:
        from_attributes = True


class LoginResponse(BaseModel):
    """Login response with user and token data"""

    user: UserResponse
    tenant: TenantResponse
    tokens: TokenResponse
