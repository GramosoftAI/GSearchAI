"""REST routes for Chat History & Memory

ENDPOINTS:
    POST   /api/v1/chats/{agent_id}/sessions            - Create new session
    GET    /api/v1/chats/{agent_id}/sessions            - List sessions
    GET    /api/v1/chats/{agent_id}/sessions/{id}       - Get session with messages
    PATCH  /api/v1/chats/{agent_id}/sessions/{id}       - Update session title
    DELETE /api/v1/chats/{agent_id}/sessions/{id}       - Delete session
    POST   /api/v1/chats/{agent_id}/message             - Send message (core)
    POST   /api/v1/chats/messages/feedback              - Save chat message feedback

PATTERN: Follows existing route conventions from agents/routes.py and rag/routes.py
    - Tenant context from middleware (request.state)
    - AsyncSessionLocal() context manager for DB sessions
    - format_success() / format_error() for standardized responses
    - HTTPException for error handling

NON-BREAKING: These are entirely NEW routes. No existing routes are modified.
"""

import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException, status, BackgroundTasks

from .schemas import (
    SendMessageRequest,
    CreateSessionRequest,
    UpdateSessionRequest,
    SendMessageResponse,
    SessionResponse,
    SessionDetailResponse,
    MessageResponse,
    ChatMessageFeedbackRequest,
    ChatMessageFeedbackResponse,
    FeedbackReasonsResponse,
    DrilldownFeedbackResponse,
    FeedbackOverviewResponse,
)
from .service import ChatService
from .knowledge_service import ChatKnowledgeService
from ...core.database import AsyncSessionLocal
from ...utils.formatters import format_success, format_error, format_paginated

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chats", tags=["Chats"])


# ============================================================================
# REQUEST CONTEXT HELPERS
# ============================================================================


def get_tenant_and_user(request: Request) -> tuple:
    """
    Extract tenant_id and user_id from request context (set by middleware).

    CRITICAL: These are injected by TenantContextMiddleware.
    Never trust values from request body or query params.

    Returns:
        Tuple of (tenant_id, user_id)

    Raises:
        HTTPException if not found in request state
    """
    tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)

    if not tenant_id or not user_id:
        logger.error("Missing tenant_id or user_id in request state")
        raise HTTPException(status_code=401, detail="Unauthorized")

    return str(tenant_id), str(user_id)


def _format_message_for_list(message) -> dict:
    """Format a ChatMessage model with extra details for list views."""
    metadata = message.message_metadata or {}

    # Extract confidence score if present in metadata
    confidence = metadata.get("confidence")

    # Extract sources/nodes count
    sources = metadata.get("sources")
    nodes = len(sources) if isinstance(sources, list) else None

    msg_dict = {
        "role": message.role,
        "content": message.content,
    }

    if confidence is not None:
        msg_dict["confidence"] = confidence
    if nodes is not None:
        msg_dict["nodes"] = nodes
    if message.created_at:
        msg_dict["timestamp"] = message.created_at.isoformat()

    msg_dict["message_count"] = message.position + 1

    return msg_dict


def _format_session(session) -> dict:
    """Format a ChatSession model into API response dict."""
    formatted = {
        "id": str(session.id),
        "agent_id": str(session.agent_id),
        "title": session.title,
        "message_count": session.message_count,
        "is_active": session.is_active,
        "last_message_at": (
            session.last_message_at.isoformat() if session.last_message_at else None
        ),
        "created_at": (
            session.created_at.isoformat() if session.created_at else None
        ),
    }

    if hasattr(session, "messages"):
        formatted["messages"] = [_format_message_for_list(m) for m in session.messages]

    return formatted


def _format_message(message) -> dict:
    """Format a ChatMessage model into API response dict."""
    formatted = {
        "id": str(message.id),
        "role": message.role,
        "content": message.content,
        "position": message.position,
        "metadata": message.message_metadata,
        "created_at": (
            message.created_at.isoformat() if message.created_at else None
        ),
    }
    if getattr(message, "feedback_type", None) is not None:
        formatted["feedback_type"] = message.feedback_type
    if getattr(message, "feedback_reason", None) is not None:
        formatted["feedback_reason"] = message.feedback_reason
    if getattr(message, "feedback_at", None) is not None:
        formatted["feedback_at"] = message.feedback_at.isoformat()
    if getattr(message, "feedback_score", None) is not None:
        formatted["feedback_score"] = message.feedback_score
    return formatted



