"""REST routes for Embeddable Chat Widget



This module handles public requests from the external chat widget.

It bypasses standard JWT authorization but enforces strict Multi-Tenancy

by validating agent ownership against tenant_id and setting PostgreSQL RLS.

"""



import os

import uuid

import logging

import json

import asyncio

from typing import Optional

from fastapi import APIRouter, Request, HTTPException, status, BackgroundTasks, Query, Response, WebSocket, WebSocketDisconnect

from pydantic import BaseModel, Field



from ..chats.service import ChatService

from ..chats.knowledge_service import ChatKnowledgeService

from ..agents.repository import AgentRepository

from ..auth.models import User

from ...core.database import AsyncSessionLocal, get_db_public, get_db_with_tenant

from ...utils.formatters import format_success, format_error

from sqlalchemy import select, text



logger = logging.getLogger(__name__)



router = APIRouter(prefix="/api/v1/embed", tags=["Embed"])



# ============================================================================

# PYDANTIC SCHEMAS

# ============================================================================



class EmbedMessageRequest(BaseModel):

    tenant_id: str = Field(..., description="Tenant UUID")

    message: str = Field(..., min_length=1, max_length=5000, description="User message text")

    session_id: Optional[str] = Field(None, description="Existing session UUID")

    top_k: Optional[int] = Field(10, ge=5, le=50, description="RAG retrieve top K chunks")

    max_depth: Optional[int] = Field(2, ge=1, le=3, description="Graph expansion depth")





# ============================================================================

# HELPER FOR TENANT/AGENT SECURITY

# ============================================================================



async def verify_agent_belongs_to_tenant(db, tenant_id: str, agent_id: str) -> bool:

    """

    Securely verify that the agent exists and belongs to the given tenant.

    Enforces active PostgreSQL RLS.

    """

    try:

        # Step 1: Set PostgreSQL session variable for RLS

        await db.execute(

            text("SELECT set_config('app.current_tenant', :tenant_id, false)"),

            {"tenant_id": str(tenant_id)}

        )



        # Step 2: Initialize repo (which queries under active RLS)

        agent_repo = AgentRepository(db, tenant_id=tenant_id)

        agent = await agent_repo.get_by_id(agent_id)

        

        return agent is not None

    except Exception as e:

        logger.error(f"Error validating agent-tenant mapping: {e}", exc_info=True)

        return False





async def resolve_or_issue_visitor_id(websocket: WebSocket, tenant_id: str) -> str:
    """
    Widget JS sends back a previously-issued visitor token (from cookie or
    localStorage) if it has one. If absent, invalid, or not signed by us,
    issue a fresh one server-side. Never trust a bare client-supplied ID.
    """
    from ...core.security import verify_visitor_token_signature, issue_signed_visitor_token
    
    candidate = websocket.query_params.get("vtoken")
    if candidate:
        visitor_id = verify_visitor_token_signature(candidate, tenant_id)
        if visitor_id:
            return visitor_id

    # If no valid token, issue a new one
    new_token = issue_signed_visitor_token(tenant_id)
    # The client must receive this, but since we are handling this before entering the main loop,
    # we will send it immediately to the client.
    await websocket.send_json({"type": "session", "vtoken": new_token})
    
    return verify_visitor_token_signature(new_token, tenant_id)


async def get_or_create_widget_user(db, tenant_id: str, visitor_id: str = None) -> User:
    """
    Retrieve or create a unique system-designated user for this specific widget visitor
    to own their specific conversation histories.
    """
    tenant_uuid = uuid.UUID(tenant_id)
    # Make email unique to visitor_id if provided, else fallback to tenant_id for legacy HTTP
    if visitor_id:
        widget_email = f"widget_{visitor_id[:8]}@graphmind.local"
    else:
        widget_email = f"widget_user_{tenant_id[:8]}@graphmind.local"

    

    # Check if user already exists (scoped by RLS to the set tenant_id)

    result = await db.execute(

        select(User).where(User.email == widget_email)

    )

    widget_user = result.scalar_one_or_none()

    

    if not widget_user:

        logger.info(f"Creating new anonymous widget user for tenant {tenant_id}")

        widget_user = User(

            id=uuid.uuid4(),

            tenant_id=tenant_uuid,

            email=widget_email,

            first_name="Anonymous",

            last_name="Visitor",

            hashed_password="WIDGET_DUMMY_PASSWORD_NOT_AUTHENTICATABLE",

            is_active=True,

            is_admin=False

        )

        db.add(widget_user)

        await db.flush()

        

    return widget_user





