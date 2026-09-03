"""
Fix B (v2): The original chunk 0 text was consumed by the previous re-ingestion attempt.
Reconstruct the narrative text directly (it's known from the NTSB report) and create 
properly-sectioned chunks.
"""
import asyncio
import uuid
from sqlalchemy import select, delete
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase, DocumentChunk
from app.core.embeddings import EmbeddingGenerator

# Known text from the NTSB report (extracted from previous diagnostic runs)
ANALYSIS_TEXT = """The pilot reported that during the landing on runway 5, the touchdown was hard and the airplane bounced and started to "porpoise". Subsequently the nosewheel landing gear failed aft, and the airplane nosed down and slid to a stop. The pilot reported no mechanical anomalies with the airplane prior to the accident."""

PROBABLE_CAUSE_TEXT = """The National Transportation Safety Board determines the probable cause(s) of this accident to be: The pilot's improper flare, which resulted in a hard landing and nose gear collapse."""

FINDINGS_TEXT = """Occurrence #1: HARD LANDING
Phase of Operation: LANDING - FLARE/TOUCHDOWN

Findings
1. (C) FLARE - IMPROPER - PILOT IN COMMAND
Occurrence #2: NOSE DOWN
Phase of Operation: LANDING - FLARE/TOUCHDOWN

Findings
2. (C) LANDING GEAR,NOSE GEAR - COLLAPSED"""

NTSB_BOILERPLATE = """The National Transportation Safety Board (NTSB), established in 1967, is an independent federal agency mandated by Congress through the Independent Safety Board Act of 1974 to investigate transportation accidents, determine the probable causes of the accidents, issue safety recommendations, study transportation safety issues, and evaluate the safety effectiveness of government agencies involved in transportation."""

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

        # 2. Delete any existing unstructured chunks (chunk_index < 90000)
        res = await db.execute(
            select(DocumentChunk).filter(
                DocumentChunk.kb_id == kb.id,
                DocumentChunk.chunk_index < 90000
            )
        )
        old_chunks = res.scalars().all()
        if old_chunks:
            old_ids = [c.id for c in old_chunks]
            await db.execute(
                delete(DocumentChunk).where(DocumentChunk.id.in_(old_ids))
            )
            print(f"Deleted {len(old_ids)} old unstructured chunk(s)")

        # 3. Create new properly-sectioned chunks
        metadata = kb.metadata_json or {}
        global_ids = metadata.get("global_identifiers", [])
        context_parts = [f"[Document Title: {kb.name}]"]
        if global_ids:
            context_parts.append(f"[Document Context: {', '.join(global_ids)}]")
        context_header = "\n".join(context_parts)

        sections = [
            ("Analysis", ANALYSIS_TEXT),
            ("Probable Cause and Findings", PROBABLE_CAUSE_TEXT),
            ("Findings", FINDINGS_TEXT),
            ("About NTSB", NTSB_BOILERPLATE),
        ]

        texts_for_embedding = []
        new_db_chunks = []
        
        for i, (section_name, section_text) in enumerate(sections):
            # Clean display text for DB/LLM
            chunk_text = f"Section: {section_name}\n\n{section_text.strip()}"
            
            # Augmented text for embedding (adds KB context)
            augmented_text = f"{context_header}\n[Section: {section_name}]\n{section_text.strip()}"
            texts_for_embedding.append(augmented_text)
            
            new_db_chunks.append(DocumentChunk(
                id=uuid.uuid4(),
                kb_id=kb.id,
                tenant_id=kb.tenant_id,
                chunk_index=i,
                text=chunk_text,
                section=section_name,
                metadata_json={"s3_path": kb.s3_path, "section": section_name},
            ))
            print(f"  Prepared chunk {i}: section='{section_name}' ({len(chunk_text)} chars)")

        # 4. Generate embeddings
        print(f"\nGenerating embeddings for {len(texts_for_embedding)} chunks...")
        embeddings = await EmbeddingGenerator.generate_embeddings_batch(texts_for_embedding)
        
        for i, chunk in enumerate(new_db_chunks):
            chunk.embedding = embeddings[i]
            db.add(chunk)

        await db.commit()
        print(f"Successfully created {len(new_db_chunks)} new chunks!")

        # 5. Verify
        print("\n" + "=" * 60)
        print("VERIFICATION: All chunks for this KB")
        print("=" * 60)
        res = await db.execute(
            select(DocumentChunk).filter(DocumentChunk.kb_id == kb.id)
        )
        all_chunks = res.scalars().all()
        
        unstructured = [c for c in all_chunks if c.chunk_index < 90000]
        synthetic = [c for c in all_chunks if c.chunk_index >= 90000]
        
        print(f"\nUnstructured chunks: {len(unstructured)}")
        for c in sorted(unstructured, key=lambda x: x.chunk_index):
            has_pc = "probable cause" in c.text.lower()
            marker = " <<<< HAS 'PROBABLE CAUSE'" if has_pc else ""
            snippet = c.text[:100].replace('\n', ' ')
            print(f"  [{c.chunk_index}] section='{c.section}' | {snippet}...{marker}")
        
        print(f"\nSynthetic table chunks: {len(synthetic)}")
        print(f"Total chunks: {len(all_chunks)}")

if __name__ == "__main__":
    asyncio.run(main())
