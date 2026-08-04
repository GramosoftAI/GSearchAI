"""Repository layer for Chat History (PostgreSQL)

PATTERN: Follows BaseRepository convention from knowledge_bases/repository.py
    - All queries include tenant_id filtering (RLS enforcement)
    - Soft-delete support on sessions
    - Pagination on list operations
    - Denormalized message_count on sessions for fast listing

CRITICAL:
    - NEVER return data from other tenants
    - All session lookups validate tenant_id
    - Message ordering guaranteed by position field
"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func as sql_func, delete, update
from typing import Optional, List, Tuple, Any
import logging
import uuid
from datetime import datetime

from .models import ChatSession, ChatMessage
from ...core.base_repository import BaseRepository

logger = logging.getLogger(__name__)


def safe_uuid(val: Any) -> uuid.UUID:
    """Safely convert a value to uuid.UUID, stripping any whitespace if it's a string."""
    if isinstance(val, uuid.UUID):
        return val
    if isinstance(val, str):
        clean_val = val.strip().strip("'\"")
        return uuid.UUID(clean_val)
    return uuid.UUID(str(val))


class ChatRepository(BaseRepository):
    """
    Repository for Chat Session and Message CRUD operations.

    CRITICAL: All queries include tenant_id filtering (RLS enforcement).
    """

    def __init__(self, db: AsyncSession, tenant_id: str):
        """
        Initialize Chat repository with tenant context.

        Args:
            db: Database session
            tenant_id: Tenant UUID (for RLS filtering)
        """
        super().__init__(db, tenant_id)

    # ========================================================================
    # SESSION OPERATIONS
    # ========================================================================

    async def create_session(
        self,
        agent_id: str,
        user_id: str,
        title: str = "New Conversation",
        session_id: Optional[str] = None,
    ) -> ChatSession:
        """
        Create a new chat session.

        Args:
            agent_id: Agent UUID this session is with
            user_id: User UUID who started the conversation
            title: Session title (auto-generated from first message if default)
            session_id: Optional custom session UUID

        Returns:
            Created ChatSession model instance
        """
        session = ChatSession(
            id=safe_uuid(session_id) if session_id else uuid.uuid4(),
            tenant_id=self.tenant_id,
            user_id=safe_uuid(user_id),
            agent_id=safe_uuid(agent_id),
            title=title,
            message_count=0,
            is_active=True,
        )

        self.db.add(session)
        await self.db.flush()

        logger.info(
            f" Created chat session: {session.id} "
            f"(agent: {agent_id}, user: {user_id})"
        )
        return session

    async def get_session_by_id(self, session_id: str) -> Optional[ChatSession]:
        """
        Get session by ID with tenant_id filtering (RLS).

        Args:
            session_id: Session UUID

        Returns:
            ChatSession model or None

        GUARANTEE: Cannot return session from other tenants
        """
        result = await self.db.execute(
            select(ChatSession).where(
                and_(
                    ChatSession.id == safe_uuid(session_id),
                    ChatSession.tenant_id == self.tenant_id,
                    ChatSession.is_active == True,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_sessions_by_agent(
        self,
        agent_id: str,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[ChatSession], int]:
        """
        List all active sessions for a user+agent pair with pagination.

        Sorted by last_message_at descending (most recent first).

        Args:
            agent_id: Agent UUID
            user_id: User UUID
            limit: Max results
            offset: Pagination offset

        Returns:
            Tuple of (sessions, total_count)

        GUARANTEE: Only returns sessions for this tenant
        """
        # Base filter
        filters = and_(
            ChatSession.tenant_id == self.tenant_id,
            ChatSession.agent_id == safe_uuid(agent_id),
            ChatSession.user_id == safe_uuid(user_id),
            ChatSession.is_active == True,
        )

        # Get count
        count_result = await self.db.execute(
            select(sql_func.count(ChatSession.id)).where(filters)
        )
        total = count_result.scalar() or 0

        # Get paginated results
        result = await self.db.execute(
            select(ChatSession)
            .where(filters)
            .order_by(ChatSession.last_message_at.desc().nullslast())
            .limit(limit)
            .offset(offset)
        )
        sessions = list(result.scalars().all())

        logger.debug(
            f"Listed {len(sessions)} sessions for agent {agent_id} "
            f"(total: {total}, user: {user_id})"
        )
        return sessions, total

    async def update_session(
        self,
        session_id: str,
        **kwargs,
    ) -> Optional[ChatSession]:
        """
        Update session fields (title, etc.).

        Args:
            session_id: Session UUID
            **kwargs: Fields to update

        Returns:
            Updated ChatSession or None if not found
        """
        session = await self.get_session_by_id(session_id)
        if not session:
            logger.warning(f"Cannot update: session not found: {session_id}")
            return None

        update_fields = {
            k: v for k, v in kwargs.items() if v is not None and hasattr(session, k)
        }

        for field, value in update_fields.items():
            setattr(session, field, value)

        await self.db.flush()
        logger.debug(f"Updated session {session_id}: {list(update_fields.keys())}")
        return session

    async def soft_delete_session(self, session_id: str) -> bool:
        """
        Soft delete a session (set is_active = False).

        Args:
            session_id: Session UUID

        Returns:
            True if deleted, False if not found
        """
        session = await self.get_session_by_id(session_id)
        if not session:
            logger.warning(f"Cannot delete: session not found: {session_id}")
            return False

        session.is_active = False
        await self.db.flush()

        logger.info(f"Soft deleted session: {session_id}")
        return True

    # ========================================================================
    # MESSAGE OPERATIONS
    # ========================================================================

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> ChatMessage:
        """
        Add a message to a session.

        CRITICAL: Also updates session's message_count and last_message_at.

        Args:
            session_id: Session UUID
            role: 'user' or 'assistant'
            content: Message text
            metadata: Optional RAG metadata (sources, tokens, etc.)

        Returns:
            Created ChatMessage model instance
        """
        # Get current message count for position
        session = await self.get_session_by_id(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        position = session.message_count

        # Create message
        message = ChatMessage(
            id=uuid.uuid4(),
            session_id=safe_uuid(session_id),
            tenant_id=self.tenant_id,
            role=role,
            content=content,
            message_metadata=metadata or {},
            position=position,
        )

        self.db.add(message)

        # Update session metadata (denormalized)
        session.message_count = position + 1
        session.last_message_at = datetime.utcnow()

        # Auto-title from first user message (if still default)
        if position == 0 and role == "user" and session.title == "New Conversation":
            # Use first 80 chars of first message as title
            session.title = content[:80].strip()
            if len(content) > 80:
                session.title += "..."

        await self.db.flush()

        logger.debug(
            f"Added {role} message to session {session_id} "
            f"(position={position}, length={len(content)})"
        )
        return message

    async def get_messages(
        self,
        session_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[ChatMessage]:
        """
        Get messages for a session, ordered by position ascending.

        Args:
            session_id: Session UUID
            limit: Max messages to return (None = all)
            offset: Skip first N messages

        Returns:
            List of ChatMessage models, ordered by position

        GUARANTEE: Only returns messages for this tenant
        """
        query = (
            select(ChatMessage)
            .where(
                and_(
                    ChatMessage.session_id == safe_uuid(session_id),
                    ChatMessage.tenant_id == self.tenant_id,
                )
            )
            .order_by(ChatMessage.position.asc())
            .offset(offset)
        )

        if limit is not None:
            query = query.limit(limit)

        result = await self.db.execute(query)
        messages = list(result.scalars().all())

        logger.debug(
            f"Retrieved {len(messages)} messages for session {session_id}"
        )
        return messages

    async def get_recent_messages(
        self,
        session_id: str,
        count: int = 10,
    ) -> List[ChatMessage]:
        """
        Get the N most recent messages for memory injection.

        Returns messages in chronological order (oldest first),
        which is the correct order for LLM context.

        DESIGN: Uses subquery to get the latest N by position DESC,
        then re-orders ASC for chronological display.

        Args:
            session_id: Session UUID
            count: Number of recent messages to retrieve

        Returns:
            List of ChatMessage models, chronological order (oldest first)
        """
        # Get total message count first
        session = await self.get_session_by_id(session_id)
        if not session or session.message_count == 0:
            return []

        # Calculate offset to get last N messages
        offset = max(0, session.message_count - count)

        result = await self.db.execute(
            select(ChatMessage)
            .where(
                and_(
                    ChatMessage.session_id == safe_uuid(session_id),
                    ChatMessage.tenant_id == self.tenant_id,
                )
            )
            .order_by(ChatMessage.position.asc())
            .offset(offset)
        )
        messages = list(result.scalars().all())

        logger.debug(
            f"Retrieved {len(messages)} recent messages for memory "
            f"(session {session_id}, total={session.message_count})"
        )
        return messages

    async def get_messages_for_sessions(
        self,
        session_ids: List[uuid.UUID],
    ) -> List[ChatMessage]:
        """
        Get all messages for a list of session IDs, ordered by session_id and position.

        Args:
            session_ids: List of session UUIDs

        Returns:
            List of ChatMessage models
        """
        if not session_ids:
            return []

        query = (
            select(ChatMessage)
            .where(
                and_(
                    ChatMessage.session_id.in_(session_ids),
                    ChatMessage.tenant_id == self.tenant_id,
                )
            )
            .order_by(ChatMessage.session_id, ChatMessage.position.asc())
        )
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_message_by_id(self, message_id: str) -> Optional[ChatMessage]:
        """
        Get message by ID with tenant_id filtering (RLS).

        Args:
            message_id: Message UUID

        Returns:
            ChatMessage model or None
        """
        result = await self.db.execute(
            select(ChatMessage).where(
                and_(
                    ChatMessage.id == safe_uuid(message_id),
                    ChatMessage.tenant_id == self.tenant_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def save_message_feedback(
        self,
        message: ChatMessage,
        feedback_type: str,
        feedback_reason: Optional[str] = None,
        feedback_score: Optional[int] = None,
    ) -> ChatMessage:
        """
        Save feedback to the ChatMessage.
        """
        message.feedback_type = feedback_type
        message.feedback_reason = feedback_reason
        message.feedback_score = feedback_score
        message.feedback_at = datetime.utcnow()
        await self.db.flush()
        return message