# ============================================================================

# PUBLIC ENDPOINTS

# ============================================================================



@router.get("/chats/script")

async def serve_widget_script(request: Request):

    """

    Dynamically serve the float chat widget script (chat.js).

    Auto-injects the current server's base URL to ensure zero-config installation.

    """

    try:

        current_dir = os.path.dirname(os.path.abspath(__file__))

        script_path = os.path.join(current_dir, "chat.js")

        

        if not os.path.exists(script_path):

            raise HTTPException(status_code=404, detail="Widget script not found")

            

        with open(script_path, "r", encoding="utf-8") as f:

            js_code = f.read()

            

        # Dynamically determine the backend host (protocol + host name)

        backend_url = f"{request.url.scheme}://{request.url.netloc}"

        

        # Inject host into script placeholder

        js_code = js_code.replace("{{BACKEND_URL}}", backend_url)

        

        return Response(

            content=js_code,

            media_type="application/javascript",

            headers={"Access-Control-Allow-Origin": "*"}

        )

    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Failed to serve widget script: {e}", exc_info=True)

        raise HTTPException(status_code=500, detail="Internal script loader error")





@router.get("/chats/{agent_id}/details")

async def get_agent_public_details(

    agent_id: str,

    tenant_id: str = Query(..., description="Tenant UUID")

):

    """

    Retrieve agent name and greeting context for the widget header.

    """

    async with AsyncSessionLocal() as db:

        valid = await verify_agent_belongs_to_tenant(db, tenant_id, agent_id)

        if not valid:

            raise HTTPException(

                status_code=status.HTTP_404_NOT_FOUND,

                detail="Agent not found or unauthorized access"

            )

            

        # Get details

        agent_repo = AgentRepository(db, tenant_id=tenant_id)

        agent = await agent_repo.get_by_id(agent_id)

        

        return format_success({

            "name": agent.name,

            "personality": agent.personality or "Friendly",

            "system_prompt": agent.system_prompt

        })





@router.get("/chats/{agent_id}/sessions/{session_id}")

async def get_widget_session_history(

    agent_id: str,

    session_id: str,

    tenant_id: str = Query(..., description="Tenant UUID")

):

    """

    Load previous conversation turn histories for the visitor.

    """

    async with AsyncSessionLocal() as db:

        valid = await verify_agent_belongs_to_tenant(db, tenant_id, agent_id)

        if not valid:

            raise HTTPException(

                status_code=status.HTTP_404_NOT_FOUND,

                detail="Agent not found or unauthorized access"

            )

            

        chat_service = ChatService(db=db, tenant_id=tenant_id)

        result = await chat_service.get_session_with_messages(session_id)

        

        if not result:

            raise HTTPException(status_code=404, detail="Session not found")

            

        session = result["session"]

        

        # Verify ownership

        if str(session.agent_id) != str(agent_id):

            raise HTTPException(status_code=403, detail="Unauthorized session access")

            

        # Formatted details

        formatted_messages = []

        for msg in result["messages"]:

            formatted_messages.append({

                "role": msg.role,

                "content": msg.content,

                "timestamp": msg.created_at.isoformat() if msg.created_at else None,

                "metadata": msg.message_metadata

            })

            

        return format_success({

            "session_id": str(session.id),

            "title": session.title,

            "messages": formatted_messages

        })





@router.post("/chats/{agent_id}/message")

