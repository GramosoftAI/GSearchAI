import asyncio
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase
from app.core.embeddings import EmbeddingGenerator
from sqlalchemy import select
import logging

logging.basicConfig(level=logging.WARNING)

async def run():
    async with AsyncSessionLocal() as session:
        stmt = select(KnowledgeBase.id, KnowledgeBase.name, KnowledgeBase.summary_embedding).where(
            KnowledgeBase.is_active == True,
            KnowledgeBase.summary_embedding != None
        )
        kbs = (await session.execute(stmt)).all()
        
    apple_kb = next((k for k in kbs if "apple" in k.name.lower()), None)
    if not apple_kb: return
    
    queries = [
        "What were the sales figures?", 
        "Tell me about the revenues.",
        "What is the total revenue?",
        "When does the period end?"
    ]
    
    for q in queries:
        q_emb = (await EmbeddingGenerator.generate_embedding_with_usage(q))[0]
        scores = [(k.name, k.id, EmbeddingGenerator.cosine_similarity(q_emb, k.summary_embedding)) for k in kbs]
        scores.sort(key=lambda x: x[2], reverse=True)
        
        top = scores[0]
        apple_score = next((s for n, i, s in scores if i == apple_kb.id), 0)
        gap = top[2] - apple_score
        
        print(f"Q: {q}")
        print(f"Top: {top[0]} ({top[2]:.3f})")
        print(f"Pinned (Apple): {apple_kb.name} ({apple_score:.3f})")
        print(f"Gap: {gap:.3f}\n")

asyncio.run(run())
