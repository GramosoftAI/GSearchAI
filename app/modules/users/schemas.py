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
    preferred_llm_model: Optional[str] = None
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
    preferred_llm_model: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    is_admin: Optional[bool] = None


class UserLLMPreferenceUpdate(BaseModel):
    """Schema for updating user's preferred LLM model"""
    preferred_llm_model: Optional[str] = None  # None or empty string reverts to system default


class AvailableModelItem(BaseModel):
    """Schema for an available LLM model"""
    model_id: str
    display_name: str
    provider: str
    input_price_per_1m: float
    output_price_per_1m: float
    context_window: int
    description: Optional[str] = None
    is_default: bool = False


class UserLLMPreferenceResponse(BaseModel):
    """Schema for user LLM model preference response"""
    user_id: uuid.UUID
    email: Optional[str] = None
    preferred_llm_model: Optional[str] = None
    active_model: str
    default_model: str
    available_models: list[AvailableModelItem] = []


class AvailableModelsResponse(BaseModel):
    """List of all available models"""
    default_model: str
    models: list[AvailableModelItem]
