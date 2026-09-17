"""
DeepInfra embedding cold-start comparison script.

Pings a set of candidate embedding models repeatedly over several minutes
and logs response latency for each call. Run this BEFORE deciding whether
to switch embedding models in production — it tells you whether a given
model is meaningfully more consistently "warm" than Qwen3-Embedding-8B
under real usage patterns, without touching your actual pipeline, KB,
or pgvector schema.

Usage:
    export DEEPINFRA_API_TOKEN=your_token_here
    python deepinfra_coldstart_test.py

Recommended: let it run for at least 5-10 minutes so you get a realistic
mix of query timings, not just the first (guaranteed-cold) call per model.
"""

import os
import time
import random
import requests
from datetime import datetime

API_TOKEN = 'qidLTyOYIZ7P8V77KihKhjd5TNqMrckb'
if not API_TOKEN:
    raise SystemExit("Set DEEPINFRA_API_TOKEN in your environment first.")

BASE_URL = "https://api.deepinfra.com/v1/openai/embeddings"

# Candidates to compare against your current production model.
# Add/remove models here as needed.
MODELS = [
    "Qwen/Qwen3-Embedding-8B",          # current production model (baseline)
    "BAAI/bge-large-en-v1.5",           # widely used, likely higher shared traffic
    "intfloat/multilingual-e5-large",   # widely used, multilingual
]

# Realistic short queries similar to what your pipeline actually sends,
# so this measures the same code path shape as production (not a
# synthetic long batch call).
SAMPLE_QUERIES = [
    "who is the ceo",
    "who is rajesh",
    "what services do you offer",
    "who is the cto",
    "tell me about the company",
]

# Seconds to wait between calls to the SAME model (simulates real query cadence)
MIN_GAP = 10
MAX_GAP = 25

TOTAL_RUNTIME_SECONDS = 600  # 10 minutes; adjust as needed

COLD_THRESHOLD_MS = 2000  # matches your app's own threshold


def call_embedding(model: str, text: str):
    headers = {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}
    payload = {"model": model, "input": text}
    start = time.monotonic()
    try:
        resp = requests.post(BASE_URL, headers=headers, json=payload, timeout=60)
        elapsed_ms = (time.monotonic() - start) * 1000
        ok = resp.status_code == 200
        return ok, elapsed_ms, resp.status_code
    except requests.RequestException as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return False, elapsed_ms, str(e)


def main():
    results = {m: [] for m in MODELS}
    start_time = time.monotonic()
    call_count = 0

    print(f"Starting cold-start comparison for {len(MODELS)} models over ~{TOTAL_RUNTIME_SECONDS/60:.0f} min\n")

    while time.monotonic() - start_time < TOTAL_RUNTIME_SECONDS:
        for model in MODELS:
            query = random.choice(SAMPLE_QUERIES)
            ok, elapsed_ms, status = call_embedding(model, query)
            call_count += 1
            is_cold = elapsed_ms > COLD_THRESHOLD_MS
            results[model].append(elapsed_ms if ok else None)

            tag = "COLD" if is_cold else "warm"
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] call#{call_count:03d} model={model:<30} "
                  f"latency={elapsed_ms:7.1f}ms  status={status}  {tag if ok else 'ERROR'}")

            gap = random.uniform(MIN_GAP, MAX_GAP)
            time.sleep(gap)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for model, latencies in results.items():
        valid = [l for l in latencies if l is not None]
        if not valid:
            print(f"{model}: no successful calls")
            continue
        cold_count = sum(1 for l in valid if l > COLD_THRESHOLD_MS)
        avg = sum(valid) / len(valid)
        print(f"\n{model}")
        print(f"  calls: {len(valid)}  |  cold (> {COLD_THRESHOLD_MS}ms): {cold_count} "
              f"({100 * cold_count / len(valid):.0f}%)")
        print(f"  avg latency: {avg:.0f}ms  |  min: {min(valid):.0f}ms  |  max: {max(valid):.0f}ms")

    print("\nInterpretation:")
    print("  - If Qwen3-8B and a candidate have similar cold %% -> switching won't help,")
    print("    the issue is likely instance-routing variance, go straight to dedicated deployment.")
    print("  - If a candidate has meaningfully LOWER cold %% -> may be worth the re-ingestion")
    print("    cost of switching production to it.")


if __name__ == "__main__":
    main()