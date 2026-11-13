import asyncio, uuid
from app.modules.database_knowledgebase.knowledge.adapters.phase1_adapter import Phase1Adapter
from app.core.database import AsyncSessionLocal

async def check():
    kb_id = uuid.UUID('d456830e-f44a-40d0-a65a-c91a0a91b3dc')
    tenant_id = uuid.UUID('2b41fa8c-9c12-491d-8199-a75292e683ec')
    async with AsyncSessionLocal() as s:
        adapter = Phase1Adapter(s)
        async with adapter.open_readonly_connection(tenant_id, kb_id) as conn:
            res = await conn.fetch("SELECT id, login, firstname, lastname FROM users WHERE LOWER(login) LIKE '%vishnu%' OR LOWER(firstname) LIKE '%vishnu%' OR LOWER(lastname) LIKE '%vishnu%'")
            print('Users with vishnu:', [dict(r) for r in res])

asyncio.run(check())
