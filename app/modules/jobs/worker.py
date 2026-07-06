import logging
import asyncio
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

logger = logging.getLogger(__name__)

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
        async with AsyncSessionLocal() as db:
            # Important: set tenant context!
            await db.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                {"tenant_id": str(tenant_id)}
            )
            
            job_service = JobService(db, tenant_id)
            
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
                
            # Classify Document Type
            await job_service.update_job_progress(job_id, status="processing", progress=15, current_step="Classifying Document Type")
            llm_client = DeepInfraLLMClient()
            prompt = f"Analyze the first 2000 characters of this document and classify its type. Valid types are: PRICE_LIST, INVOICE, QUOTATION, PURCHASE_ORDER, STOCK_REPORT, FINANCIAL_STATEMENT, GENERAL. Return ONLY the type string, nothing else.\n\nDOCUMENT START:\n{document_text[:2000]}"
            document_type = await llm_client.generate(prompt=prompt, system_prompt="You are a document classifier. Return only the exact category string.", temperature=0.0, max_tokens=15)
            document_type = document_type.strip()
            if document_type not in ["PRICE_LIST", "INVOICE", "QUOTATION", "PURCHASE_ORDER", "STOCK_REPORT", "FINANCIAL_STATEMENT", "GENERAL"]:
                document_type = "GENERAL"
            logger.info(f"Classified document as: {document_type}")
                
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
                s3_path=s3_url
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
            
            logger.info(f"Job {job_id}: Starting embedding and graph ingestion for {kb_id}")
            ingest_result = await kb_service.ingest_document(
                kb_id, 
                document_text, 
                source=s3_url, 
                s3_path=s3_url,
                parsed_path=parsed_url,
                structured_records=structured_records
            )


            
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
