"""
RAG API routes - REST endpoints for graph-based question answering
Phase 2 Step 4: Product-facing RAG query interface
"""

import logging
from typing import Union

from fastapi import APIRouter, HTTPException, Request, status

from .schemas import RAGQueryRequest, RAGQueryResponse, RAGErrorResponse
from .service import RAGService


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rag", tags=["RAG"])


# ============================================================================
# REQUEST CONTEXT HELPERS
# ============================================================================


def get_tenant_and_user(request: Request) -> tuple[str, str]:
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


@router.post(
    "/query",
    response_model=Union[RAGQueryResponse, RAGErrorResponse],
    status_code=status.HTTP_200_OK,
    summary="Execute RAG Query",
    description="Execute graph-based question answering on knowledge base",
)
async def rag_query(
    request: Request,
    query_request: RAGQueryRequest,
) -> Union[RAGQueryResponse, RAGErrorResponse]:
    """
    Execute graph-based RAG query on knowledge base.

    FLOW:
    1. Extract tenant_id from JWT (via middleware)
    2. Validate KB ownership (agent owns KB)
    3. Execute RAG pipeline:
       - Retrieve seed chunks (semantic similarity)
       - Expand via graph (SIMILAR, MENTIONS, NEXT)
       - Score and rank (hybrid: 0.6 embedding + 0.4 graph)
       - Select context (token budget)
    4. Generate answer
    5. Return answer + sources + metadata

    SECURITY:
    - tenant_id extracted from JWT, never from request body
    - Agent must own KB (validated via repository)
    - All Neo4j queries validated against tenant_id (RLS)
    - Multi-tenant isolation enforced

    PERFORMANCE:
    - Max 15 chunks in context (token budget ~3000)
    - Max depth 2 graph expansion
    - Deterministic scoring (same query  same results)
    - Async throughout

    Args:
        request: FastAPI request (contains JWT middleware data)
        query_request: RAG query (query, agent_id, kb_id)

    Returns:
        RAGQueryResponse: Answer with sources and metadata
        RAGErrorResponse: Error with fallback answer

    Examples:
        POST /rag/query
        {
            "query": "What is the main topic?",
            "agent_id": "550e8400-...",
            "kb_id": "550e8400-...",
            "top_k": 15,
            "max_depth": 2
        }

        200 OK:
        {
            "answer": "Based on the knowledge base...",
            "sources": [
                {"chunk_id": "550e8400-...", "score": 0.95, "position": 0}
            ],
            "context": {...},
            "stats": {...}
        }

        401 Unauthorized: Missing/invalid JWT
        403 Forbidden: Agent doesn't own KB
        404 Not Found: KB not found
    """
    logger.info(f" RAG Query Endpoint: {query_request.query[:50]}...")

    # EXTRACT TENANT + USER FROM JWT (via middleware)
    try:
        tenant_id, user = get_tenant_and_user(request)
        logger.debug(f" Tenant extracted: {tenant_id}, User: {user}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f" Failed to extract tenant: {e}")
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid JWT")

    # VALIDATE QUERY
    if not query_request.query or len(query_request.query.strip()) < 5:
        logger.warning(" Query too short")
        raise HTTPException(
            status_code=400, detail="Query must be at least 5 characters"
        )

    # INITIALIZE RAG SERVICE
    logger.debug("Initializing RAG service...")
    rag_service = RAGService(tenant_id=tenant_id)

    # EXECUTE RAG PIPELINE
    logger.debug("Executing RAG pipeline...")
    try:
        response = await rag_service.generate_answer(
            query=query_request.query,
            agent_id=query_request.agent_id,
            kb_id=query_request.kb_id,
            top_k=query_request.top_k or 15,
            max_depth=query_request.max_depth or 2,
        )

        # Check if response contains error
        if "error" in response:
            logger.warning(f" RAG service returned error: {response['error']}")
            return RAGErrorResponse(
                error=response["error"],
                answer=response.get("answer"),
                sources=response.get("sources", []),
            )

        # Success response
        logger.info(
            f" RAG query complete: {len(response['sources'])} sources, "
            f"{response['stats']['total_tokens']} tokens"
        )
        return RAGQueryResponse(**response)

    except Exception as e:
        logger.error(f" RAG pipeline failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"RAG generation failed: {str(e)}")


@router.get("/health")
async def rag_health() -> dict:
    """
    Health check for RAG service.

    Returns:
        {"status": "ok"}
    """
    logger.debug("RAG health check")
    return {"status": "ok", "module": "rag"}
