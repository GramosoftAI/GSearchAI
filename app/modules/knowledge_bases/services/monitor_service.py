import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Any
from uuid import UUID
import httpx
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import EmailService
from app.core.config import get_settings
from ..models import WebsiteMonitor, MonitoredUrlSnapshot, KnowledgeBase, DocumentChunk
from .scraper_service import ScraperService
from ..service import KnowledgeBaseService

logger = logging.getLogger(__name__)
settings = get_settings()


class SitemapMonitorService:
    """
    Integrates directly with GCrawl's official Website Monitor API:
    - POST /gc/api/v1/monitor/website (Register monitor: manual or scheduled)
    - GET  /gc/api/v1/monitor/website (List monitors)
    - POST /gc/api/v1/monitor/website/{monitor_id}/run-now (Execute manual sync)
    """

    @classmethod
    def _get_gcrawl_headers(cls) -> Dict[str, str]:
        api_key = getattr(settings, "gcrawl_api_key", None)
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-API-Key": api_key or "",
            "x-api-key": api_key or ""
        }

    @classmethod
    async def resolve_best_sitemap_url(cls, raw_url: str) -> str:
        """
        Determines the most comprehensive sitemap URL:
        1. Checks {origin}/sitemap_index.xml first (for multi-sitemap & subdomains).
        2. Falls back to {origin}/sitemap.xml (for standard sites & SPAs).
        3. Falls back to {origin}/wp-sitemap.xml (for WordPress).
        """
        from urllib.parse import urlparse

        raw_url = raw_url.strip()
        try:
            parsed = urlparse(raw_url if raw_url.startswith("http") else f"https://{raw_url}")
            origin = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            return raw_url

        # Priority candidates: sitemap_index.xml first, then sitemap.xml
        candidates = [
            f"{origin}/sitemap_index.xml",
            f"{origin}/sitemap.xml",
            f"{origin}/wp-sitemap.xml"
        ]

        # If user explicitly passed an XML file, test it first
        if raw_url.endswith(".xml") and raw_url not in candidates:
            candidates.insert(0, raw_url)

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
            "Accept": "application/xml, text/xml, */*"
        }

        async with httpx.AsyncClient(headers=headers, timeout=12.0, follow_redirects=True) as client:
            for cand in candidates:
                try:
                    resp = await client.get(cand)
                    ct = resp.headers.get("content-type", "").lower()
                    text_start = resp.text.strip()[:120].lower()

                    is_valid_xml = (
                        resp.status_code == 200
                        and ("xml" in ct or text_start.startswith("<?xml") or "<urlset" in text_start or "<sitemapindex" in text_start)
                        and not text_start.startswith("<!doctype")
                        and not text_start.startswith("<html")
                    )

                    if is_valid_xml:
                        logger.info(f"Resolved best sitemap for {raw_url} -> {cand}")
                        return cand
                except Exception as e:
                    logger.debug(f"Candidate {cand} check failed: {e}")

        # Default fallback
        return f"{origin}/sitemap_index.xml"

    @classmethod
    async def register_gcrawl_monitor(
        cls,
        sitemap_url: str,
        manual_trigger: bool = True,
        schedule_interval_days: Optional[int] = 1,
        geo: str = "IN"
    ) -> Optional[str]:
        """
        Registers or retrieves a monitor on GCrawl.
        Returns the GCrawl monitor_id.
        """
        url = "https://gcrawlai.com/gc/api/v1/monitor/website"
        payload = {
            "sitemap_url": sitemap_url,
            "manual_trigger": manual_trigger,
            "geo": geo
        }
        if not manual_trigger and schedule_interval_days:
            payload["schedule_interval_days"] = schedule_interval_days

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                res = await client.post(url, json=payload, headers=cls._get_gcrawl_headers())
                if res.status_code in (200, 201):
                    data = res.json()
                    monitor_id = data.get("monitor_id") or data.get("id") or (data.get("data") and data["data"].get("id"))
                    return monitor_id
                elif res.status_code == 400 and "already being monitored" in res.text:
                    # Fetch existing monitors from GCrawl to find the monitor_id
                    list_res = await client.get(url, headers=cls._get_gcrawl_headers())
                    if list_res.status_code == 200:
                        monitors = list_res.json().get("monitors", [])
                        for m in monitors:
                            if m.get("sitemap_url", "").rstrip("/") == sitemap_url.rstrip("/"):
                                return m.get("monitor_id")
                else:
                    logger.warning(f"GCrawl monitor registration returned {res.status_code}: {res.text}")
        except Exception as e:
            logger.error(f"Error registering monitor on GCrawl for {sitemap_url}: {e}")
        return None

    @classmethod
    async def trigger_run_now(cls, gcrawl_monitor_id: str, timeout: float = 90.0) -> Dict[str, Any]:
        """
        Calls POST /gc/api/v1/monitor/website/{monitor_id}/run-now on GCrawl.
        Returns the diff details (added_urls, modified_urls, removed_urls, total_urls).
        """
        url = f"https://gcrawlai.com/gc/api/v1/monitor/website/{gcrawl_monitor_id}/run-now"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                res = await client.post(url, headers=cls._get_gcrawl_headers())
                if res.status_code == 200:
                    return res.json()
                else:
                    logger.error(f"GCrawl run-now returned {res.status_code}: {res.text}")
                    return {"status": "error", "message": f"GCrawl returned {res.status_code}"}
        except Exception as e:
            logger.error(f"Error calling GCrawl run-now for {gcrawl_monitor_id}: {e}")
            return {"status": "error", "message": str(e)}

    @classmethod
    async def preview_sitemap_diff(
        cls,
        db: AsyncSession,
        sitemap_url: str,
        kb_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes manual sync via GCrawl API:
        1. Ensures monitor exists on GCrawl (manual_trigger: True).
        2. Calls /run-now to obtain live sitemap URLs & diffs from GCrawl.
        3. Diffs against KB chunks to show:
           - already_crawled_urls (In KB - Green)
           - new_urls (New / Uncrawled - Red)
        """
        # Resolve best sitemap candidate (sitemap_index.xml first, fallback to sitemap.xml)
        sitemap_clean = await cls.resolve_best_sitemap_url(sitemap_url)

        # 1. Register or find existing GCrawl monitor
        gcrawl_id = await cls.register_gcrawl_monitor(sitemap_clean, manual_trigger=True)
        if not gcrawl_id:
            # Fallback: check if we have it in our DB (use first() to prevent MultipleResultsFound)
            stmt = select(WebsiteMonitor).where(WebsiteMonitor.sitemap_url == sitemap_clean).order_by(WebsiteMonitor.created_at.desc())
            res = await db.execute(stmt)
            m = res.scalars().first()
            if m and m.gcrawl_monitor_id:
                gcrawl_id = m.gcrawl_monitor_id

        # 2. Call run-now on GCrawl
        gcrawl_diff: Dict[str, Any] = {}
        if gcrawl_id:
            gcrawl_diff = await cls.trigger_run_now(gcrawl_id)

        # 3. Check what URLs are already in KB chunks
        crawled_in_kb: Set[str] = set()
        if kb_id:
            try:
                chunk_stmt = select(DocumentChunk.section, DocumentChunk.metadata_json).where(DocumentChunk.kb_id == UUID(kb_id))
                chunk_res = await db.execute(chunk_stmt)
                for sec, meta in chunk_res.all():
                    if sec and sec.startswith("http"):
                        crawled_in_kb.add(sec.strip())
                        crawled_in_kb.add(sec.strip().rstrip("/"))
                    if meta and isinstance(meta, dict):
                        for k in ("source_url", "url", "source"):
                            val = meta.get(k)
                            if val and isinstance(val, str) and val.startswith("http"):
                                crawled_in_kb.add(val.strip())
                                crawled_in_kb.add(val.strip().rstrip("/"))
            except Exception as e:
                logger.warning(f"Error checking existing KB chunks: {e}")

        def is_url_in_set(target_url: str, url_set: Set[str]) -> bool:
            u_clean = target_url.strip()
            return u_clean in url_set or u_clean.rstrip("/") in url_set or f"{u_clean.rstrip('/')}/" in url_set

        # If GCrawl returned added_urls or total_urls
        added_urls = gcrawl_diff.get("added_urls", [])
        total_urls_count = gcrawl_diff.get("total_urls", 0)

        # Fallback to direct sitemap parse if GCrawl run-now returned empty total
        all_sitemap_urls = []
        if total_urls_count == 0 or not added_urls or any(u.endswith(".xml") for u in (all_sitemap_urls or added_urls)):
            from urllib.parse import urlparse
            import xml.etree.ElementTree as ET

            queue = [sitemap_clean]
            visited = set()

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)",
                "Accept": "application/xml, text/xml, */*"
            }

            async with httpx.AsyncClient(headers=headers, timeout=15, follow_redirects=True) as client:
                try:
                    resp = await client.get(sitemap_clean)
                    if resp.status_code == 200 and ("xml" in resp.headers.get("content-type", "") or resp.text.strip().startswith("<?xml")):
                        root = ET.fromstring(resp.text)
                        tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag

                        if tag == "sitemapindex":
                            # Extract child sitemaps
                            child_sitemaps = []
                            for elem in root.iter():
                                el_tag = elem.tag.split("}")[-1]
                                if el_tag == "loc" and elem.text and elem.text.strip().startswith("http"):
                                    child_sitemaps.append(elem.text.strip())

                            # Fetch child sitemaps concurrently
                            async def fetch_child(child_url: str):
                                try:
                                    c_resp = await client.get(child_url)
                                    if c_resp.status_code == 200:
                                        c_root = ET.fromstring(c_resp.text)
                                        found = []
                                        for el in c_root.iter():
                                            if el.tag.split("}")[-1] == "loc" and el.text and el.text.strip().startswith("http"):
                                                t = el.text.strip()
                                                if not t.endswith(".xml"):
                                                    found.append(t)
                                        return found
                                except Exception:
                                    pass
                                return []

                            results = await asyncio.gather(*[fetch_child(u) for u in child_sitemaps], return_exceptions=True)
                            for r in results:
                                if isinstance(r, list):
                                    for p in r:
                                        if p not in all_sitemap_urls:
                                            all_sitemap_urls.append(p)
                        else:
                            for elem in root.iter():
                                if elem.tag.split("}")[-1] == "loc" and elem.text and elem.text.strip().startswith("http"):
                                    t = elem.text.strip()
                                    if not t.endswith(".xml") and t not in all_sitemap_urls:
                                        all_sitemap_urls.append(t)
                except Exception as e:
                    logger.warning(f"Error reading root sitemap {sitemap_clean}: {e}")

        if not all_sitemap_urls and added_urls:
            all_sitemap_urls = added_urls

        # Categorize
        already_crawled: List[str] = []
        brand_new_urls: List[str] = []
        uncrawled_urls: List[str] = []

        for u in all_sitemap_urls:
            if is_url_in_set(u, crawled_in_kb):
                already_crawled.append(u)
            elif u in added_urls:
                brand_new_urls.append(u)
            else:
                uncrawled_urls.append(u)

        all_new_and_uncrawled = brand_new_urls + uncrawled_urls
        if not all_sitemap_urls and crawled_in_kb:
            already_crawled = list(crawled_in_kb)

        return {
            "success": True,
            "gcrawl_monitor_id": gcrawl_id,
            "sitemap_url": sitemap_clean,
            "total_sitemap_urls": len(all_sitemap_urls) or total_urls_count,
            "already_crawled_count": len(already_crawled),
            "already_crawled_urls": already_crawled,
            "brand_new_count": len(brand_new_urls),
            "uncrawled_count": len(uncrawled_urls),
            "new_urls_count": len(all_new_and_uncrawled),
            "brand_new_urls": brand_new_urls,
            "uncrawled_urls": uncrawled_urls,
            "new_urls": all_new_and_uncrawled,
            "has_changed": gcrawl_diff.get("has_changed", False),
            "change_summary": gcrawl_diff.get("change_summary", "")
        }

    @classmethod
    async def check_and_sync(
        cls,
        db: AsyncSession,
        monitor: WebsiteMonitor,
        user_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes scheduled sync via GCrawl API:
        1. Ensures monitor exists on GCrawl.
        2. Calls /run-now to get diffs.
        3. Dispatches alert if changes found.
        4. Auto-ingests into Knowledge Base if auto_crawl is True.
        """
        sitemap_url = monitor.sitemap_url
        logger.info(f"Triggering GCrawl scheduled sync for monitor {monitor.id} ({sitemap_url})")

        # 1. Ensure GCrawl monitor ID is present
        if not monitor.gcrawl_monitor_id:
            monitor.gcrawl_monitor_id = await cls.register_gcrawl_monitor(
                sitemap_url=sitemap_url,
                manual_trigger=monitor.manual_trigger,
                schedule_interval_days=monitor.schedule_interval_days or 1
            )
            if monitor.gcrawl_monitor_id:
                await db.commit()

        if not monitor.gcrawl_monitor_id:
            logger.warning(f"No GCrawl monitor ID available for {sitemap_url}")
            return {"status": "error", "message": "Failed to register monitor on GCrawl"}

        # 2. Execute run-now on GCrawl
        diff = await cls.trigger_run_now(monitor.gcrawl_monitor_id)
        has_changed = diff.get("has_changed", False)
        added_urls = diff.get("added_urls", [])
        modified_urls = diff.get("modified_urls", [])

        # 3. Email Alert if changes exist
        email_sent = False
        if has_changed and monitor.notify_email and (added_urls or modified_urls):
            try:
                email_sent = await EmailService.send_sitemap_monitor_alert(
                    email=monitor.notify_email,
                    user_name=user_name or "Subscriber",
                    sitemap_url=sitemap_url,
                    total_urls=diff.get("total_urls", 0),
                    new_urls=added_urls,
                    modified_urls=modified_urls,
                    auto_crawled=monitor.auto_crawl and bool(monitor.knowledge_base_id)
                )
            except Exception as e:
                logger.error(f"Failed to send sitemap alert email: {e}")

        # 4. Auto-crawl new URLs into KB
        chunks_created = 0
        if monitor.auto_crawl and monitor.knowledge_base_id and (added_urls or modified_urls):
            target_urls = (added_urls + modified_urls)[:20]
            try:
                kb_service = KnowledgeBaseService(db, str(monitor.tenant_id))
                for target_url in target_urls:
                    try:
                        docs = await ScraperService.extract_website_content(url=target_url, crawl_type="single")
                        for doc in docs:
                            content = f"# SOURCE: {doc['source']}\n\n{doc['content']}"
                            ingest_res = await kb_service.ingest_document(
                                kb_id=str(monitor.knowledge_base_id),
                                text=content,
                                source=doc["source"]
                            )
                            if ingest_res.get("success"):
                                chunks_created += ingest_res.get("data", {}).get("chunks_created", 0)
                    except Exception as err:
                        logger.error(f"Error auto-crawling page {target_url}: {err}")
            except Exception as e:
                logger.error(f"Error during auto-ingestion for monitor {monitor.id}: {e}")

        monitor.last_checked_at = datetime.now(timezone.utc)
        monitor.total_urls_detected = diff.get("total_urls", monitor.total_urls_detected)
        await db.commit()

        return {
            "monitor_id": str(monitor.id),
            "gcrawl_monitor_id": monitor.gcrawl_monitor_id,
            "status": "success",
            "has_changed": has_changed,
            "new_urls": added_urls,
            "modified_urls": modified_urls,
            "email_sent": email_sent,
            "chunks_created": chunks_created
        }
