from fastapi import Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.core.database import get_db

async def get_tenant_from_request(request: Request) -> Optional[str]:
    # Extract tenant from request headers, state, or mock it depending on auth logic
    # In this app, it usually expects request.state.tenant_id or extracts from token
    try:
        return request.state.tenant_id
    except AttributeError:
        # Fallback or default
        return "default_tenant"

async def get_rag_service(db: AsyncSession = Depends(get_db), request: Request = None):
    """
    Lazy loads RAGService so that pipeline.py (heavy) is not imported 
    when main.py scans routes at startup.
    This is a request-scoped factory, NOT a singleton, to prevent tenant leakage.
    """
    from .service import RAGService
    tenant_id = None
    if request:
        tenant_id = await get_tenant_from_request(request)
    return RAGService(db=db, tenant_id=tenant_id)

async def get_chat_pipeline(db: AsyncSession = Depends(get_db), request: Request = None):
    """
    Lazy loads ChatPipeline to prevent full startup crashes on RAG syntax errors.
    Created per-request.
    """
    from .stream.chat_pipeline import ChatPipeline
    tenant_id = None
    if request:
        tenant_id = await get_tenant_from_request(request)
    return ChatPipeline(db=db, tenant_id=tenant_id)
