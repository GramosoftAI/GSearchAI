"""Database Knowledgebase FastAPI Endpoints

Provides REST APIs for managing database knowledgebases, testing connections,
running deterministic schema introspection, and retrieving canonical schemas.

CRITICAL SECURITY:
- Multi-tenancy is enforced on EVERY request via TenantContextMiddleware and RLS.
- Database credentials and passwords are NEVER returned in any endpoint response.
- Tenant ID is ALWAYS extracted from request.state.tenant_id, NEVER from query/body parameters.
"""

from fastapi import APIRouter, Depends, Request, status, Query, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Dict, Any
import uuid
import logging
from datetime import datetime

from app.core.database import get_db
from .services.service import DatabaseKnowledgebaseService
from .schemas.api import (
    DatabaseKnowledgebaseCreate,
    DatabaseKnowledgebaseUpdate,
    DatabaseKnowledgebaseResponse,
    DatabaseKnowledgebaseListResponse,
    DatabaseSchemaResponse,
    SchemaSnapshotResponse,
    SchemaRetrievalApiRequest,
    QueryPlanApiRequest,
    GenerateSQLApiRequest,
    DatabaseQueryApiRequest,
    StandardApiResponse,
    GlossaryConfirmApiRequest,
)
from .retrieval.retriever import SchemaRetrievalResult
from .planning.models import QueryPlanIR
from .sql_generator.repair import ValidatedCandidateSQL
from .execution import CanonicalQueryResult, ExecutionConfig
from .answering import GroundedDatabaseAnswer
from .schemas.connection import DatabaseConnectionConfig, ConnectionTestResult
from .observability import DatabaseKnowledgebaseMetrics
from .schemas.audit_api import AuditLogFilterParams, AuditLogListResponse
from .schemas.health import DatabaseKnowledgebaseHealth
from .exceptions.errors import TenantMismatchError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/database-knowledgebases",
    tags=["Database Knowledgebases"],
)


def get_service(
    request: Request, db: AsyncSession = Depends(get_db)
) -> DatabaseKnowledgebaseService:
    """Dependency helper to instantiate tenant-scoped service."""
    tenant_id = str(request.state.tenant_id)
    return DatabaseKnowledgebaseService(db=db, tenant_id=tenant_id)


