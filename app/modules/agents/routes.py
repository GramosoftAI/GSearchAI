"""REST routes for Agent CRUD operations"""



from fastapi import APIRouter, Request, HTTPException, status, UploadFile, File

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from typing import Optional, List, Dict, Any

import io

try:

    import pdfplumber

except ImportError:

    pass

import logging

import uuid

import asyncio

import re



from .service import AgentService

from . import schemas

from ...core.database import AsyncSessionLocal

from ...utils.formatters import format_error, format_success

from ..knowledge_bases.service import KnowledgeBaseService

from ..knowledge_bases.schemas import KBCreate, KBURLIngest

from ..knowledge_bases.services.scraper_service import ScraperService

import httpx

try:

    from bs4 import BeautifulSoup

except ImportError:

    pass  # Handled at route level

from ...core.llm.deepinfra_llm import get_llm_client

from ...core.config import get_settings

import re



logger = logging.getLogger(__name__)

settings = get_settings()



router = APIRouter(prefix="/api/v1/agents", tags=["agents"])





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





# ============================================================================

# ENDPOINTS

# ============================================================================





@router.post(

    "",

    response_model=dict,

    status_code=status.HTTP_200_OK,

    summary="Create Agent",

    description="Create a new agent for the current tenant",

)

@router.post(

    "/",

    response_model=dict,

    status_code=status.HTTP_200_OK,

    include_in_schema=False,

)

async def create_agent(

    request: Request,

    agent_request: schemas.AgentCreate,

) -> dict:

    """

    Create a new agent.



    Creates agent in BOTH:

    1. PostgreSQL (metadata storage)

    2. Neo4j (graph node for future KB/Chunk relationships)



    TRANSACTION SAFETY:

    - If either database fails, entire operation is rolled back

    - No orphaned nodes or records



    Args:

        request: FastAPI request (contains tenant_id in state)

        agent_request: AgentCreate schema with name, system_prompt, etc.



    Returns:

        JSON response with created agent



    Raises:

        HTTPException 401: Not authenticated

        HTTPException 400: Invalid request

        HTTPException 500: Database error

    """

    try:

        tenant_id, user_id = get_tenant_and_user(request)



        async with AsyncSessionLocal() as db:

            service = AgentService(db, tenant_id)

            result = await service.create_agent(user_id, agent_request)



            if not result.get("success"):

                error_msg = result.get("error", "Unknown error")

                status_code = result.get("status_code", 400)

                raise HTTPException(status_code=status_code, detail=error_msg)



            return result



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Unexpected error creating agent: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/detailed",

    response_model=dict,

    summary="List Agents Detailed (Audit View)",

    description="List all agents with owner names, tenant names, and linked KB IDs. Supports smart search across names.",

)

async def list_agents_detailed(

    request: Request,

    search: schemas.Optional[str] = None,

    limit: int = 50,

    offset: int = 0,

) -> dict:

    """

    Get comprehensive list of agents with User, Tenant, and KB details.

    

    SEARCH CAPABILITY:

    - If 'search' is provided, filters results where username, agent name, or tenant name match.

    """

    try:

        tenant_id, _ = get_tenant_and_user(request)



        async with AsyncSessionLocal() as db:

            agent_service = AgentService(db, tenant_id)

            return await agent_service.list_agents_enhanced(

                search=search, limit=limit, offset=offset

            )



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Failed to list enhanced agents: {e}")

        return format_error(f"Internal server error: {str(e)}")





@router.get(

    "",

    response_model=dict,

    summary="List Agents",

    description="List all agents for the current tenant",

)

@router.get(

    "/",

    response_model=dict,

    include_in_schema=False,

)

async def list_agents(

    request: Request,

    limit: int = 50,

    offset: int = 0,

) -> dict:

    """

    List all agents for tenant.



    TENANT ISOLATION: Only returns agents belonging to current tenant.

    Supports pagination via limit/offset.



    Args:

        request: FastAPI request

        limit: Max agents to return (default 50)

        offset: Pagination offset (default 0)



    Returns:

        JSON response with agents list and total count



    Raises:

        HTTPException 401: Not authenticated

        HTTPException 500: Database error

    """

    try:

        tenant_id, _ = get_tenant_and_user(request)



        # Validate pagination params

        if limit > 1000:

            limit = 1000

        if offset < 0:

            offset = 0



        async with AsyncSessionLocal() as db:

            service = AgentService(db, tenant_id)

            result = await service.list_agents(limit=limit, offset=offset)



            if not result.get("success"):

                raise HTTPException(status_code=500, detail="Failed to list agents")



            return result



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Unexpected error listing agents: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/by-user",

    response_model=dict,

    summary="List Agents by User ID",

    description="List all agents created by a specific user (identified by user_id)",

)

