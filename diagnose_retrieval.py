"""
Deep diagnostic: trace why chunk 0 (the one with 'probable cause') is not
surfacing in the final 13 RRF-selected chunks.
"""
import asyncio
from sqlalchemy import select, text
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase, DocumentChunk
from app.core.embeddings import EmbeddingGenerator

async def main():
    async with AsyncSessionLocal() as db:
        # 1. Find the KB
        res = await db.execute(
            select(KnowledgeBase).filter(KnowledgeBase.name.ilike('%20071231X02009.pdf%'))
        )
        kb = res.scalar_one_or_none()
        if not kb:
            print("KB not found.")
            return
        print(f"KB: {kb.name} (ID: {kb.id})")

        # 2. Get ALL chunks for this KB
        res = await db.execute(
            select(DocumentChunk).filter(DocumentChunk.kb_id == kb.id)
        )
        chunks = res.scalars().all()
        print(f"Total chunks: {len(chunks)}")
        print()

        # 3. Show every chunk's section + first 120 chars
        print("=" * 80)
        print("ALL CHUNKS: index | section | first 120 chars")
        print("=" * 80)
        for c in sorted(chunks, key=lambda x: x.chunk_index):
            snippet = c.text[:120].replace('\n', ' ').replace('\r', ' ')
            has_probable = "probable cause" in c.text.lower()
            marker = " <<<< CONTAINS 'PROBABLE CAUSE'" if has_probable else ""
            print(f"  [{c.chunk_index:6d}] section='{c.section}' | {snippet}...{marker}")
        print()

        # 4. Generate the query embedding and compute cosine similarity against EVERY chunk
        query = "What was the probable cause of the Beech A23 airplane accident in Death Valley, CA on November 29, 2007?"
        query_embedding = await EmbeddingGenerator.generate_embedding(query)

        print("=" * 80)
        print("VECTOR SIMILARITY: query vs each chunk (sorted by similarity DESC)")
        print("=" * 80)

        similarities = []
        for c in chunks:
            if c.embedding is not None and len(c.embedding) > 0:
                # cosine similarity = 1 - cosine_distance
                # pgvector stores as list; compute dot product / norms
                import numpy as np
                q = np.array(query_embedding)
                e = np.array(c.embedding)
                cos_sim = float(np.dot(q, e) / (np.linalg.norm(q) * np.linalg.norm(e)))
                similarities.append((c.chunk_index, c.section, cos_sim, "probable cause" in c.text.lower()))
            else:
                similarities.append((c.chunk_index, c.section, -1.0, "probable cause" in c.text.lower()))

        similarities.sort(key=lambda x: x[2], reverse=True)
        for idx, (chunk_idx, section, sim, has_pc) in enumerate(similarities):
            marker = " <<<< HAS PROBABLE CAUSE" if has_pc else ""
            print(f"  Rank {idx+1:3d}: chunk_index={chunk_idx:6d} section='{section}' similarity={sim:.4f}{marker}")

        # 5. Check: what does the ILIKE keyword search return for 'probable cause'?
        print()
        print("=" * 80)
        print("POSTGRES ILIKE CHECK: which chunks match 'probable cause'?")
        print("=" * 80)
        from uuid import UUID
        stmt = select(DocumentChunk.id, DocumentChunk.chunk_index, DocumentChunk.section).where(
            DocumentChunk.kb_id == kb.id,
            text("text ILIKE '%probable cause%'")
        )
        res = await db.execute(stmt)
        for row in res.all():
            print(f"  chunk_index={row.chunk_index} section='{row.section}' id={row.id}")

        # 6. Check: what does get_candidate_sections return?
        print()
        print("=" * 80)
        print("DISTINCT SECTIONS from Postgres (what get_candidate_sections would return)")
        print("=" * 80)
        stmt = select(DocumentChunk.section).where(
            DocumentChunk.kb_id == kb.id,
            DocumentChunk.section.is_not(None)
        ).distinct()
        res = await db.execute(stmt)
        for row in res.all():
            print(f"  section='{row.section}'")

if __name__ == "__main__":
    asyncio.run(main())
