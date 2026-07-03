import sys
import os
import asyncio
import time
from dotenv import load_dotenv

# Add root directory to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.core.unified_extractor import UnifiedExtractor
from app.core.entity_extraction import EntityExtractor
from app.core.triplet_extractor import TripletExtractor
from app.core.pdf_extractor import PDFExtractor

async def main():
    if len(sys.argv) > 1:
        chunk_text = sys.argv[1]
    else:
        # Sample dense chunk
        chunk_text = """
        Apple Inc. is an American multinational technology company headquartered in Cupertino, California.
        It was founded by Steve Jobs in 1976.
        INVOICE_NUMBER: INV-2023-9912.
        Place of Delivery: 123 Main St, New York.
        GSTIN: 33AAACS8779D1Z7.
        The shipping is managed by Global Logistics Corp.
        """

    chunk_id = "test_chunk_1"

    print(f"Testing chunk: {chunk_text[:100].strip()}...\n")

    # --- LEGACY PIPELINE ---
    start_legacy = time.time()
    
    entities_legacy = []
    try:
        entities_legacy = await EntityExtractor.extract_entities(chunk_text)
    except Exception as e:
        pass

    triplets_legacy = []
    try:
        te = TripletExtractor()
        triplet_res = await te.extract_from_chunk(chunk_id, chunk_text)
        if triplet_res and triplet_res.triplets:
            triplets_legacy = triplet_res.triplets
    except Exception as e:
        pass

    structured_legacy = {"identifiers": []}
    try:
        structured_legacy = await PDFExtractor.extract_structured_entities(chunk_text)
    except Exception as e:
        pass

    time_legacy = time.time() - start_legacy

    # --- UNIFIED PIPELINE ---
    start_unified = time.time()
    
    try:
        unified_extractor = UnifiedExtractor()
        unified_res = await unified_extractor.extract_all(chunk_id, chunk_text)
        
        entities_unified = unified_res.get("entities", [])
        triplets_unified = unified_res.get("triplets", [])
        structured_unified = unified_res.get("structured", {}).get("identifiers", [])
    except Exception as e:
        print(f"Unified Error: {e}")
        entities_unified = []
        triplets_unified = []
        structured_unified = []
    
    time_unified = time.time() - start_unified

    # --- BENCHMARK REPORT ---
    print("===============================")
    print("       BENCHMARK REPORT")
    print("===============================\n")

    print(f"Chunk ID: {chunk_id}\n")

    print(f"Entities:\n  Legacy: {len(entities_legacy)}\n  Unified: {len(entities_unified)}")
    print(f"Triplets:\n  Legacy: {len(triplets_legacy)}\n  Unified: {len(triplets_unified)}")
    print(f"Identifiers:\n  Legacy: {len(structured_legacy.get('identifiers', []))}\n  Unified: {len(structured_unified)}")
    
    print("\nPerformance:")
    print(f"  Legacy Time: {time_legacy:.2f} sec (3 LLM calls)")
    print(f"  Unified Time: {time_unified:.2f} sec (1 LLM call)")
    
    # We consider it a pass if Unified is at least as good or very close.
    status = "PASS" if len(entities_unified) >= len(entities_legacy) * 0.8 else "WARN"
    print(f"\nStatus: {status}")

if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
