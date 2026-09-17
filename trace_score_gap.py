import asyncio
import logging
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase
from app.core.embeddings import EmbeddingGenerator
from sqlalchemy import select

# Configure basic logging to see output
logging.basicConfig(level=logging.INFO)

async def run_trace():
    print("Fetching Knowledge Bases from DB...")
    async with AsyncSessionLocal() as session:
        stmt = select(KnowledgeBase.id, KnowledgeBase.name, KnowledgeBase.summary_embedding).where(
            KnowledgeBase.is_active == True,
            KnowledgeBase.summary_embedding != None
        )
        result = await session.execute(stmt)
        kbs = result.all()
    
    if not kbs:
        print("No KBs with summary embeddings found.")
        return

    print(f"Found {len(kbs)} KBs with embeddings.")
    
    # We will simulate a conversation switching topics
    queries = [
        # PDF A Queries (e.g. Apple 10-K)
        "What is the total amount of unrecognized tax benefits?",
        "What portion of this would impact the company's effective tax rate if recognized?", # ambiguous follow-up
        
        # Topic Switch to PDF B (e.g. some HR Policy or different company 10-K)
        "What are the employee benefits and stock options?",
        "What is the vacation policy?",
        
        # Topic Switch back to PDF A
        "What is the effective interest rate on the Notes due 2026 for Apple?"
    ]

    for q in queries:
        print(f"\n=========================================")
        print(f"QUERY: '{q}'")
        emb_result = await EmbeddingGenerator.generate_embedding_with_usage(q)
        q_emb = emb_result[0]

        scores = []
        for kb in kbs:
            score = EmbeddingGenerator.cosine_similarity(q_emb, kb.summary_embedding)
            scores.append((kb.name, kb.id, score))
        
        # Sort descending by score
        scores.sort(key=lambda x: x[2], reverse=True)
        
        print("Top 3 Matches:")
        for i in range(min(3, len(scores))):
            print(f"  {i+1}. {scores[i][0]} (ID: {scores[i][1]}) - Score: {scores[i][2]:.3f}")
            
        if len(scores) > 1:
            gap = scores[0][2] - scores[1][2]
            print(f"-> GAP between Top 1 and Top 2: {gap:.3f}")

if __name__ == "__main__":
    asyncio.run(run_trace())
