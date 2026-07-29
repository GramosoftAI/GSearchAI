"""Pydantic schemas for Chat History & Memory API

REQUEST/RESPONSE VALIDATION:
    - All request bodies validated via Pydantic
    - Response models match existing StandardResponse pattern
    - Optional fields have sensible defaults
    - UUID validation on path/body params

PATTERN: Matches existing schema conventions from agents/schemas.py and rag/schemas.py
"""

from uuid import UUID
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator
from datetime import datetime


# ============================================================================
# REQUEST SCHEMAS
# ============================================================================


class SendMessageRequest(BaseModel):
    """Send a message to an agent within a chat session.

    If session_id is omitted, a new session is created automatically.
    """

    message: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="User message to send to the agent",
    )
    session_id: Optional[str] = Field(
        None,
        description="Existing session ID. Omit to create a new session.",
    )
    top_k: Optional[int] = Field(
        10,
        ge=5,
        le=50,
        description="Initial seed chunks for RAG retrieval",
    )
    max_depth: Optional[int] = Field(
        2,
        ge=1,
        le=3,
        description="Graph expansion depth",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "message": "What is the main topic of this knowledge base?",
                "session_id": None,
            }
        }


class CreateSessionRequest(BaseModel):
    """Explicitly create a new chat session."""

    title: Optional[str] = Field(
        None,
        max_length=500,
        description="Session title. Auto-generated from first message if omitted.",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Research Discussion",
            }
        }


class UpdateSessionRequest(BaseModel):
    """Update a chat session (rename, etc.)."""

    title: Optional[str] = Field(
        None,
        max_length=500,
        description="New session title",
    )


# ============================================================================
# RESPONSE SCHEMAS
# ============================================================================


class MessageResponse(BaseModel):
    """Single chat message in response."""

    id: str = Field(..., description="Message UUID")
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")
    position: int = Field(..., description="Message position in session (0-indexed)")
    metadata: Optional[Dict[str, Any]] = Field(
        None, description="RAG metadata for assistant messages"
    )
    created_at: Optional[str] = Field(None, description="ISO timestamp")
    feedback_type: Optional[str] = Field(None, description="thumbs_up / thumbs_down")
    feedback_reason: Optional[str] = Field(None, description="Optional feedback reason")
    feedback_at: Optional[str] = Field(None, description="Feedback timestamp")
    feedback_score: Optional[int] = Field(None, description="Optional feedback score or rating")


class SessionResponse(BaseModel):
    """Chat session summary in response."""

    id: str = Field(..., description="Session UUID")
    agent_id: str = Field(..., description="Agent UUID")
    title: str = Field(..., description="Session title")
    message_count: int = Field(0, description="Total messages in session")
    is_active: bool = Field(True, description="Whether session is active")
    last_message_at: Optional[str] = Field(None, description="Last message ISO timestamp")
    created_at: Optional[str] = Field(None, description="Session creation ISO timestamp")


class SessionDetailResponse(BaseModel):
    """Chat session with all messages."""

    session: SessionResponse = Field(..., description="Session metadata")
    messages: List[MessageResponse] = Field(
        default_factory=list, description="All messages in order"
    )


class SendMessageResponse(BaseModel):
    """Response after sending a message (includes agent reply)."""

    session_id: str = Field(..., description="Session UUID (new or existing)")
    answer: str = Field(..., description="Agent's generated answer")
    sources: List[Dict[str, Any]] = Field(
        default_factory=list, description="Source chunks with scores"
    )
    context: Optional[Dict[str, Any]] = Field(
        None, description="RAG context metadata (kb_name, chunks_used, etc.)"
    )
    message_position: int = Field(
        ..., description="Position of the assistant message in the session"
    )
    memory_used: bool = Field(
        False, description="Whether conversation history was injected into context"
    )
    conversation_turns: int = Field(
        0, description="Number of user-assistant exchanges in this session"
    )