async def list_agents_by_user(

    request: Request,

    user_id: str,

    limit: int = 50,

    offset: int = 0,

) -> dict:

    """

    List all agents created by a specific user (identified by user_id).

    """

    try:

        tenant_id, _ = get_tenant_and_user(request)



        async with AsyncSessionLocal() as db:

            service = AgentService(db, tenant_id)

            result = await service.list_agents_by_user(

                user_id=user_id, limit=limit, offset=offset

            )



            if not result.get("success"):

                raise HTTPException(

                    status_code=404 if "not found" in result.get("error", "").lower() else 500,

                    detail=result.get("error", "Failed to list agents for user")

                )



            return result



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Unexpected error listing agents by user ID: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/{agent_id}",

    response_model=dict,

    summary="Get Agent",

    description="Retrieve a specific agent by ID",

)

async def get_agent(

    request: Request,

    agent_id: str,

) -> dict:

    """

    Get agent by ID.



    TENANT ISOLATION: Only returns agent if it belongs to current tenant.



    Args:

        request: FastAPI request

        agent_id: Agent UUID



    Returns:

        JSON response with agent details



    Raises:

        HTTPException 401: Not authenticated

        HTTPException 404: Agent not found

        HTTPException 500: Database error

    """

    try:

        tenant_id, _ = get_tenant_and_user(request)



        async with AsyncSessionLocal() as db:

            service = AgentService(db, tenant_id)

            result = await service.get_agent(agent_id)



            if not result.get("success"):

                status_code = result.get("status_code", 404)

                error_msg = result.get("error", "Agent not found")

                raise HTTPException(status_code=status_code, detail=error_msg)



            return result



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Unexpected error getting agent: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")




















@router.get(
    "/{agent_id}/integration/{integration_type}",
    response_model=dict,
    summary="Get Integration Status",
    description="Returns true if the agent is connected to the specified integration",
)
async def get_integration_status(
    request: Request,
    agent_id: str,
    integration_type: str,
) -> dict:
    """
    Check if a specific integration is active for this agent.
    """
    try:
        tenant_id, _ = get_tenant_and_user(request)
        async with AsyncSessionLocal() as db:
            service = AgentService(db, tenant_id)
            result = await service.get_agent(agent_id)
            
            if not result.get("success"):
                status_code = result.get("status_code", 404)
                error_msg = result.get("error", "Agent not found")
                raise HTTPException(status_code=status_code, detail=error_msg)
                
            agent_data = result["data"]["agent"]
            connected_integrations = agent_data.get("connected_integrations", [])
            
            is_connected = integration_type in connected_integrations
            
            return format_success({
                "integration_type": integration_type,
                "is_connected": is_connected
            }, meta={"message": "Status fetched successfully"})
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error getting integration status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.patch(

    "/{agent_id}",

    response_model=dict,

    summary="Update Agent",

    description="Update agent properties",

)

async def update_agent(

    request: Request,

    agent_id: str,

    agent_request: schemas.AgentUpdate,

) -> dict:

    """

    Update agent (partial update).



    Only provided fields are updated. All fields are optional.



    Args:

        request: FastAPI request

        agent_id: Agent UUID

        agent_request: AgentUpdate schema with optional fields



    Returns:

        JSON response with updated agent



    Raises:

        HTTPException 401: Not authenticated

        HTTPException 404: Agent not found

        HTTPException 400: Invalid request

        HTTPException 500: Database error

    """

    try:

        tenant_id, user_id = get_tenant_and_user(request)



        async with AsyncSessionLocal() as db:

            service = AgentService(db, tenant_id)

            result = await service.update_agent(user_id, agent_id, agent_request)



            if not result.get("success"):

                status_code = result.get("status_code", 400)

                error_msg = result.get("error", "Failed to update agent")

                raise HTTPException(status_code=status_code, detail=error_msg)



            return result



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Unexpected error updating agent: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")





