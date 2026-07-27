from typing import Optional, List, Dict, Any
"""REST routes for Knowledge Base CRUD and document ingestion"""

import os
import httpx
import urllib.parse

from fastapi import APIRouter, Request, HTTPException, status, BackgroundTasks

from sqlalchemy.ext.asyncio import AsyncSession

import logging

import uuid

from fastapi.responses import RedirectResponse
from .models import DatabaseConnection

from .service import KnowledgeBaseService

from . import schemas

from ...core.database import AsyncSessionLocal

from ...utils.formatters import format_error, format_success



logger = logging.getLogger(__name__)



router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["knowledge-bases"])





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

    summary="Create Knowledge Base",

    description="Create a new knowledge base for an agent",

)

async def create_kb(

    request: Request,

    kb_request: schemas.KBCreate,

) -> dict:

    """

    Create a new knowledge base linked to an agent.



    Creates KB in BOTH:

    1. PostgreSQL (metadata storage)

    2. Neo4j (graph node for chunk relationships)



    TRANSACTION SAFETY:

    - If either database fails, entire operation is rolled back

    - No orphaned nodes or records



    Args:

        request: FastAPI request (contains tenant_id in state)

        kb_request: KBCreate schema with name, agent_id, description



    Returns:

        JSON response with created KB



    Raises:

        HTTPException 401: Not authenticated

        HTTPException 400: Invalid request

        HTTPException 500: Database error

    """

    try:

        tenant_id, user_id = get_tenant_and_user(request)



        async with AsyncSessionLocal() as db:

            service = KnowledgeBaseService(db, tenant_id)

            result = await service.create_knowledge_base(user_id, kb_request)



            if not result.get("success"):

                error_msg = result.get("error", "Unknown error")

                status_code = result.get("status_code", 400)

                raise HTTPException(status_code=status_code, detail=error_msg)



            return result



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Create KB endpoint error: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/{kb_id}",

    response_model=dict,

    summary="Get Knowledge Base",

    description="Get a knowledge base by ID",

)

async def get_kb(request: Request, kb_id: str) -> dict:

    """

    Get a knowledge base by ID.



    Args:

        request: FastAPI request

        kb_id: KB UUID



    Returns:

        JSON response with KB details



    Raises:

        HTTPException 401: Not authenticated

        HTTPException 404: KB not found

        HTTPException 500: Database error

    """

    try:

        tenant_id, _ = get_tenant_and_user(request)



        async with AsyncSessionLocal() as db:

            service = KnowledgeBaseService(db, tenant_id)

            result = await service.get_kb(kb_id)



            if not result.get("success"):

                error_msg = result.get("error", "Unknown error")

                status_code = result.get("status_code", 404)

                raise HTTPException(status_code=status_code, detail=error_msg)



            return result



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Get KB endpoint error: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "",

    response_model=dict,

    summary="List Knowledge Bases",

    description="List all knowledge bases for the tenant",

)

async def list_kbs(request: Request, limit: int = 50, offset: int = 0) -> dict:

    """

    List all knowledge bases for the tenant with pagination.



    Args:

        request: FastAPI request

        limit: Max results (default 50)

        offset: Pagination offset (default 0)



    Returns:

        JSON response with KBs list



    Raises:

        HTTPException 401: Not authenticated

        HTTPException 500: Database error

    """

    try:

        tenant_id, _ = get_tenant_and_user(request)



        # Validate pagination

        if limit < 1 or limit > 1000:

            limit = 50

        if offset < 0:

            offset = 0



        async with AsyncSessionLocal() as db:

            service = KnowledgeBaseService(db, tenant_id)

            result = await service.list_kbs(limit=limit, offset=offset)



            if not result.get("success"):

                raise HTTPException(status_code=500, detail=result.get("error"))



            return result



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"List KBs endpoint error: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")





@router.get(

    "/agents/{agent_id}",

    response_model=dict,

    summary="List Knowledge Bases for Agent",

    description="List all knowledge bases for a specific agent",

)

async def list_agent_kbs(

    request: Request,

    agent_id: str,

    limit: int = 50,

    offset: int = 0,

) -> dict:

    """

    List knowledge bases for a specific agent.



    Args:

        request: FastAPI request

        agent_id: Agent UUID

        limit: Max results (default 50)

        offset: Pagination offset (default 0)



    Returns:

        JSON response with KBs list



    Raises:

        HTTPException 401: Not authenticated

        HTTPException 500: Database error

    """

    try:

        tenant_id, _ = get_tenant_and_user(request)



        # Validate pagination

        if limit < 1 or limit > 1000:

            limit = 50

        if offset < 0:

            offset = 0



        async with AsyncSessionLocal() as db:

            service = KnowledgeBaseService(db, tenant_id)

            result = await service.list_kbs_by_agent(

                agent_id, limit=limit, offset=offset

            )



            if not result.get("success"):

                raise HTTPException(status_code=500, detail=result.get("error"))



            return result



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"List agent KBs endpoint error: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")


@router.get(
    "/users/{user_id}",
    response_model=dict,
    summary="List Knowledge Bases for User",
    description="List all knowledge bases uploaded by a specific user with optional date and agent filters",
)
async def list_user_kbs(
    request: Request,
    user_id: str,
    date: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    try:
        tenant_id, _ = get_tenant_and_user(request)

        # Validate pagination
        if limit < 1 or limit > 1000:
            limit = 50
        if offset < 0:
            offset = 0

        async with AsyncSessionLocal() as db:
            service = KnowledgeBaseService(db, tenant_id)
            result = await service.list_kbs_by_user(
                user_id=user_id,
                date=date,
                agent_id=agent_id,
                limit=limit,
                offset=offset,
            )

            if not result.get("success"):
                error_msg = result.get("error", "Unknown error")
                status_code = result.get("status_code", 400)
                raise HTTPException(status_code=status_code, detail=error_msg)

            return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"List user KBs endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")






