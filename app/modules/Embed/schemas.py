"""Pydantic Schemas for Widget Customization & Embed Endpoints"""

from pydantic import BaseModel, Field
from typing import Optional


class WidgetCustomizationUpdate(BaseModel):
    """Schema for creating or updating widget customization settings"""
    logo_url: Optional[str] = Field(None, description="Public S3 URL of the uploaded logo image")
    show_in_header: bool = Field(True, description="Whether to display logo in widget header")
    show_in_chat: bool = Field(True, description="Whether to display logo inside chat messages")
    show_in_embed: bool = Field(False, description="Whether to show branding/logo in embed view")


class WidgetCustomizationResponse(BaseModel):
    """Schema for widget customization response"""
    logo_url: Optional[str] = Field(None, description="Public S3 URL of the logo")
    show_in_header: bool = Field(True, description="Logo visibility in header")
    show_in_chat: bool = Field(True, description="Logo visibility in chat")
    show_in_embed: bool = Field(True, description="Logo visibility in embed")

    class Config:
        from_attributes = True


class LogoUploadResponse(BaseModel):
    """Response model for logo image upload"""
    success: bool = True
    logo_url: str


class CustomizationSaveResponse(BaseModel):
    """Response model for saving customization"""
    success: bool = True
    message: str = "Widget customization saved successfully."