@router.post(
    "",
    response_model=DatabaseKnowledgebaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Database Knowledgebase",
    description="Registers a new live database data source with encrypted credentials.",
)
async def create_database_knowledgebase(
    payload: DatabaseKnowledgebaseCreate,
    request: Request,
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    user_id = uuid.UUID(str(request.state.user_id))
    return await service.create_database_knowledgebase(user_id=user_id, data=payload)


@router.get(
    "",
    response_model=DatabaseKnowledgebaseListResponse,
    summary="List Database Knowledgebases",
    description="Lists all database knowledgebases belonging to the authenticated tenant.",
)
async def list_database_knowledgebases(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    agent_id: Optional[uuid.UUID] = Query(None),
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    items = await service.list_database_knowledgebases(skip=skip, limit=limit, agent_id=agent_id)
    return DatabaseKnowledgebaseListResponse(
        success=True,
        data=items,
        meta={"skip": skip, "limit": limit, "count": len(items)},
    )


@router.get(
    "/{id}",
    response_model=DatabaseKnowledgebaseResponse,
    summary="Get Database Knowledgebase",
    description="Fetches a specific database knowledgebase configuration (credentials masked).",
)
async def get_database_knowledgebase(
    id: uuid.UUID,
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    return await service.get_database_knowledgebase(kb_id=id)


@router.put(
    "/{id}",
    response_model=DatabaseKnowledgebaseResponse,
    summary="Update Database Knowledgebase",
    description="Updates metadata or connection credentials for a database knowledgebase.",
)
async def update_database_knowledgebase(
    id: uuid.UUID,
    payload: DatabaseKnowledgebaseUpdate,
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    return await service.update_database_knowledgebase(kb_id=id, data=payload)


@router.delete(
    "/{id}",
    response_model=StandardApiResponse,
    summary="Delete Database Knowledgebase",
    description="Soft-deletes a database knowledgebase from the catalog.",
)
async def delete_database_knowledgebase(
    id: uuid.UUID,
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    await service.delete_database_knowledgebase(kb_id=id)
    return StandardApiResponse(
        success=True,
        data={"id": str(id), "deleted": True},
    )


# ============= CONNECTION TESTING ENDPOINTS =============

@router.post(
    "/test-connection-adhoc",
    response_model=ConnectionTestResult,
    summary="Test Ad-Hoc Connection",
    description="Safely tests connection parameters before persisting.",
)
async def test_connection_adhoc(
    config: DatabaseConnectionConfig,
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    return await service.test_connection_adhoc(config=config)


@router.post(
    "/{id}/test-connection",
    response_model=ConnectionTestResult,
    summary="Test Stored Database Connection",
    description="Tests connection against a stored database knowledgebase using decrypted credentials.",
)
async def test_connection(
    id: uuid.UUID,
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    return await service.test_connection(kb_id=id)


# ============= SCHEMA INTROSPECTION & RETRIEVAL =============

@router.post(
    "/{id}/introspect",
    response_model=DatabaseSchemaResponse,
    summary="Introspect Database Schema",
    description="Performs deterministic schema introspection on target DB and persists canonical snapshot.",
)
async def introspect_database_schema(
    id: uuid.UUID,
    schemas: Optional[List[str]] = Query(None, description="Optional schema namespaces to filter (e.g. ['public'])"),
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    return await service.introspect_and_snapshot_schema(kb_id=id, schemas=schemas)


@router.get(
    "/{id}/schema",
    response_model=DatabaseSchemaResponse,
    summary="Get Latest Canonical Schema",
    description="Retrieves the latest introspected canonical schema snapshot.",
)
async def get_latest_schema(
    id: uuid.UUID,
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    return await service.get_latest_schema(kb_id=id)


@router.get(
    "/{id}/snapshots",
    response_model=List[SchemaSnapshotResponse],
    summary="List Schema Snapshots",
    description="Lists historical schema snapshot versions for drift tracking.",
)
async def list_schema_snapshots(
    id: uuid.UUID,
    limit: int = Query(10, ge=1, le=50),
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    return await service.list_schema_snapshots(kb_id=id, limit=limit)


@router.post(
    "/{id}/retrieve-schema",
    response_model=SchemaRetrievalResult,
    summary="Retrieve Sub-Schema for Query",
    description="Executes hybrid semantic schema retrieval (vector + keyword + FK graph) to find the minimal relevant sub-schema.",
)
async def retrieve_schema(
    id: uuid.UUID,
    payload: SchemaRetrievalApiRequest,
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    return await service.retrieve_schema(
        kb_id=id,
        user_query=payload.query,
        conversation_context=payload.conversation_context,
        top_k_tables=payload.top_k_tables,
        top_k_columns_per_table=payload.top_k_columns_per_table,
        include_relationships=payload.include_relationships,
    )


@router.post(
    "/{id}/plan-query",
    response_model=QueryPlanIR,
    summary="Construct Query Plan IR",
    description="Constructs a machine-validated QueryPlanIR from user query and retrieved sub-schema.",
)
async def plan_query(
    id: uuid.UUID,
    payload: QueryPlanApiRequest,
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    return await service.plan_query(
        kb_id=id,
        user_query=payload.query,
        top_k_tables=payload.top_k_tables,
        top_k_columns_per_table=payload.top_k_columns_per_table,
    )


@router.post(
    "/{id}/generate-sql",
    response_model=ValidatedCandidateSQL,
    summary="Generate Validated Candidate SQL",
    description="Generates, security-validates, and repairs candidate SQL for a user query.",
)
async def generate_sql(
    id: uuid.UUID,
    payload: GenerateSQLApiRequest,
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    return await service.generate_candidate_sql(
        kb_id=id,
        user_query=payload.query,
        top_k_tables=payload.top_k_tables,
        top_k_columns_per_table=payload.top_k_columns_per_table,
        use_llm=payload.use_llm,
    )


@router.post(
    "/{id}/query",
    response_model=GroundedDatabaseAnswer,
    summary="Query Database Knowledgebase",
    description="Safely queries target database from natural-language question through full retrieval, planning, AST validation, and read-only execution pipeline.",
)
async def query_database(
    id: uuid.UUID,
    payload: DatabaseQueryApiRequest,
    request: Request,
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    exec_config = None
    if payload.timeout_seconds:
        exec_config = ExecutionConfig(
            statement_timeout_ms=payload.timeout_seconds * 1000,
            connection_timeout_seconds=payload.timeout_seconds,
        )
    request_id = getattr(request.state, "request_id", None) if hasattr(request, "state") else None
    return await service.query_database(
        kb_id=id,
        user_query=payload.query,
        top_k_tables=payload.top_k_tables,
        top_k_columns_per_table=payload.top_k_columns_per_table,
        use_llm=payload.use_llm,
        execution_config=exec_config,
        request_id=request_id,
    )


@router.post(
    "/{id}/query/stream",
    summary="Stream Database Knowledgebase Query (SSE)",
    description="Streams real-time pipeline lifecycle events (Server-Sent Events) during database query processing.",
)
async def stream_query_database(
    id: uuid.UUID,
    payload: DatabaseQueryApiRequest,
    request: Request,
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    from .streaming.streamer import stream_database_query

    # Verify tenant ownership before establishing SSE stream (Tenant Isolation Gate)
    entity = await service.repo.get_by_id(id)
    if not entity:
        raise TenantMismatchError(detail=f"Database knowledgebase '{id}' not found.")

    exec_config = None
    if payload.timeout_seconds:
        exec_config = ExecutionConfig(
            statement_timeout_ms=payload.timeout_seconds * 1000,
            connection_timeout_seconds=payload.timeout_seconds,
        )

    return StreamingResponse(
        stream_database_query(
            service=service,
            kb_id=id,
            user_query=payload.query,
            request=request,
            top_k_tables=payload.top_k_tables,
            top_k_columns_per_table=payload.top_k_columns_per_table,
            use_llm=payload.use_llm,
            execution_config=exec_config,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/{id}/metrics",
    summary="Get Database Knowledgebase Operational Metrics",
    description="Returns tenant-isolated operational metrics, success/failure rates, and latency percentiles.",
)
async def get_database_metrics(
    id: uuid.UUID,
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    # Tenant isolation is strictly enforced via service.tenant_id
    kb = await service.repo.get_by_id(id)
    if not kb:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Database knowledgebase '{id}' not found.")
    metrics = DatabaseKnowledgebaseMetrics.get_instance().get_metrics(tenant_id=service.tenant_id)
    return {"success": True, "data": metrics}


@router.get(
    "/{id}/audit-logs",
    response_model=AuditLogListResponse,
    summary="Get Database Knowledgebase Audit Logs",
    description="Returns tenant-isolated, paginated audit records capturing query execution telemetry without exposing sensitive data.",
)
async def get_audit_logs(
    id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    start_time: Optional[datetime] = Query(default=None),
    end_time: Optional[datetime] = Query(default=None),
    final_status: Optional[str] = Query(default=None),
    min_latency_ms: Optional[float] = Query(default=None, ge=0.0),
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    params = AuditLogFilterParams(
        limit=limit,
        offset=offset,
        start_time=start_time,
        end_time=end_time,
        final_status=final_status,
        min_latency_ms=min_latency_ms,
    )
    return await service.get_audit_logs(id, params)


@router.get(
    "/{id}/health",
    response_model=DatabaseKnowledgebaseHealth,
    summary="Database Knowledgebase Health & Diagnostics Probe",
    description="Checks target database connectivity, read-only transaction privilege, schema freshness, and telemetry status.",
)
async def get_database_health(
    id: uuid.UUID,
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    return await service.check_health(id)


@router.post(
    "/{id}/glossary/confirm",
    summary="Confirm and Publish Concept Glossary Entry",
    description="Elevated operator endpoint (admin/editor required) to confirm, publish, and optionally register semantic roles for a glossary entry.",
)
async def confirm_glossary_entry(
    id: uuid.UUID,
    body: GlossaryConfirmApiRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    service: DatabaseKnowledgebaseService = Depends(get_service),
):
    """
    CRITICAL SECURITY GUARD:
    Confirming and publishing a concept glossary entry elevates it to HUMAN_VERIFIED,
    which impacts schema retrieval and LLM context for all users in the tenant.
    Requires explicit elevated role (admin or editor).
    """
    user_role = (
        getattr(request.state, "role", "")
        or request.headers.get("X-User-Role", "")
    )
    is_admin = getattr(request.state, "is_admin", False)
    if not (is_admin or user_role in ("admin", "editor")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Elevated permission (admin or editor) required to confirm glossary entries",
        )

    kb = await service.get_knowledgebase(id)
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Database knowledgebase '{id}' not found.",
        )

    from .semantic_glossary.feedback_loop import GlossaryFeedbackLoop
    fingerprint = kb.schema_version or f"kb_{id}"

    entry = await GlossaryFeedbackLoop.record_human_verified_mapping(
        session=db,
        tenant_id=service.tenant_id,
        table_name=body.table_name,
        column_name=body.column_name,
        schema_fingerprint=fingerprint,
        synonyms=body.synonyms,
        business_description=body.business_description,
        semantic_role=body.semantic_role,
    )
    await db.commit()

    return {
        "success": True,
        "data": {
            "id": entry.id,
            "tenant_id": entry.tenant_id,
            "table_name": entry.table_name,
            "column_name": entry.column_name,
            "business_description": entry.business_description,
            "synonyms": entry.synonyms,
            "semantic_role": entry.semantic_role,
            "is_published": entry.is_published,
            "confidence_source": entry.confidence_source,
        },
    }


