import asyncio
import uuid
from sqlalchemy import select, update
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase, DocumentChunk
from app.core.embeddings import EmbeddingGenerator

async def main():
    async with AsyncSessionLocal() as db:
        # Find the KB
        res = await db.execute(select(KnowledgeBase).filter(KnowledgeBase.name.ilike('%20071231X02009.pdf%')))
        kb = res.scalar_one_or_none()
        if not kb:
            print("KB not found.")
            return
            
        print(f"Found KB: {kb.name}")
        
        # 1. Update metadata_json
        formatted_ids = ["Registration N8770M", "Aircraft Beech A23", "Accident Number SEA08CA049"]
        await db.execute(
            update(KnowledgeBase)
            .where(KnowledgeBase.id == kb.id)
            .values(metadata_json={"global_identifiers": formatted_ids})
        )
        await db.commit()
        print("Updated KB metadata_json.")
        
        # 2. Re-embed unstructured chunks
        context_parts = [f"[Document Title: {kb.name}]", f"[Document Context: {', '.join(formatted_ids)}]"]
        context_header = "\n".join(context_parts)
        
        res = await db.execute(select(DocumentChunk).filter(
            DocumentChunk.kb_id == kb.id,
            DocumentChunk.chunk_index < 90000
        ))
        chunks = res.scalars().all()
        
        if not chunks:
            print("No unstructured chunks found.")
            return
            
        print(f"Re-embedding {len(chunks)} unstructured chunks...")
        texts_for_embedding = [f"{context_header}\n{chunk.text}" for chunk in chunks]
        embeddings = await EmbeddingGenerator.generate_embeddings_batch(texts_for_embedding)
        
        for i, chunk in enumerate(chunks):
            chunk.embedding = embeddings[i]
            
        await db.commit()
        print("Successfully re-embedded chunks and saved to DB!")

if __name__ == "__main__":
    asyncio.run(main())