@router.post(

    "/{kb_id}/ingest",

    response_model=dict,

    summary="Ingest Document",

    description="Upload and ingest a document into a knowledge base",

)

async def ingest_document(

    request: Request,

    kb_id: str,

    body: dict,  # {"document_text": "..."}

) -> dict:

    """

    Ingest a document into a knowledge base.



    PROCESS:

    1. Validate KB exists

    2. Split text into chunks (500-1000 tokens, overlap)

    3. Generate embeddings for each chunk

    4. Store chunks in Neo4j

    5. Create ChunkChunk(NEXT) relationships



    Args:

        request: FastAPI request

        kb_id: KB UUID

        body: Request body with "document_text" field



    Returns:

        JSON response with chunks created count



    Raises:

        HTTPException 401: Not authenticated

        HTTPException 404: KB not found

        HTTPException 400: Invalid request

        HTTPException 500: Database error

    """

    try:

        tenant_id, _ = get_tenant_and_user(request)



        # Extract document text and optional source

        document_text = body.get("document_text", "").strip()

        source = body.get("source", "text").strip()

        if not document_text:

            raise HTTPException(status_code=400, detail="document_text is required")





        async with AsyncSessionLocal() as db:

            service = KnowledgeBaseService(db, tenant_id)

            result = await service.ingest_document(kb_id, document_text, source=source)



            if not result.get("success"):

                error_msg = result.get("error", "Unknown error")

                status_code = result.get("status_code", 400)

                raise HTTPException(status_code=status_code, detail=error_msg)



            return result



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Ingest document endpoint error: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")





from fastapi import UploadFile, File



@router.post(

    "/{kb_id}/ingest/file",

    response_model=dict,

    summary="Ingest Document File",

    description="Upload and ingest a PDF, Excel (.xlsx, .xls) or CSV (.csv) file into the knowledge base.",

)

async def ingest_file(

    request: Request,

    kb_id: str,

    file: UploadFile = File(...),

) -> dict:

    """

    Ingest a document file (PDF, Excel, or CSV) into a knowledge base.

    """

    try:

        tenant_id, _ = get_tenant_and_user(request)

        filename = file.filename.lower()

        # Read file content
        content = await file.read()
        
        # Calculate file hash
        import hashlib
        import uuid
        file_hash = hashlib.sha256(content).hexdigest()

        # Check database for duplicate hash
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            from .models import KnowledgeBase
            stmt = select(KnowledgeBase).where(
                KnowledgeBase.tenant_id == uuid.UUID(tenant_id),
                KnowledgeBase.file_hash == file_hash,
                KnowledgeBase.is_active == True
            )
            res = await db.execute(stmt)
            existing_kb = res.scalars().first()
            if existing_kb:
                logger.info(f"Duplicate file hash detected in ingest_file for tenant {tenant_id}: {file.filename} (Hash: {file_hash}). Rejecting upload.")
                raise HTTPException(
                    status_code=400,
                    detail="File already uploaded. Duplicates are not allowed."
                )

        # 1. Store in S3 and check for duplicates
        from ...core.s3 import S3StorageService
        s3_service = S3StorageService()
        await s3_service.store_file_if_not_duplicate(str(tenant_id), file.filename, content)

        # 2. Route based on file extension
        if filename.endswith(".pdf"):



            # Extract PDF using PDFExtractor (Gdocz primary + pdfplumber fallback)

            from ...core.pdf_extractor import PDFExtractor



            try:

                document_text = await PDFExtractor.extract(

                    pdf_bytes=content,

                    filename=file.filename,

                    tenant_id=tenant_id,

                )

            except ValueError as e:

                raise HTTPException(status_code=400, detail=str(e))

            except Exception as e:

                logger.error(f"PDF extraction failed: {e}")

                raise HTTPException(

                    status_code=400,

                    detail=f"Failed to extract text from PDF: {str(e)}",

                )



            if not document_text.strip():

                raise HTTPException(

                    status_code=400,

                    detail="Could not extract any text from the PDF",

                )



            # Store parsed content in S3
            parsed_url = None
            try:
                is_html = getattr(document_text, "is_html", False)
                is_markdown = getattr(document_text, "is_markdown", False)
                raw_content = getattr(document_text, "raw_content", getattr(document_text, "raw_html", document_text))
                if is_markdown:
                    content_type = "text/markdown"
                elif is_html:
                    content_type = "text/html"
                else:
                    content_type = "text/plain"

                parsed_url = s3_service.store_parsed_content(
                    tenant_id=str(tenant_id),
                    kb_id=str(kb_id),
                    content=raw_content,
                    content_type=content_type
                )
            except Exception as e:
                logger.error(f"Failed to store parsed content in S3: {e}")

            # Ingest standard document text

            async with AsyncSessionLocal() as db:

                service = KnowledgeBaseService(db, tenant_id)
                await service.clear_kb_contents(kb_id)
                s3_url = s3_service.get_s3_url(str(tenant_id), file.filename)

                result = await service.ingest_document(
                    kb_id, 
                    document_text, 
                    s3_path=s3_url,
                    parsed_path=parsed_url
                )



                if not result.get("success"):

                    error_msg = result.get("error", "Unknown error")

                    status_code = result.get("status_code", 400)

                    raise HTTPException(status_code=status_code, detail=error_msg)

                # Set file_hash and description on the KnowledgeBase
                from sqlalchemy import update
                method = getattr(document_text, "extraction_method", "gdocz")
                display_method = "Gdocz" if method.lower() == "gdocz" else "pdfplumber"
                kb_description = f"Automated PDF upload source ({display_method} extraction)"
                await db.execute(
                    update(KnowledgeBase)
                    .where(KnowledgeBase.id == uuid.UUID(kb_id))
                    .values(file_hash=file_hash, description=kb_description)
                )
                await db.commit()

                return result



        elif filename.endswith((".xlsx", ".xls", ".csv")):
            import tempfile
            import os
            from app.core.parquet_ingester import ParquetIngester
            
            # Write bytes to temp file so ParquetIngester can read it
            temp_fd, temp_path = tempfile.mkstemp(suffix=os.path.splitext(filename)[1])
            try:
                with os.fdopen(temp_fd, 'wb') as f:
                    f.write(content)
                    
                dataset_name = os.path.splitext(filename)[0]
                ParquetIngester.ingest_to_parquet(temp_path, dataset_name=dataset_name)
                
                async with AsyncSessionLocal() as db:
                    from sqlalchemy import update
                    await db.execute(
                        update(KnowledgeBase)
                        .where(KnowledgeBase.id == uuid.UUID(kb_id))
                        # Save dataset_name to parsed_path so query engine can retrieve active file
                        # Save description to "excel_parquet" to route queries
                        .values(file_hash=file_hash, parsed_path=dataset_name, description="excel_parquet")
                    )
                    await db.commit()
                    
                return {"success": True, "message": "Successfully ingested into memory-safe Parquet pipeline."}
                
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

        else:

            raise HTTPException(

                status_code=400,

                detail="Unsupported file format. Supported extensions: .pdf, .xlsx, .xls, .csv"

            )



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Ingest file endpoint error: {e}")

        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")





