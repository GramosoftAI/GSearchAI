import logging
import asyncio
import time
import re
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import uuid

from app.core.database import AsyncSessionLocal
from .service import JobService
from app.modules.knowledge_bases.service import KnowledgeBaseService
from app.modules.agents.service import AgentService
from app.modules.knowledge_bases.schemas import KBCreate
from app.core.pdf_extractor import PDFExtractor
from app.core.excel_extractor import ExcelExtractor
from app.core.llm.deepinfra_llm import DeepInfraLLMClient
from app.modules.knowledge_bases.services.excel_ingestion_service import ExcelIngestionService

logger = logging.getLogger(__name__)


def classify_document_fast(text: str) -> str:
    """
    Fast regex-based document classifier. Replaces slow LLM classification.
    Analyzes the first 3000 characters for keyword patterns.
    """
    sample = text[:3000].lower()
    
    # Score each type by keyword matches
    patterns = {
        "PRICE_LIST": [r'\bprice\s*list\b', r'\bunit\s*price\b', r'\brate\s*card\b', r'\bmsrp\b', r'\blist\s*price\b'],
        "INVOICE": [r'\binvoice\b', r'\bbill\s*to\b', r'\binv[\.\s\-]?no\b', r'\btax\s*invoice\b', r'\bdue\s*date\b', r'\bamount\s*due\b'],
        "QUOTATION": [r'\bquotation\b', r'\bquote\b', r'\bestimate\b', r'\bproforma\b', r'\bvalidity\b'],
        "PURCHASE_ORDER": [r'\bpurchase\s*order\b', r'\bp\.?o\.?\s*(?:no|number)\b', r'\bship\s*to\b', r'\border\s*(?:no|number)\b'],
        "STOCK_REPORT": [r'\bstock\s*report\b', r'\binventory\b', r'\bsku\b', r'\bquantity\s*on\s*hand\b', r'\bwarehouse\b'],
        "FINANCIAL_STATEMENT": [r'\bbalance\s*sheet\b', r'\bincome\s*statement\b', r'\bcash\s*flow\b', r'\btotal\s*(?:revenue|assets|liabilities)\b', r'\bearnings?\s*per\s*share\b', r'\bfiscal\s*(?:year|quarter)\b', r'\bnet\s*income\b', r'\bgross\s*(?:profit|margin)\b', r'\boperating\s*(?:income|expenses?)\b'],
    }
    
    best_type = "GENERAL"
    best_score = 0
    
    for doc_type, regexes in patterns.items():
        score = sum(1 for r in regexes if re.search(r, sample))
        if score > best_score and score >= 2:  # Need at least 2 keyword matches
            best_score = score
            best_type = doc_type
    
    return best_type

