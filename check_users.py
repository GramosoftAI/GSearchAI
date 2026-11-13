import asyncio
import uuid
import sys
sys.path.insert(0, r"c:\Users\hp\Desktop\GSOFT\RAG\GSearchAI")

from app.core.database import AsyncSessionLocal
from app.modules.database_knowledgebase.services.service import DatabaseKnowledgebaseService
from app.modules.database_knowledgebase.retrieval.grounded_entity_resolver import GroundedEntityResolver

async def check():
    async with AsyncSessionLocal() as session:
        service = DatabaseKnowledgebaseService(db=session, tenant_id='2b41fa8c-9c12-491d-8199-a75292e683ec')
        entity = await service.repo.get_by_id(uuid.UUID('d456830e-f44a-40d0-a65a-c91a0a91b3dc'))
        config = service.secrets.decrypt_credentials(entity.encrypted_credentials)
        users = await GroundedEntityResolver.get_all_users(conn_config=config, kb_id=str(entity.id))
        print(f'Fetched {len(users)} users.')
        term, cands = GroundedEntityResolver.find_user_candidates("What was Arun's progress yesterday?", users)
        print('Matched term:', term, 'Candidates:', cands)

if __name__ == '__main__':
    asyncio.run(check())