@router.post(

    "/{kb_id}/ingest/pdf",

    response_model=dict,

    summary="Ingest PDF Document (Alias/Legacy)",

    description="Unified upload endpoint wrapper supporting PDF, Excel, and CSV under the legacy path.",

)

async def ingest_pdf(

    request: Request,

    kb_id: str,

    file: UploadFile = File(...),

) -> dict:

    """

    Unified PDF legacy route wrapper to support Excel/CSV uploaded through the existing PDF interface.

    """

    return await ingest_file(request=request, kb_id=kb_id, file=file)





@router.post(

    "/{kb_id}/ingest/url",

    response_model=dict,

    summary="Ingest URL Content",

    description="Crawl a URL and ingest its content into the knowledge base. Uses Gcrawl API with BeautifulSoup fallback.",

)

async def ingest_url(

    request: Request,

    kb_id: str,

    ingest_request: schemas.KBURLIngest,

) -> dict:

    """

    Ingest content from a URL into a knowledge base.



    STRATEGY:

    1. Scrape content using ScraperService (Gcrawl + BS4 fallback)

    2. Normalize multiple pages if crawl_type is 'all'

    3. Ingest each page's content into the KB

    """

    try:

        tenant_id, _ = get_tenant_and_user(request)



        from .services.scraper_service import ScraperService



        # 1. Scrape content

        documents = await ScraperService.extract_website_content(

            url=ingest_request.url,

            crawl_type=ingest_request.crawl_type,

            proxy_mode=ingest_request.proxy_mode

        )



        if not documents:

            raise HTTPException(

                status_code=400,

                detail="Could not extract any content from the provided URL"

            )



        async with AsyncSessionLocal() as db:

            service = KnowledgeBaseService(db, tenant_id)



            total_chunks = 0

            results = []



            # 2. Ingest each document

            for doc in documents:

                # Prepare document text with source header

                content = doc["content"]

                if len(documents) > 1:

                    content = f"# SOURCE: {doc['source']}\n\n{content}"



                ingest_result = await service.ingest_document(kb_id, content, source=doc["source"])



                if ingest_result.get("success"):

                    total_chunks += ingest_result["data"]["chunks_created"]

                    results.append({

                        "source": doc["source"],

                        "chunks": ingest_result["data"]["chunks_created"]

                    })



            if not results:

                raise HTTPException(status_code=500, detail="Failed to ingest any content")



            return format_success(

                {

                    "kb_id": kb_id,

                    "total_pages": len(results),

                    "total_chunks_created": total_chunks,

                    "details": results

                },

                meta={"message": f"Successfully ingested {len(results)} pages from {ingest_request.url}"}

            )



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"URL ingestion endpoint error: {e}")

        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")







@router.delete(

    "/{kb_id}",

    response_model=dict,

    summary="Delete Knowledge Base",

    description="Delete a knowledge base and all its chunks",

)

async def delete_kb(request: Request, kb_id: str) -> dict:
    """
    Delete a knowledge base.

    Deletes KB from BOTH:
    1. Neo4j (KB node + cascade chunks)
    2. PostgreSQL (soft-delete)

    Args:
        request: FastAPI request
        kb_id: KB UUID

    Returns:
        JSON response with deletion confirmation

    Raises:
        HTTPException 401: Not authenticated
        HTTPException 404: KB not found
        HTTPException 500: Database error
    """
    try:
        tenant_id, user_id = get_tenant_and_user(request)

        async with AsyncSessionLocal() as db:
            service = KnowledgeBaseService(db, tenant_id)
            result = await service.delete_kb(kb_id, user_id=user_id)



            if not result.get("success"):

                error_msg = result.get("error", "Unknown error")

                status_code = result.get("status_code", 404)

                raise HTTPException(status_code=status_code, detail=error_msg)



            return result



    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Delete KB endpoint error: {e}")

        raise HTTPException(status_code=500, detail="Internal server error")