async def run_pdf_ingestion_job(
    tenant_id: str,
    user_id: str,
    agent_id: str,
    job_id: str,
    filename: str,
    content: bytes
):
    """
    Background task for extracting and ingesting a PDF.
    Updates the ProcessingJob table with progress.
    """
    try:
        # Calculate file hash
        import hashlib
        file_hash = hashlib.sha256(content).hexdigest()

        async with AsyncSessionLocal() as db:
            # Important: set tenant context!
            await db.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                {"tenant_id": str(tenant_id)}
            )
            
            job_service = JobService(db, tenant_id)
            
            # Check database for duplicate hash
            from sqlalchemy import select
            from app.modules.knowledge_bases.models import KnowledgeBase
            import uuid
            
            stmt = select(KnowledgeBase).where(
                KnowledgeBase.tenant_id == uuid.UUID(tenant_id),
                KnowledgeBase.file_hash == file_hash,
                KnowledgeBase.is_active == True
            )
            res = await db.execute(stmt)
            existing_kb = res.scalars().first()
            if existing_kb:
                logger.info(f"Job {job_id}: Duplicate file hash {file_hash} detected in run_pdf_ingestion_job. Skipping processing and linking to existing KB.")
                await job_service.update_job_progress(
                    job_id,
                    status="completed",
                    progress=100,
                    current_step="Complete",
                    kb_id=str(existing_kb.id)
                )
                return

            is_spreadsheet = filename.lower().endswith(('.csv', '.xls', '.xlsx'))
            
            # Update status to processing
            step_name = "Starting Spreadsheet Extraction" if is_spreadsheet else "Starting PDF Extraction (OCR)"
            await job_service.update_job_progress(job_id, status="processing", progress=5, current_step=step_name)
            
            # Step 1: Document Extraction
            logger.info(f"Job {job_id}: Starting extraction for {filename}")
            try:
                table_rows = []
                dataset_schema = None
                structured_records = None
                
                if filename.lower().endswith(('.csv', '.xls', '.xlsx')):
                    document_text, table_rows, dataset_schema = await ExcelExtractor.extract(
                        file_bytes=content,
                        filename=filename,
                    )
                    if table_rows:
                        from app.core.structured_chunker import StructuredRecord
                        columns = list(dataset_schema.get("columns", {}).keys()) if dataset_schema else []
                        structured_records = [
                            StructuredRecord(
                                document_type="spreadsheet",
                                source_file=filename,
                                group_name="Sheet1", # Simplified for now
                                row_index=row.get("row_index", i),
                                columns=columns,
                                values=row.get("row_data", {})
                            )
                            for i, row in enumerate(table_rows)
                        ]
                else:
                    document_text = await PDFExtractor.extract(
                        pdf_bytes=content,
                        filename=filename,
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                    )
            except Exception as e:
                logger.error(f"Job {job_id}: Extraction failed: {e}")
                await job_service.update_job_progress(job_id, status="failed", progress=5, current_step="Extraction", error_message=f"Failed to extract text: {str(e)}")
                return
                
            if not document_text.strip():
                err_step = "Spreadsheet Extraction" if is_spreadsheet else "PDF Extraction"
                err_msg = "Spreadsheet appears to be empty or contains no extractable text." if is_spreadsheet else "PDF appears to be empty or contains no extractable text."
                await job_service.update_job_progress(job_id, status="failed", progress=5, current_step=err_step, error_message=err_msg)
                return
                
            # Classify Document Type (Fast regex classifier - no LLM call needed)
            await job_service.update_job_progress(job_id, status="processing", progress=15, current_step="Classifying Document Type")
            t_classify = time.time()
            document_type = classify_document_fast(document_text)
            logger.info(f"Job {job_id}: Classified document as: {document_type} (took {time.time() - t_classify:.2f}s)")
                
            await job_service.update_job_progress(job_id, status="processing", progress=25, current_step="Extracting Structured Tables")
            
            # Step 1.5: Table Extraction (PDF only)
            if not filename.lower().endswith(('.csv', '.xls', '.xlsx')):
                logger.info(f"Job {job_id}: Extracting structured tables")
                table_rows = await PDFExtractor.extract_tables_to_json(pdf_bytes=content)
            
            await job_service.update_job_progress(job_id, status="processing", progress=40, current_step="Creating Knowledge Base Entry")

            # Step 2: Create KB Entry
            from app.core.s3 import S3StorageService
            s3_service = S3StorageService()
            s3_url = s3_service.get_s3_url(str(tenant_id), filename)

            kb_service = KnowledgeBaseService(db, tenant_id)
            kb_name = f"Spreadsheet: {filename}" if is_spreadsheet else f"PDF: {filename}"
            kb_description = f"Automated spreadsheet upload source (Table extraction)" if is_spreadsheet else f"Automated PDF upload source (Gdocz extraction)"
            kb_source = "spreadsheet_upload" if is_spreadsheet else "pdf_upload"

            kb_request = KBCreate(
                name=kb_name,
                description=kb_description,
                agent_id=uuid.UUID(agent_id),
                source=kb_source,
                document_type=document_type,
                dataset_schema=dataset_schema,
                s3_path=s3_url,
                file_hash=file_hash
            )
            
            kb_result = await kb_service.create_knowledge_base(user_id, kb_request)
            if not kb_result.get("success"):
                await job_service.update_job_progress(job_id, status="failed", progress=45, current_step="Creating Knowledge Base Entry", error_message="Failed to create Knowledge Base tracking row in database.")
                return
                
            kb_id = str(kb_result["data"]["kb"].id)
            await job_service.update_job_progress(job_id, status="processing", progress=45, current_step="Knowledge Base Created", kb_id=kb_id)
            
            # Step 2.5: Save Table Rows
            if table_rows:
                await kb_service.save_table_rows(kb_id, table_rows)
            
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

                parsed_url = await asyncio.to_thread(
                    s3_service.store_parsed_content,
                    str(tenant_id),
                    str(kb_id),
                    raw_content,
                    content_type
                )
            except Exception as e:
                logger.error(f"Job {job_id}: Failed to store parsed content in S3: {e}")

            # Step 3: Ingest Document (Chunking + Embeddings + Neo4j)
            await job_service.update_job_progress(job_id, status="processing", progress=60, current_step="Chunking and Generating Embeddings")
            
            t_ingest_start = time.time()
            logger.info(f"Job {job_id}: Starting embedding and graph ingestion for {kb_id}")
            ingest_result = await kb_service.ingest_document(
                kb_id, 
                document_text, 
                source=s3_url, 
                s3_path=s3_url,
                parsed_path=parsed_url,
                structured_records=structured_records
            )

            t_ingest_end = time.time()
            logger.info(f"Job {job_id}: Ingestion completed in {t_ingest_end - t_ingest_start:.1f}s")
            
            if not ingest_result.get("success"):
                error_msg = ingest_result.get("error", "Unknown ingestion error")
                await job_service.update_job_progress(job_id, status="failed", progress=80, current_step="Generating Embeddings", error_message=error_msg)
                return
                
            # Success!
            await job_service.update_job_progress(job_id, status="completed", progress=100, current_step="Complete")
            logger.info(f"Job {job_id}: Successfully completed!")

    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error: {e}", exc_info=True)
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                    {"tenant_id": str(tenant_id)}
                )
                job_service = JobService(db, tenant_id)
                await job_service.update_job_progress(job_id, status="failed", error_message=f"Internal Server Error: {str(e)}")
        except Exception as rollback_err:
            logger.error(f"Job {job_id}: Failed to update job status on error: {rollback_err}")


