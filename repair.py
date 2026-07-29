import sys

with open('app/modules/jobs/worker.py', 'r') as f:
    lines = f.readlines()

# Find the end of run_excel_ingestion_job
end_idx = 0
for i, line in enumerate(lines):
    if 'logger.error(f"Job {job_id}: Unexpected error in Excel job: {e}", exc_info=True)' in line:
        end_idx = i
        break

if end_idx == 0:
    print('Could not find end of Excel job')
    sys.exit(1)

new_lines = lines[:end_idx+1]
excel_error_block = """        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                    {"tenant_id": str(tenant_id)}
                )
                job_service = JobService(db, tenant_id)
                await job_service.update_job_progress(job_id, status="failed", error_message=f"Internal Server Error: {str(e)}")
        except Exception as rollback_err:
            logger.error(f"Job {job_id}: Failed to update job status on error: {rollback_err}")

async def run_url_ingestion_job(
    tenant_id: str,
    user_id: str,
    agent_id: str,
    job_id: str,
    url: str,
    crawl_type: str
):
    \"\"\"
    Background task for extracting and ingesting a URL.
    Updates the ProcessingJob table with progress.
    \"\"\"
    kb_id = None
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                text("SELECT set_config('app.current_tenant', :tenant_id, false)"),
                {"tenant_id": str(tenant_id)}
            )
            job_service = JobService(db, tenant_id)
            
            await job_service.update_job_progress(job_id, status="processing", progress=5, current_step="Crawling URL")
            
            # Step 1: Crawl URL
            from app.modules.knowledge_bases.services.scraper_service import ScraperService
            logger.info(f"Job {job_id}: Starting crawl for {url}")
            try:
                documents = await ScraperService.extract_website_content(
                    url=url,
                    crawl_type=crawl_type,
                    proxy_mode="default"
                )
                if not documents:
                    await job_service.update_job_progress(job_id, status="failed", progress=10, current_step="Crawling URL", error_message="Failed to extract content from URL.")
                    return
                
                document_text = ""
                for doc in documents:
                    if len(documents) > 1:
                        document_text += f"\\n\\n# SOURCE: {doc['source']}\\n\\n"
                    document_text += doc["content"]
                document_text = document_text.strip()
            except Exception as e:
                logger.error(f"Job {job_id}: Crawl failed: {e}")
                await job_service.update_job_progress(job_id, status="failed", progress=10, current_step="Crawling URL", error_message=f"Failed to crawl URL: {str(e)}")
                return

            if not document_text:
                await job_service.update_job_progress(job_id, status="failed", progress=10, current_step="Crawling URL", error_message="URL returned empty content.")
                return

            await job_service.update_job_progress(job_id, status="processing", progress=30, current_step="Creating Knowledge Base Entry")

            # Step 2: Create KB Entry
            kb_service = KnowledgeBaseService(db, tenant_id)
            kb_request = KBCreate(
                name=f"Web: {url}",
                description="Crawled web source",
                agent_id=uuid.UUID(agent_id),
                source="url_crawl"
            )
            
            kb_result = await kb_service.create_knowledge_base(user_id, kb_request)
            if not kb_result.get("success"):
                await job_service.update_job_progress(job_id, status="failed", progress=40, current_step="Creating Knowledge Base Entry", error_message="Failed to create Knowledge Base tracking row in database.")
                return
                
            kb_id = str(kb_result["data"]["kb"].id)
            await job_service.update_job_progress(job_id, status="processing", progress=40, current_step="Knowledge Base Created", kb_id=kb_id)
            
            # Step 3: Ingest Document (Chunking + Embeddings + Neo4j)
            await job_service.update_job_progress(job_id, status="processing", progress=60, current_step="Chunking and Graph Extraction")
            
            ingest_result = await kb_service.ingest_document(
                kb_id, 
                document_text, 
            )

            if not ingest_result.get("success"):
                error_msg = ingest_result.get("error", "Unknown ingestion error")
                await job_service.update_job_progress(job_id, status="failed", progress=80, current_step="Extracting Knowledge", error_message=error_msg)
                try:
                    logger.info(f"Job {job_id}: Ingestion failed. Cleaning up KnowledgeBase {kb_id}.")
                    await kb_service.delete_kb(kb_id, user_id=user_id)
                except Exception as cleanup_err:
                    logger.error(f"Job {job_id}: Failed to clean up KnowledgeBase {kb_id} after ingestion failure: {cleanup_err}")
                return
                
            # Success!
            await job_service.update_job_progress(job_id, status="completed", progress=100, current_step="Complete")
            logger.info(f"Job {job_id}: URL ingestion successfully completed!")

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
                if kb_id:
                    try:
                        kb_service = KnowledgeBaseService(db, tenant_id)
                        await kb_service.delete_kb(kb_id, user_id=user_id)
                    except Exception as cleanup_err:
                        pass
        except Exception as rollback_err:
            pass
"""

with open('app/modules/jobs/worker.py', 'w') as f:
    f.writelines(new_lines)
    f.write(excel_error_block)

print('Successfully repaired worker.py')