class ChatMessageFeedbackRequest(BaseModel):
    """Request schema for message feedback."""
    message_id: UUID = Field(..., description="Message UUID")
    feedback_type: str = Field(..., description="thumbs_up / thumbs_down")
    feedback_reason: Optional[str] = Field(None, max_length=255, description="Optional feedback reason")
    feedback_score: Optional[int] = Field(None, description="Optional feedback score or rating")

    @field_validator("feedback_type")
    @classmethod
    def validate_feedback_type(cls, v: str) -> str:
        if v not in ["thumbs_up", "thumbs_down"]:
            raise ValueError("feedback_type must be either 'thumbs_up' or 'thumbs_down'")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "message_id": "9a4f9a5d-1234-5678-9012-abcdef123456",
                "feedback_type": "thumbs_down",
                "feedback_reason": "Incorrect Answer"
            }
        }


class ChatMessageFeedbackResponse(BaseModel):
    """Response schema for message feedback."""
    success: bool = Field(True, description="Indicates if the feedback was saved successfully")
    message: str = Field("Feedback saved successfully", description="Status message")


# ============================================================================
# ANALYTICS & DASHBOARD SCHEMAS
# ============================================================================


class FeedbackReasonSummary(BaseModel):
    """Summary of a single feedback reason with count and percentage."""
    feedback_type: str = Field(..., description="thumbs_up / thumbs_down")
    reason: str = Field(..., description="The feedback reason comment")
    count: int = Field(..., description="Number of occurrences")
    percentage: float = Field(..., description="Percentage of total feedback")


class FeedbackReasonsResponse(BaseModel):
    """Response with list of feedback reasons."""
    success: bool = Field(True)
    data: List[FeedbackReasonSummary]
    meta: Dict[str, Any] = Field(default_factory=dict)


class DrilldownFeedbackRecord(BaseModel):
    """A detailed record of a chat feedback instance for administrative drill-down."""
    time: str = Field(..., description="Timestamp of feedback or message creation")
    user: Dict[str, Any] = Field(..., description="User details (id, email, names)")
    tenant: Dict[str, Any] = Field(..., description="Tenant details (id, name)")
    agent: Optional[Dict[str, Any]] = Field(None, description="Agent details (id, name)")
    knowledge_base: List[Dict[str, Any]] = Field(..., description="KBs associated with agent/session")
    feedback_type: str = Field(..., description="thumbs_up / thumbs_down")
    feedback_reason: Optional[str] = Field(None, description="The feedback reason")
    question: Optional[str] = Field(None, description="The user's question before this reply")
    ai_response: str = Field(..., description="The assistant's response")
    rating: Optional[int] = Field(None, description="The rating score")
    view: Dict[str, Any] = Field(..., description="Full context (session, message, chunks, metadata)")


class DrilldownFeedbackResponse(BaseModel):
    """Response with drill-down detailed feedback records."""
    success: bool = Field(True)
    data: List[DrilldownFeedbackRecord]
    meta: Dict[str, Any] = Field(default_factory=dict)


class FeedbackOverviewItem(BaseModel):
    """Overall feedback statistics for a single type (thumbs_up/thumbs_down)."""
    count: int = Field(..., description="Number of feedback items")
    percentage: float = Field(..., description="Percentage of total feedback")


class FeedbackOverviewData(BaseModel):
    """Data payload for overall feedback statistics."""
    positive: FeedbackOverviewItem = Field(..., description="Positive feedback (thumbs_up) statistics")
    negative: FeedbackOverviewItem = Field(..., description="Negative feedback (thumbs_down) statistics")
    total: int = Field(..., description="Total feedback count")


class FeedbackOverviewResponse(BaseModel):
    """Response containing overall feedback statistics."""
    success: bool = Field(True)
    data: FeedbackOverviewData
    meta: Dict[str, Any] = Field(default_factory=dict)
