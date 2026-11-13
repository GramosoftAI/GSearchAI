import asyncio
from app.modules.knowledge_bases.services.scraper_service import GCrawlClient

async def test_gcrawl():
    client = GCrawlClient()
    urls = ['https://gramosoft.tech/']
    payload = {
        'urls': urls,
        'markdown': {'enabled': True, 'clean': True},
        'concurrency': 10,
        'timeout_per_url': 20,
        'wait_until': 'domcontentloaded'
    }
    r = await client._request('POST', '/api/v1/batch', json_data=payload, timeout=60)
    print('Submission:', r)

asyncio.run(test_gcrawl())