async def send_widget_message(

    agent_id: str,

    body: EmbedMessageRequest,

    background_tasks: BackgroundTasks

):

    """

    Process message turn sent from the embedded widget.

    Runs completely inside RAG pipeline with proper tenant RLS active.

    """

    tenant_id = body.tenant_id

    message_text = body.message.strip()

    

    async with AsyncSessionLocal() as db:

        try:

            # 1. Enforce security (Verifies tenant/agent mapping & sets RLS)

            valid = await verify_agent_belongs_to_tenant(db, tenant_id, agent_id)

            if not valid:

                raise HTTPException(

                    status_code=status.HTTP_404_NOT_FOUND,

                    detail="Agent not found or unauthorized access"

                )

                

            # 2. Get the tenant-designated anonymous visitor user

            widget_user = await get_or_create_widget_user(db, tenant_id)

            

            # 3. Create or load the session under this widget user

            chat_service = ChatService(db=db, tenant_id=tenant_id)

            session_id = body.session_id

            

            if session_id:

                session = await chat_service.chat_repo.get_session_by_id(session_id)

                if not session or str(session.agent_id) != str(agent_id):

                    session = await chat_service.create_session(

                        agent_id=agent_id,

                        user_id=str(widget_user.id),

                        title="Website Chat"

                    )

                    session_id = str(session.id)

            else:

                session = await chat_service.create_session(

                    agent_id=agent_id,

                    user_id=str(widget_user.id),

                    title="Website Chat"

                )

                session_id = str(session.id)

                

            # 4. Generate RAG-grounded response

            result = await chat_service.send_message(

                agent_id=agent_id,

                user_id=str(widget_user.id),

                message=message_text,

                session_id=session_id,

                top_k=body.top_k or 10,

                max_depth=body.max_depth or 2,

            )

            

            # 5. Extract knowledge flywheel (sync turn back to graph)

            if result.get("answer") and result.get("sources"):

                top_chunk_id = result["sources"][0]["chunk_id"]

                kb_id = result.get("context", {}).get("kb_id")

                

                if top_chunk_id and kb_id:

                    background_tasks.add_task(

                        ChatKnowledgeService.run_sync_background,

                        tenant_id=tenant_id,

                        session_id=result["session_id"],

                        kb_id=kb_id,

                        chunk_id=top_chunk_id,

                        user_message=message_text,

                        assistant_message=result["answer"]

                    )

                    

            return format_success(result)

            

        except HTTPException:

            raise

        except Exception as e:

            logger.error(f"Embed message failed: {e}", exc_info=True)

            raise HTTPException(

                status_code=500,

                detail=f"Failed to process chatbot interaction: {str(e)}"

            )



# ============================================================================
# PUBLIC ENDPOINTS
# ============================================================================

@router.get("/chats/script")
async def serve_widget_script(request: Request):
    """
    Dynamically serve the float chat widget script (chat.js).
    Auto-injects the current server's base URL to ensure zero-config installation.
    """
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(current_dir, "chat.js")
        
        if not os.path.exists(script_path):
            raise HTTPException(status_code=404, detail="Widget script not found")
            
        with open(script_path, "r", encoding="utf-8") as f:
            js_code = f.read()
            
        # Dynamically determine the backend host (protocol + host name)
        backend_url = f"{request.url.scheme}://{request.url.netloc}"
        
        # Inject host into script placeholder
        js_code = js_code.replace("{{BACKEND_URL}}", backend_url)
        
        return Response(
            content=js_code,
            media_type="application/javascript",
            headers={"Access-Control-Allow-Origin": "*"}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve widget script: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal script loader error")


@router.get("/chats/{agent_id}/details")
async def get_agent_public_details(
    agent_id: str,
    tenant_id: str = Query(..., description="Tenant UUID")
):
    """
    Retrieve agent name and greeting context for the widget header.
    """
    async with AsyncSessionLocal() as db:
        valid = await verify_agent_belongs_to_tenant(db, tenant_id, agent_id)
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found or unauthorized access"
            )
            
        # Get details
        agent_repo = AgentRepository(db, tenant_id=tenant_id)
        agent = await agent_repo.get_by_id(agent_id)
        
        return format_success({
            "name": agent.name,
            "personality": agent.personality or "Friendly",
            "system_prompt": agent.system_prompt
        })