async def run_excel_ingestion_job(
    tenant_id: str,
    user_id: str,
    agent_id: str,
    job_id: str,
    filename: str,
    content: bytes
):
    """
    Background task for extracting and ingesting an Excel/CSV file using ESDIP v3.
    """
    try:
        import hashlib
        file_hash = hashlib.sha256(content).hexdigest()

        async with AsyncSessionLocal() as db:
            await db.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                {"tenant_id": str(tenant_id)}
            )
            
            job_service = JobService(db, tenant_id)
            kb_service = KnowledgeBaseService(db, tenant_id)
            
            from sqlalchemy import select
            from app.modules.knowledge_bases.models import KnowledgeBase
            import uuid
            
            stmt = select(KnowledgeBase).where(
                KnowledgeBase.tenant_id == uuid.UUID(tenant_id),
                KnowledgeBase.file_hash == file_hash,
                KnowledgeBase.is_active == True
            )
            res = await db.execute(stmt)
            existing_kb = res.scalars().first()
            
            if existing_kb:
                logger.info(f"Job {job_id}: Duplicate file hash {file_hash} detected. Skipping processing.")
                await job_service.update_job_progress(
                    job_id, status="completed", progress=100, current_step="Complete", kb_id=str(existing_kb.id)
                )
                return

            await job_service.update_job_progress(job_id, status="processing", progress=5, current_step="Starting ESDIP Ingestion")
            
            # Step 1: Create KB Entry First
            from app.core.s3 import S3StorageService
            s3_service = S3StorageService()
            s3_url = s3_service.get_s3_url(str(tenant_id), filename)

            kb_request = KBCreate(
                name=f"Spreadsheet: {filename}",
                description="Automated spreadsheet upload (ESDIP Extracted)",
                agent_id=uuid.UUID(agent_id),
                source="spreadsheet_upload",
                document_type="STRUCTURED_DATA",
                s3_path=s3_url,
                file_hash=file_hash
            )
            
            kb_result = await kb_service.create_knowledge_base(user_id, kb_request)
            if not kb_result.get("success"):
                await job_service.update_job_progress(job_id, status="failed", progress=10, current_step="Creating Knowledge Base", error_message="Failed to create Knowledge Base tracking row in database.")
                return
                
            kb_id = str(kb_result["data"]["kb"].id)
            await job_service.update_job_progress(job_id, status="processing", progress=20, current_step="Knowledge Base Created", kb_id=kb_id)
            
            # Step 2: Run ESDIP Service
            logger.info(f"Job {job_id}: Invoking ExcelIngestionService for KB {kb_id}")
            await job_service.update_job_progress(job_id, status="processing", progress=50, current_step="Running ESDIP Inference")
            
            ingestion_service = ExcelIngestionService(db, tenant_id)
            
            result = await ingestion_service.ingest_file(
                kb_id=kb_id,
                file_bytes=content,
                filename=filename,
                mime_type=None,
                source=s3_url
            )
            
            if not result.get("success"):
                await job_service.update_job_progress(job_id, status="failed", progress=80, current_step="ESDIP Failure", error_message=result.get("error", "Unknown ingestion error"))
                return
                
            await db.commit()
                
            # Success!
            await job_service.update_job_progress(job_id, status="completed", progress=100, current_step="Complete")
            logger.info(f"Job {job_id}: ESDIP successfully completed!")

    except Exception as e:
        logger.error(f"Job {job_id}: Unexpected error in Excel job: {e}", exc_info=True)
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                    {"tenant_id": str(tenant_id)}
                )
                job_service = JobService(db, tenant_id)
                await job_service.update_job_progress(job_id, status="failed", error_message=f"Internal Server Error: {str(e)}")
        except Exception as rollback_err:
            logger.error(f"Job {job_id}: Failed to update job status on error: {rollback_err}")