@router.delete(
    "/agent/{agent_id}/integration/{integration_type}",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Disconnect Agent Integration",
    description="Deletes all knowledge bases for a specific agent that match the integration type.",
)
async def disconnect_agent_integration(request: Request, agent_id: str, integration_type: str) -> dict:
    try:
        tenant_id, user_id = get_tenant_and_user(request)
        
        valid_integrations = ["google_drive", "sharepoint", "gmail", "outlook"]
        if integration_type not in valid_integrations:
            raise HTTPException(status_code=400, detail=f"Invalid integration type. Must be one of {valid_integrations}")

        async with AsyncSessionLocal() as db:
            service = KnowledgeBaseService(db, tenant_id)
            result = await service.disconnect_agent_integration(agent_id, integration_type, user_id=user_id)
            return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Disconnect Integration endpoint error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================================================

# NATIVE DATABASE CONNECTOR ENDPOINTS

# ============================================================================



@router.post(

    "/{kb_id}/database-connection",

    response_model=dict,

    status_code=status.HTTP_200_OK,

    summary="Register Database Connection",

    description="Register and validate an external/local database connection config for this KB"

)

async def register_db_connection(

    request: Request,

    kb_id: str,

    db_request: schemas.DatabaseConnectionRegister

) -> dict:

    try:

        tenant_id, _ = get_tenant_and_user(request)



        async with AsyncSessionLocal() as db:

            service = KnowledgeBaseService(db, tenant_id)

            result = await service.register_database_connection(kb_id, db_request)



            if not result.get("success"):

                raise HTTPException(status_code=400, detail=result.get("error"))



            return result

    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Error in register_db_connection: {e}")

        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")





@router.get(

    "/{kb_id}/database-schema",

    response_model=dict,

    status_code=status.HTTP_200_OK,

    summary="Discover Database Schema",

    description="Introspect the registered database tables for this KB"

)

async def discover_db_schema(request: Request, kb_id: str) -> dict:

    try:

        tenant_id, _ = get_tenant_and_user(request)



        async with AsyncSessionLocal() as db:

            service = KnowledgeBaseService(db, tenant_id)

            result = await service.discover_database_schema(kb_id)



            if not result.get("success"):

                raise HTTPException(status_code=400, detail=result.get("error"))



            return result

    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Error in discover_db_schema: {e}")

        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")





@router.post(

    "/{kb_id}/sync-database",

    response_model=dict,

    status_code=status.HTTP_200_OK,

    summary="Synchronize Database to Graph",

    description="Introspect tables, transform rows into Chunk nodes, generate embeddings, and load them into Neo4j"

)

async def sync_db_to_graph(request: Request, kb_id: str) -> dict:

    try:

        tenant_id, _ = get_tenant_and_user(request)



        async with AsyncSessionLocal() as db:

            service = KnowledgeBaseService(db, tenant_id)

            result = await service.sync_database_source(kb_id)



            if not result.get("success"):

                raise HTTPException(status_code=400, detail=result.get("error"))



            return result

    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Error in sync_db_to_graph: {e}")

        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")



@router.get("/{agent_id}/list_knowledge_bases")

async def list_knowledge_bases(request: Request, agent_id: str) -> dict:

    try:

        tenant_id, _ = get_tenant_and_user(request)



        async with AsyncSessionLocal() as db:

            service = KnowledgeBaseService(db, tenant_id)

            result = await service.list_knowledge_source(agent_id)

            

            if not result.get("success"):

                status_code = result.get("meta", {}).get("status_code", 400)

                raise HTTPException(status_code=status_code, detail=result.get("error"))



            return result

    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Error in list_knowledge_bases: {e}")

        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")





# ============================================================================

# GOOGLE DRIVE CONNECTOR ENDPOINTS

# ============================================================================



@router.post(

    "/{kb_id}/google-drive/register",

    response_model=dict,

    status_code=status.HTTP_200_OK,

    summary="Register Google Drive Connection",

    description="Register Google Drive credentials and folder configurations for this KB"

)

async def register_google_drive(

    request: Request,

    kb_id: str,

    gd_request: schemas.GoogleDriveRegister

) -> dict:

    try:

        tenant_id, _ = get_tenant_and_user(request)



        async with AsyncSessionLocal() as db:

            from sqlalchemy import select

            from .models import DatabaseConnection

            import uuid

            

            # Check if a connection already exists to update it (upsert)

            query = select(DatabaseConnection).where(

                DatabaseConnection.kb_id == uuid.UUID(kb_id),

                DatabaseConnection.tenant_id == uuid.UUID(tenant_id)

            )

            db_conn_res = await db.execute(query)

            db_conn = db_conn_res.scalar_one_or_none()



            connection_params = {

                "credentials": gd_request.credentials,

                "folder_urls": gd_request.folder_urls or []

            }



            if db_conn:

                db_conn.db_type = "google_drive"

                db_conn.connection_params = connection_params

            else:

                db_conn = DatabaseConnection(

                    tenant_id=uuid.UUID(tenant_id),

                    kb_id=uuid.UUID(kb_id),

                    db_type="google_drive",

                    connection_params=connection_params

                )

                db.add(db_conn)



            await db.commit()

            return format_success(

                {"success": True},

                meta={"message": "Google Drive connection registered successfully"}

            )

    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Error in register_google_drive: {e}")

        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")






