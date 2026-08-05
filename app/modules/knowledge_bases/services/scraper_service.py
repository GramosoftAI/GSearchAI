import logging
import httpx
import asyncio
import time
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable, Set
from pydantic import BaseModel, Field
from ....core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# =====================================================================
# Exception Hierarchy
# =====================================================================

class GCrawlException(Exception):
    """Base exception for all GCrawl acquisition errors."""
    pass


class LinkDiscoveryFailed(GCrawlException):
    """Raised when link discovery job submission fails or status is failed/error."""
    pass


class LinkDiscoveryTimeout(GCrawlException):
    """Raised when link discovery polling exceeds maximum attempts/time."""
    pass


class ScrapeSubmissionFailed(GCrawlException):
    """Raised when bulk scraping job submission fails or status is failed/error."""
    pass


class ScrapeTimeout(GCrawlException):
    """Raised when bulk scrape polling exceeds maximum attempts/time."""
    pass


class MarkdownUnavailable(GCrawlException):
    """Raised when no valid markdown content could be extracted."""
    pass


class InvalidURLException(GCrawlException):
    """Raised when a URL is invalid or uses an unsupported scheme/hostname."""
    pass


# =====================================================================
# Configuration & Domain Models
# =====================================================================

@dataclass
class GCrawlConfig:
    """Configuration for GCrawl bounded polling and retry behavior."""
    LINK_DISCOVERY_TIMEOUT: int = 120
    SCRAPE_TIMEOUT: int = 300
    POLL_INTERVAL: int = 2
    MAX_PAGES: int = 50
    RETRY_COUNT: int = 3
    BACKOFF_FACTOR: int = 2


@dataclass
class CrawlContext:
    """Correlation object and execution metrics for a website ingestion run."""
    tenant_id: Optional[str] = None
    kb_id: Optional[str] = None
    crawl_id: Optional[str] = None
    gsearch_id: Optional[str] = None
    start_time: float = field(default_factory=time.time)
    # Timing metrics (in seconds)
    discovery_time: float = 0.0
    filtering_time: float = 0.0
    scraping_time: float = 0.0
    conversion_time: float = 0.0
    total_time: float = 0.0
    # Count metrics
    links_found: int = 0
    links_filtered: int = 0
    pages_scraped: int = 0
    pages_failed: int = 0
    markdown_generated: int = 0

    def format_log_prefix(self) -> str:
        parts = []
        if self.tenant_id:
            parts.append(f"tenant={self.tenant_id}")
        if self.kb_id:
            parts.append(f"kb={self.kb_id}")
        if self.crawl_id:
            parts.append(f"crawl_id={self.crawl_id}")
        if self.gsearch_id:
            parts.append(f"gsearch_id={self.gsearch_id}")
        return " ".join(parts)


@dataclass
class WebsiteDocument:
    """Domain model representing a scraped website document."""
    url: str
    markdown: str
    metadata: Dict[str, Any]

    def to_legacy_dict(self) -> Dict[str, Any]:
        """
        Converts to the legacy dictionary format expected by downstream ingestion code
        (routes.py and agents/routes.py) without dict inheritance.
        """
        return {
            "url": self.url,
            "source": self.url,
            "markdown": self.markdown,
            "content": self.markdown,
            "metadata": self.metadata,
        }


# =====================================================================
# Response Validators
# =====================================================================

class LinkDiscoveryResponse(BaseModel):
    crawl_id: str
    task_url: Optional[str] = None
    status: Optional[str] = None
    url: Optional[str] = None


class ScrapeSubmissionResponse(BaseModel):
    gsearch_id: str
    urls_submitted: Optional[int] = 0
    status: Optional[str] = None


# =====================================================================
# URL Validation & Canonicalization Rules
# =====================================================================

TRACKING_PARAMS = {
    "utm_source", "utm_campaign", "utm_medium", "utm_term", "utm_content",
    "fbclid", "gclid", "ref"
}

EXCLUDED_EXTENSIONS = {
    ".pdf", ".zip", ".exe", ".dmg", ".tar", ".gz", ".png", ".jpg", ".jpeg",
    ".gif", ".svg", ".css", ".js"
}

EXCLUDED_PATHS = set()  # List all internal URLs per user requirement


