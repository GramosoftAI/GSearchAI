import asyncio
import json
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.modules.rag.service import RAGService
from app.core.config import get_settings

settings = get_settings()

async def debug_evaluate():
    with open('golden_set_v1.json', 'r') as f:
        questions = json.load(f)[:3]
        
    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    async with async_session() as db:
        res = await db.execute(text("SELECT id, tenant_id FROM agents LIMIT 1"))
        row = res.fetchone()
        if not row:
            print("No agents found in DB!")
            return
            
        agent_id, tenant_id = row
        agent_id = str(agent_id)
        tenant_id = str(tenant_id)
        
        # Get kb_ids for the agent
        res2 = await db.execute(text(f"SELECT id, name FROM knowledge_bases WHERE agent_id = '{agent_id}'"))
        kb_info = {str(r[0]): r[1] for r in res2.fetchall()}
        kb_ids = list(kb_info.keys())
        
        print(f"Debug Eval - Agent: {agent_id}, Tenant: {tenant_id}")
        print(f"Agent KBs: {kb_info}")
        
        rag_service = RAGService(db=db, tenant_id=tenant_id)
        
        for idx, q in enumerate(questions):
            print(f"\n[{idx+1}] Query: '{q['query']}'")
            print(f"Expected Source: '{q['expected_source']}'")
            try:
                response = await rag_service.generate_answer(
                    query=q['query'],
                    agent_id=agent_id,
                    kb_id=kb_ids,
                    user_id=None,
                    top_k=5,
                    max_depth=2,
                    reasoning_enabled=False,
                    memory_enabled=False,
                    target_kb_id=None
                )
                
                if "error" in response:
                    print(f"ERROR RETURNED: {response['error']}")
                else:
                    sources = response.get('sources', [])
                    print(f"Returned {len(sources)} sources:")
                    for i, src in enumerate(sources):
                        # src is a dict based on RAGQueryResponse schema, print metadata/source fields
                        print(f"  {i+1}. Source: {src.get('source')} | File: {src.get('metadata', {}).get('source')} | Score: {src.get('score')} | Chunk: {src.get('chunk_id')} | Text[:50]: {str(src.get('text'))[:50]}")
                        
            except Exception as e:
                import traceback
                print(f"EXCEPTION: {str(e)}")
                traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug_evaluate())
