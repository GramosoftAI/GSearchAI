import asyncio
import json
import urllib.parse
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.modules.rag.service import RAGService
from app.core.config import get_settings

settings = get_settings()

def extract_filename(url_or_path: str) -> str:
    if not url_or_path:
        return ""
    # url decode
    decoded = urllib.parse.unquote(url_or_path)
    # get basename
    basename = decoded.split('/')[-1].split('\\')[-1]
    return basename.lower()

async def evaluate():
    with open('golden_set_v1.json', 'r') as f:
        questions = json.load(f)
        
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
        res2 = await db.execute(text(f"SELECT id FROM knowledge_bases WHERE agent_id = '{agent_id}'"))
        kb_ids = [str(r[0]) for r in res2.fetchall()]
        
        rag_service = RAGService(db=db, tenant_id=tenant_id)
        
        total = len(questions)
        recall_at_5 = 0
        mrr = 0.0
        results = []
        
        for idx, q in enumerate(questions):
            print(f"Evaluating {idx+1}/{total}: {q['query']}")
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
                
                sources = response.get('sources', [])
                found_rank = -1
                expected = q['expected_source'].lower()
                
                for r, src in enumerate(sources[:5]):
                    src_val = src.get('source', '') or ''
                    file_name = extract_filename(str(src_val))
                    
                    # also check metadata if source is something generic like "DocumentChunk 47"
                    meta = src.get('metadata', {}) or {}
                    meta_src = meta.get('source', '') or ''
                    meta_file = extract_filename(str(meta_src))
                    
                    if expected in file_name or expected in meta_file or expected in str(src_val).lower():
                        found_rank = r + 1
                        break
                        
                if found_rank > 0:
                    recall_at_5 += 1
                    mrr += 1.0 / found_rank
                    
                results.append({
                    "id": q['id'],
                    "query": q['query'],
                    "expected": expected,
                    "found_rank": found_rank,
                    "top_source": str(sources[0].get('source')) if sources else "None"
                })
                
            except Exception as e:
                print(f"Error evaluating '{q['query']}': {e}")
                results.append({"id": q['id'], "error": str(e)})
                
        final_mrr = mrr / total if total > 0 else 0
        final_recall = (recall_at_5 / total) * 100 if total > 0 else 0
        
        print(f"\n--- EVALUATION RESULTS ---")
        print(f"Recall@5: {final_recall:.2f}%")
        print(f"MRR: {final_mrr:.4f}")
        
        with open('eval_results_v2.json', 'w') as f:
            json.dump({
                "metrics": {"recall_at_5": final_recall, "mrr": final_mrr},
                "details": results
            }, f, indent=2)

if __name__ == "__main__":
    asyncio.run(evaluate())