def validate_url(url: str) -> str:
    """
    Validates a URL before calling GCrawl API to avoid quota waste on unsupported schemes/hostnames.
    """
    url = url.strip()
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    netloc = (parsed.netloc or "").lower()

    if scheme in ["ftp", "file", "javascript"] or scheme not in ["http", "https"]:
        raise InvalidURLException(f"Unsupported or invalid URL scheme: '{url}'")

    if any(h in hostname or h in netloc for h in ["localhost", "127.0.0.1", "0.0.0.0", "::1"]):
        raise InvalidURLException(f"Cannot crawl localhost or loopback address: '{url}'")

    return url


def canonicalize_url(url: str) -> Optional[str]:
    """
    Canonicalizes a URL by stripping tracking params, fragments, trailing slashes,
    and filtering out non-HTML extensions or administrative paths.
    Returns None if the URL should be excluded.
    """
    if not url or url.startswith(("mailto:", "tel:", "javascript:", "#")):
        return None

    url = url.strip()
    if "#" in url:
        url = url.split("#", 1)[0]

    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        return None

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return None

    path = parsed.path
    path_lower = path.lower()
    for ext in EXCLUDED_EXTENSIONS:
        if path_lower.endswith(ext):
            return None

    for excl in EXCLUDED_PATHS:
        if excl in path_lower:
            return None

    # Normalize trailing slashes including root path
    if path == "/":
        path = ""
    elif len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # Strip tracking query parameters
    query_str = ""
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        filtered_params = {
            k: v for k, v in params.items() if k.lower() not in TRACKING_PARAMS
        }
        if filtered_params:
            query_str = urlencode(filtered_params, doseq=True)

    return urlunparse((scheme, hostname, path, parsed.params, query_str, ""))


def filter_links(
    urls: List[str],
    root_url: str,
    crawl_type: str = "all",
    max_pages: int = 50
) -> List[str]:
    """
    Applies business filtering rules: domain matching, deduplication, URL normalization,
    and page count limits.
    """
    canon_root = canonicalize_url(root_url) or root_url.rstrip("/")
    parsed_root = urlparse(canon_root)
    root_domain = (parsed_root.hostname or "").lower()

    if crawl_type == "single":
        return [canon_root]

    selected: List[str] = []
    seen: Set[str] = set()

    # Always ensure the root URL is included first if valid
    if canon_root and canon_root not in seen:
        selected.append(canon_root)
        seen.add(canon_root)

    for raw_u in urls:
        canon_u = canonicalize_url(raw_u)
        if not canon_u or canon_u in seen:
            continue

        parsed_u = urlparse(canon_u)
        u_domain = (parsed_u.hostname or "").lower()
        if u_domain != root_domain:
            continue

        selected.append(canon_u)
        seen.add(canon_u)
        if len(selected) >= max_pages:
            break

    return selected


# =====================================================================
# Low-Level HTTP Client (GCrawlClient)
# =====================================================================