@router.get(
    "/{kb_id}/google-drive/files",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="List Google Drive Files",
    description="List files and folders from the connected Google Drive for selective ingestion."
)
async def list_google_drive_files(request: Request, kb_id: str, parent_id: Optional[str] = None) -> dict:
    try:
        tenant_id, _ = get_tenant_and_user(request)
        async with AsyncSessionLocal() as db:
            service = KnowledgeBaseService(db, tenant_id)
            return await service.list_google_drive_directory(kb_id=kb_id, parent_id=parent_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in list_google_drive_files: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post(

    "/{kb_id}/google-drive/sync",

    response_model=dict,

    status_code=status.HTTP_200_OK,

    summary="Synchronize Google Drive to Graph",

    description="Crawl Google Drive, download files, generate embeddings, and load them into Neo4j graph"

)

async def sync_google_drive_to_graph(request: Request, kb_id: str, sync_req: Optional[schemas.GoogleDriveSyncRequest] = None) -> dict:

    try:

        tenant_id, _ = get_tenant_and_user(request)



        async with AsyncSessionLocal() as db:

            from sqlalchemy import select

            from .models import DatabaseConnection

            from datetime import datetime

            import uuid

            

            query = select(DatabaseConnection).where(

                DatabaseConnection.kb_id == uuid.UUID(kb_id),

                DatabaseConnection.tenant_id == uuid.UUID(tenant_id),

                DatabaseConnection.db_type == "google_drive"

            )

            res = await db.execute(query)

            db_conn = res.scalar_one_or_none()

            if not db_conn:

                raise HTTPException(status_code=404, detail="No registered Google Drive connection found for this KB")



            connection_params = db_conn.connection_params

            credentials = connection_params.get("credentials", {})

            folder_urls = connection_params.get("folder_urls", [])



            service = KnowledgeBaseService(db, tenant_id)

            file_ids = sync_req.file_ids if sync_req else None
            folder_ids = sync_req.folder_ids if sync_req else None
            user_email = sync_req.user_email if sync_req else None
            result = await service.sync_google_drive_source(
                kb_id=kb_id,
                credentials_dict=credentials,
                folder_urls=folder_urls,
                file_ids=file_ids,
                folder_ids=folder_ids,
                user_email=user_email
            )



            if not result.get("success"):

                raise HTTPException(status_code=400, detail=result.get("error"))



            # Update sync status timestamp

            db_conn.last_synced_at = datetime.now()

            await db.commit()



            return result

    except HTTPException:

        raise

    except Exception as e:

        logger.error(f"Error in sync_google_drive_to_graph: {e}")

        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


# ============================================================================
# SHAREPOINT CONNECTOR ENDPOINTS
# ============================================================================

@router.post(
    "/{kb_id}/sharepoint/register",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Register SharePoint Connection",
    description="Register SharePoint credentials for this KB"
)
async def register_sharepoint(
    request: Request,
    kb_id: str,
    sp_request: schemas.SharePointRegister
) -> dict:
    try:
        tenant_id, _ = get_tenant_and_user(request)
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            from .models import DatabaseConnection
            import uuid
            
            query = select(DatabaseConnection).where(
                DatabaseConnection.kb_id == uuid.UUID(kb_id),
                DatabaseConnection.tenant_id == uuid.UUID(tenant_id)
            )
            db_conn_res = await db.execute(query)
            db_conn = db_conn_res.scalar_one_or_none()

            import os
            # Always use the backend's secure environment variables instead of trusting the frontend payload
            backend_credentials = {
                "client_id": os.getenv("MS_CLIENT_ID"),
                "client_secret": os.getenv("MS_CLIENT_SECRET"),
                "tenant_id": "common"
            }
            
            connection_params = {
                "credentials": backend_credentials,
                "site_urls": sp_request.site_urls or []
            }

            if db_conn:
                # Merge with existing to preserve access tokens if they somehow exist
                existing_creds = db_conn.connection_params.get("credentials", {})
                existing_creds.update(backend_credentials)
                connection_params["credentials"] = existing_creds
                
                db_conn.db_type = "sharepoint"
                db_conn.connection_params = connection_params
            else:
                db_conn = DatabaseConnection(
                    tenant_id=uuid.UUID(tenant_id),
                    kb_id=uuid.UUID(kb_id),
                    db_type="sharepoint",
                    connection_params=connection_params
                )
                db.add(db_conn)

            await db.commit()
            return format_success(
                {"success": True},
                meta={"message": "SharePoint connection registered successfully"}
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in register_sharepoint: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get(
    "/{kb_id}/sharepoint/files",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="List SharePoint Files",
    description="List files and folders from the connected SharePoint for selective ingestion."
)
async def list_sharepoint_files(request: Request, kb_id: str, parent_id: Optional[str] = None) -> dict:
    try:
        tenant_id, _ = get_tenant_and_user(request)
        async with AsyncSessionLocal() as db:
            service = KnowledgeBaseService(db, tenant_id)
            return await service.list_sharepoint_directory(kb_id=kb_id, parent_id=parent_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in list_sharepoint_files: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post(
    "/{kb_id}/sharepoint/sync",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Synchronize SharePoint to Graph",
    description="Crawl SharePoint, download files, generate embeddings, and load them into Neo4j graph"
)
async def sync_sharepoint_to_graph(request: Request, kb_id: str, sync_req: Optional[schemas.SharePointSyncRequest] = None) -> dict:
    try:
        tenant_id, _ = get_tenant_and_user(request)

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            from .models import DatabaseConnection
            from datetime import datetime
            import uuid
            
            query = select(DatabaseConnection).where(
                DatabaseConnection.kb_id == uuid.UUID(kb_id),
                DatabaseConnection.tenant_id == uuid.UUID(tenant_id),
                DatabaseConnection.db_type == "sharepoint"
            )
            res = await db.execute(query)
            db_conn = res.scalar_one_or_none()
            if not db_conn:
                raise HTTPException(status_code=404, detail="No registered SharePoint connection found for this KB")

            connection_params = db_conn.connection_params
            credentials = connection_params.get("credentials", {})
            site_urls = connection_params.get("site_urls", [])

            service = KnowledgeBaseService(db, tenant_id)
            file_ids = sync_req.file_ids if sync_req else None
            folder_ids = sync_req.folder_ids if sync_req else None
            result = await service.sync_sharepoint_source(
                kb_id=kb_id,
                credentials_dict=credentials,
                site_urls=site_urls,
                file_ids=file_ids,
                folder_ids=folder_ids
            )

            if not result.get("success"):
                raise HTTPException(status_code=400, detail=result.get("error"))

            # Update sync status timestamp
            db_conn.last_synced_at = datetime.now()
            await db.commit()

            return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in sync_sharepoint_to_graph: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# ============================================================================
# GMAIL CONNECTOR ENDPOINTS
# ============================================================================

@router.post(
    "/{kb_id}/gmail/register",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Register Gmail Connection",
    description="Register Gmail credentials for this KB"
)
async def register_gmail(
    request: Request,
    kb_id: str,
    gm_request: schemas.GmailRegister
) -> dict:
    try:
        tenant_id, _ = get_tenant_and_user(request)
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            from .models import DatabaseConnection
            import uuid
            
            query = select(DatabaseConnection).where(
                DatabaseConnection.kb_id == uuid.UUID(kb_id),
                DatabaseConnection.tenant_id == uuid.UUID(tenant_id)
            )
            db_conn_res = await db.execute(query)
            db_conn = db_conn_res.scalar_one_or_none()

            connection_params = gm_request.credentials

            if db_conn:
                db_conn.db_type = "gmail"
                db_conn.connection_params = connection_params
            else:
                db_conn = DatabaseConnection(
                    tenant_id=uuid.UUID(tenant_id),
                    kb_id=uuid.UUID(kb_id),
                    db_type="gmail",
                    connection_params=connection_params
                )
                db.add(db_conn)

            await db.commit()
            return format_success(
                {"success": True},
                meta={"message": "Gmail connection registered successfully"}
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in register_gmail: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post(
    "/{kb_id}/gmail/sync",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Synchronize Gmail to Graph",
    description="Crawl Gmail, fetch messages, generate embeddings, and load them into Neo4j graph"
)
async def sync_gmail_to_graph(request: Request, kb_id: str, sync_req: schemas.GmailSyncRequest) -> dict:
    try:
        tenant_id, _ = get_tenant_and_user(request)
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            from .models import DatabaseConnection
            from datetime import datetime
            import uuid
            
            query = select(DatabaseConnection).where(
                DatabaseConnection.kb_id == uuid.UUID(kb_id),
                DatabaseConnection.tenant_id == uuid.UUID(tenant_id),
                DatabaseConnection.db_type == "gmail"
            )
            res = await db.execute(query)
            db_conn = res.scalar_one_or_none()
            if not db_conn:
                raise HTTPException(status_code=404, detail="No registered Gmail connection found for this KB")

            service = KnowledgeBaseService(db, tenant_id)
            result = await service.sync_gmail_source(
                kb_id=kb_id,
                sync_req=sync_req.model_dump()
            )

            if not result.get("success"):
                raise HTTPException(status_code=400, detail=result.get("error"))

            db_conn.last_synced_at = datetime.now()
            await db.commit()
            return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in sync_gmail_to_graph: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


# ============================================================================
# OUTLOOK CONNECTOR ENDPOINTS
# ============================================================================

@router.post(
    "/{kb_id}/outlook/register",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Register Outlook Connection",
    description="Register Outlook credentials for this KB"
)
async def register_outlook(
    request: Request,
    kb_id: str,
    ol_request: schemas.OutlookRegister
) -> dict:
    try:
        tenant_id, _ = get_tenant_and_user(request)
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            from .models import DatabaseConnection
            import uuid
            
            query = select(DatabaseConnection).where(
                DatabaseConnection.kb_id == uuid.UUID(kb_id),
                DatabaseConnection.tenant_id == uuid.UUID(tenant_id)
            )
            db_conn_res = await db.execute(query)
            db_conn = db_conn_res.scalar_one_or_none()

            connection_params = ol_request.credentials

            if db_conn:
                db_conn.db_type = "outlook"
                db_conn.connection_params = connection_params
            else:
                db_conn = DatabaseConnection(
                    tenant_id=uuid.UUID(tenant_id),
                    kb_id=uuid.UUID(kb_id),
                    db_type="outlook",
                    connection_params=connection_params
                )
                db.add(db_conn)

            await db.commit()
            return format_success(
                {"success": True},
                meta={"message": "Outlook connection registered successfully"}
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in register_outlook: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post(
    "/{kb_id}/outlook/sync",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Synchronize Outlook to Graph",
    description="Crawl Outlook, fetch messages, generate embeddings, and load them into Neo4j graph"
)
async def sync_outlook_to_graph(request: Request, kb_id: str, sync_req: schemas.OutlookSyncRequest) -> dict:
    try:
        tenant_id, _ = get_tenant_and_user(request)
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            from .models import DatabaseConnection
            from datetime import datetime
            import uuid
            
            query = select(DatabaseConnection).where(
                DatabaseConnection.kb_id == uuid.UUID(kb_id),
                DatabaseConnection.tenant_id == uuid.UUID(tenant_id),
                DatabaseConnection.db_type == "outlook"
            )
            res = await db.execute(query)
            db_conn = res.scalar_one_or_none()
            if not db_conn:
                raise HTTPException(status_code=404, detail="No registered Outlook connection found for this KB")

            service = KnowledgeBaseService(db, tenant_id)
            result = await service.sync_outlook_source(
                kb_id=kb_id,
                sync_req=sync_req.model_dump()
            )

            if not result.get("success"):
                raise HTTPException(status_code=400, detail=result.get("error"))

            db_conn.last_synced_at = datetime.now()
            await db.commit()
            return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in sync_outlook_to_graph: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

# Add to your existing router, or create a new one
@router.get("/{kb_id}/sharepoint/login")
async def sharepoint_login(kb_id: str):
    """Step 1: Redirect user to Microsoft Login"""
    tenant_id = "common"
    client_id = os.getenv("MS_CLIENT_ID")
    redirect_uri = "http://localhost:4915/api/v1/knowledge-bases/sharepoint/callback"
    
    # We pass the kb_id in the state parameter so we know which KB to save the token to
    state = kb_id 
    
    auth_url = (
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
        f"?client_id={client_id}"
        f"&response_type=code"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&response_mode=query"
        f"&scope=openid profile email offline_access Files.Read.All Sites.Read.All"
        f"&state={kb_id}"
        f"&prompt=select_account"
    )
    return RedirectResponse(auth_url)
@router.get("/sharepoint/callback")
async def sharepoint_callback(code: str, state: str):
    """Step 2: Microsoft redirects here with the auth code. Exchange for tokens."""
    kb_id = state
    tenant_id = "common"
    client_id = os.getenv("MS_CLIENT_ID")
    client_secret = os.getenv("MS_CLIENT_SECRET")
    redirect_uri = "http://localhost:4915/api/v1/knowledge-bases/sharepoint/callback"
    
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    
    data = {
        "client_id": client_id,
        "scope": "openid profile email offline_access Files.Read.All Sites.Read.All",
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "client_secret": client_secret,
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data)
        token_data = resp.json()
        
        if "error" in token_data:
            raise HTTPException(status_code=400, detail=token_data.get("error_description"))
            
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        
    # Save tokens to DatabaseConnection
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        import uuid
        
        query = select(DatabaseConnection).where(DatabaseConnection.kb_id == uuid.UUID(kb_id))
        res = await db.execute(query)
        db_conn = res.scalar_one_or_none()
        
        if not db_conn:
            db_conn = DatabaseConnection(
                tenant_id=uuid.UUID("506a8be1-fa85-4441-99c7-5e3c1408e15e"),  # Replace with actual user tenant mapping if needed
                kb_id=uuid.UUID(kb_id),
                db_type="sharepoint",
                connection_params={}
            )
            db.add(db_conn)
            
        # Update with new OAuth tokens while preserving existing config
        current_params = db_conn.connection_params or {}
        
        # If 'credentials' doesn't exist, create it
        if "credentials" not in current_params:
            current_params["credentials"] = {}
            
        current_params["credentials"]["access_token"] = access_token
        current_params["credentials"]["refresh_token"] = refresh_token
        
        # Fetch Microsoft User Info
        import httpx
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient() as client:
            me_res = await client.get("https://graph.microsoft.com/v1.0/me", headers=headers)
            if me_res.status_code == 200:
                me_data = me_res.json()
                current_params["credentials"]["microsoft_user_id"] = me_data.get("id")
                current_params["credentials"]["microsoft_email"] = me_data.get("userPrincipalName")
                
        # In case the service layer looks for it at the root too
        current_params["access_token"] = access_token
        current_params["refresh_token"] = refresh_token
        
        # Reassign to trigger SQLAlchemy JSONB update
        from sqlalchemy.orm.attributes import flag_modified
        db_conn.connection_params = current_params
        flag_modified(db_conn, "connection_params")
        
        await db.commit()

        
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        content="<script>window.close();</script><h2>Successfully connected SharePoint! You can close this window.</h2>"
    )


@router.get("/{kb_id}/gmail/login")
async def gmail_login(kb_id: str):
    import os, urllib.parse
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    redirect_uri = "http://localhost:4915/api/v1/knowledge-bases/gmail/callback"
    state = kb_id
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth"
        f"?client_id={client_id}"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&response_type=code"
        f"&scope=https://www.googleapis.com/auth/gmail.readonly%20https://www.googleapis.com/auth/userinfo.email"
        f"&access_type=offline"
        f"&prompt=consent"
        f"&state={state}"
    )
    return RedirectResponse(auth_url)

@router.get("/gmail/callback")
async def gmail_callback(code: str, state: str):
    import os, httpx, uuid
    kb_id = state
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    redirect_uri = "http://localhost:4915/api/v1/knowledge-bases/gmail/callback"
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data)
        token_data = resp.json()
        if "error" in token_data:
            raise HTTPException(status_code=400, detail=token_data.get("error_description"))
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        query = select(DatabaseConnection).where(DatabaseConnection.kb_id == uuid.UUID(kb_id))
        res = await db.execute(query)
        db_conn = res.scalar_one_or_none()
        if not db_conn:
            db_conn = DatabaseConnection(
                tenant_id=uuid.UUID("506a8be1-fa85-4441-99c7-5e3c1408e15e"),
                kb_id=uuid.UUID(kb_id),
                db_type="gmail",
                connection_params={}
            )
            db.add(db_conn)
        db_conn.connection_params = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret
        }
        await db.commit()
    return {"message": "Successfully connected Gmail! You can now close this window."}


@router.get("/{kb_id}/outlook/login")
async def outlook_login(kb_id: str):
    import os, urllib.parse
    tenant_id = os.getenv("MS_TENANT_ID")
    client_id = os.getenv("MS_CLIENT_ID")
    redirect_uri = "http://localhost:4915/api/v1/knowledge-bases/outlook/callback"
    state = kb_id 
    auth_url = (
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize"
        f"?client_id={client_id}"
        f"&response_type=code"
        f"&redirect_uri={urllib.parse.quote(redirect_uri)}"
        f"&response_mode=query"
        f"&scope=offline_access%20User.Read%20Mail.Read"
        f"&state={state}"
    )
    return RedirectResponse(auth_url)

@router.get("/outlook/callback")
async def outlook_callback(code: str, state: str):
    import os, httpx, uuid
    kb_id = state
    tenant_id = os.getenv("MS_TENANT_ID")
    client_id = os.getenv("MS_CLIENT_ID")
    client_secret = os.getenv("MS_CLIENT_SECRET")
    redirect_uri = "http://localhost:4915/api/v1/knowledge-bases/outlook/callback"
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    data = {
        "client_id": client_id,
        "scope": "offline_access User.Read Mail.Read",
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
        "client_secret": client_secret,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data)
        token_data = resp.json()
        if "error" in token_data:
            raise HTTPException(status_code=400, detail=token_data.get("error_description"))
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        query = select(DatabaseConnection).where(DatabaseConnection.kb_id == uuid.UUID(kb_id))
        res = await db.execute(query)
        db_conn = res.scalar_one_or_none()
        if not db_conn:
            db_conn = DatabaseConnection(
                tenant_id=uuid.UUID("506a8be1-fa85-4441-99c7-5e3c1408e15e"),
                kb_id=uuid.UUID(kb_id),
                db_type="outlook",
                connection_params={}
            )
            db.add(db_conn)
        db_conn.connection_params = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "tenant_id": tenant_id
        }
        await db.commit()
    return {"message": "Successfully connected Outlook! You can now close this window."}


