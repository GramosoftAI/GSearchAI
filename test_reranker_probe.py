import asyncio
import httpx
from app.core.config import get_settings

async def test_rerank():
    s = get_settings()
    print("model_reranker:", s.model_reranker)
    base = s.deepinfra_api_url.replace("/openai", "")
    url = f"{base}/inference/{s.model_reranker}"
    headers = {
        "Authorization": f"Bearer {s.deepinfra_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "queries": ["what is the security policy?"],
        "documents": [
            "The security policy requires two factor authentication for all users.",
            "The cafeteria serves lunch from 12pm to 2pm."
        ]
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(url, headers=headers, json=payload, timeout=10.0)
        print("Status:", r.status_code)
        print("Response:", r.json())

if __name__ == "__main__":
    asyncio.run(test_rerank())
