import asyncio
from app.core.config import get_settings
from app.modules.knowledge_bases.services.scraper_service import GCrawlClient, GCrawlConfig

async def test_gcrawl():
    client = GCrawlClient()
    urls = ['https://gramosoft.tech/']
    # clean: False
    p1 = {'urls': urls, 'markdown': {'enabled': True, 'clean': False}}
    # clean: True
    p2 = {'urls': urls, 'markdown': {'enabled': True, 'clean': True}}
    
    r1 = await client._request('POST', '/api/v1/batch', json_data=p1, timeout=60)
    r2 = await client._request('POST', '/api/v1/batch', json_data=p2, timeout=60)
    
    print('Submissions:', r1, r2)
    import time
    time.sleep(10)
    
    d1 = await client._request('GET', f'/crawler/results/{r1['crawl_id']}', timeout=60)
    d2 = await client._request('GET', f'/crawler/results/{r2['crawl_id']}', timeout=60)
    
    md1 = d1.get('data', [{}])[0].get('markdown_content', '')
    md2 = d2.get('data', [{}])[0].get('markdown_content', '')
    
    with open('md_false.md', 'w', encoding='utf-8') as f: f.write(md1)
    with open('md_true.md', 'w', encoding='utf-8') as f: f.write(md2)
    print('Wrote files.')

asyncio.run(test_gcrawl())