# ============================================================================
# SESSION ENDPOINTS
# ============================================================================


@router.post(
    "/{agent_id}/sessions",
    status_code=status.HTTP_200_OK,
    summary="Create a new chat session",
    description="Creates a new conversation session with an agent.",
)
async def create_session(
    request: Request,
    agent_id: str,
    body: CreateSessionRequest,
):
    """
    Create a new chat session for an agent.

    Args:
        agent_id: Agent UUID (path param)
        body: Optional title

    Returns:
        Created session metadata
    """
    tenant_id, user_id = get_tenant_and_user(request)

    async with AsyncSessionLocal() as db:
        chat_service = ChatService(db=db, tenant_id=tenant_id)

        try:
            session = await chat_service.create_session(
                agent_id=agent_id.strip(),
                user_id=user_id,
                title=body.title,
            )

            return format_success(_format_session(session))

        except ValueError as e:
            logger.warning(f"Invalid UUID: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid parameter format: {str(e)}"
            )
        except Exception as e:
            logger.error(f" Failed to create session: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Failed to create session: {str(e)}"
            )


@router.get(
    "/{agent_id}/sessions",
    summary="List chat sessions",
    description="List all chat sessions for the authenticated user with an agent.",
)
async def list_sessions(
    request: Request,
    agent_id: str,
    limit: int = 50,
    offset: int = 0,
):
    """
    List chat sessions for a user+agent pair, sorted by most recent first.

    Args:
        agent_id: Agent UUID (path param)
        limit: Max results (default 50)
        offset: Pagination offset

    Returns:
        Paginated list of sessions
    """
    tenant_id, user_id = get_tenant_and_user(request)

    async with AsyncSessionLocal() as db:
        chat_service = ChatService(db=db, tenant_id=tenant_id)

        try:
            sessions, total = await chat_service.list_sessions(
                agent_id=agent_id.strip(),
                user_id=user_id,
                limit=limit,
                offset=offset,
            )

            formatted = [_format_session(s) for s in sessions]
            return format_paginated(formatted, total, skip=offset, limit=limit)

        except ValueError as e:
            logger.warning(f"Invalid UUID: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid parameter format: {str(e)}"
            )
        except Exception as e:
            logger.error(f" Failed to list sessions: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Failed to list sessions: {str(e)}"
            )


@router.get(
    "/{agent_id}/sessions/{session_id}",
    summary="Get session with messages",
    description="Get a chat session with all its messages, ordered chronologically.",
)
async def get_session(
    request: Request,
    agent_id: str,
    session_id: str,
):
    """
    Get a session with all its messages.

    Args:
        agent_id: Agent UUID (path param)
        session_id: Session UUID (path param)

    Returns:
        Session metadata + list of messages
    """
    tenant_id, user_id = get_tenant_and_user(request)

    async with AsyncSessionLocal() as db:
        chat_service = ChatService(db=db, tenant_id=tenant_id)

        try:
            clean_session_id = session_id.strip()
            clean_agent_id = agent_id.strip()

            result = await chat_service.get_session_with_messages(clean_session_id)

            if not result:
                raise HTTPException(status_code=404, detail="Session not found")

            session = result["session"]

            # Validate agent ownership
            if str(session.agent_id) != clean_agent_id:
                raise HTTPException(
                    status_code=403,
                    detail="Session does not belong to this agent",
                )

            formatted = {
                "session": _format_session(session),
                "messages": [_format_message(m) for m in result["messages"]],
            }

            return format_success(formatted)

        except HTTPException:
            raise
        except ValueError as e:
            logger.warning(f"Invalid UUID: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid parameter format: {str(e)}"
            )
        except Exception as e:
            logger.error(f" Failed to get session: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Failed to get session: {str(e)}"
            )


