"""Pydantic Schemas for Widget Embed Configuration & Legacy Customization Endpoints"""

import re
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import Optional, List, Any, Dict
from datetime import datetime
import uuid


# ---------------------------------------------------------------------------
# SECURITY HELPERS
# ---------------------------------------------------------------------------

# Allowed lead field names — prevents injection / arbitrary field enumeration
_ALLOWED_LEAD_FIELDS = {"name", "email", "phone", "company", "message"}

# Allowed hex color pattern
_HEX_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

# Allowed alignment values
_ALLOWED_ALIGNMENTS = {"left", "center", "right"}

# Allowed chat types
_ALLOWED_CHAT_TYPES = {"icon", "search"}

# Allowed lead timing values
_ALLOWED_LEAD_TIMINGS = {"pre-chat", "post-chat"}

# HTML-injection strip regex (prevents <script> or tag injection in text fields)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(value: str) -> str:
    """Remove all HTML/script tags from string fields for XSS safety."""
    return _TAG_RE.sub("", value).strip()


def _validate_hex_color(color: str, field_name: str) -> str:
    """Validate and normalize a CSS hex color value."""
    if not _HEX_COLOR_RE.match(color):
        raise ValueError(f"'{field_name}' must be a valid hex color (e.g. #0fb5a1 or #fff)")
    return color.lower()


# ---------------------------------------------------------------------------
# EMBED CONFIG SCHEMAS (NEW CRUD SYSTEM)
# ---------------------------------------------------------------------------