class GCrawlClient:
    """
    Low-level HTTP client responsible only for API calls to Gcrawl endpoints.
    Centralizes retry, timeout, authentication, headers, and logging in _request().
    """
    def __init__(self, api_key: Optional[str] = None, config: Optional[GCrawlConfig] = None):
        self.api_key = api_key or getattr(settings, "gcrawl_api_key", None)
        if not self.api_key:
            logger.error("GCRAWL_API_KEY is missing in configuration.")
            raise ValueError("GCRAWL_API_KEY not configured")
        self.config = config or GCrawlConfig()
        self.base_url = "https://gcrawlai.com/gc"

    async def _request(
        self,
        method: str,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": self.api_key,
            "x-api-key": self.api_key,
        }
        retry_codes = {429, 500, 502, 503, 504}
        no_retry_codes = {400, 401, 403, 404}

        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(self.config.RETRY_COUNT + 1):
                try:
                    if method.upper() == "POST":
                        response = await client.post(url, json=json_data, headers=headers)
                    else:
                        response = await client.get(url, params=params, headers=headers)

                    if response.status_code in no_retry_codes:
                        response.raise_for_status()

                    if response.status_code in retry_codes:
                        response.raise_for_status()

                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError as e:
                    status = e.response.status_code
                    if status in no_retry_codes or attempt == self.config.RETRY_COUNT:
                        raise
                    backoff_time = (self.config.BACKOFF_FACTOR ** attempt)
                    logger.warning(
                        f"GCrawl HTTP {status} error on {method} {url} "
                        f"(attempt {attempt+1}/{self.config.RETRY_COUNT}). Retrying in {backoff_time}s..."
                    )
                    await asyncio.sleep(backoff_time)
                except httpx.RequestError as e:
                    if attempt == self.config.RETRY_COUNT:
                        raise
                    backoff_time = (self.config.BACKOFF_FACTOR ** attempt)
                    logger.warning(
                        f"GCrawl request error on {method} {url} "
                        f"(attempt {attempt+1}/{self.config.RETRY_COUNT}): {e}. Retrying in {backoff_time}s..."
                    )
                    await asyncio.sleep(backoff_time)
        raise GCrawlException(f"Failed to execute request to {url}")

    async def discover_links(self, url: str) -> LinkDiscoveryResponse:
        """Step 1: POST /api/v1/links to submit link discovery job."""
        payload = {
            "url": url,
            "links": {
                "limit": "auto",
                "same_domain_only": True,
                "include_subdomains": True
            },
            "proxy": {
                "geo": "default"
            }
        }
        data = await self._request("POST", "/api/v1/links", json_data=payload, timeout=30)
        try:
            return LinkDiscoveryResponse(**data)
        except Exception as e:
            raise LinkDiscoveryFailed(f"Invalid link discovery response: {e}, payload={data}")

    async def get_link_results(self, crawl_id: str) -> Dict[str, Any]:
        """Step 2: GET /crawler/results/{crawl_id} to poll link discovery results."""
        return await self._request("GET", f"/crawler/results/{crawl_id}", timeout=15)

    async def submit_scrape(self, urls: List[str]) -> ScrapeSubmissionResponse:
        """Step 3: POST /api/v1/grag/scrape-links to submit bulk scrape job."""
        payload = {"urls": urls}
        data = await self._request("POST", "/api/v1/grag/scrape-links", json_data=payload, timeout=30)
        try:
            return ScrapeSubmissionResponse(**data)
        except Exception as e:
            raise ScrapeSubmissionFailed(f"Invalid scrape submission response: {e}, payload={data}")

    async def get_scrape_results(self, gsearch_id: str) -> Dict[str, Any]:
        """Step 4: GET /api/v1/grag/scrape-links/results/{gsearch_id} to poll scraped contents."""
        return await self._request("GET", f"/api/v1/grag/scrape-links/results/{gsearch_id}", timeout=15)


# =====================================================================
# Business Orchestrator (WebsiteCrawler)
# =====================================================================

