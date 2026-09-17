"""
Benchmark to measure embedding latency across cold, warm, and idle periods (Phase A, B, C).
Uses the EXACT production DeepInfraEmbeddingClient and configuration without modifying production code.
"""

import os
import sys
import time
import asyncio
from datetime import datetime

# Set up environment path to import app modules
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app.core.config import get_settings
from app.core.llm.deepinfra import DeepInfraEmbeddingClient, _embedding_cache

async def measure_single_embedding(client: DeepInfraEmbeddingClient, query: str):
    """
    Measures a single embedding request with high-resolution timing,
    bypassing the in-memory cache to measure true network/remote latency.
    """
    # Clear cache for this specific text to ensure fresh request
    import hashlib
    text_hash = hashlib.sha256(query.encode()).hexdigest()
    _embedding_cache.pop(text_hash, None)

    # Granular timing markers
    t_entry = time.perf_counter()
    req_prep_start = time.perf_counter()

    headers = {
        "Authorization": f"Bearer {client.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": client.model,
        "input": query,
    }

    import httpx
    import app.core.llm.deepinfra as deepinfra_module
    from app.core.llm.deepinfra import _embedding_semaphore

    if deepinfra_module._embedding_http_client is None or deepinfra_module._embedding_http_client.is_closed:
        deepinfra_module._embedding_http_client = httpx.AsyncClient(
            timeout=client.timeout,
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=50)
        )
    http_client = deepinfra_module._embedding_http_client

    t_prep = time.perf_counter() - req_prep_start

    status_code = None
    retries = 0
    t_api = 0.0
    t_parse = 0.0
    t_post = 0.0
    emb_dim = 0
    err = None

    async with _embedding_semaphore:
        for attempt in range(client.max_retries):
            retries = attempt
            t_req_start = time.perf_counter()
            req_timestamp = datetime.now().isoformat()
            try:
                response = await http_client.post(
                    client.base_url, headers=headers, json=payload
                )
                t_api = time.perf_counter() - t_req_start
                status_code = response.status_code
                response.raise_for_status()

                # Parse JSON
                t_parse_start = time.perf_counter()
                data = response.json()
                t_parse = time.perf_counter() - t_parse_start

                # Post processing / dimension validation
                t_post_start = time.perf_counter()
                emb = data["data"][0]["embedding"]
                emb_dim = len(emb)
                t_post = time.perf_counter() - t_post_start
                break
            except Exception as e:
                err = e
                if attempt < client.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

    t_total = time.perf_counter() - t_entry

    return {
        "query": query,
        "timestamp": req_timestamp,
        "status": status_code,
        "api_time": t_api,
        "prep_time": t_prep,
        "parse_time": t_parse,
        "post_time": t_post,
        "total_time": t_total,
        "retries": retries,
        "dim": emb_dim,
        "model": client.model,
        "error": str(err) if err else None,
    }

async def run_idle_benchmark():
    settings = get_settings()
    print("=" * 80)
    print("TASK 2 & 3: PRODUCTION-LIKE COLD/WARM & IDLE-PERIOD BENCHMARK")
    print(f"Model: {settings.model_embedding} | Dimension: {settings.embedding_dimension}")
    print("=" * 80)

    # Initialize client once (measuring init time)
    t_init_0 = time.perf_counter()
    client = DeepInfraEmbeddingClient()
    t_client_init = (time.perf_counter() - t_init_0) * 1000.0
    print(f"Client Init Time: {t_client_init:.4f} ms\n")

    # PHASE A — Initial request
    print("--- PHASE A: Initial Request ('hello') ---")
    res_a = await measure_single_embedding(client, "hello")
    print(f"Timestamp:    {res_a['timestamp']}")
    print(f"Total Time:   {res_a['total_time']:.3f}s")
    print(f"API Time:     {res_a['api_time']:.3f}s (HTTP/network + remote inference)")
    print(f"Parse Time:   {res_a['parse_time']*1000:.2f}ms")
    print(f"Status Code:  {res_a['status']}")
    print(f"Retries:      {res_a['retries']}")
    print(f"Model/Dim:    {res_a['model']} / {res_a['dim']}")
    print()

    # PHASE B — Immediate warm requests (5 requests continuously)
    print("--- PHASE B: Immediate Warm Requests (5 continuous) ---")
    warm_queries = [
        "hello",
        "who is cto",
        "what is a database?",
        "explain vector search",
        "explain RAG architecture"
    ]
    warm_results = []
    for idx, q in enumerate(warm_queries, 1):
        res = await measure_single_embedding(client, q)
        warm_results.append(res)
        print(f"Warm {idx} | '{q[:22]:<22}' | Total: {res['total_time']:.3f}s | API: {res['api_time']:.3f}s | Status: {res['status']}")

    avg_warm = sum(r['total_time'] for r in warm_results) / len(warm_results)
    print(f"Average Warm Latency: {avg_warm:.3f}s\n")

    # PHASE C — Idle-period test
    # Intervals: 10s, 30s, 60s, 2m (120s), 5m (300s)
    # We will test 10s, 30s, 60s, 120s (2m), 300s (5m)
    intervals = [
        ("10 seconds", 10),
        ("30 seconds", 30),
        ("60 seconds", 60),
        ("2 minutes", 120),
        ("5 minutes", 300),
    ]

    print("--- PHASE C: Idle-Period Retention Test (Query: 'who is cto') ---")
    idle_table = []
    idle_table.append(("Initial", "0s", f"{res_a['total_time']:.3f}s", f"{res_a['api_time']:.3f}s"))
    idle_table.append(("Warm 1", "0s", f"{warm_results[0]['total_time']:.3f}s", f"{warm_results[0]['api_time']:.3f}s"))
    idle_table.append(("Warm 2", "0s", f"{warm_results[1]['total_time']:.3f}s", f"{warm_results[1]['api_time']:.3f}s"))

    for label, duration in intervals:
        print(f"Sleeping for {label} ({duration}s)...", flush=True)
        await asyncio.sleep(duration)
        res = await measure_single_embedding(client, "who is cto")
        print(f"After {label:<10} | Total: {res['total_time']:.3f}s | API: {res['api_time']:.3f}s | Status: {res['status']}", flush=True)
        idle_table.append((label, f"{duration}s", f"{res['total_time']:.3f}s", f"{res['api_time']:.3f}s"))

    print("\n" + "=" * 80)
    print("IDLE PERIOD BENCHMARK SUMMARY TABLE")
    print("=" * 80)
    print(f"{'Test':<15} | {'Idle Time':<10} | {'Total Latency':<15} | {'API Latency (Net+Inf)'}")
    print("-" * 80)
    for row in idle_table:
        print(f"{row[0]:<15} | {row[1]:<10} | {row[2]:<15} | {row[3]}")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_idle_benchmark())
