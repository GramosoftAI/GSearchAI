"""
Standalone Embedding Benchmark Script.
Isolates user query -> embedding function -> DeepInfra API -> embedding returned.
Measures:
1. Client initialization
2. Request preparation
3. DeepInfra API request time per attempt
4. Response parsing
5. Post-processing / embedding validation
6. Total function time

Runs 1 Warm-up query, then RUN 1 (10 queries), then RUN 2 (10 queries).
Calculates percentiles and identifies exact latency leakage category.
"""

import sys
import os
import time
import json
import statistics
import asyncio
from typing import List, Dict, Any, Optional
import httpx

# Ensure project root is in python path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from app.core.config import get_settings
import app.core.llm.deepinfra as di_module

TEST_QUERIES = [
    "hello",
    "who is cto",
    "what is a database?",
    "What are the benefits of artificial intelligence in business?",
    "Explain the difference between vector search and keyword search in a RAG system.",
    "According to the uploaded documents, what are the main responsibilities of the CTO and CEO?",
    "Compare the security controls described in the documents and explain which controls address authentication, authorization, and data protection.",
    "According to the provided documents, identify the major risks, explain their causes, describe the recommended mitigations, and indicate which sections support each recommendation.",
    "Analyze the information across the available documents and determine whether there are any conflicting statements about security architecture, access control, data protection, and incident response. Identify each conflict and explain the supporting evidence.",
    "Considering all relevant information in the knowledge base, provide a comprehensive comparison of the security architecture, authentication mechanisms, authorization controls, encryption requirements, monitoring capabilities, incident response procedures, limitations, and recommendations, while preserving all important technical terminology and relationships from the source material."
]


class GranularEmbeddingTracer:
    """Wraps DeepInfraEmbeddingClient execution with granular high-resolution timers."""

    def __init__(self, bypass_cache: bool = True):
        self.settings = get_settings()
        self.bypass_cache = bypass_cache

        # Measure Client initialization
        t_init_start = time.perf_counter()
        self.client = di_module.DeepInfraEmbeddingClient()
        self.client_init_ms = (time.perf_counter() - t_init_start) * 1000

    async def trace_query(self, text: str) -> Dict[str, Any]:
        """
        Executes query embedding with granular timing:
        - Request preparation time
        - API request time per attempt (with retry tracking)
        - Response parsing time
        - Post-processing / validation time
        - Total time
        """
        t_func_start = time.perf_counter()

        if self.bypass_cache:
            # Clear cache entry if present to ensure raw API latency is measured accurately
            di_module._embedding_cache.clear()
            di_module._embedding_cache_insertion_order.clear()

        # 1. Request preparation
        t_prep_start = time.perf_counter()
        truncated_text = text[: self.client.max_text_length]
        headers = {
            "Authorization": f"Bearer {self.client.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.client.model,
            "input": truncated_text,
        }
        t_prep_end = time.perf_counter()
        prep_time_ms = (t_prep_end - t_prep_start) * 1000

        # Ensure persistent HTTP client exists
        if di_module._embedding_http_client is None or di_module._embedding_http_client.is_closed:
            di_module._embedding_http_client = httpx.AsyncClient(
                timeout=self.client.timeout,
                limits=httpx.Limits(max_connections=200, max_keepalive_connections=50)
            )

        http_client = di_module._embedding_http_client

        attempts = []
        last_error = None
        embedding = None
        data = None
        http_status = None
        response_bytes = 0

        # Rate limiter
        async with di_module._embedding_semaphore:
            for attempt_idx in range(self.client.max_retries):
                t_att_start = time.perf_counter()
                try:
                    resp = await http_client.post(
                        self.client.base_url,
                        headers=headers,
                        json=payload
                    )
                    t_att_end = time.perf_counter()
                    att_duration = (t_att_end - t_att_start) * 1000
                    http_status = resp.status_code
                    response_bytes = len(resp.content)
                    resp.raise_for_status()

                    # Response parsing
                    t_parse_start = time.perf_counter()
                    data = resp.json()
                    t_parse_end = time.perf_counter()
                    parse_time_ms = (t_parse_end - t_parse_start) * 1000

                    # Post-processing / vector validation
                    t_post_start = time.perf_counter()
                    if "data" not in data or len(data["data"]) == 0:
                        raise ValueError("Missing embedding data")
                    embedding = data["data"][0].get("embedding")
                    if not embedding:
                        raise ValueError("Missing embedding vector")
                    if len(embedding) != self.client.expected_dimension:
                        raise ValueError(f"Dim mismatch: {len(embedding)} vs {self.client.expected_dimension}")
                    t_post_end = time.perf_counter()
                    post_time_ms = (t_post_end - t_post_start) * 1000

                    attempts.append({
                        "attempt": attempt_idx + 1,
                        "duration_ms": att_duration,
                        "status": "SUCCESS",
                        "status_code": http_status
                    })
                    break

                except Exception as exc:
                    t_att_end = time.perf_counter()
                    att_duration = (t_att_end - t_att_start) * 1000
                    last_error = exc
                    attempts.append({
                        "attempt": attempt_idx + 1,
                        "duration_ms": att_duration,
                        "status": "FAILED",
                        "error": str(exc),
                        "status_code": getattr(getattr(exc, "response", None), "status_code", None)
                    })
                    if attempt_idx < self.client.max_retries - 1:
                        await asyncio.sleep(2 ** attempt_idx)

        t_func_end = time.perf_counter()
        total_time_ms = (t_func_end - t_func_start) * 1000

        total_api_ms = sum(a["duration_ms"] for a in attempts)
        retry_count = len(attempts) - 1

        return {
            "query": text,
            "length": len(text),
            "client_init_ms": self.client_init_ms,
            "prep_ms": prep_time_ms,
            "api_ms": total_api_ms,
            "parse_ms": parse_time_ms if data else 0.0,
            "post_ms": post_time_ms if embedding else 0.0,
            "total_ms": total_time_ms,
            "attempts": attempts,
            "retry_count": retry_count,
            "http_status": http_status,
            "response_bytes": response_bytes,
            "dim": len(embedding) if embedding else 0,
            "model": self.client.model,
            "error": str(last_error) if last_error else None,
            "success": embedding is not None
        }


