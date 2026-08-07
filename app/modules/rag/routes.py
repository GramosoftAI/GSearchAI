"""

RAG API routes - REST endpoints for graph-based question answering

Phase 2 Step 4: Product-facing RAG query interface

"""



import logging

from typing import Union



from fastapi import APIRouter, HTTPException, Request, status, Depends



from .schemas import RAGQueryRequest, RAGQueryResponse, RAGErrorResponse, RAGFeedbackRequest

from .loader import get_rag_service

from ...core.database import get_db, AsyncSessionLocal

from sqlalchemy.ext.asyncio import AsyncSession





logger = logging.getLogger(__name__)



router = APIRouter(prefix="/api/v1/rag", tags=["RAG"])



# Include WebSocket routes

from .websocket_routes import router as ws_router

router.include_router(ws_router)





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

    "/{agent_id}/query",

    response_model=Union[RAGQueryResponse, RAGErrorResponse],

    status_code=status.HTTP_200_OK,

    summary="Execute RAG Query (Elite Simplified)",

    description="Execute graph-based question answering on an agent's primary knowledge base.",

)

async def rag_query(

    request: Request,

    agent_id: str,

    query_request: RAGQueryRequest,

    rag_service: "RAGService" = Depends(get_rag_service),

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

    # rag_service is now injected via Depends



    # EXECUTE RAG PIPELINE

    logger.debug("Executing RAG pipeline...")

    try:

        # AUTO-RESOLVE KBs: Fetch all knowledge bases owned by this agent

        from ..knowledge_bases.repository import KnowledgeBaseRepository

        kb_repo = KnowledgeBaseRepository(db, tenant_id)

        kbs, _ = await kb_repo.list_by_agent(agent_id, limit=10)

        

        if not kbs:

            raise HTTPException(status_code=404, detail="No knowledge bases found for this agent.")

 

        kb_ids = [str(kb.id) for kb in kbs]

        

        response = await rag_service.generate_answer(

            query=query_request.query,

            agent_id=agent_id,

            kb_id=kb_ids,

            user_id=user,

            top_k=query_request.top_k or 15,

            max_depth=query_request.max_depth or 2,

            reasoning_enabled=(str(query_request.Reasoning).strip().lower() in ("true", "1", "yes")),

            memory_enabled=(str(query_request.Memory).strip().lower() in ("true", "1", "yes")),

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

        raise HTTPException(

            status_code=500, detail=f"RAG generation failed: {str(e)}"

        )





@router.post(

    "/feedback",

    status_code=status.HTTP_200_OK,

    summary="Submit RAG Feedback (Phase 4B)",

    description="Update graph node weights based on user feedback to enable self-improving retrieval.",

)

async def rag_feedback(

    request: Request,

    feedback: RAGFeedbackRequest,

    db: AsyncSession = Depends(get_db),

):

    """

    Process user feedback to update chunk weights in the graph.

    """

    logger.info(f" RAG Feedback Endpoint: rating={feedback.rating}, chunks={len(feedback.chunk_ids)}")



    # EXTRACT TENANT + USER FROM JWT

    try:

        tenant_id, user = get_tenant_and_user(request)

    except HTTPException:

        raise

    except Exception as e:

        raise HTTPException(status_code=401, detail="Unauthorized: Invalid JWT")



    rag_service = RAGService(db=db, tenant_id=tenant_id)

    try:

        await rag_service.process_feedback(feedback.chunk_ids, feedback.rating)

        return {"status": "success", "message": "Feedback processed successfully, graph weights updated."}

    except Exception as e:

        logger.error(f" Feedback processing failed: {e}")

        raise HTTPException(status_code=500, detail="Failed to process feedback")





@router.get("/health")

async def rag_health() -> dict:

    """

    Health check for RAG service with metrics.



    Returns comprehensive health metrics:

    - status: Service status (ok)

    - module: Module name (rag)

    - avg_latency: Average query latency in milliseconds

    - cache_hit_rate: Percentage of queries served from cache

    - total_queries: Total number of queries processed

    - cache_size: Current number of cached entries

    - timeout_rate: Percentage of queries that hit timeout

    - partial_result_rate: Percentage using fallback (seed-only)



    Returns:

        Dict with service status and metrics

    """

    logger.debug("RAG health check")



    # Initialize service to get metrics (no DB transaction needed)

    async with AsyncSessionLocal() as db:

        # Use any tenant ID (metrics are system-wide)

        rag_service = RAGService(db=db, tenant_id="system")

        health_metrics = rag_service.get_health_metrics()



    return {
        "status": "ok",
        "module": "rag",
        **health_metrics,
    }


@router.get(
    "/telemetry/traces",
    status_code=status.HTTP_200_OK,
    summary="Get Explainability Traces",
    description="Returns the execution traces of recent RAG queries to power the Explainability Dashboard.",
)
async def get_telemetry_traces(
    request: Request,
    limit: int = 50,
):
    """
    Fetch telemetry traces from the log file.
    """
    try:
        tenant_id, user = get_tenant_and_user(request)
    except HTTPException:
        pass # Allow for local dev without auth for now or handle appropriately
        
    import os
    import json
    
    log_file = "v:/graphmind/logs/telemetry.jsonl"
    traces = []
    
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()
                for line in reversed(lines):
                    if not line.strip():
                        continue
                    try:
                        traces.append(json.loads(line))
                        if len(traces) >= limit:
                            break
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"Failed to read telemetry log: {e}")
            
    return {"traces": traces}


@router.get(
    "/telemetry/metrics",
    status_code=status.HTTP_200_OK,
    summary="Get System Metrics",
)
async def get_telemetry_metrics(
    request: Request,
):
    from app.modules.rag.engines.telemetry_optimizer import TelemetryOptimizer
    TelemetryOptimizer.load_stats()
    
    return {
        "engine_stats": TelemetryOptimizer._engine_stats
    }

