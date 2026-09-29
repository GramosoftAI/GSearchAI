import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

import asyncio
import argparse
import time
import math
from typing import List, Tuple
from sqlalchemy import select, update
from app.core.database import AsyncSessionLocal
from app.modules.knowledge_bases.models import KnowledgeBase, DocumentChunk
from app.modules.knowledge_bases.service import format_chunk_embedding_input
from app.core.embeddings import EmbeddingGenerator


def cosine_distance(v1, v2) -> float:
    """1.0 - cosine_similarity"""
    if v1 is None or v2 is None:
        return 1.0
    try:
        import numpy as np
        a1 = np.array(v1, dtype=float)
        a2 = np.array(v2, dtype=float)
        if a1.shape != a2.shape or len(a1) == 0:
            return 1.0
        dot = np.dot(a1, a2)
        norm1 = np.linalg.norm(a1)
        norm2 = np.linalg.norm(a2)
        if norm1 == 0 or norm2 == 0:
            return 1.0
        return float(1.0 - (dot / (norm1 * norm2)))
    except Exception:
        return 1.0


async def run_backfill(dry_run: bool = True, limit: int = 10, batch_size: int = 25):
    print("=" * 70)
    print(f"STARTING EMBEDDING BACKFILL (dry_run={dry_run}, limit={limit}, batch_size={batch_size})")
    print("=" * 70)

    async with AsyncSessionLocal() as db:
        # 1. Fetch chunks where length(text) > 1000 and has embedding
        # Order by created_at or chunk_index for deterministic resumability
        query = (
            select(DocumentChunk, KnowledgeBase.name)
            .join(KnowledgeBase, DocumentChunk.kb_id == KnowledgeBase.id)
            .filter(
                DocumentChunk.text != None,
                DocumentChunk.chunk_index < 90000 # Unstructured chunks
            )
        )
        
        res = await db.execute(query)
        all_rows = res.fetchall()

        # Filter strictly for text length > 1000
        target_rows = [r for r in all_rows if len(r[0].text or "") > 1000]
        total_eligible = len(target_rows)
        print(f"Found {total_eligible} total chunks in DB with len(text) > 1000 characters.")

        if limit > 0:
            target_rows = target_rows[:limit]
            print(f"Limiting execution to {len(target_rows)} chunk(s).")

        if not target_rows:
            print("No chunks to process. Exiting.")
            return

        # 2. Process in batches
        processed_count = 0
        total_time_start = time.perf_counter()

        for b_start in range(0, len(target_rows), batch_size):
            batch = target_rows[b_start : b_start + batch_size]
            print(f"\n--- Processing Batch {b_start // batch_size + 1} ({len(batch)} chunks) ---")

            texts_for_embedding = []
            chunks_to_update = []
            old_embeddings = []

            for chunk_obj, kb_name in batch:
                meta = chunk_obj.metadata_json or {}
                sec = chunk_obj.section or meta.get("section")
                src_url = meta.get("source_url")
                doc_title = meta.get("title")

                # REUSE the exact service.py formatting function!
                formatted_input = format_chunk_embedding_input(
                    chunk_text=chunk_obj.text,
                    kb_name=kb_name,
                    section=sec,
                    document_category=None,
                    source_url=src_url,
                    title=doc_title
                )
                texts_for_embedding.append(formatted_input)
                chunks_to_update.append(chunk_obj)
                old_embeddings.append(chunk_obj.embedding)

            t0 = time.perf_counter()
            new_embeddings, tokens = await EmbeddingGenerator.generate_embeddings_batch_with_usage(texts_for_embedding)
            t_batch = time.perf_counter() - t0
            print(f"  Batch embedding call finished in {t_batch:.2f}s ({tokens} tokens consumed)")

            for idx, chunk in enumerate(chunks_to_update):
                old_emb = old_embeddings[idx]
                new_emb = new_embeddings[idx]
                dist = cosine_distance(old_emb, new_emb) if old_emb is not None else 1.0

                print(
                    f"  Chunk [{chunk.id}] (len={len(chunk.text)}): "
                    f"Cosine distance old->new = {dist:.4f} "
                    f"({'SIGNIFICANT CHANGE' if dist > 0.05 else 'minimal drift'})"
                )

                if not dry_run:
                    chunk.embedding = new_emb

            if not dry_run:
                await db.commit()
                print(f"  [DB COMMIT] Saved batch of {len(batch)} re-embedded chunks.")
            else:
                print(f"  [DRY RUN] Skipped DB commit for batch.")

            processed_count += len(batch)

        total_time = time.perf_counter() - total_time_start
        print("\n" + "=" * 70)
        print(f"BACKFILL COMPLETE: {processed_count} chunks processed in {total_time:.2f}s (dry_run={dry_run})")
        print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-embed truncated document chunks")
    parser.add_argument("--dry-run", action="store_true", default=False, help="Compute embeddings and log vector diffs without updating database")
    parser.add_argument("--limit", type=int, default=10, help="Max number of chunks to process (0 for all)")
    parser.add_argument("--batch-size", type=int, default=20, help="Batch size for embedding API calls")

    args = parser.parse_args()
    asyncio.run(run_backfill(dry_run=args.dry_run, limit=args.limit, batch_size=args.batch_size))