def format_stats(latencies_sec: List[float]) -> Dict[str, float]:
    sorted_l = sorted(latencies_sec)
    n = len(sorted_l)
    return {
        "avg": statistics.mean(sorted_l),
        "min": min(sorted_l),
        "max": max(sorted_l),
        "p50": statistics.median(sorted_l),
        "p90": sorted_l[int(0.9 * (n - 1))]
    }


async def run_benchmark():
    print("=" * 80)
    print("GSearchAI STANDALONE QUERY EMBEDDING BENCHMARK")
    print("=" * 80)

    tracer = GranularEmbeddingTracer(bypass_cache=True)
    print(f"CLIENT_INIT = {tracer.client_init_ms:.3f} ms")
    print(f"MODEL = {tracer.client.model}")
    print(f"EXPECTED DIM = {tracer.client.expected_dimension}")
    print(f"ENDPOINT = {tracer.client.base_url}")
    print(f"TIMEOUT = {tracer.client.timeout}s")
    print(f"MAX RETRIES = {tracer.client.max_retries}")
    print("=" * 80)

    # 1. Warm-up
    print("\nRunning Warm-up Query: 'warm up embedding'...")
    t_warm_start = time.perf_counter()
    warmup_res = await tracer.trace_query("warm up embedding")
    warmup_dur = time.perf_counter() - t_warm_start
    print(f"WARMUP = {warmup_dur:.3f} seconds (API: {warmup_res['api_ms']/1000:.3f}s, Retries: {warmup_res['retry_count']})\n")

    # 2. RUN 1
    print("=" * 80)
    print("EXECUTING RUN 1 (10 Queries)")
    print("=" * 80)
    run1_results = []
    print(f"{'No':<3} | {'Length':<10} | {'API Time':<10} | {'Parse Time':<12} | {'Total Time':<11} | {'Retries':<7} | {'Status'}")
    print("-" * 80)
    for idx, q in enumerate(TEST_QUERIES, 1):
        res = await tracer.trace_query(q)
        run1_results.append(res)
        status = "OK" if res["success"] else f"ERR: {res['error']}"
        print(f"{idx:02d} | {res['length']:>4} chars | {res['api_ms']/1000:>7.3f}s | {res['parse_ms']:>8.3f}ms | {res['total_ms']/1000:>7.3f}s | {res['retry_count']:>7} | {status}")

    # 3. RUN 2
    print("\n" + "=" * 80)
    print("EXECUTING RUN 2 (10 Queries - Session Reused)")
    print("=" * 80)
    run2_results = []
    print(f"{'No':<3} | {'Length':<10} | {'API Time':<10} | {'Parse Time':<12} | {'Total Time':<11} | {'Retries':<7} | {'Status'}")
    print("-" * 80)
    for idx, q in enumerate(TEST_QUERIES, 1):
        res = await tracer.trace_query(q)
        run2_results.append(res)
        status = "OK" if res["success"] else f"ERR: {res['error']}"
        print(f"{idx:02d} | {res['length']:>4} chars | {res['api_ms']/1000:>7.3f}s | {res['parse_ms']:>8.3f}ms | {res['total_ms']/1000:>7.3f}s | {res['retry_count']:>7} | {status}")

    # Summary Statistics
    run1_totals = [r["total_ms"] / 1000 for r in run1_results]
    run2_totals = [r["total_ms"] / 1000 for r in run2_results]
    stats1 = format_stats(run1_totals)
    stats2 = format_stats(run2_totals)

    print("\n" + "=" * 80)
    print("EMBEDDING BENCHMARK SUMMARY")
    print("=" * 80)
    print(f"Warm-up: {warmup_dur:.3f} sec\n")

    print("Run 1:")
    print(f"  Average: {stats1['avg']:.3f}s")
    print(f"  Minimum: {stats1['min']:.3f}s")
    print(f"  Maximum: {stats1['max']:.3f}s")
    print(f"  P50:     {stats1['p50']:.3f}s")
    print(f"  P90:     {stats1['p90']:.3f}s\n")

    print("Run 2:")
    print(f"  Average: {stats2['avg']:.3f}s")
    print(f"  Minimum: {stats2['min']:.3f}s")
    print(f"  Maximum: {stats2['max']:.3f}s")
    print(f"  P50:     {stats2['p50']:.3f}s")
    print(f"  P90:     {stats2['p90']:.3f}s\n")

    print("Compare (Run 1 vs Run 2):")
    print(f"  Average difference: {stats2['avg'] - stats1['avg']:+.3f}s")
    print(f"  Maximum difference: {stats2['max'] - stats1['max']:+.3f}s\n")

    # Latency Leakage Analysis
    all_results = run1_results + run2_results
    total_total_ms = sum(r["total_ms"] for r in all_results)
    total_prep_ms = sum(r["prep_ms"] for r in all_results)
    total_api_ms = sum(r["api_ms"] for r in all_results)
    total_parse_ms = sum(r["parse_ms"] for r in all_results)
    total_post_ms = sum(r["post_ms"] for r in all_results)
    total_local_ms = total_prep_ms + total_parse_ms + total_post_ms

    pct_api = (total_api_ms / total_total_ms) * 100 if total_total_ms > 0 else 0.0
    pct_prep = (total_prep_ms / total_total_ms) * 100 if total_total_ms > 0 else 0.0
    pct_parse = (total_parse_ms / total_total_ms) * 100 if total_total_ms > 0 else 0.0
    pct_post = (total_post_ms / total_total_ms) * 100 if total_total_ms > 0 else 0.0
    pct_local = (total_local_ms / total_total_ms) * 100 if total_total_ms > 0 else 0.0

    print("=" * 80)
    print("LATENCY LEAKAGE ANALYSIS")
    print("=" * 80)
    print(f"Client Init Overhead:          {tracer.client_init_ms:.3f} ms (executed once at startup)")
    print(f"Request Preparation:           {total_prep_ms:.2f} ms ({pct_prep:.2f}%)")
    print(f"DeepInfra API Request Time:    {total_api_ms:.2f} ms ({pct_api:.2f}%)")
    print(f"Response Parsing:              {total_parse_ms:.2f} ms ({pct_parse:.2f}%)")
    print(f"Local Post-Processing:         {total_post_ms:.2f} ms ({pct_post:.2f}%)")
    print(f"Total Local Python Processing: {total_local_ms:.2f} ms ({pct_local:.2f}%)")
    print("-" * 80)
    if pct_api > 90.0:
        bottleneck = "DeepInfra API / Remote Server Model Inference & Network Transfer"
    else:
        bottleneck = "Local Python Processing Overhead"
    print(f"PRIMARY BOTTLENECK = {bottleneck} ({pct_api:.1f}% of execution time)")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_benchmark())