@router.get("/chats/{agent_id}/sessions/{session_id}")
async def get_widget_session_history(
    agent_id: str,
    session_id: str,
    tenant_id: str = Query(..., description="Tenant UUID")
):
    """
    Load previous conversation turn histories for the visitor.
    """
    async with AsyncSessionLocal() as db:
        valid = await verify_agent_belongs_to_tenant(db, tenant_id, agent_id)
        if not valid:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found or unauthorized access"
            )
            
        chat_service = ChatService(db=db, tenant_id=tenant_id)
        result = await chat_service.get_session_with_messages(session_id)
        
        if not result:
            raise HTTPException(status_code=404, detail="Session not found")
            
        session = result["session"]
        
        # Verify ownership
        if str(session.agent_id) != str(agent_id):
            raise HTTPException(status_code=403, detail="Unauthorized session access")
            
        # Formatted details
        formatted_messages = []
        for msg in result["messages"]:
            formatted_messages.append({
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat() if msg.created_at else None,
                "metadata": msg.message_metadata
            })
            
        return format_success({
            "session_id": str(session.id),
            "title": session.title,
            "messages": formatted_messages
        })


@router.post("/chats/{agent_id}/message")
async def send_widget_message(
    agent_id: str,
    body: EmbedMessageRequest,
    background_tasks: BackgroundTasks
):
    """
    Process message turn sent from the embedded widget.
    Runs completely inside RAG pipeline with proper tenant RLS active.
    """
    tenant_id = body.tenant_id
    message_text = body.message.strip()
    
    async with AsyncSessionLocal() as db:
        try:
            # 1. Enforce security (Verifies tenant/agent mapping & sets RLS)
            valid = await verify_agent_belongs_to_tenant(db, tenant_id, agent_id)
            if not valid:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Agent not found or unauthorized access"
                )
                
            # 2. Get the tenant-designated anonymous visitor user
            widget_user = await get_or_create_widget_user(db, tenant_id)
            
            # 3. Create or load the session under this widget user
            chat_service = ChatService(db=db, tenant_id=tenant_id)
            session_id = body.session_id
            
            if session_id:
                session = await chat_service.chat_repo.get_session_by_id(session_id)
                if not session or str(session.agent_id) != str(agent_id):
                    session = await chat_service.create_session(
                        agent_id=agent_id,
                        user_id=str(widget_user.id),
                        title="Website Chat"
                    )
                    session_id = str(session.id)
            else:
                session = await chat_service.create_session(
                    agent_id=agent_id,
                    user_id=str(widget_user.id),
                    title="Website Chat"
                )
                session_id = str(session.id)
                
            # 4. Generate RAG-grounded response
            result = await chat_service.send_message(
                agent_id=agent_id,
                user_id=str(widget_user.id),
                message=message_text,
                session_id=session_id,
                top_k=body.top_k or 10,
                max_depth=body.max_depth or 2,
            )
            
            # 5. Extract knowledge flywheel (sync turn back to graph)
            if result.get("answer") and result.get("sources"):
                top_chunk_id = result["sources"][0]["chunk_id"]
                kb_id = result.get("context", {}).get("kb_id")
                
                if top_chunk_id and kb_id:
                    background_tasks.add_task(
                        ChatKnowledgeService.run_sync_background,
                        tenant_id=tenant_id,
                        session_id=result["session_id"],
                        kb_id=kb_id,
                        chunk_id=top_chunk_id,
                        user_message=message_text,
                        assistant_message=result["answer"]
                    )

            from ..rag.escalation import detect_escalation_intent
            result["escalation_detected"] = detect_escalation_intent(
                query=message_text,
                sources=result.get("sources"),
                response_text=result.get("answer")
            )
            return format_success(result)
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Embed message failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process chatbot interaction: {str(e)}"
            )


