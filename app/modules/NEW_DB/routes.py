"""FastAPI Endpoints for NEW_DB Module

Provides REST endpoints for database registration, fast schema sync (Markdown + pgvector),
and grounded natural-language database querying.
"""

from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List, Dict, Any
import uuid
import logging

from app.core.database import get_db
from .service import NewDBService
from .schemas import (
    DBConnectionConfig,
    ConnectionTestResult,
    RegisterDatabaseRequest,
    RegisterDatabaseResponse,
    SyncResult,
    QueryRequest,
    QueryResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/new-db",
    tags=["NEW_DB (Grounded Docs Architecture)"],
)


def get_new_db_service(request: Request, db: AsyncSession = Depends(get_db)) -> NewDBService:
    """Dependency helper injecting tenant-scoped NewDBService."""
    tenant_id = str(getattr(request.state, "tenant_id", "00000000-0000-0000-0000-000000000000"))
    return NewDBService(db=db, tenant_id=tenant_id)


@router.post(
    "/test-connection",
    response_model=ConnectionTestResult,
    summary="Test Ad-Hoc Database Connection",
    description="Tests target database connectivity, latency, and server version before persisting.",
)
async def test_connection(
    config: DBConnectionConfig,
    service: NewDBService = Depends(get_new_db_service),
):
    return await service.test_adhoc_connection(config)


@router.post(
    "",
    response_model=RegisterDatabaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register Database Knowledgebase",
    description="Securely registers a new database source with encrypted credentials.",
)
async def register_database(
    payload: RegisterDatabaseRequest,
    request: Request,
    service: NewDBService = Depends(get_new_db_service),
):
    user_id_str = getattr(request.state, "user_id", None)
    user_id = uuid.UUID(str(user_id_str)) if user_id_str else uuid.uuid4()
    return await service.register_database(
        user_id=user_id,
        name=payload.name,
        config=payload.connection,
        description=payload.description,
    )


@router.post(
    "/{id}/sync",
    response_model=SyncResult,
    summary="Sync Database (Introspect + Markdown Docs + pgvector)",
    description="Fast 1-click sync: Introspects tables, generates Markdown cheat sheets, and indexes vectors into pgvector. No heavy 7-stage profiling queue!",
)
async def sync_database(
    id: uuid.UUID,
    service: NewDBService = Depends(get_new_db_service),
):
    try:
        return await service.sync_database(kb_id=id)
    except Exception as e:
        logger.error(f"[NEW_DB] Sync failed for KB {id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Sync failed: {e}")


@router.post(
    "/{id}/query",
    response_model=QueryResponse,
    summary="Query Database (Grounded Docs Pipeline)",
    description="Answers natural-language question using pgvector table doc retrieval, entity resolution, AST-validated SQL generation, read-only execution, and synthesis.",
)
async def query_database(
    id: uuid.UUID,
    payload: QueryRequest,
    service: NewDBService = Depends(get_new_db_service),
):
    try:
        return await service.query_database(
            kb_id=id,
            user_query=payload.query,
            top_k=payload.top_k_tables,
            model=payload.model,
            resolved_entities=payload.resolved_entities,
        )
    except ValueError as val_err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err))
    except Exception as e:
        logger.error(f"[NEW_DB] Query failed for KB {id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Query failed: {e}")


@router.get(
    "/{id}/docs",
    summary="Get Table Markdown Cheat Sheets",
    description="Fetches the AI-understandable Markdown cheat sheets generated and indexed for this database.",
)
async def get_table_docs(
    id: uuid.UUID,
    table: Optional[str] = Query(None, description="Optional table name filter"),
    service: NewDBService = Depends(get_new_db_service),
):
    docs = await service.get_table_docs(kb_id=id, table_name=table)
    return {"success": True, "count": len(docs), "docs": docs}


@router.get(
    "/{id}/health",
    summary="Database Health Check",
    description="Verifies connection health to the client database.",
)
async def check_health(
    id: uuid.UUID,
    service: NewDBService = Depends(get_new_db_service),
):
    _, config = await service.get_connection_config(id)
    test_res = await service.test_adhoc_connection(config)
    return {
        "success": test_res.success,
        "latency_ms": test_res.latency_ms,
        "server_version": test_res.server_version,
        "error": test_res.error_message,
    }