@router.delete(

    "/{agent_id}",

    response_model=dict,

    status_code=status.HTTP_200_OK,

    summary="Delete Agent",

    description="Delete an agent and cascade delete related data",

)

async def delete_agent(

    request: Request,

    agent_id: str,

) -> dict:

    """

    Delete agent from both PostgreSQL and Neo4j.



    CASCADE DELETES:

    - PostgreSQL: Agent marked as inactive (soft delete)

    - Neo4j: Agent node and all related nodes (KBs, Chunks, Entities)



    TRANSACTION SAFETY:

    - If Neo4j deletion fails, PostgreSQL is not touched

    - Ensures consistency between databases



    Args:

        request: FastAPI request

        agent_id: Agent UUID



    Returns:

        JSON response with deletion confirmation



    Raises:

        HTTPException 401: Not authenticated

        HTTPException 404: Agent not found

        HTTPException 500: Database error

    """

    try:

        tenant_id, user_id = get_tenant_and_user(request)



        async with AsyncSessionLocal() as db:

            service = AgentService(db, tenant_id)

            result = await service.delete_agent(user_id, agent_id)



            if not result.get("success"):

                status_code = result.get("status_code", 500)

                error_msg = result.get("error", "Failed to delete agent")

                raise HTTPException(status_code=status_code, detail=error_msg)



            return result



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Unexpected error deleting agent: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")





# ============================================================================

# INSTANT INGESTION OVERRIDES (For Dashboard UI)

# ============================================================================



@router.post(

    "/{agent_id}/sources",

    response_model=dict,

    status_code=status.HTTP_200_OK,

    summary="Generic Source Ingestion",

    description="Automatically detect and ingest a source (File, URL, or Text) for the given agent.",

)

async def generic_ingest_source(

    request: Request,

    agent_id: str,

    file: Optional[UploadFile] = File(None),

) -> dict:

    """

    INTELLIGENT DISPATCHER:

    1. If a file is provided  Route to PDF ingestion

    2. If JSON body has 'url'  Route to URL ingestion

    3. If JSON body has 'text'  Route to Text ingestion

    """

    # 1. Handle File Upload (PDF)

    if file and file.filename:

        return await instant_ingest_pdf(request, agent_id, file)



    # 2. Handle JSON Body (URL or Text)

    try:

        body = await request.json()

        if "url" in body:

            from ..knowledge_bases.schemas import KBURLIngest

            url_data = KBURLIngest(**body)

            return await instant_ingest_url(request, agent_id, url_data)

        elif "text" in body:

            return await instant_ingest_text(request, agent_id, body)

        else:

            raise HTTPException(status_code=400, detail="Invalid source format. Expected 'file', 'url', or 'text'.")

    except Exception as e:

        if isinstance(e, HTTPException): raise

        raise HTTPException(status_code=400, detail=f"Request body parsing failed: {str(e)}")





from fastapi import BackgroundTasks