class WebsiteCrawler:
    """
    Business orchestration layer executing: discover -> poll -> filter -> scrape -> poll -> convert.
    Includes progress reporting, bounded polling, canonical URL filtering, and metrics tracking.
    """
    def __init__(
        self,
        client: GCrawlClient,
        config: Optional[GCrawlConfig] = None,
        progress_cb: Optional[Callable[[str, int], None]] = None
    ):
        self.client = client
        self.config = config or GCrawlConfig()
        self.progress_cb = progress_cb or self._default_progress

    def _default_progress(self, stage: str, percent: int) -> None:
        logger.info(f"Progress {percent}% | {stage}")

    async def discover(self, url: str, context: CrawlContext) -> str:
        self.progress_cb("Submitting link discovery", 10)
        t0 = time.time()
        res = await self.client.discover_links(url)
        if not res.crawl_id:
            raise LinkDiscoveryFailed("No crawl_id returned from link discovery endpoint")
        context.crawl_id = res.crawl_id
        logger.info(f"[{context.format_log_prefix()}] Submitted link discovery, crawl_id={res.crawl_id}")
        return res.crawl_id

    async def poll_link_discovery(self, crawl_id: str, context: CrawlContext) -> List[str]:
        self.progress_cb("Discovering website pages", 25)
        t0 = time.time()
        step = max(1, self.config.POLL_INTERVAL)
        max_attempts = max(1, self.config.LINK_DISCOVERY_TIMEOUT // step)

        for attempt in range(max_attempts):
            res_data = await self.client.get_link_results(crawl_id)
            status = (res_data.get("status") or "").lower()

            if status in ["success", "completed", "finished"]:
                data_list = res_data.get("data", [])
                if not data_list:
                    context.discovery_time = time.time() - t0
                    return []
                first_item = data_list[0]
                links = first_item.get("links", [])
                context.links_found = len(links)
                context.discovery_time = time.time() - t0
                logger.info(
                    f"[{context.format_log_prefix()}] Link discovery success: {len(links)} links found"
                )
                return links
            elif status in ["failed", "error", "cancelled"]:
                raise LinkDiscoveryFailed(
                    f"Link discovery task {crawl_id} failed with status '{status}'"
                )

            await asyncio.sleep(self.config.POLL_INTERVAL)

        raise LinkDiscoveryTimeout(
            f"Link discovery timed out after {self.config.LINK_DISCOVERY_TIMEOUT} seconds for crawl_id {crawl_id}"
        )

    def filter(self, urls: List[str], root_url: str, crawl_type: str, context: CrawlContext) -> List[str]:
        self.progress_cb("Filtering links", 45)
        t0 = time.time()
        selected = filter_links(
            urls, root_url, crawl_type=crawl_type, max_pages=self.config.MAX_PAGES
        )
        context.links_filtered = len(selected)
        context.filtering_time = time.time() - t0
        logger.info(
            f"[{context.format_log_prefix()}] Filtered links: {len(selected)} selected from {len(urls)}"
        )
        return selected

    async def scrape(self, urls: List[str], context: CrawlContext) -> str:
        self.progress_cb("Submitting bulk scraping", 60)
        res = await self.client.submit_scrape(urls)
        if not res.gsearch_id:
            raise ScrapeSubmissionFailed("No gsearch_id returned from scrape submission endpoint")
        context.gsearch_id = res.gsearch_id
        logger.info(
            f"[{context.format_log_prefix()}] Submitted bulk scrape for {len(urls)} URLs, gsearch_id={res.gsearch_id}"
        )
        return res.gsearch_id

    async def poll_scraping(self, gsearch_id: str, context: CrawlContext) -> List[Dict[str, Any]]:
        self.progress_cb("Downloading markdown", 80)
        t0 = time.time()
        step = max(1, self.config.POLL_INTERVAL)
        max_attempts = max(1, self.config.SCRAPE_TIMEOUT // step)

        for attempt in range(max_attempts):
            res_data = await self.client.get_scrape_results(gsearch_id)
            status = (res_data.get("status") or "").lower()

            if status in ["completed", "success", "finished"]:
                data_list = res_data.get("data", [])
                context.scraping_time = time.time() - t0
                logger.info(
                    f"[{context.format_log_prefix()}] Bulk scrape task {gsearch_id} completed successfully"
                )
                return data_list
            elif status in ["failed", "error", "cancelled"]:
                raise ScrapeSubmissionFailed(
                    f"Bulk scrape task {gsearch_id} failed with status '{status}'"
                )

            await asyncio.sleep(self.config.POLL_INTERVAL)

        raise ScrapeTimeout(
            f"Bulk scrape timed out after {self.config.SCRAPE_TIMEOUT} seconds for gsearch_id {gsearch_id}"
        )

    def convert(self, scraped_data: List[Dict[str, Any]], root_url: str, context: CrawlContext) -> List[WebsiteDocument]:
        t0 = time.time()
        documents: List[WebsiteDocument] = []
        scraped_count = 0
        failed_count = 0

        for item in scraped_data:
            item_status = (item.get("status") or "").lower()
            url = item.get("url") or root_url
            err = item.get("error")

            if err or item_status in ["failed", "error"]:
                failed_count += 1
                logger.warning(f"[{context.format_log_prefix()}] Page scrape error for {url}: {err}")
                continue

            content = item.get("markdown_content") or item.get("markdown") or ""
            if not content or not str(content).strip():
                failed_count += 1
                logger.warning(f"[{context.format_log_prefix()}] Empty markdown content for {url}; skipping page")
                continue

            scraped_count += 1
            meta = {
                "source": "gcrawl",
                "title": item.get("title", "Untitled Page"),
                "description": item.get("description"),
                "scraped_at": item.get("scraped_at")
            }
            if context.crawl_id:
                meta["crawl_id"] = context.crawl_id
            if context.gsearch_id:
                meta["gsearch_id"] = context.gsearch_id

            doc = WebsiteDocument(
                url=url,
                markdown=str(content).strip(),
                metadata=meta
            )
            documents.append(doc)

        context.pages_scraped = scraped_count
        context.pages_failed = failed_count
        context.markdown_generated = len(documents)
        context.conversion_time = time.time() - t0
        self.progress_cb("Website acquisition completed", 100)
        return documents

    async def run_pipeline(
        self,
        url: str,
        crawl_type: str = "all",
        context: Optional[CrawlContext] = None
    ) -> List[WebsiteDocument]:
        """
        Executes the full website acquisition pipeline and returns domain WebsiteDocument objects.
        """
        context = context or CrawlContext()
        context.start_time = time.time()
        logger.info(
            f"Starting Website Crawl [{context.format_log_prefix()}] url={url} mode={crawl_type}"
        )

        valid_url = validate_url(url)

        # Stage 1: Discover Links
        crawl_id = await self.discover(valid_url, context)

        # Stage 2: Poll Link Discovery
        discovered_urls = await self.poll_link_discovery(crawl_id, context)

        # Stage 3: Filter Links
        selected_urls = self.filter(discovered_urls, valid_url, crawl_type=crawl_type, context=context)
        if not selected_urls:
            logger.warning(f"[{context.format_log_prefix()}] No valid links selected after filtering.")
            return []

        # Stage 4: Bulk Scrape Selected URLs
        gsearch_id = await self.scrape(selected_urls, context)

        # Stage 5: Poll Scraping Result
        scraped_data = await self.poll_scraping(gsearch_id, context)

        # Stage 6: Convert response into domain model
        documents = self.convert(scraped_data, valid_url, context)

        context.total_time = time.time() - context.start_time
        logger.info(
            f"Website Crawl Metrics [{context.format_log_prefix()}] | "
            f"links_found={context.links_found} links_filtered={context.links_filtered} "
            f"pages_scraped={context.pages_scraped} pages_failed={context.pages_failed} "
            f"markdown_generated={context.markdown_generated} | "
            f"discovery_time={context.discovery_time:.2f}s filtering_time={context.filtering_time:.2f}s "
            f"scraping_time={context.scraping_time:.2f}s conversion_time={context.conversion_time:.2f}s "
            f"total_time={context.total_time:.2f}s"
        )
        return documents


# =====================================================================
# Public Service Entry Point (ScraperService)
# =====================================================================

class ScraperService:
    """
    URL Scraper Service using Gcrawl API as the primary crawling engine.
    Supports phase-switching feature flag ('website_acquisition_provider').
    """

    @staticmethod
    async def extract_website_content(
        url: str,
        crawl_type: str = "all",
        proxy_mode: str = "default",
        **kwargs: Any
    ) -> List[Dict[str, Any]]:
        """
        Main entry point for website extraction using Gcrawl.
        Returns legacy dictionary format compatible with downstream ingestion code.
        """
        url = url.rstrip("/")

        if not settings.gcrawl_enabled:
            logger.error("Gcrawl is disabled but is the only supported crawling engine.")
            return []

        provider = getattr(settings, "website_acquisition_provider", "gcrawl_v2")

        if provider == "gcrawl_v1":
            logger.info(f"Using legacy website acquisition provider: {provider}")
            return await ScraperService._extract_website_content_v1(url, crawl_type, proxy_mode)

        try:
            tenant_id = kwargs.get("tenant_id")
            kb_id = kwargs.get("kb_id")
            progress_cb = kwargs.get("progress_cb")

            context = CrawlContext(tenant_id=tenant_id, kb_id=kb_id)
            client = GCrawlClient()
            crawler = WebsiteCrawler(client=client, progress_cb=progress_cb)

            documents = await crawler.run_pipeline(url, crawl_type=crawl_type, context=context)
            return [doc.to_legacy_dict() for doc in documents]

        except InvalidURLException as e:
            logger.error(f"URL validation error for {url}: {e}")
            raise
        except (LinkDiscoveryFailed, LinkDiscoveryTimeout, ScrapeSubmissionFailed, ScrapeTimeout, MarkdownUnavailable) as e:
            logger.error(f"Acquisition pipeline error for {url}: {e}", exc_info=True)
            raise
        except httpx.HTTPStatusError as e:
            logger.error(f"Gcrawl HTTP error for {url}: {e.response.status_code} - {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Gcrawl failed for {url}: {str(e)}", exc_info=True)
            return []

    @staticmethod
    async def discover_site_links(url: str, max_pages: int = 50) -> Dict[str, Any]:
        """
        Discover and filter all valid internal URLs from a website for UI presentation.
        Returns {'root_url': url, 'total_discovered': len(urls), 'urls': urls}
        """
        validated_url = validate_url(url)
        client = GCrawlClient()
        crawler = WebsiteCrawler(client=client)
        context = CrawlContext()
        logger.info(f"Discovering links for UI selection: {validated_url}")
        crawl_id = await crawler.discover(validated_url, context)
        raw_urls = await crawler.poll_link_discovery(crawl_id, context)
        filtered_urls = filter_links(raw_urls, validated_url, crawl_type="all", max_pages=max_pages)
        if validated_url not in filtered_urls:
            filtered_urls.insert(0, validated_url)
        return {
            "root_url": validated_url,
            "total_discovered": len(filtered_urls),
            "urls": filtered_urls
        }

    @staticmethod
    async def scrape_selected_urls(urls: List[str]) -> List[Dict[str, Any]]:
        """
        Bulk scrape a specific list of user-selected URLs and return legacy document dictionaries.
        """
        if not urls:
            return []
        root_url = validate_url(urls[0])
        client = GCrawlClient()
        crawler = WebsiteCrawler(client=client)
        context = CrawlContext()
        logger.info(f"Bulk scraping {len(urls)} user-selected URLs...")
        gsearch_id = await crawler.scrape(urls, context)
        scraped_data = await crawler.poll_scraping(gsearch_id, context)
        documents = crawler.convert(scraped_data, root_url, context)
        return [doc.to_legacy_dict() for doc in documents]

    # =================================================================
    # Legacy Implementation (v1 Fallback via Feature Flag)
    # =================================================================

    @staticmethod
    async def _extract_website_content_v1(
        url: str,
        crawl_type: str = "all",
        proxy_mode: str = "default"
    ) -> List[Dict[str, Any]]:
        try:
            response_data = await ScraperService.call_gcrawl_api(url, crawl_type, proxy_mode)

            if response_data:
                job_id = response_data.get("job_id") or response_data.get("crawl_id") or response_data.get("id")

                if job_id:
                    logger.info(f" Gcrawl queued task {job_id} for {url}. Polling for results...")
                    poll_data = await ScraperService.poll_gcrawl_data(job_id)

                    if poll_data and (poll_data.get("data") or poll_data.get("markdown")):
                        logger.info(f" Gcrawl success for {url}")
                        return ScraperService.normalize_gcrawl_response(poll_data, url)

            logger.warning(f"Gcrawl returned empty data for {url}. Response was: {response_data}")

        except httpx.HTTPStatusError as e:
            logger.error(f"Gcrawl HTTP error for {url}: {e.response.status_code} - {str(e)}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Gcrawl failed for {url}: {str(e)}", exc_info=True)

        return []

    @staticmethod
    async def call_gcrawl_api(url: str, crawl_type: str, proxy_mode: str) -> Optional[Dict[str, Any]]:
        """Call the Gcrawl Scrape API with retries and the required payload (v1 Legacy)."""
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
        """Poll the Gcrawl results endpoint until status is 'completed' or 'success' (v1 Legacy)."""
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

                    await asyncio.sleep(5)
                except Exception as e:
                    logger.warning(f"Error while polling Gcrawl task {job_id}: {e}")
                    await asyncio.sleep(5)

    @staticmethod
    def normalize_gcrawl_response(response: Dict[str, Any], root_url: str) -> List[Dict[str, Any]]:
        """Normalize Gcrawl response to existing document schema (v1 Legacy)."""
        documents = []

        if "data" in response:
            data = response.get("data", [])
            if isinstance(data, dict):
                data = [data]
        else:
            data = [response]

        for page in data:
            content = (
                page.get("markdown_content")
                or page.get("markdown")
                or page.get("text")
                or page.get("content")
                or ""
            )
            if not content.strip():
                logger.warning("No extractable text content found on the page; skipping this page.")
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
