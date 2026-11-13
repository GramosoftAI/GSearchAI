"""
Stress test: fires N concurrent requests at memory-api's process-turn
endpoint to see if Ollama's single-server concurrency becomes a bottleneck.

Usage:
    pip install httpx --break-system-packages   (if not already installed)
    python stress_test.py
"""
import asyncio
import time
import httpx

URL = "http://localhost:8002/api/v1/memory/process-turn"
CONCURRENT_REQUESTS = 8


async def fire_one(client: httpx.AsyncClient, i: int):
    payload = {
        "query": f"test query {i} - what is the salary",
        "session_id": "stress1",
        "agent_id": "a1",
        "user_id": "u1",
        "tenant_id": "t1",
    }
    start = time.monotonic()
    try:
        resp = await client.post(URL, json=payload, timeout=100.0)
        elapsed = time.monotonic() - start
        print(f"[{i}] status={resp.status_code} took={elapsed:.1f}s")
    except Exception as e:
        elapsed = time.monotonic() - start
        print(f"[{i}] FAILED after {elapsed:.1f}s: {type(e).__name__}: {e}")


async def main():
    print(f"Firing {CONCURRENT_REQUESTS} concurrent requests at {URL} ...")
    async with httpx.AsyncClient() as client:
        tasks = [fire_one(client, i) for i in range(CONCURRENT_REQUESTS)]
        start = time.monotonic()
        await asyncio.gather(*tasks)
        print(f"\nAll done in {time.monotonic() - start:.1f}s total")


if __name__ == "__main__":
    asyncio.run(main())