import asyncio
import json
import uuid
from app.modules.rag.engines.vector_engine import VectorEngine
from app.core.neo4j_repository import Neo4jRepository
from app.core.config import get_settings

settings = get_settings()

async def evaluate():
    with open('golden_set_v1.json', 'r') as f:
        questions = json.load(f)
    
    tenant_id = str(uuid.uuid4())
    neo4j_repo = Neo4jRepository(tenant_id)
    engine = VectorEngine(tenant_id=tenant_id, neo4j_repo=neo4j_repo)
    
    total = len(questions)
    recall_at_5 = 0
    mrr = 0.0
    
    results = []
    
    for idx, q in enumerate(questions):
        print(f"Evaluating {idx+1}/{total}: {q['query']}")
        try:
            chunks = await engine.search(
                query=q['query'],
                top_k=5,
                agent_id=None
            )
            
            found_rank = -1
            for r, chunk in enumerate(chunks):
                source = chunk.metadata.get('source', '') if chunk.metadata else getattr(chunk, 'source', '')
                if source and q['expected_source'].lower() in str(source).lower():
                    found_rank = r + 1
                    break
            
            if found_rank > 0:
                recall_at_5 += 1
                mrr += 1.0 / found_rank
            
            results.append({
                "id": q['id'],
                "query": q['query'],
                "expected": q['expected_source'],
                "found_rank": found_rank
            })
            
        except Exception as e:
            print(f"Error evaluating '{q['query']}': {e}")
            results.append({"id": q['id'], "error": str(e)})
            
    final_mrr = mrr / total if total > 0 else 0
    final_recall = (recall_at_5 / total) * 100 if total > 0 else 0
    
    print(f"\n--- EVALUATION RESULTS ---")
    print(f"Recall@5: {final_recall:.2f}%")
    print(f"MRR: {final_mrr:.4f}")
    
    with open('eval_results_v1.json', 'w') as f:
        json.dump({
            "metrics": {"recall_at_5": final_recall, "mrr": final_mrr},
            "details": results
        }, f, indent=2)

if __name__ == "__main__":
    asyncio.run(evaluate())