class WidgetEmbedConfigCreate(BaseModel):
    """
    Schema for creating or upserting a full widget embed configuration.

    All fields except agent_id have defaults so the frontend can send
    only the fields it knows about; the rest fall back to safe defaults.
    """

    agent_id: str = Field(..., description="UUID of the agent this config belongs to")

    # Optimistic concurrency — client passes the version it last read.
    # Server rejects with 409 if the DB version doesn't match.
    # Omit (None) to skip concurrency check (first-write-wins).
    expected_version: Optional[int] = Field(
        None, description="Current version the client holds; omit for first save"
    )
    change_reason: Optional[str] = Field(
        None, max_length=500, description="Human-readable reason for this change (audit log)"
    )

    # Theme & Colors
    theme_color: str = Field("#0fb5a1", max_length=20)
    theme_text_color: str = Field("#ffffff", max_length=20)
    btn_bg_color: str = Field("#0fb5a1", max_length=20)
    btn_border_color: str = Field("#0fb5a1", max_length=20)

    # Header
    header_logo: Optional[str] = Field(None, description="S3/proxy URL of the header logo")
    header_align: str = Field("center", max_length=10)
    header_name: str = Field("Gsearch AI", max_length=200)
    header_subtext: Optional[str] = Field("The team can also help", max_length=300)

    # Bot Identity
    agent_label: str = Field("Agent", max_length=100)
    bot_avatar: str = Field("chat", max_length=200)

    # Chat Type & Layout
    chat_type: str = Field("icon", max_length=20)
    position: str = Field("right", max_length=20)
    placeholder_text: Optional[str] = Field(None, max_length=300)

    # Entry Button
    button_icon: str = Field("chat", max_length=200)
    button_align: str = Field("right", max_length=10)
    show_button_text: bool = Field(True)
    button_text: str = Field("Help", max_length=100)

    # Content & Behavior
    search_mobile_icon: bool = Field(False)
    initial_message: Optional[str] = Field(
        "Hi! I'm your AI Support Agent. How can I help you today?",
        max_length=2000,
    )
    display_sources: bool = Field(True)
    allow_downloads: bool = Field(False)
    display_copy: bool = Field(True)
    display_feedback: bool = Field(True)
    link_safety: bool = Field(True)

    # Lead Capture
    lead_collection: bool = Field(False)
    lead_fields: List[str] = Field(default=["name", "email"])
    lead_timing: str = Field("pre-chat", max_length=20)

    # Escalation
    escalation_enabled: bool = Field(False)
    escalation_link: Optional[str] = Field("", max_length=500)

    # Logo Visibility (legacy-compat)
    show_in_header: bool = Field(True)
    show_in_chat: bool = Field(True)
    show_in_embed: bool = Field(False)

    # ── Validators ─────────────────────────────────────────────────────────

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError("agent_id must be a valid UUID")
        return v

    @field_validator("theme_color", "theme_text_color", "btn_bg_color", "btn_border_color")
    @classmethod
    def validate_colors(cls, v: str) -> str:
        return _validate_hex_color(v, "color field")

    @field_validator("header_align", "button_align")
    @classmethod
    def validate_alignment(cls, v: str) -> str:
        if v not in _ALLOWED_ALIGNMENTS:
            raise ValueError(f"Alignment must be one of: {_ALLOWED_ALIGNMENTS}")
        return v

    @field_validator("chat_type")
    @classmethod
    def validate_chat_type(cls, v: str) -> str:
        if v not in _ALLOWED_CHAT_TYPES:
            raise ValueError(f"chat_type must be one of: {_ALLOWED_CHAT_TYPES}")
        return v

    @field_validator("position")
    @classmethod
    def validate_position(cls, v: str) -> str:
        if v not in _ALLOWED_ALIGNMENTS:
            raise ValueError(f"position must be one of: {_ALLOWED_ALIGNMENTS}")
        return v

    @field_validator("lead_timing")
    @classmethod
    def validate_lead_timing(cls, v: str) -> str:
        if v not in _ALLOWED_LEAD_TIMINGS:
            raise ValueError(f"lead_timing must be one of: {_ALLOWED_LEAD_TIMINGS}")
        return v

    @field_validator("lead_fields")
    @classmethod
    def validate_lead_fields(cls, v: List[str]) -> List[str]:
        invalid = set(v) - _ALLOWED_LEAD_FIELDS
        if invalid:
            raise ValueError(f"Invalid lead_fields: {invalid}. Allowed: {_ALLOWED_LEAD_FIELDS}")
        return list(dict.fromkeys(v))  # deduplicate preserving order

    @field_validator("header_name", "agent_label", "button_text")
    @classmethod
    def sanitize_text_fields(cls, v: str) -> str:
        return _strip_html(v)

    @field_validator("initial_message", "header_subtext", "placeholder_text")
    @classmethod
    def sanitize_optional_text(cls, v: Optional[str]) -> Optional[str]:
        return _strip_html(v) if v else v

    @field_validator("escalation_link")
    @classmethod
    def validate_escalation_url(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return ""
        # Basic URL safety: must start with http/https or be empty
        if v and not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("escalation_link must be a valid http/https URL or empty")
        return v


class WidgetEmbedConfigUpdate(WidgetEmbedConfigCreate):
    """
    Schema for updating an existing widget embed config.
    Identical to Create (agent_id is the key) but semantically signals an update.
    """
    pass


class WidgetEmbedConfigResponse(BaseModel):
    """Full embed config response — returned to authenticated dashboard users."""

    id: str
    tenant_id: str
    agent_id: str
    user_id: str
    version: int
    config_schema_version: int

    # Theme
    theme_color: str
    theme_text_color: str
    btn_bg_color: str
    btn_border_color: str

    # Header
    header_logo: Optional[str]
    header_align: str
    header_name: str
    header_subtext: Optional[str]

    # Bot Identity
    agent_label: str
    bot_avatar: str

    # Chat Type
    chat_type: str
    position: str
    placeholder_text: Optional[str]

    # Button
    button_icon: str
    button_align: str
    show_button_text: bool
    button_text: str

    # Content
    search_mobile_icon: bool
    initial_message: Optional[str]
    display_sources: bool
    allow_downloads: bool
    display_copy: bool
    display_feedback: bool
    link_safety: bool

    # Lead
    lead_collection: bool
    lead_fields: List[Any]
    lead_timing: str

    # Escalation
    escalation_enabled: bool
    escalation_link: Optional[str]

    # Legacy
    show_in_header: bool
    show_in_chat: bool
    show_in_embed: bool

    # Metadata
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class WidgetEmbedConfigPublicResponse(BaseModel):
    """
    Sanitized embed config for public widget access (no JWT required).

    Exposes only the fields needed by chat.js to initialize the widget.
    Internal metadata (user_id, version, history info) is excluded.
    """

    agent_id: str
    theme_color: str
    theme_text_color: str
    btn_bg_color: str
    btn_border_color: str
    header_logo: Optional[str]
    header_align: str
    header_name: str
    header_subtext: Optional[str]
    agent_label: str
    bot_avatar: str
    chat_type: str
    position: str
    placeholder_text: Optional[str]
    button_icon: str
    button_align: str
    show_button_text: bool
    button_text: str
    search_mobile_icon: bool
    initial_message: Optional[str]
    display_sources: bool
    allow_downloads: bool
    display_copy: bool
    display_feedback: bool
    link_safety: bool
    lead_collection: bool
    lead_fields: List[Any]
    lead_timing: str
    escalation_enabled: bool
    escalation_link: Optional[str]

    class Config:
        from_attributes = True


class WidgetEmbedConfigListResponse(BaseModel):
    """Response for listing all configs for a tenant."""
    configs: List[WidgetEmbedConfigResponse]
    total: int


class WidgetEmbedConfigDeleteResponse(BaseModel):
    """Response confirming deletion of a widget embed config."""
    success: bool = True
    message: str = "Widget embed configuration deleted successfully."
    agent_id: str


# ---------------------------------------------------------------------------
# LEGACY SCHEMAS (kept for backward compatibility with /embed/customization)
# ---------------------------------------------------------------------------

class WidgetCustomizationUpdate(BaseModel):
    """Schema for creating or updating widget customization settings (logo only — legacy)"""
    logo_url: Optional[str] = Field(None, description="Public S3 URL of the uploaded logo image")
    show_in_header: bool = Field(True, description="Whether to display logo in widget header")
    show_in_chat: bool = Field(True, description="Whether to display logo inside chat messages")
    show_in_embed: bool = Field(False, description="Whether to show branding/logo in embed view")


class WidgetCustomizationResponse(BaseModel):
    """Schema for widget customization response (legacy)"""
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
    """Response model for saving customization (legacy)"""
    success: bool = True
    message: str = "Widget customization saved successfully."
