import asyncio
from app.core.database import AsyncSessionLocal
from sqlalchemy import text
from app.modules.jobs.worker import run_pdf_ingestion_job
import uuid
import logging
from unittest.mock import patch

logging.basicConfig(level=logging.INFO)

async def mock_fail_generate_kb_summary_embedding(*args, **kwargs):
    raise Exception("INTENTIONAL FAILURE to verify non-blocking behavior")

async def main():
    async with AsyncSessionLocal() as session:
        res = await session.execute(text('SELECT id FROM tenants LIMIT 1'))
        tenant_id = str(res.scalar_one())
        print(f'Using tenant {tenant_id}')
        
        res_u = await session.execute(text('SELECT id FROM users LIMIT 1'))
        user_id = str(res_u.scalar_one())
        
        res_a = await session.execute(text('SELECT id FROM agents LIMIT 1'))
        agent_id = str(res_a.scalar_one())
        
        job_id = str(uuid.uuid4())
        filename = 'test_ingestion_fix_fail.csv'
        content = b'col1,col2\nfail1,fail2\nfail3,fail4'
        
        print('Running ingestion with mocked summary failure...')
        with patch('app.modules.knowledge_bases.kb_summary.generate_kb_summary_embedding', side_effect=mock_fail_generate_kb_summary_embedding):
            await run_pdf_ingestion_job(tenant_id, user_id, agent_id, job_id, filename, content)
        
        # Now verify
        res2 = await session.execute(text(f"SELECT summary_embedding IS NULL FROM knowledge_bases WHERE name = 'Spreadsheet: {filename}'"))
        is_null = res2.scalar_one()
        print(f'Is summary_embedding null (expected True)? {is_null}')
        
        # Verify chunks exist
        res3 = await session.execute(text(f"SELECT COUNT(*) FROM document_table_rows WHERE kb_id = (SELECT id FROM knowledge_bases WHERE name = 'Spreadsheet: {filename}')"))
        count = res3.scalar_one()
        print(f'Chunk/row count (expected > 0): {count}')

asyncio.run(main())
