"""Users schemas (Pydantic models)"""
import uuid
from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class UserResponse(BaseModel):
    """User response schema"""
    id: uuid.UUID
    email: str
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    is_active: bool
    is_admin: Optional[bool] = None
    role: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """User update schema"""
    email: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None