@router.post("/{kb_id}/gmail/register", status_code=200)
async def register_gmail(request: Request, kb_id: str, payload: schemas.GmailRegister):
    try:
        tenant_id, _ = get_tenant_and_user(request)
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            import uuid
            query = select(DatabaseConnection).where(DatabaseConnection.kb_id == uuid.UUID(kb_id))
            res = await db.execute(query)
            db_conn = res.scalar_one_or_none()
            if not db_conn:
                db_conn = DatabaseConnection(
                    tenant_id=uuid.UUID(tenant_id),
                    kb_id=uuid.UUID(kb_id),
                    db_type="gmail",
                    connection_params={"credentials": payload.credentials}
                )
                db.add(db_conn)
            else:
                db_conn.db_type = "gmail"
                db_conn.connection_params = {"credentials": payload.credentials}
            await db.commit()
            return {"success": True, "message": "Gmail credentials registered."}
    except Exception as e:
        logger.error(f"Error in register_gmail: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{kb_id}/gmail/labels", status_code=200)
async def list_gmail_labels(request: Request, kb_id: str):
    try:
        tenant_id, _ = get_tenant_and_user(request)
        from app.utils.formatters import format_success
        return format_success({"items": [
            {"id": "INBOX", "name": "Inbox", "is_folder": True},
            {"id": "SENT", "name": "Sent", "is_folder": True},
            {"id": "STARRED", "name": "Starred", "is_folder": True}
        ]})
    except Exception as e:
        logger.error(f"Error in list_gmail_labels: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{kb_id}/gmail/sync", status_code=200)
