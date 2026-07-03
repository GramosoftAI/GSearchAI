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
    if len(sys.argv) < 2:
        print("Usage: python scripts/benchmark_custom_text.py <path_to_text_file>")
        sys.exit(1)
        
    doc_path = sys.argv[1]
    print(f"Reading {doc_path}...", flush=True)
    
    with open(doc_path, "r", encoding="utf-8") as f:
        extracted_text = f.read()
    
    # Simple chunking for benchmark (about 300 words per chunk)
    words = extracted_text.split()
    chunks = []
    chunk_size = 300
    for i in range(0, len(words), chunk_size):
        chunk_text = " ".join(words[i:i+chunk_size])
        chunks.append({
            "chunk_id": f"chunk_{i//chunk_size}",
            "text": chunk_text
        })
        
    print(f"\nDocument chunked into {len(chunks)} chunks.", flush=True)
    
    # Optional: Cap at a few chunks for a fast benchmark to avoid extreme API bills
    max_chunks = 4
    if len(chunks) > max_chunks:
        print(f"Limiting to first {max_chunks} chunks for the benchmark.", flush=True)
        chunks = chunks[:max_chunks]

    print("\n==============================================", flush=True)
    print("Starting LEGACY Full Document Benchmark...", flush=True)
    print("==============================================\n", flush=True)

    # --- LEGACY PIPELINE ---
    start_legacy = time.time()
    
    legacy_entities = []
    legacy_triplets = []
    legacy_identifiers = []

    async def run_legacy_chunk(chunk):
        try:
            ent = await EntityExtractor.extract_entities(chunk["text"])
        except:
            ent = []
            
        try:
            te = TripletExtractor()
            res = await te.extract_from_chunk(chunk["chunk_id"], chunk["text"])
            trip = res.triplets if res and res.triplets else []
        except:
            trip = []
            
        try:
            struct = await PDFExtractor.extract_structured_entities(chunk["text"])
            struct_ids = struct.get("identifiers", [])
        except:
            struct_ids = []
            
        return ent, trip, struct_ids

    # Process sequentially to avoid API rate limiting in testing
    for i, chunk in enumerate(chunks):
        ent, trip, struct = await run_legacy_chunk(chunk)
        legacy_entities.extend(ent)
        legacy_triplets.extend(trip)
        legacy_identifiers.extend(struct)
        print(f"  Processed legacy chunk {i+1}/{len(chunks)}", flush=True)

    time_legacy = time.time() - start_legacy

    print(f"\nLegacy complete in {time_legacy:.2f}s", flush=True)
    print("Legacy Entities:", len(legacy_entities))
    print("Legacy Triplets:", len(legacy_triplets))
    print("Legacy Identifiers:", len(legacy_identifiers))

    print("\n==============================================", flush=True)
    print("Starting UNIFIED Full Document Benchmark...", flush=True)
    print("==============================================\n", flush=True)

    # --- UNIFIED PIPELINE ---
    start_unified = time.time()
    unified_extractor = UnifiedExtractor()
    
    unified_entities = []
    unified_triplets = []
    unified_identifiers = []

    for i, chunk in enumerate(chunks):
        res = await unified_extractor.extract_all(chunk["chunk_id"], chunk["text"])
        unified_entities.extend(res.get("entities", []))
        unified_triplets.extend(res.get("triplets", []))
        unified_identifiers.extend(res.get("identifiers", []))
        print(f"  Processed unified chunk {i+1}/{len(chunks)}", flush=True)

    time_unified = time.time() - start_unified

    print(f"\nUnified complete in {time_unified:.2f}s", flush=True)
    print("Unified Entities:", len(unified_entities))
    print("Unified Triplets:", len(unified_triplets))
    print("Unified Identifiers:", len(unified_identifiers))

    print("\n==============================================", flush=True)
    print("                  RESULTS                     ")
    print("==============================================", flush=True)
    print(f"Legacy Time:  {time_legacy:.2f}s")
    print(f"Unified Time: {time_unified:.2f}s")
    
    if time_unified < time_legacy:
        speedup = (time_legacy - time_unified) / time_legacy * 100
        print(f"\n✅ Unified is {speedup:.1f}% FASTER!")
    else:
        slowdown = (time_unified - time_legacy) / time_unified * 100
        print(f"\n⚠️ Unified is {slowdown:.1f}% SLOWER.")

if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