# ============================================================================
# WEBSOCKET STREAMING ENDPOINT
# ============================================================================

@router.websocket("/chats/{agent_id}/ws")
async def websocket_chat_endpoint(
    websocket: WebSocket,
    agent_id: str
):
    """
    WebSocket endpoint for real-time streaming RAG chatbot interaction.
    Requires tenant_id in query parameters, e.g. /chats/{agent_id}/ws?tenant_id=UUID
    """
    tenant_id = websocket.query_params.get("tenant_id")
    if not tenant_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing tenant_id query parameter")
        return
        
    await websocket.accept()
    logger.info(f" WebSocket connection accepted: agent={agent_id}, tenant={tenant_id}")
    
    try:
        async with get_db_with_tenant(tenant_id) as db:
            valid = await verify_agent_belongs_to_tenant(db, tenant_id, agent_id)
            if not valid:
                await websocket.send_json({"type": "error", "detail": "Agent unauthorized or not found"})
                return

            visitor_id = await resolve_or_issue_visitor_id(websocket, tenant_id)
            widget_user = await get_or_create_widget_user(db, tenant_id, visitor_id)
            
            chat_service = ChatService(db=db, tenant_id=tenant_id)
            kbs, _ = await chat_service.kb_repo.list_by_agent(agent_id, limit=10)
            kb_ids = [str(kb.id) for kb in kbs] if kbs else []

            from ..rag.websocket_core import run_unified_rag_websocket_loop
            from ..rag.adapters import EmbedAdapter
            from ..rag.service import RAGService

            rag_service = RAGService(db=db, tenant_id=tenant_id)

            await run_unified_rag_websocket_loop(
                websocket=websocket,
                db=db,
                agent_id=agent_id,
                tenant_id=tenant_id,
                user_id=str(widget_user.id),
                kb_ids=kb_ids,
                adapter=EmbedAdapter(),
                chat_service=chat_service,
                rag_service=rag_service,
                enable_memory=False,
            )
            
    except Exception as e:
        logger.error(f"WebSocket uncaught exception: {e}", exc_info=True)


# ============================================================================
# PUBLIC AGENT KNOWLEDGE BASE SOURCES ENDPOINT FOR WIDGET
# ============================================================================

from fastapi.responses import StreamingResponse
import urllib.parse
from ..knowledge_bases.models import KnowledgeBase
from ...core.s3 import S3StorageService
from ...core.config import get_settings

CONTENT_TYPE_MAP = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".csv": "text/csv",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".txt": "text/plain",
    ".html": "text/html",
    ".md": "text/markdown",
    ".json": "application/json"
}


@router.get("/agents/{agent_id}/sources")
async def get_agent_embed_sources(
    agent_id: str,
    tenant_id: Optional[str] = Query(None, description="Optional tenant UUID")
):
    """
    Public endpoint for embedded chat widgets to fetch knowledge base sources
    attached to an agent. Requires no JWT authentication.
    """
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent_id UUID format")

    async with AsyncSessionLocal() as db:
        if tenant_id:
            valid = await verify_agent_belongs_to_tenant(db, tenant_id, agent_id)
            if not valid:
                raise HTTPException(status_code=404, detail="Agent not found or unauthorized access")

        query = select(KnowledgeBase).where(
            KnowledgeBase.agent_id == agent_uuid,
            KnowledgeBase.is_active == True
        )
        result = await db.execute(query)
        kbs = result.scalars().all()

        sources = []
        for kb in kbs:
            kb_id_str = str(kb.id)
            preview_url = f"/api/v1/embed/files/{kb_id_str}/preview"
            sources.append({
                "id": kb_id_str,
                "kb_id": kb_id_str,
                "name": kb.name,
                "source": kb.source or kb.name,
                "s3_path": kb.s3_path,
                "url": preview_url
            })

        return format_success(sources)


