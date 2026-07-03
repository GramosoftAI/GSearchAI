import sys
import os
import asyncio
import time
from dotenv import load_dotenv

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.pdf_extractor import PDFExtractor
from app.core.unified_extractor import UnifiedExtractor
from app.core.entity_extraction import EntityExtractor
from app.core.triplet_extractor import TripletExtractor

async def main():
    doc_path = r"v:\graphmind\README.md"
    print(f"Reading {doc_path}...", flush=True)
    
    with open(doc_path, "r", encoding="utf-8") as f:
        extracted_text = f.read()
    
    # Simple chunking for benchmark
    words = extracted_text.split()
    chunks = []
    chunk_size = 300
    for i in range(0, len(words), chunk_size):
        chunk_text = " ".join(words[i:i+chunk_size])
        chunks.append({
            "chunk_id": f"chunk_{i//chunk_size}",
            "text": chunk_text
        })
        
    # Cap at 2 chunks to avoid API rate limiting in testing
    chunks = chunks[:2]
    
    print(f"\nDocument chunked into {len(chunks)} chunks.", flush=True)
    print("Starting LEGACY Full Document Benchmark...", flush=True)

    # --- LEGACY PIPELINE ---
    start_legacy = time.time()
    
    # 1. Entity Extraction
    legacy_entities = []
    legacy_entity_calls = 0
    async def run_legacy_entity(chunk):
        nonlocal legacy_entity_calls
        legacy_entity_calls += 1
        try:
            return await EntityExtractor.extract_entities(chunk["text"])
        except:
            return []

    # 2. Triplet Extraction
    legacy_triplets = []
    legacy_triplet_calls = 0
    te = TripletExtractor()
    async def run_legacy_triplet(chunk):
        nonlocal legacy_triplet_calls
        legacy_triplet_calls += 1
        try:
            res = await te.extract_from_chunk(chunk["chunk_id"], chunk["text"])
            return res.triplets if res and res.triplets else []
        except:
            return []

    # 3. Structured Extraction
    legacy_identifiers = []
    legacy_structured_calls = 0
    async def run_legacy_structured(chunk):
        nonlocal legacy_structured_calls
        legacy_structured_calls += 1
        try:
            res = await PDFExtractor.extract_structured_entities(chunk["text"])
            return res.get("identifiers", [])
        except:
            return []

    async def run_legacy_chunk(chunk):
        return await asyncio.gather(
            run_legacy_entity(chunk),
            run_legacy_triplet(chunk),
            run_legacy_structured(chunk)
        )

    # Process sequentially to avoid API rate limiting
    for i, chunk in enumerate(chunks):
        ent, trip, struct = await run_legacy_chunk(chunk)
        legacy_entities.extend(ent)
        legacy_triplets.extend(trip)
        legacy_identifiers.extend(struct)
        print(f"  Processed legacy chunk {i+1}", flush=True)

    time_legacy = time.time() - start_legacy

    print(f"Legacy complete in {time_legacy:.2f}s", flush=True)
    print("\nStarting UNIFIED Full Document Benchmark...", flush=True)

    # --- UNIFIED PIPELINE ---
    start_unified = time.time()
    unified_extractor = UnifiedExtractor()
    
    unified_entities = []
    unified_triplets = []
    unified_identifiers = []
    unified_calls = 0
    
    async def run_unified_chunk(chunk):
        nonlocal unified_calls
        unified_calls += 1
        try:
            return await unified_extractor.extract_all(chunk["chunk_id"], chunk["text"])
        except:
            return {"entities": [], "triplets": [], "structured": {"identifiers": []}}

    for i, chunk in enumerate(chunks):
        res = await run_unified_chunk(chunk)
        unified_entities.extend(res.get("entities", []))
        unified_triplets.extend(res.get("triplets", []))
        unified_identifiers.extend(res.get("structured", {}).get("identifiers", []))
        print(f"  Processed unified chunk {i+1}", flush=True)

    time_unified = time.time() - start_unified

    print(f"Unified complete in {time_unified:.2f}s", flush=True)

    # --- REPORT ---
    print("\n===============================")
    print("    FULL DOCUMENT BENCHMARK")
    print("===============================\n")

    print("Document:\nv:\\graphmind\\README.md\n")
    print(f"Chunks:\n{len(chunks)}\n")

    print(f"Legacy:\n  Calls: {legacy_entity_calls + legacy_triplet_calls + legacy_structured_calls}\n  Time: {time_legacy:.2f} sec\n")
    print(f"Unified:\n  Calls: {unified_calls}\n  Time: {time_unified:.2f} sec\n")

    print("Entities:")
    print(f"  Legacy: {len(legacy_entities)}")
    print(f"  Unified: {len(unified_entities)}\n")

    print("Triplets:")
    print(f"  Legacy: {len(legacy_triplets)}")
    print(f"  Unified: {len(unified_triplets)}\n")

    print("Identifiers:")
    print(f"  Legacy: {len(legacy_identifiers)}")
    print(f"  Unified: {len(unified_identifiers)}\n")

    # Calculate variance
    def pct_diff(leg, uni):
        if leg == 0: return 0.0
        return ((uni - leg) / leg) * 100

    print("Variance:")
    print(f"  Entities: {pct_diff(len(legacy_entities), len(unified_entities)):.1f}%")
    print(f"  Triplets: {pct_diff(len(legacy_triplets), len(unified_triplets)):.1f}%")
    print(f"  Identifiers: {pct_diff(len(legacy_identifiers), len(unified_identifiers)):.1f}%")

if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