async def sync_gmail_api(request: Request, kb_id: str, payload: schemas.GmailSyncRequest):
    try:
        tenant_id, _ = get_tenant_and_user(request)
        
        actual_email = payload.user_email or payload.email
        if not actual_email:
            return {"success": False, "message": "User Email is required"}
            
        payload.user_email = actual_email

        async with AsyncSessionLocal() as db:
            from app.modules.knowledge_bases.service import KnowledgeBaseService
            service = KnowledgeBaseService(db, tenant_id)
            result = await service.sync_gmail_source(kb_id, payload.model_dump())
            return result
    except Exception as e:
        logger.error(f"Error in sync_gmail: {e}")
        from app.utils.formatters import format_error
        return format_error(f"Internal server error: {e}")


@router.post("/{kb_id}/outlook/register", status_code=200)
async def register_outlook(request: Request, kb_id: str, payload: schemas.OutlookRegister):
    try:
        tenant_id, _ = get_tenant_and_user(request)
        async with AsyncSessionLocal() as db:
            from sqlalchemy import select
            import uuid
            query = select(DatabaseConnection).where(DatabaseConnection.kb_id == uuid.UUID(kb_id))
            res = await db.execute(query)
            db_conn = res.scalar_one_or_none()
            if not db_conn:
                db_conn = DatabaseConnection(
                    tenant_id=uuid.UUID(tenant_id),
                    kb_id=uuid.UUID(kb_id),
                    db_type="outlook",
                    connection_params={"credentials": payload.credentials}
                )
                db.add(db_conn)
            else:
                db_conn.db_type = "outlook"
                db_conn.connection_params = {"credentials": payload.credentials}
            await db.commit()
            return {"success": True, "message": "Outlook credentials registered."}
    except Exception as e:
        logger.error(f"Error in register_outlook: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{kb_id}/outlook/folders", status_code=200)
