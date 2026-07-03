import os
import json
import asyncio
import time
from app.core.unified_extractor import UnifiedExtractor

# Ensure we're in the right working directory
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS_DIR = os.path.join(ROOT_DIR, "test_corpus")
EXPECTED_METRICS_FILE = os.path.join(CORPUS_DIR, "expected_metrics.json")

async def benchmark_corpus():
    print("======================================")
    print("      CORPUS DRIFT BENCHMARKING       ")
    print("======================================")
    
    if not os.path.exists(CORPUS_DIR):
        print(f"Error: Corpus directory not found at {CORPUS_DIR}")
        return

    if not os.path.exists(EXPECTED_METRICS_FILE):
        print(f"Error: Expected metrics file not found at {EXPECTED_METRICS_FILE}")
        return

    with open(EXPECTED_METRICS_FILE, 'r') as f:
        expected_metrics = json.load(f)

    extractor = UnifiedExtractor(tenant_id="test_tenant")
    
    total_files = 0
    passed_files = 0

    for filename, expected in expected_metrics.items():
        filepath = os.path.join(CORPUS_DIR, filename)
        if not os.path.exists(filepath):
            print(f" [SKIP] {filename} (File not found in test_corpus/)")
            continue
            
        total_files += 1
        print(f"\n[RUNNING] Analyzing {filename}...")
        
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Simplified execution for benchmark: assumes 1 chunk for demonstration.
        # In a real environment, you'd chunk this up.
        start_time = time.time()
        result = await extractor.extract_all(chunk_id="chunk_1", chunk_text=content)
        duration = time.time() - start_time
        
        actual_entities = len(result.get("entities", []))
        actual_triplets = len(result.get("triplets", []))
        
        expected_entities = expected.get("entities", 0)
        expected_triplets = expected.get("triplets", 0)
        
        ent_variance = actual_entities - expected_entities
        trip_variance = actual_triplets - expected_triplets
        
        print(f"  Time: {duration:.2f}s")
        print(f"  Entities: Expected {expected_entities}, Got {actual_entities} (Variance: {ent_variance})")
        print(f"  Triplets: Expected {expected_triplets}, Got {actual_triplets} (Variance: {trip_variance})")
        
        # Determine pass/fail based on a strict 5% variance threshold
        if abs(ent_variance) <= (expected_entities * 0.05) and abs(trip_variance) <= (expected_triplets * 0.05):
            print(f"  [PASS] {filename}")
            passed_files += 1
        else:
            print(f"  [FAIL] {filename} drifted beyond 5% tolerance threshold!")

    print("\n======================================")
    print(f"RESULTS: {passed_files}/{total_files} passed.")
    if total_files > 0 and passed_files == total_files:
        print("PIPELINE STABLE. Safe to deploy.")
    else:
        print("PIPELINE DRIFTED! Do not deploy without investigation.")

if __name__ == "__main__":
    asyncio.run(benchmark_corpus())