@router.post(
    "/{agent_id}/sources/pdf",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Instant File Ingestion",
    description="Automatically create a knowledge base data source and parse the uploaded PDF, Excel, or CSV directly for the given agent.",
)
async def instant_ingest_pdf(
    request: Request,
    agent_id: str,
    file: UploadFile = File(...),
) -> dict:

    """

    COMBINED ROUTE: Create KB + Ingest PDF/Excel/CSV.



    EXTRACTION STRATEGY:

    1. For PDFs: Gdocz SDK (primary)  Cloud API, handles complex/scanned PDFs, falls back to pdfplumber

    2. For Excel/CSV: ExcelIngestionService ontology-based graph ingestion

    """

    try:

        tenant_id, user_id = get_tenant_and_user(request)



        filename = file.filename

        ext = filename.lower().split(".")[-1]

        if ext not in ["pdf", "csv", "xlsx", "xls"]:

            raise HTTPException(

                status_code=400,

                detail="Unsupported file format. Supported formats: PDF, CSV, Excel (.xlsx, .xls)"

            )



        content = await file.read()

        # Calculate file hash
        import hashlib
        import uuid
        file_hash = hashlib.sha256(content).hexdigest()

        # Check database for duplicate hash
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select, or_
            from app.modules.knowledge_bases.models import KnowledgeBase
            from ...core.s3 import S3StorageService
            
            s3_service = S3StorageService()
            s3_url = s3_service.get_s3_url(str(tenant_id), filename)
            is_spreadsheet = filename.lower().endswith(('.csv', '.xls', '.xlsx'))
            kb_name = f"Spreadsheet: {filename}" if is_spreadsheet else f"PDF: {filename}"

            # 1. Check for exact duplicate content first
            stmt = select(KnowledgeBase).where(
                KnowledgeBase.tenant_id == uuid.UUID(tenant_id),
                KnowledgeBase.file_hash == file_hash,
                KnowledgeBase.is_active == True
            )
            res = await db.execute(stmt)
            existing_kb = res.scalars().first()
            if existing_kb:
                logger.info(f"Duplicate file hash detected in instant_ingest_pdf for tenant {tenant_id}: {filename} (Hash: {file_hash}). Rejecting upload.")
                raise HTTPException(
                    status_code=400,
                    detail="File already uploaded. Duplicates are not allowed."
                )

            # 2. Check for same filename/s3_url but different hash (modified content)
            stmt_modified = select(KnowledgeBase).where(
                KnowledgeBase.tenant_id == uuid.UUID(tenant_id),
                KnowledgeBase.is_active == True,
                or_(
                    KnowledgeBase.s3_path == s3_url,
                    KnowledgeBase.name == kb_name
                )
            )
            res_modified = await db.execute(stmt_modified)
            existing_kb_modified = res_modified.scalars().first()
            if existing_kb_modified:
                logger.info(f"Modified file upload detected for {filename}. Deleting old KB {existing_kb_modified.id} before re-ingestion.")
                from app.modules.knowledge_bases.service import KnowledgeBaseService
                kb_service = KnowledgeBaseService(db, tenant_id)
                await kb_service.delete_kb(str(existing_kb_modified.id), user_id=user_id)

        # ----------------------------------------------------
        # S3 STORAGE & DUPLICATE PREVENTION
        # ----------------------------------------------------
        from ...core.s3 import S3StorageService
        s3_service = S3StorageService()
        await s3_service.store_file_if_not_duplicate(str(tenant_id), filename, content)


        # ----------------------------------------------------
        # DOCUMENT PIPELINE (BACKGROUND JOBS)
        # ----------------------------------------------------
        from app.modules.jobs.service import JobService
        from app.modules.jobs.schemas import JobCreate
        from app.modules.jobs.worker import run_pdf_ingestion_job
        from ...core.pdf_extractor import PDFExtractor

        async with AsyncSessionLocal() as db:
            # Set context
            await db.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                {"tenant_id": str(tenant_id)}
            )
            
            # 1. Verify Agent belongs to User/Tenant
            agent_service = AgentService(db, tenant_id)
            agent_result = await agent_service.get_agent(agent_id)
            if not agent_result.get("success"):
                raise HTTPException(status_code=404, detail="Agent not found")
                
            # 2. Create Job in DB
            job_service = JobService(db, tenant_id)
            job_create = JobCreate(job_type="pdf_ingestion", file_name=filename)
            job_result = await job_service.create_job(user_id, job_create)
            
            if not job_result.get("success"):
                raise HTTPException(status_code=500, detail="Failed to create processing job")
                
            job_id = str(job_result["data"]["job"].id)
            
        # 3. Launch ingestion as an independent async task (not via background_tasks
        # which runs AFTER the response and can block the event loop for other requests)
        import asyncio
        asyncio.create_task(
            run_pdf_ingestion_job(
                tenant_id=str(tenant_id),
                user_id=str(user_id),
                agent_id=str(agent_id),
                job_id=job_id,
                filename=filename,
                content=content
            )
        )

        return {
            "success": True,
            "job_id": job_id,
            "status": "queued",
            "meta": {"message": "Document ingestion has been queued in the background. Use the job_id to poll for status."}
        }



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Instant Ingest file error: {e}")

        raise HTTPException(status_code=500, detail=str(e))





@router.post(

    "/{agent_id}/sources/text",

    response_model=dict,

    status_code=status.HTTP_200_OK,

    summary="Instant Raw Text Ingestion",

    description="Automatically create a knowledge base data source from provided raw text for the given agent.",

)