@router.patch(
    "/{agent_id}/sessions/{session_id}",
    summary="Update session",
    description="Update a chat session's title.",
)
async def update_session(
    request: Request,
    agent_id: str,
    session_id: str,
    body: UpdateSessionRequest,
):
    """
    Update session metadata (currently: title only).

    Args:
        agent_id: Agent UUID (path param)
        session_id: Session UUID (path param)
        body: Fields to update

    Returns:
        Updated session metadata
    """
    tenant_id, user_id = get_tenant_and_user(request)

    async with AsyncSessionLocal() as db:
        chat_service = ChatService(db=db, tenant_id=tenant_id)

        try:
            clean_session_id = session_id.strip()
            clean_agent_id = agent_id.strip()

            session = await chat_service.update_session(
                session_id=clean_session_id,
                title=body.title,
            )

            if not session:
                raise HTTPException(status_code=404, detail="Session not found")

            # Validate agent ownership
            if str(session.agent_id) != clean_agent_id:
                raise HTTPException(
                    status_code=403,
                    detail="Session does not belong to this agent",
                )

            return format_success(_format_session(session))

        except HTTPException:
            raise
        except ValueError as e:
            logger.warning(f"Invalid UUID: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid parameter format: {str(e)}"
            )
        except Exception as e:
            logger.error(f" Failed to update session: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Failed to update session: {str(e)}"
            )


@router.delete(
    "/{agent_id}/sessions/{session_id}",
    summary="Delete session",
    description="Soft-delete a chat session and all its messages.",
)
async def delete_session(
    request: Request,
    agent_id: str,
    session_id: str,
):
    """
    Soft-delete a chat session.

    Args:
        agent_id: Agent UUID (path param)
        session_id: Session UUID (path param)

    Returns:
        Success confirmation
    """
    tenant_id, user_id = get_tenant_and_user(request)

    async with AsyncSessionLocal() as db:
        chat_service = ChatService(db=db, tenant_id=tenant_id)

        try:
            clean_session_id = session_id.strip()
            clean_agent_id = agent_id.strip()

            # First verify existence and agent ownership
            result = await chat_service.get_session_with_messages(clean_session_id)
            if not result:
                raise HTTPException(status_code=404, detail="Session not found")
            
            session = result["session"]
            if str(session.agent_id) != clean_agent_id:
                raise HTTPException(
                    status_code=403,
                    detail="Session does not belong to this agent",
                )

            deleted = await chat_service.delete_session(clean_session_id)

            if not deleted:
                raise HTTPException(status_code=404, detail="Session not found")

            return format_success({"deleted": True, "session_id": clean_session_id})

        except HTTPException:
            raise
        except ValueError as e:
            logger.warning(f"Invalid UUID: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid parameter format: {str(e)}"
            )
        except Exception as e:
            logger.error(f" Failed to delete session: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Failed to delete session: {str(e)}"
            )


# ============================================================================
# CORE: SEND MESSAGE
# ============================================================================


@router.post(
    "/{agent_id}/message",
    summary="Send message to agent",
    description=(
        "Send a message to an agent and get a RAG-powered response. "
        "Conversation history is automatically injected as memory context. "
        "If session_id is omitted, a new session is created."
    ),
)
async def send_message(
    request: Request,
    agent_id: str,
    body: SendMessageRequest,
    background_tasks: BackgroundTasks,
):
    """
    Send a message to an agent and receive a response.

    FLOW:
    1. Create or retrieve session
    2. Save user message
    3. Load conversation history (memory injection)
    4. Augment query with memory context
    5. Call existing RAG pipeline (UNTOUCHED)
    6. Save assistant response
    7. Return answer + session info

    Args:
        agent_id: Agent UUID (path param)
        body: Message request with text and optional session_id

    Returns:
        Agent response with sources, session ID, and memory metadata
    """
    tenant_id, user_id = get_tenant_and_user(request)
    clean_agent_id = agent_id.strip()
    clean_session_id = body.session_id.strip() if (body.session_id and body.session_id.strip()) else None

    logger.info(
        f" Chat message: agent={clean_agent_id}, "
        f"session={clean_session_id or 'NEW'}, "
        f"msg_len={len(body.message)}"
    )

    # Validate message length
    if not body.message or len(body.message.strip()) < 1:
        raise HTTPException(
            status_code=400, detail="Message cannot be empty"
        )

    async with AsyncSessionLocal() as db:
        chat_service = ChatService(db=db, tenant_id=tenant_id)

        try:
            result = await chat_service.send_message(
                agent_id=clean_agent_id,
                user_id=user_id,
                message=body.message.strip(),
                session_id=clean_session_id,
                top_k=body.top_k or 10,
                max_depth=body.max_depth or 2,
            )

            # ============= KNOWLEDGE FLYWHEEL (Sync Session to Graph) =============
            # Triggered in background to avoid latency. Extract facts from this turn.
            if result.get("answer") and result.get("sources"):
                # Use the top source chunk to ground the new knowledge
                top_chunk_id = result["sources"][0]["chunk_id"]
                kb_id = result.get("context", {}).get("kb_id")
                
                if top_chunk_id and kb_id:
                    background_tasks.add_task(
                        ChatKnowledgeService.run_sync_background,
                        tenant_id=tenant_id,
                        session_id=result["session_id"],
                        kb_id=kb_id,
                        chunk_id=top_chunk_id,
                        user_message=body.message.strip(),
                        assistant_message=result["answer"]
                    )

            return format_success(result)

        except ValueError as e:
            logger.warning(f"Invalid UUID: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid parameter format: {str(e)}"
            )
        except Exception as e:
            logger.error(f" Chat message failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Failed to process message: {str(e)}"
            )


