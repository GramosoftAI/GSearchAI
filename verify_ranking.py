"""
Post-fix verification: check that the new chunks rank correctly.
"""
import asyncio
import numpy as np
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase, DocumentChunk
from app.core.embeddings import EmbeddingGenerator

async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(KnowledgeBase).filter(KnowledgeBase.name.ilike('%20071231X02009.pdf%'))
        )
        kb = res.scalar_one_or_none()

        res = await db.execute(select(DocumentChunk).filter(DocumentChunk.kb_id == kb.id))
        chunks = res.scalars().all()

        query = "What was the probable cause of the Beech A23 airplane accident in Death Valley, CA on November 29, 2007?"
        query_embedding = await EmbeddingGenerator.generate_embedding(query)

        similarities = []
        for c in chunks:
            if c.embedding is not None and len(c.embedding) > 0:
                q = np.array(query_embedding)
                e = np.array(c.embedding)
                cos_sim = float(np.dot(q, e) / (np.linalg.norm(q) * np.linalg.norm(e)))
                similarities.append((c.chunk_index, c.section, cos_sim, "probable cause" in c.text.lower()))

        similarities.sort(key=lambda x: x[2], reverse=True)
        
        print("TOP 15 by similarity (what VectorEngine would return):")
        print("=" * 80)
        for idx, (chunk_idx, section, sim, has_pc) in enumerate(similarities[:15]):
            marker = " <<<< HAS PROBABLE CAUSE" if has_pc else ""
            is_table = "TABLE" if chunk_idx >= 90000 else "TEXT "
            print(f"  Rank {idx+1:3d}: [{is_table}] chunk={chunk_idx:6d} section='{section}' sim={sim:.4f}{marker}")

        print()
        print("SECTIONS that get_candidate_sections would find (ILIKE 'probable cause'):")
        from sqlalchemy import text
        stmt = select(DocumentChunk.section).where(
            DocumentChunk.kb_id == kb.id,
            DocumentChunk.section.is_not(None),
            text("text ILIKE '%probable cause%'")
        ).distinct()
        res = await db.execute(stmt)
        for row in res.all():
            print(f"  section='{row.section}'")

if __name__ == "__main__":
    asyncio.run(main())