async def list_outlook_folders(request: Request, kb_id: str):
    try:
        tenant_id, _ = get_tenant_and_user(request)
        from app.utils.formatters import format_success
        return format_success({"items": [
            {"id": "inbox", "name": "Inbox", "is_folder": True},
            {"id": "sentitems", "name": "Sent Items", "is_folder": True},
            {"id": "archive", "name": "Archive", "is_folder": True}
        ]})
    except Exception as e:
        logger.error(f"Error in list_outlook_folders: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{kb_id}/outlook/sync", status_code=200)
async def sync_outlook_api(request: Request, kb_id: str, payload: schemas.OutlookSyncRequest):
    try:
        tenant_id, _ = get_tenant_and_user(request)

        actual_email = payload.user_email or payload.email
        if not actual_email:
            return {"success": False, "message": "User Email is required"}
            
        if payload.folder_ids:
            payload.folder_id = payload.folder_ids[0]
            
        payload.user_email = actual_email

        async with AsyncSessionLocal() as db:
            from app.modules.knowledge_bases.service import KnowledgeBaseService
            service = KnowledgeBaseService(db, tenant_id)
            result = await service.sync_outlook_source(kb_id, payload.model_dump())
            return result
    except Exception as e:
        logger.error(f"Error in sync_outlook: {e}")
        from app.utils.formatters import format_error
        return format_error(f"Internal server error: {e}")


