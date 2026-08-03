"""Widget Customization Model for Embeddable Chat Widget"""

from sqlalchemy import Column, String, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from ...models.base import BaseModel


class WidgetCustomization(BaseModel):
    """
    Widget Customization model - stores appearance & feature flags for embeddable chat widget.

    Properties:
    - id: UUID primary key (inherited from BaseModel)
    - tenant_id: Multi-tenancy scoping (inherited from BaseModel, RLS filtered)
    - user_id: User who created/updated customization
    - logo_url: Public S3 URL of uploaded logo image
    - show_in_header: Toggle logo display in widget header
    - show_in_chat: Toggle logo display inside chat messages
    - show_in_embed: Toggle embed branding/feature
    - created_at, updated_at: Timestamps (inherited from BaseModel)
    """

    __tablename__ = "widget_customizations"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    logo_url = Column(String, nullable=True)
    show_in_header = Column(Boolean, nullable=False, default=True)
    show_in_chat = Column(Boolean, nullable=False, default=True)
    show_in_embed = Column(Boolean, nullable=False, default=True)
