"""Pydantic schemas for Profile Management API"""

from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class ProfileBase(BaseModel):
    username: Optional[str] = Field(None, min_length=2, max_length=100, description="Unique username")
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    display_name: Optional[str] = Field(None, max_length=200)
    phone_number: Optional[str] = Field(None, max_length=50)
    avatar_url: Optional[str] = Field(None, max_length=1000)
    bio: Optional[str] = Field(None, max_length=1000)
    job_title: Optional[str] = Field(None, max_length=200)
    department: Optional[str] = Field(None, max_length=200)
    organization: Optional[str] = Field(None, max_length=200)
    country: Optional[str] = Field(None, max_length=100)
    timezone: Optional[str] = Field("UTC", max_length=100)
    language: Optional[str] = Field("en", max_length=20)
    theme: Optional[str] = Field("system", max_length=20)
    notification_preferences: Optional[Dict[str, Any]] = Field(default_factory=dict)
    custom_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class ProfileCreate(ProfileBase):
    """Payload to explicitly create or initialize a profile"""
    pass


class ProfileUpdate(BaseModel):
    """Payload to update profile information"""
    username: Optional[str] = Field(None, min_length=2, max_length=100)
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    display_name: Optional[str] = Field(None, max_length=200)
    phone_number: Optional[str] = Field(None, max_length=50)
    avatar_url: Optional[str] = Field(None, max_length=1000)
    bio: Optional[str] = Field(None, max_length=1000)
    job_title: Optional[str] = Field(None, max_length=200)
    department: Optional[str] = Field(None, max_length=200)
    organization: Optional[str] = Field(None, max_length=200)
    country: Optional[str] = Field(None, max_length=100)
    timezone: Optional[str] = Field(None, max_length=100)
    language: Optional[str] = Field(None, max_length=20)
    theme: Optional[str] = Field(None, max_length=20)
    preferred_llm_model: Optional[str] = Field(None, max_length=255)
    notification_preferences: Optional[Dict[str, Any]] = None
    custom_metadata: Optional[Dict[str, Any]] = None


class UserResourceSummary(BaseModel):
    """Resource inventory summary owned by the user"""
    agents_count: int = 0
    knowledge_bases_count: int = 0
    database_knowledgebases_count: int = 0
    chat_sessions_count: int = 0
    chat_messages_count: int = 0
    episodic_memories_count: int = 0
    user_preferences_count: int = 0
    api_keys_count: int = 0
    files_count: int = 0
    total_resources: int = 0


class ProfileResponse(BaseModel):
    """Complete profile response with login and account details"""
    id: UUID
    user_id: UUID
    tenant_id: UUID
    username: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    display_name: Optional[str] = None
    phone_number: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    job_title: Optional[str] = None
    department: Optional[str] = None
    organization: Optional[str] = None
    country: Optional[str] = None
    timezone: str = "UTC"
    language: str = "en"
    theme: str = "system"
    notification_preferences: Dict[str, Any] = Field(default_factory=dict)
    custom_metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    # Account metadata directly from User
    role: str = "user"
    is_admin: bool = False
    is_active: bool = True
    last_login_at: Optional[datetime] = None
    preferred_llm_model: Optional[str] = None
    resource_summary: Optional[UserResourceSummary] = None

    class Config:
        from_attributes = True


class DeleteAccountRequest(BaseModel):
    """Confirmation payload for permanent account and profile deletion"""
    confirm: bool = Field(True, description="Must be true to authorize deletion")
    password: Optional[str] = Field(None, description="Current user password for verification (optional for admins)")
    reason: Optional[str] = Field(None, max_length=500, description="Optional feedback on why deleting account")


class DeleteAccountResponse(BaseModel):
    """Audit response after complete account cleanup"""
    success: bool = True
    message: str
    user_id: str
    email: str
    deleted_at: datetime
    purged_resources: Dict[str, int]