# ============================================================================
# FEEDBACK ENDPOINT
# ============================================================================


@router.post(
    "/messages/feedback",
    response_model=ChatMessageFeedbackResponse,
    summary="Save message feedback",
    description="Save thumbs_up/thumbs_down feedback and optional reason for an assistant message.",
)
async def save_message_feedback(
    request: Request,
    body: ChatMessageFeedbackRequest,
):
    """
    Save or update thumbs_up/thumbs_down feedback for a chat message.

    Args:
        body: ChatMessageFeedbackRequest (message_id, feedback_type, feedback_reason)

    Returns:
        ChatMessageFeedbackResponse
    """
    tenant_id, user_id = get_tenant_and_user(request)

    async with AsyncSessionLocal() as db:
        chat_service = ChatService(db=db, tenant_id=tenant_id)

        try:
            await chat_service.save_message_feedback(
                message_id=str(body.message_id),
                feedback_type=body.feedback_type,
                feedback_reason=body.feedback_reason,
                feedback_score=body.feedback_score,
            )
            return {
                "success": True,
                "message": "Feedback saved successfully"
            }

        except KeyError as e:
            logger.warning(f"Message not found for feedback: {body.message_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
        except ValueError as e:
            logger.warning(f"Feedback validation failed: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        except Exception as e:
            logger.error(f"Failed to save message feedback: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save feedback: {str(e)}"
            )


# ============================================================================
# ANALYTICS & DASHBOARD ENDPOINTS
# ============================================================================


@router.get(
    "/feedback/analytics/overview",
    response_model=FeedbackOverviewResponse,
    summary="Get overall positive/negative feedback statistics",
)
async def get_feedback_overview(
    request: Request,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    tenant_id: Optional[str] = None,
    kb_id: Optional[str] = None,
    model: Optional[str] = None,
):
    """
    Get positive (thumbs_up) and negative (thumbs_down) feedback counts and percentages.
    """
    from sqlalchemy import select, and_, func, or_
    from app.modules.auth.models import User
    from app.modules.knowledge_bases.models import KnowledgeBase
    from .repository import safe_uuid
    from .models import ChatMessage, ChatSession
    
    current_tenant_id, user_id = get_tenant_and_user(request)
    
    async with AsyncSessionLocal() as db:
        # Validate admin role
        user_query = select(User).where(User.id == safe_uuid(user_id))
        user_res = await db.execute(user_query)
        db_user = user_res.scalar_one_or_none()
        if not db_user or (not db_user.is_admin and db_user.role != "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can access feedback analytics."
            )
            
        is_platform_admin = db_user.is_admin
        
        target_tenant_id = None
        if tenant_id:
            if not is_platform_admin and str(tenant_id) != str(current_tenant_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to access feedback analytics for other tenants."
                )
            target_tenant_id = safe_uuid(tenant_id)
        else:
            if not is_platform_admin:
                target_tenant_id = safe_uuid(current_tenant_id)
                
        # Build filters
        filters = [
            ChatMessage.feedback_type.in_(["thumbs_up", "thumbs_down"])
        ]
        
        if target_tenant_id:
            filters.append(ChatMessage.tenant_id == target_tenant_id)
            
        if start_date:
            filters.append(ChatMessage.feedback_at >= start_date)
        if end_date:
            filters.append(ChatMessage.feedback_at <= end_date)
            
        if model:
            filters.append(
                or_(
                    ChatMessage.message_metadata['model'].astext == model,
                    ChatMessage.message_metadata['stats']['model'].astext == model
                )
            )
            
        # Build query
        query = (
            select(
                ChatMessage.feedback_type,
                func.count(ChatMessage.id).label("total")
            )
            .where(and_(*filters))
        )
        
        if kb_id:
            query = query.join(ChatSession, ChatMessage.session_id == ChatSession.id)
            query = query.join(KnowledgeBase, ChatSession.agent_id == KnowledgeBase.agent_id)
            query = query.where(KnowledgeBase.id == safe_uuid(kb_id))
            
        query = query.group_by(ChatMessage.feedback_type)
        
        result = await db.execute(query)
        rows = result.all()
        
        positive_count = 0
        negative_count = 0
        for r in rows:
            if r.feedback_type == "thumbs_up":
                positive_count = r.total
            elif r.feedback_type == "thumbs_down":
                negative_count = r.total
                
        total_count = positive_count + negative_count
        
        positive_pct = round((positive_count / total_count) * 100, 2) if total_count > 0 else 0.0
        negative_pct = round((negative_count / total_count) * 100, 2) if total_count > 0 else 0.0
        
        return {
            "success": True,
            "data": {
                "positive": {
                    "count": positive_count,
                    "percentage": positive_pct
                },
                "negative": {
                    "count": negative_count,
                    "percentage": negative_pct
                },
                "total": total_count
            }
        }


@router.get(
    "/feedback/analytics/reasons",
    response_model=FeedbackReasonsResponse,
    summary="Get summary of feedback reasons for analytics dashboard",
)
async def get_feedback_reasons(
    request: Request,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    tenant_id: Optional[str] = None,
    kb_id: Optional[str] = None,
    model: Optional[str] = None,
):
    """
    Get the most common feedback reasons along with their occurrence count and percentage.
    """
    from sqlalchemy import select, and_, func, or_
    from app.modules.auth.models import User
    from app.modules.knowledge_bases.models import KnowledgeBase
    from .repository import safe_uuid
    from .models import ChatMessage, ChatSession
    
    current_tenant_id, user_id = get_tenant_and_user(request)
    
    async with AsyncSessionLocal() as db:
        # Validate admin role
        user_query = select(User).where(User.id == safe_uuid(user_id))
        user_res = await db.execute(user_query)
        db_user = user_res.scalar_one_or_none()
        if not db_user or (not db_user.is_admin and db_user.role != "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can access feedback analytics."
            )
            
        is_platform_admin = db_user.is_admin
        
        target_tenant_id = None
        if tenant_id:
            if not is_platform_admin and str(tenant_id) != str(current_tenant_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to access feedback analytics for other tenants."
                )
            target_tenant_id = safe_uuid(tenant_id)
        else:
            if not is_platform_admin:
                target_tenant_id = safe_uuid(current_tenant_id)
                
        # Build filters
        filters = [
            ChatMessage.feedback_type.in_(["thumbs_up", "thumbs_down"]),
            ChatMessage.feedback_reason.isnot(None)
        ]
        
        if target_tenant_id:
            filters.append(ChatMessage.tenant_id == target_tenant_id)
            
        if start_date:
            filters.append(ChatMessage.feedback_at >= start_date)
        if end_date:
            filters.append(ChatMessage.feedback_at <= end_date)
            
        if model:
            filters.append(
                or_(
                    ChatMessage.message_metadata['model'].astext == model,
                    ChatMessage.message_metadata['stats']['model'].astext == model
                )
            )
            
        # Build query
        query = (
            select(
                ChatMessage.feedback_type,
                ChatMessage.feedback_reason,
                func.count(ChatMessage.id).label("total")
            )
            .where(and_(*filters))
        )
        
        if kb_id:
            query = query.join(ChatSession, ChatMessage.session_id == ChatSession.id)
            query = query.join(KnowledgeBase, ChatSession.agent_id == KnowledgeBase.agent_id)
            query = query.where(KnowledgeBase.id == safe_uuid(kb_id))
            
        query = query.group_by(ChatMessage.feedback_type, ChatMessage.feedback_reason).order_by(func.count(ChatMessage.id).desc())
        
        result = await db.execute(query)
        rows = result.all()
        
        grand_total = sum(r.total for r in rows)
        
        data = []
        for r in rows:
            pct = round((r.total / grand_total) * 100, 2) if grand_total > 0 else 0.0
            data.append({
                "feedback_type": r.feedback_type,
                "reason": r.feedback_reason,
                "count": r.total,
                "percentage": pct
            })
            
        return {
            "success": True,
            "data": data,
            "meta": {
                "total_feedback_count": grand_total
            }
        }


@router.get(
    "/feedback/analytics/drilldown",
    response_model=DrilldownFeedbackResponse,
    summary="Get detailed feedback records for drill-down view",
)
async def get_feedback_drilldown(
    request: Request,
    reason: str,
    feedback_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    tenant_id: Optional[str] = None,
    kb_id: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """
    Get detailed records of a specific feedback reason for administrators to drill down and investigate.
    """
    from sqlalchemy import select, and_, func, or_
    from app.modules.auth.models import User, Tenant
    from app.modules.knowledge_bases.models import KnowledgeBase
    from .repository import safe_uuid
    from .models import ChatMessage, ChatSession
    from app.modules.agents.models import Agent
    
    current_tenant_id, user_id = get_tenant_and_user(request)
    
    async with AsyncSessionLocal() as db:
        # Validate admin role
        user_query = select(User).where(User.id == safe_uuid(user_id))
        user_res = await db.execute(user_query)
        db_user = user_res.scalar_one_or_none()
        if not db_user or (not db_user.is_admin and db_user.role != "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can access feedback analytics."
            )
            
        is_platform_admin = db_user.is_admin
        
        target_tenant_id = None
        if tenant_id:
            if not is_platform_admin and str(tenant_id) != str(current_tenant_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to access feedback analytics for other tenants."
                )
            target_tenant_id = safe_uuid(tenant_id)
        else:
            if not is_platform_admin:
                target_tenant_id = safe_uuid(current_tenant_id)
                
        # Build filters
        filters = [
            ChatMessage.feedback_type.in_(["thumbs_up", "thumbs_down"]),
            ChatMessage.feedback_reason == reason
        ]
        
        if target_tenant_id:
            filters.append(ChatMessage.tenant_id == target_tenant_id)
            
        if feedback_type:
            filters.append(ChatMessage.feedback_type == feedback_type)
            
        if start_date:
            filters.append(ChatMessage.feedback_at >= start_date)
        if end_date:
            filters.append(ChatMessage.feedback_at <= end_date)
            
        if model:
            filters.append(
                or_(
                    ChatMessage.message_metadata['model'].astext == model,
                    ChatMessage.message_metadata['stats']['model'].astext == model
                )
            )
            
        # Base query joining ChatSession, User, Tenant, and Agent
        query = (
            select(ChatMessage, ChatSession, User, Tenant, Agent)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .join(User, ChatSession.user_id == User.id)
            .join(Tenant, ChatSession.tenant_id == Tenant.id)
            .join(Agent, ChatSession.agent_id == Agent.id)
            .where(and_(*filters))
        )
        
        if kb_id:
            query = query.join(KnowledgeBase, ChatSession.agent_id == KnowledgeBase.agent_id)
            query = query.where(KnowledgeBase.id == safe_uuid(kb_id))
            
        # Get total count for metadata pagination
        count_query = select(func.count(ChatMessage.id)).where(and_(*filters))
        if kb_id:
            count_query = count_query.join(ChatSession, ChatMessage.session_id == ChatSession.id)
            count_query = count_query.join(KnowledgeBase, ChatSession.agent_id == KnowledgeBase.agent_id)
            count_query = count_query.where(KnowledgeBase.id == safe_uuid(kb_id))
            
        count_res = await db.execute(count_query)
        total_count = count_res.scalar() or 0
        
        # Paginated results
        query = query.order_by(ChatMessage.feedback_at.desc()).limit(limit).offset(offset)
        result = await db.execute(query)
        rows = result.all()
        
        # Fetch corresponding user questions in bulk
        user_msg_conditions = []
        for msg, _, _, _, _ in rows:
            user_msg_conditions.append(
                and_(
                    ChatMessage.session_id == msg.session_id,
                    ChatMessage.position == msg.position - 1
                )
            )
            
        user_msgs = {}
        if user_msg_conditions:
            user_msgs_query = select(ChatMessage).where(or_(*user_msg_conditions))
            user_msgs_res = await db.execute(user_msgs_query)
            for u_msg in user_msgs_res.scalars().all():
                user_msgs[(u_msg.session_id, u_msg.position)] = u_msg.content
                
        # Fetch associated Knowledge Bases in bulk
        agent_ids = list(set(session.agent_id for _, session, _, _, _ in rows))
        agent_kbs = {}
        if agent_ids:
            kbs_query = select(KnowledgeBase).where(KnowledgeBase.agent_id.in_(agent_ids))
            kbs_res = await db.execute(kbs_query)
            from collections import defaultdict
            agent_kbs = defaultdict(list)
            for kb in kbs_res.scalars().all():
                agent_kbs[kb.agent_id].append({
                    "id": str(kb.id),
                    "name": kb.name
                })
                
        # Format records
        records = []
        for msg, session, usr, tnt, agent in rows:
            question = user_msgs.get((msg.session_id, msg.position - 1), "Question not found")
            
            user_info = {
                "id": str(usr.id),
                "email": usr.email,
                "first_name": usr.first_name or "",
                "last_name": usr.last_name or ""
            }
            
            tenant_info = {
                "id": str(tnt.id),
                "name": tnt.name
            }
            
            agent_info = {
                "id": str(agent.id),
                "name": agent.name
            }
            
            kb_list = agent_kbs.get(session.agent_id, [])
            
            metadata = msg.message_metadata or {}
            retrieved_chunks = metadata.get("sources", [])
            citations = [c.get("source") for c in retrieved_chunks if c.get("source")]
            citations = list(set(citations))
            
            view_detail = {
                "session_id": str(session.id),
                "message_id": str(msg.id),
                "agent_id": str(session.agent_id),
                "retrieved_chunks": retrieved_chunks,
                "citations": citations,
                "metadata": metadata
            }
            
            records.append({
                "time": (msg.feedback_at or msg.created_at).isoformat(),
                "user": user_info,
                "tenant": tenant_info,
                "agent": agent_info,
                "knowledge_base": kb_list,
                "feedback_type": msg.feedback_type,
                "feedback_reason": msg.feedback_reason,
                "question": question,
                "ai_response": msg.content,
                "rating": msg.feedback_score,
                "view": view_detail
            })
            
        return {
            "success": True,
            "data": records,
            "meta": {
                "total": total_count,
                "limit": limit,
                "offset": offset
            }
        }


@router.get(
    "/feedback/analytics/messages",
    response_model=DrilldownFeedbackResponse,
    summary="Get detailed feedback messages with filters",
)
async def get_feedback_messages(
    request: Request,
    feedback_reason: Optional[str] = None,
    feedback_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    tenant_id: Optional[str] = None,
    kb_id: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """
    Get list of chat messages where feedback_type is present, with filtering capabilities.
    """
    from sqlalchemy import select, and_, func, or_
    from app.modules.auth.models import User, Tenant
    from app.modules.knowledge_bases.models import KnowledgeBase
    from .repository import safe_uuid
    from .models import ChatMessage, ChatSession
    from app.modules.agents.models import Agent
    
    current_tenant_id, user_id = get_tenant_and_user(request)
    
    async with AsyncSessionLocal() as db:
        # Validate admin role
        user_query = select(User).where(User.id == safe_uuid(user_id))
        user_res = await db.execute(user_query)
        db_user = user_res.scalar_one_or_none()
        if not db_user or (not db_user.is_admin and db_user.role != "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only administrators can access feedback analytics."
            )
            
        is_platform_admin = db_user.is_admin
        
        target_tenant_id = None
        if tenant_id:
            if not is_platform_admin and str(tenant_id) != str(current_tenant_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to access feedback analytics for other tenants."
                )
            target_tenant_id = safe_uuid(tenant_id)
        else:
            if not is_platform_admin:
                target_tenant_id = safe_uuid(current_tenant_id)
                
        # Build filters
        filters = [
            ChatMessage.feedback_type.isnot(None)
        ]
        
        if target_tenant_id:
            filters.append(ChatMessage.tenant_id == target_tenant_id)
            
        if feedback_type:
            filters.append(ChatMessage.feedback_type == feedback_type)
            
        if feedback_reason:
            filters.append(ChatMessage.feedback_reason == feedback_reason)
            
        if start_date:
            filters.append(ChatMessage.feedback_at >= start_date)
        if end_date:
            filters.append(ChatMessage.feedback_at <= end_date)
            
        if model:
            filters.append(
                or_(
                    ChatMessage.message_metadata['model'].astext == model,
                    ChatMessage.message_metadata['stats']['model'].astext == model
                )
            )
            
        # Base query joining ChatSession, User, Tenant, and Agent
        query = (
            select(ChatMessage, ChatSession, User, Tenant, Agent)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .join(User, ChatSession.user_id == User.id)
            .join(Tenant, ChatSession.tenant_id == Tenant.id)
            .join(Agent, ChatSession.agent_id == Agent.id)
            .where(and_(*filters))
        )
        
        if kb_id:
            query = query.join(KnowledgeBase, ChatSession.agent_id == KnowledgeBase.agent_id)
            query = query.where(KnowledgeBase.id == safe_uuid(kb_id))
            
        # Get total count for metadata pagination
        count_query = select(func.count(ChatMessage.id)).where(and_(*filters))
        if kb_id:
            count_query = count_query.join(ChatSession, ChatMessage.session_id == ChatSession.id)
            count_query = count_query.join(KnowledgeBase, ChatSession.agent_id == KnowledgeBase.agent_id)
            count_query = count_query.where(KnowledgeBase.id == safe_uuid(kb_id))
            
        count_res = await db.execute(count_query)
        total_count = count_res.scalar() or 0
        
        # Paginated results
        query = query.order_by(ChatMessage.feedback_at.desc()).limit(limit).offset(offset)
        result = await db.execute(query)
        rows = result.all()
        
        # Fetch corresponding user questions in bulk
        user_msg_conditions = []
        for msg, _, _, _, _ in rows:
            user_msg_conditions.append(
                and_(
                    ChatMessage.session_id == msg.session_id,
                    ChatMessage.position == msg.position - 1
                )
            )
            
        user_msgs = {}
        if user_msg_conditions:
            user_msgs_query = select(ChatMessage).where(or_(*user_msg_conditions))
            user_msgs_res = await db.execute(user_msgs_query)
            for u_msg in user_msgs_res.scalars().all():
                user_msgs[(u_msg.session_id, u_msg.position)] = u_msg.content
                
        # Fetch associated Knowledge Bases in bulk
        agent_ids = list(set(session.agent_id for _, session, _, _, _ in rows))
        agent_kbs = {}
        if agent_ids:
            kbs_query = select(KnowledgeBase).where(KnowledgeBase.agent_id.in_(agent_ids))
            kbs_res = await db.execute(kbs_query)
            from collections import defaultdict
            agent_kbs = defaultdict(list)
            for kb in kbs_res.scalars().all():
                agent_kbs[kb.agent_id].append({
                    "id": str(kb.id),
                    "name": kb.name
                })
                
        # Format records
        records = []
        for msg, session, usr, tnt, agent in rows:
            question = user_msgs.get((msg.session_id, msg.position - 1), "Question not found")
            
            user_info = {
                "id": str(usr.id),
                "email": usr.email,
                "first_name": usr.first_name or "",
                "last_name": usr.last_name or ""
            }
            
            tenant_info = {
                "id": str(tnt.id),
                "name": tnt.name
            }
            
            agent_info = {
                "id": str(agent.id),
                "name": agent.name
            }
            
            kb_list = agent_kbs.get(session.agent_id, [])
            
            metadata = msg.message_metadata or {}
            retrieved_chunks = metadata.get("sources", [])
            citations = [c.get("source") for c in retrieved_chunks if c.get("source")]
            citations = list(set(citations))
            
            view_detail = {
                "session_id": str(session.id),
                "message_id": str(msg.id),
                "agent_id": str(session.agent_id),
                "retrieved_chunks": retrieved_chunks,
                "citations": citations,
                "metadata": metadata
            }
            
            records.append({
                "time": (msg.feedback_at or msg.created_at).isoformat(),
                "user": user_info,
                "tenant": tenant_info,
                "agent": agent_info,
                "knowledge_base": kb_list,
                "feedback_type": msg.feedback_type,
                "feedback_reason": msg.feedback_reason,
                "question": question,
                "ai_response": msg.content,
                "rating": msg.feedback_score,
                "view": view_detail
            })
            
        return {
            "success": True,
            "data": records,
            "meta": {
                "total": total_count,
                "limit": limit,
                "offset": offset
            }
        }
