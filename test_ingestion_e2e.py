import asyncio, uuid, logging
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.services.scraper_service import ScraperService
from app.modules.knowledge_bases.service import KnowledgeBaseService

logging.basicConfig(level=logging.INFO)

async def test_e2e():
    tenant_id = 'b91f23d9-7127-420d-acc9-fc420b46bf9e'
    # Mix of valid and invalid/slow URLs to test timeout
    urls = ['https://gramosoft.tech/', 'https://example.com/', 'https://nonexistent.gramosoft.tech/slow']
    
    print('Scraping...')
    docs, failed = await ScraperService.scrape_selected_urls(urls)
    print(f'Scraping done. {len(docs)} succeeded, {len(failed)} failed.')
    
    if not docs:
        print('No docs!')
        return
    
    kb_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as db:
        # We need a KB record for ingest_document to work.
        from app.modules.knowledge_bases.models import KnowledgeBase
        kb = KnowledgeBase(id=uuid.UUID(kb_id), tenant_id=uuid.UUID(tenant_id), name='Test E2E URLs')
        db.add(kb)
        await db.commit()
        
        kb_service = KnowledgeBaseService(db, tenant_id)
        print('Ingesting...')
        res = await kb_service.ingest_document(kb_id, document_text='', source='url_list', documents_list=docs)
        print('Ingestion Result:', res)
        
        # Check chunks
        from sqlalchemy import text
        c_res = await db.execute(text(f"SELECT text, metadata_json FROM document_table_rows WHERE kb_id = '{kb_id}' LIMIT 5"))
        print('\n--- Chunks ---')
        for r in c_res.fetchall():
            print(r.text[:100], '| META:', r.metadata_json)

asyncio.run(test_e2e())
