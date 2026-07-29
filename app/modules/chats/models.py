"""Chat models - ChatSession and ChatMessage stored in PostgreSQL

ARCHITECTURE:
    ChatSession: Represents a conversation between a user and an agent.
    ChatMessage: Individual message within a session (user or assistant).

RELATIONSHIPS:
    Tenant  1:N  ChatSession  1:N  ChatMessage
    User    1:N  ChatSession
    Agent   1:N  ChatSession

MULTI-TENANCY:
    - Both tables have tenant_id for RLS enforcement
    - All queries MUST include tenant_id filtering
    - RLS policies are auto-created at startup

DESIGN DECISIONS:
    - Messages store full content (not references) for fast retrieval
    - metadata JSON column stores sources, tokens, latency per message
    - position field ensures strict message ordering within a session
    - Soft delete on sessions (is_active flag) for audit trail
"""

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
    UUID as SQLAlchemyUUID,
)
from sqlalchemy.sql import func
from datetime import datetime
import uuid

# Use the shared Base from models package (ensures proper metadata registration)
from ...models.base import Base


class ChatSession(Base):
    """
    Chat Session - represents a conversation between a user and an agent.

    CRITICAL:
    - Each session belongs to one tenant (RLS enforced)
    - Each session is tied to one agent and one user
    - Sessions are soft-deleted (is_active flag)
    - last_message_at tracks recency for sorting

    Properties:
    - id: Unique UUID per session
    - tenant_id: Multi-tenancy scoping (RLS filtered)
    - user_id: User who started the conversation
    - agent_id: Agent this conversation is with
    - title: Auto-generated from first message or user-provided
    - message_count: Denormalized count for fast display
    - is_active: For soft-deletion
    - last_message_at: Most recent message timestamp (for sorting)
    """

    __tablename__ = "chat_sessions"

    # ============= PRIMARY KEY =============
    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    # ============= MULTI-TENANCY =============
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ============= OWNERSHIP =============
    user_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ============= AGENT RELATIONSHIP =============
    agent_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ============= SESSION METADATA =============
    title = Column(
        String(500),
        nullable=False,
        default="New Conversation",
    )

    # Denormalized message count for fast listing (avoid COUNT query)
    message_count = Column(
        Integer,
        nullable=False,
        default=0,
    )

    # ============= STATUS =============
    is_active = Column(Boolean, default=True, nullable=False)

    # ============= TEMPORAL TRACKING =============
    last_message_at = Column(
        DateTime(timezone=True),
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

    # ============= INDEXES =============
    __table_args__ = (
        # RLS enforcement
        Index("ix_chat_sessions_tenant_id", "tenant_id"),
        # Find sessions by user
        Index("ix_chat_sessions_user_id", "user_id"),
        # Find sessions by agent
        Index("ix_chat_sessions_agent_id", "agent_id"),
        # Composite: tenant + agent + user (list conversations)
        Index("ix_chat_sessions_tenant_agent_user", "tenant_id", "agent_id", "user_id"),
        # Sort by recency
        Index("ix_chat_sessions_last_message", "last_message_at"),
        # Soft-delete filtering
        Index("ix_chat_sessions_is_active", "is_active"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        return (
            f"<ChatSession id={self.id} agent_id={self.agent_id} "
            f"messages={self.message_count} title={self.title[:30]}>"
        )


class ChatMessage(Base):
    """
    Chat Message - individual message within a chat session.

    CRITICAL:
    - Each message belongs to one session AND one tenant (double RLS)
    - role is either 'user' or 'assistant'
    - position ensures strict ordering (0-indexed)
    - metadata stores RAG pipeline details (sources, tokens, latency)

    Properties:
    - id: Unique UUID per message
    - session_id: FK to ChatSession
    - tenant_id: Multi-tenancy scoping (RLS filtered)
    - role: 'user' or 'assistant'
    - content: Full message text
    - metadata: JSON with sources, tokens, latency, etc.
    - position: Message order within session (0-indexed)
    """

    __tablename__ = "chat_messages"

    # ============= PRIMARY KEY =============
    id = Column(
        SQLAlchemyUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
        nullable=False,
    )

    # ============= SESSION RELATIONSHIP =============
    session_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ============= MULTI-TENANCY =============
    tenant_id = Column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ============= MESSAGE DATA =============
    role = Column(
        String(20),
        nullable=False,
    )  # 'user' or 'assistant'

    content = Column(
        Text,
        nullable=False,
    )

    # ============= RAG METADATA =============
    # Stores pipeline details for assistant messages:
    # {
    #   "sources": [{"chunk_id": "...", "score": 0.95}],
    #   "tokens_used": 450,
    #   "latency_ms": 1200,
    #   "model": "Qwen/Qwen2.5-72B-Instruct",
    #   "confidence": 0.87,
    #   "kb_name": "Research KB"
    # }
    # NOTE: 'metadata' is reserved by SQLAlchemy Declarative API.
    # Using 'message_metadata' instead.
    from sqlalchemy.dialects.postgresql import JSONB as PostgresJSONB
    message_metadata = Column(
        PostgresJSONB,
        nullable=True,
        default=dict,
    )

    # ============= ORDERING =============
    position = Column(
        Integer,
        nullable=False,
        default=0,
    )

    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # ============= FEEDBACK =============
    feedback_type = Column(
        String(20),
        nullable=True,
    )  # thumbs_up / thumbs_down

    feedback_reason = Column(
        String(255),
        nullable=True,
    )

    feedback_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    feedback_score = Column(
        Integer,
        nullable=True,
    )

    # ============= INDEXES =============
    __table_args__ = (
        # RLS enforcement
        Index("ix_chat_messages_tenant_id", "tenant_id"),
        # Find messages by session (primary query pattern)
        Index("ix_chat_messages_session_id", "session_id"),
        # Composite: session + position (ordered message retrieval)
        Index("ix_chat_messages_session_position", "session_id", "position"),
        {"extend_existing": True},
    )

    def __repr__(self) -> str:
        preview = self.content[:40] if self.content else ""
        return (
            f"<ChatMessage id={self.id} role={self.role} "
            f"pos={self.position} preview={preview}...>"
        )
