import logging
import httpx
import asyncio
from typing import List, Dict, Any, Optional
from ....core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

class ScraperService:
    """
    URL Scraper Service using Gcrawl API as the primary and exclusive crawling engine.
    """

    @staticmethod
    async def extract_website_content(
        url: str, 
        crawl_type: str = "all", 
        proxy_mode: str = "default"
    ) -> List[Dict[str, Any]]:
        """
        Main entry point for website extraction using Gcrawl.
        """
        url = url.rstrip("/")
        
        if not settings.gcrawl_enabled:
            logger.error("Gcrawl is disabled but is the only supported crawling engine.")
            return []

        try:
            # 1. Submit crawl job
            response_data = await ScraperService.call_gcrawl_api(url, crawl_type, proxy_mode)
            
            if response_data:
                # Gcrawl API might return the ID under different keys (crawl_id, id, job_id)
                job_id = response_data.get("job_id") or response_data.get("crawl_id") or response_data.get("id")
                
                if job_id:
                    logger.info(f" Gcrawl queued task {job_id} for {url}. Polling for results...")
                    
                    # 2. Poll for results
                    poll_data = await ScraperService.poll_gcrawl_data(job_id)
                    
                    if poll_data and (poll_data.get("data") or poll_data.get("markdown")):
                        logger.info(f" Gcrawl success for {url}")
                        return ScraperService.normalize_gcrawl_response(poll_data, url)
                
            logger.warning(f"Gcrawl returned empty data for {url}. Response was: {response_data}")

        except Exception as e:
            logger.error(f"Gcrawl failed for {url}: {str(e)}", exc_info=True)

        return []

    @staticmethod
    async def call_gcrawl_api(url: str, crawl_type: str, proxy_mode: str) -> Optional[Dict[str, Any]]:
        """
        Call the Gcrawl Scrape API with retries and the required payload.
        """
        api_key = getattr(settings, "gcrawl_api_key", None)
        if not api_key:
            logger.error("GCRAWL_API_KEY is missing in configuration.")
            raise ValueError("GCRAWL_API_KEY not configured")

        payload = {
            "url": url,
            "crawl": {
                "max_pages": "auto",
                "same_domain_only": True,
                "include_subdomains": False
            },
            "proxy": {
                "geo": proxy_mode if proxy_mode else "default"
            },
            "markdown": {
                "enabled": True,
                "clean": False
            },
            "html": {
                "enabled": False,
                "clean": False,
                "remove_external_links": False,
                "relative_to_absolute_links": True,
                "remove_data_images": False,
                "ignore_tags": []
            },
            "screenshot": {
                "enabled": False,
                "full_page": False,
                "format": "png",
                "quality": 90,
                "js_render": False,
                "render_timeout": 30000,
                "auto_scroll": True,
                "scroll_delay": 500,
                "max_scrolls": 2
            },
            "seo": {
                "enabled": False
            },
            "images": {
                "enabled": False
            }
        }
        
        url_endpoint = "https://gcrawlai.com/gc/api/v1/crawl"
        
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key
        }

        async with httpx.AsyncClient(timeout=settings.gcrawl_timeout) as client:
            for attempt in range(settings.gcrawl_retry + 1):
                try:
                    response = await client.post(url_endpoint, json=payload, headers=headers)
                    response.raise_for_status()
                    return response.json()
                except (httpx.HTTPStatusError, httpx.RequestError) as e:
                    if attempt < settings.gcrawl_retry:
                        logger.warning(f"Gcrawl attempt {attempt + 1} failed: {e}. Retrying...")
                        await asyncio.sleep(2)
                    else:
                        raise e
        return None

    @staticmethod
    async def poll_gcrawl_data(job_id: str, timeout_seconds: int = 300) -> Optional[Dict[str, Any]]:
        """
        Poll the Gcrawl results endpoint until status is 'completed' or 'success'.
        """
        api_key = getattr(settings, "gcrawl_api_key", None)
        
        poll_url = f"https://gcrawlai.com/gc/crawler/results/{job_id}"
        
        headers = {
            "Accept": "application/json",
            "x-api-key": api_key
        }
            
        start_time = asyncio.get_event_loop().time()
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                if asyncio.get_event_loop().time() - start_time > timeout_seconds:
                    logger.warning(f"Gcrawl polling timed out after {timeout_seconds}s for task {job_id}")
                    return None
                    
                try:
                    response = await client.get(poll_url, headers=headers)
                    response.raise_for_status()
                    data = response.json()
                    
                    status = data.get("status", "").lower()
                    if status in ["success", "completed"]:
                        logger.info(f"Gcrawl polling success for task {job_id}")
                        return data
                    elif status in ["failed", "error"]:
                        logger.error(f"Gcrawl task {job_id} failed: {data}")
                        return None
                        
                    # If still queued/processing, wait and poll again
                    await asyncio.sleep(5)
                except Exception as e:
                    logger.warning(f"Error while polling Gcrawl task {job_id}: {e}")
                    await asyncio.sleep(5)

    @staticmethod
    def normalize_gcrawl_response(response: Dict[str, Any], root_url: str) -> List[Dict[str, Any]]:
        """
        Normalize Gcrawl response to existing document schema.
        Extracts markdown content to be passed into the knowledge base pipeline.
        """
        documents = []
        
        # Some API responses might nest it under "data"
        if "data" in response:
            data = response.get("data", [])
            if isinstance(data, dict):
                data = [data]
        else:
            # Or it might be at the root of the response
            data = [response]
            
        for page in data:
            content = page.get("markdown_content") or page.get("markdown") or page.get("text") or page.get("content") or ""
            if not content.strip():
                logger.warning(f"No extractable text found in page. Available keys: {list(page.keys())}")
                continue
                
            documents.append({
                "content": content,
                "source": page.get("start_url") or page.get("url") or root_url,
                "metadata": {
                    "title": page.get("title", "Untitled Page"),
                    "description": page.get("description"),
                    "job_id": response.get("job_id") or response.get("crawl_id") or response.get("id")
                }
            })
            
        return documents
