import asyncio, httpx
from app.core.config import get_settings

async def test_gcrawl():
    api_key = get_settings().gcrawl_api_key
    url = 'https://gcrawlai.com/gc/api/v1/batch'
    headers = {'Content-Type': 'application/json', 'X-API-Key': api_key}
    payload = {
        'urls': ['https://gramosoft.tech/'],
        'markdown': {'enabled': True, 'clean': True},
        'crawl': {'concurrency': 10, 'timeout': 20, 'wait_until': 'domcontentloaded'}
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, headers=headers)
        print('Status:', r.status_code)
        print('Response:', r.text)

asyncio.run(test_gcrawl())