async def instant_ingest_text(

    request: Request,

    agent_id: str,

    text_data: dict,  # {"text": "..."}

) -> dict:

    """

    COMBINED ROUTE: Create KB + Ingest Raw Text.

    """

    try:

        tenant_id, user_id = get_tenant_and_user(request)



        document_text = text_data.get("text")

        if not document_text or not document_text.strip():

            raise HTTPException(status_code=400, detail="Text content cannot be empty")



        async with AsyncSessionLocal() as db:

            # 2. Verify Agent

            agent_service = AgentService(db, tenant_id)

            agent_result = await agent_service.get_agent(agent_id)

            if not agent_result.get("success"):

                raise HTTPException(status_code=404, detail="Agent not found")



            # 3. Create Source Metadata

            kb_service = KnowledgeBaseService(db, tenant_id)

            kb_request = KBCreate(

                name=f"Text Source: {document_text[:30]}...",

                description=f"Raw text input via dashboard",

                agent_id=uuid.UUID(agent_id),

                source="raw_text"

            )

            

            kb_result = await kb_service.create_knowledge_base(user_id, kb_request)

            if not kb_result.get("success"):

                raise HTTPException(status_code=500, detail="Backend logic failure")

                

            kb_id = str(kb_result["data"]["kb"].id)



            # 4. Ingest

            ingest_result = await kb_service.ingest_document(kb_id, document_text)

            # Add agent name to response

            agent_name = agent_result["data"]["agent"]["name"]

            ingest_result["data"]["agent_name"] = agent_name

            ingest_result["meta"]["message"] = f"Text knowledge stored to agent: {agent_name}"

            

            return ingest_result



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Instant Ingest Text error: {e}")

        raise HTTPException(status_code=500, detail=str(e))



async def crawl_url(url: str, mode: str = "single", proxy_mode: str = "basic") -> str:

    """

    Refactored crawling process using ScraperService.

    Uses Gcrawl API as primary with BS4 fallback.

    """

    logger.info(f" ScraperService Crawl: {url} (mode: {mode}, proxy: {proxy_mode})")

    

    documents = await ScraperService.extract_website_content(

        url=url,

        crawl_type=mode,

        proxy_mode=proxy_mode

    )

    

    if not documents:

        return ""

        

    # Combine content from all pages

    final_doc = ""

    for doc in documents:

        if len(documents) > 1:

            final_doc += f"\n\n# SOURCE: {doc['source']}\n\n"

        final_doc += doc["content"]

        

    return final_doc.strip()





@router.post(

    "/{agent_id}/sources/url",

    response_model=dict,

    status_code=status.HTTP_200_OK,

    summary="Instant URL Ingestion",

    description="Automatically crawl a URL and ingest its content into the graph for the given agent.",

)

async def instant_ingest_url(

    request: Request,

    agent_id: str,

    url_data: KBURLIngest,

) -> dict:

    """

    COMBINED ROUTE: Create KB + Crawl URL (Primary/Fallback) + Ingest.

    """

    try:

        tenant_id, user_id = get_tenant_and_user(request)

        

        # 1. Crawl URL (Robust primary + Fallback)

        try:

            document_text = await crawl_url(

                url=url_data.url, 

                mode=url_data.crawl_type, 

                proxy_mode=url_data.proxy_mode

            )

        except Exception as e:

            raise HTTPException(status_code=400, detail=f"Failed to fetch content from URL: {str(e)}")



        if not document_text.strip():

            raise HTTPException(status_code=400, detail="No extractable text content found on the page")



        async with AsyncSessionLocal() as db:

            # 2. Verify Agent

            agent_service = AgentService(db, tenant_id)

            agent_result = await agent_service.get_agent(agent_id)

            if not agent_result.get("success"):

                raise HTTPException(status_code=404, detail="Agent not found")



            # 3. Create Source Metadata

            kb_service = KnowledgeBaseService(db, tenant_id)

            kb_request = KBCreate(

                name=f"Web: {url_data.url[:50]}",

                description=f"Crawled web source",

                agent_id=uuid.UUID(agent_id),

                source="url_crawl"

            )

            

            kb_result = await kb_service.create_knowledge_base(user_id, kb_request)

            kb_id = str(kb_result["data"]["kb"].id)



            # 4. Ingest

            # 4. Ingest

            ingest_result = await kb_service.ingest_document(kb_id, document_text)

            

            # Add agent name to response

            agent_name = agent_result["data"]["agent"]["name"]

            ingest_result["data"]["agent_name"] = agent_name

            ingest_result["meta"]["message"] = f"Web content from {url_data.url} stored to agent: {agent_name}"

            

            return ingest_result



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Instant Ingest URL error: {e}")

        raise HTTPException(status_code=500, detail=str(e))