# ============================================================================
# PUBLIC FILE PREVIEW ENDPOINT FOR EMBEDDABLE WIDGET
# ============================================================================

@router.get("/files/{kb_id}/preview")
async def preview_embed_file(kb_id: str):
    """
    Public endpoint to stream file preview for embedded chat widget users.
    Bypasses JWT authentication and streams binary file content directly from S3.
    """
    try:
        file_uuid = uuid.UUID(kb_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid kb_id UUID format")

    async with AsyncSessionLocal() as db:
        query = select(KnowledgeBase).where(
            KnowledgeBase.id == file_uuid,
            KnowledgeBase.is_active == True
        )
        result = await db.execute(query)
        kb = result.scalar_one_or_none()

        if not kb:
            raise HTTPException(status_code=404, detail="Knowledge base file not found")

        filename = kb.name
        file_ext = os.path.splitext(filename.lower())[1]
        content_type = CONTENT_TYPE_MAP.get(file_ext, "application/octet-stream")

        s3_service = S3StorageService()
        
        # Resolve S3 Key
        s3_key = None
        if kb.s3_path:
            s3_key = s3_service._parse_s3_key_from_url(kb.s3_path)
            if not s3_key and kb.s3_path.startswith("s3://"):
                parts = kb.s3_path.split("/", 3)
                if len(parts) >= 4:
                    s3_key = parts[3]
        
        if not s3_key:
            settings_cfg = get_settings()
            bucket_parts = (settings_cfg.aws_s3_bucket or "").split('/', 1)
            base_prefix = bucket_parts[1] + '/' if len(bucket_parts) > 1 else ''
            s3_key = f"{base_prefix}uploads/{kb.tenant_id}/{filename}"

        try:
            stream_body = s3_service.get_file_stream(s3_key)
        except Exception as s3_err:
            logger.error(f"S3 fetch failed for key {s3_key}: {s3_err}", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to fetch file from S3 storage")

        encoded_filename = urllib.parse.quote(filename)
        headers = {
            "Content-Disposition": f'inline; filename="{filename}"; filename*=UTF-8\'\'{encoded_filename}'
        }

        return StreamingResponse(
            stream_body,
            media_type=content_type,
            headers=headers
        )


# ============================================================================
# WIDGET CUSTOMIZATION ENDPOINTS
# ============================================================================


from fastapi import UploadFile, File
from .schemas import (
    WidgetCustomizationUpdate, WidgetCustomizationResponse,
    LogoUploadResponse, CustomizationSaveResponse,
    WidgetEmbedConfigCreate,
)
from .service import WidgetCustomizationService, WidgetEmbedConfigService
from .repository import OptimisticLockError



from ...core.security import verify_access_token


async def get_tenant_and_user_embed(request: Request) -> tuple[str, str]:
    """Helper to extract tenant_id and user_id from request state or Authorization header"""
    tenant_id = getattr(request.state, "tenant_id", None)
    user_id = getattr(request.state, "user_id", None)

    if tenant_id and user_id:
        return str(tenant_id), str(user_id)

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        payload = await verify_access_token(token)
        if payload:
            return str(payload.tenant_id), str(payload.user_id)

    raise HTTPException(status_code=401, detail="Unauthorized")


# ============================================================================
# NEW CRUD: Full Widget Embed Configuration Endpoints
# ============================================================================

@router.get("/configs", status_code=status.HTTP_200_OK)
async def list_embed_configs(request: Request):
    """
    List all widget embed configurations for the authenticated tenant.
    Requires JWT authentication.
    Returns newest-first list of all saved configs.
    """
    try:
        tenant_id, user_id = await get_tenant_and_user_embed(request)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with AsyncSessionLocal() as db:
        service = WidgetEmbedConfigService(db, tenant_id)
        result = await service.list_configs()
        logger.info(
            "Embed configs listed",
            extra={"tenant_id": tenant_id, "user_id": user_id, "total": result.get("total", 0)},
        )
        return format_success(result)


@router.get("/configs/{agent_id}", status_code=status.HTTP_200_OK)
async def get_embed_config(
    agent_id: str,
    request: Request,
    tenant_id: Optional[str] = Query(None, description="Tenant UUID — required for public widget access (no JWT)"),
):
    """
    Get widget embed configuration for a specific agent.

    Dual access mode:
    - Authenticated (JWT): returns full config including metadata (id, version, user_id).
    - Public (tenant_id query param, no JWT): returns sanitized config for chat.js widget init.

    If no configuration is saved, returns safe defaults.
    """
    # Try JWT first; fall back to query-param tenant_id for public widget use
    resolved_tenant_id = tenant_id
    is_public_access = False

    if not resolved_tenant_id:
        try:
            resolved_tenant_id, _ = await get_tenant_and_user_embed(request)
        except HTTPException:
            raise HTTPException(
                status_code=400,
                detail="Either a valid JWT or 'tenant_id' query parameter is required."
            )
    else:
        is_public_access = True

    # Validate agent_id format
    try:
        uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent_id UUID format")

    async with AsyncSessionLocal() as db:
        service = WidgetEmbedConfigService(db, str(resolved_tenant_id))
        config = await service.get_config(agent_id)

    if is_public_access:
        # Return sanitized public response — excludes internal metadata
        PUBLIC_FIELDS = {
            "agent_id", "theme_color", "theme_text_color", "btn_bg_color", "btn_border_color",
            "header_logo", "header_align", "header_name", "header_subtext",
            "agent_label", "bot_avatar", "chat_type", "position", "placeholder_text",
            "button_icon", "button_align", "show_button_text", "button_text",
            "initial_message", "display_sources", "allow_downloads", "display_copy",
            "display_feedback", "link_safety", "lead_collection", "lead_fields",
            "lead_timing", "escalation_enabled", "escalation_link",
        }
        sanitized = {k: v for k, v in config.items() if k in PUBLIC_FIELDS}
        return format_success(sanitized)

    return format_success(config)


@router.post("/configs", status_code=status.HTTP_200_OK)
async def save_embed_config(
    request: Request,
    body: WidgetEmbedConfigCreate,
):
    """
    Create or update widget embed configuration for an agent (UPSERT).

    - First save creates the config (version=1).
    - Subsequent saves increment the version atomically.
    - Pass 'expected_version' in the body to enable Optimistic Concurrency Control.
      If the DB version doesn't match, HTTP 409 Conflict is returned.
    - Appends an immutable history record on every save.

    Requires JWT authentication.
    """
    try:
        tenant_id, user_id = await get_tenant_and_user_embed(request)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with AsyncSessionLocal() as db:
        service = WidgetEmbedConfigService(db, tenant_id)
        try:
            result = await service.save_config(user_id=user_id, data=body)
        except OptimisticLockError as e:
            logger.warning(
                "Embed config OCC conflict",
                extra={
                    "tenant_id": tenant_id,
                    "agent_id": body.agent_id,
                    "expected_version": body.expected_version,
                    "detail": str(e),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e),
            )
        except Exception as e:
            logger.error(
                "Embed config save failed",
                extra={"tenant_id": tenant_id, "agent_id": body.agent_id, "error": str(e)},
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail="Failed to save embed configuration.")

    return format_success(result)


@router.delete("/configs/{agent_id}", status_code=status.HTTP_200_OK)
async def delete_embed_config(
    agent_id: str,
    request: Request,
    change_reason: Optional[str] = Query(None, description="Optional reason for deletion (audit log)"),
):
    """
    Delete widget embed configuration for a specific agent.

    - Appends a 'delete' history record before deletion (audit preserved).
    - Returns HTTP 200 with success=False if no config exists (idempotent).
    - Requires JWT authentication.
    """
    try:
        tenant_id, user_id = await get_tenant_and_user_embed(request)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Validate agent_id format
    try:
        uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent_id UUID format")

    async with AsyncSessionLocal() as db:
        service = WidgetEmbedConfigService(db, tenant_id)
        result = await service.delete_config(
            agent_id=agent_id,
            user_id=user_id,
            change_reason=change_reason,
        )

    return format_success(result)


# ============================================================================
# LEGACY: Logo Upload & Customization (kept for backward compatibility)
# ============================================================================

@router.post("/logo", response_model=LogoUploadResponse, status_code=status.HTTP_200_OK)
async def upload_widget_logo(
    request: Request,
    logo: UploadFile = File(..., description="Logo image file (PNG, JPG, JPEG, SVG, WEBP up to 2MB)")
):
    """
    Upload a logo image for widget customization.
    Validates file format and max size (2MB). Returns public logo URL.
    """
    try:
        tenant_id, user_id = await get_tenant_and_user_embed(request)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")

    file_bytes = await logo.read()
    async with AsyncSessionLocal() as db:
        service = WidgetCustomizationService(db, tenant_id)
        result = await service.upload_logo(
            filename=logo.filename or "logo.png",
            content_type=logo.content_type or "image/png",
            file_bytes=file_bytes
        )

        if not result.get("success"):
            status_code = result.get("status_code", 400)
            error_msg = result.get("error", "Upload failed")
            raise HTTPException(status_code=status_code, detail=error_msg)

        return result


@router.put("/customization", response_model=CustomizationSaveResponse, status_code=status.HTTP_200_OK)
async def update_widget_customization(
    request: Request,
    body: WidgetCustomizationUpdate
):
    """
    Create or update widget customization settings for the authenticated tenant.
    """
    try:
        tenant_id, user_id = await get_tenant_and_user_embed(request)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")

    async with AsyncSessionLocal() as db:
        service = WidgetCustomizationService(db, tenant_id)
        result = await service.save_customization(user_id, body)
        return result


@router.get("/customization", response_model=WidgetCustomizationResponse, status_code=status.HTTP_200_OK)
async def get_widget_customization(
    request: Request,
    tenant_id: Optional[str] = Query(None, description="Optional tenant UUID for public widget callers")
):
    """
    Get widget customization settings for the authenticated tenant or query parameter tenant_id.
    Returns default settings if no customization record exists.
    """
    resolved_tenant_id = tenant_id
    if not resolved_tenant_id:
        try:
            resolved_tenant_id, _ = await get_tenant_and_user_embed(request)
        except Exception:
            resolved_tenant_id = None

    if not resolved_tenant_id:
        return {
            "logo_url": None,
            "show_in_header": True,
            "show_in_chat": True,
            "show_in_embed": True
        }

    async with AsyncSessionLocal() as db:
        service = WidgetCustomizationService(db, str(resolved_tenant_id))
        return await service.get_customization()


@router.get("/logo/render/{tenant_id}/{filename}")
async def render_widget_logo(tenant_id: str, filename: str):
    """
    Public proxy endpoint to stream logo image for embedded chat widgets.
    Bypasses AWS S3 bucket 403 Forbidden restrictions by fetching via backend IAM credentials.
    """
    s3_service = S3StorageService()
    settings_cfg = get_settings()
    bucket_parts = (settings_cfg.aws_s3_bucket or "").split('/', 1)
    base_prefix = bucket_parts[1] + '/' if len(bucket_parts) > 1 else ''
    s3_key = f"{base_prefix}logos/{tenant_id}/{filename}"

    try:
        stream_body = s3_service.get_file_stream(s3_key)
    except Exception as s3_err:
        logger.error(f"S3 fetch failed for logo key {s3_key}: {s3_err}", exc_info=True)
        raise HTTPException(status_code=404, detail="Logo image not found in storage")

    file_ext = os.path.splitext(filename.lower())[1]
    content_type = CONTENT_TYPE_MAP.get(file_ext, "image/png")

    return StreamingResponse(
        stream_body,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"}
    )



