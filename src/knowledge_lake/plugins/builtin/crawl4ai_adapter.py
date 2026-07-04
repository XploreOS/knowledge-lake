"""Crawl4AI adapter — async-first web crawler with native robots.txt (INGEST-04).

Implements CrawlerPlugin for the Crawl4AI library (0.9.x). Features:
  - Async page fetching via AsyncWebCrawler
  - Native robots.txt checking via check_robots_txt=True
  - SSRF guard: validate_public_url called BEFORE every fetch (T-02-09)
  - 50 MB size cap on returned HTML bytes (T-02-12)
  - In-process eager execution; results cached by job_id

Entry point:
    [project.entry-points."knowledge_lake.crawlers"]
    crawl4ai = "knowledge_lake.plugins.builtin.crawl4ai_adapter:Crawl4AIAdapter"

The adapter's CrawlerPlugin interface (start_crawl/poll_status/get_results) wraps
the single-page-at-a-time nature of Crawl4AI: the orchestrator (pipeline/crawl.py)
drives page-level iteration; the adapter handles one URL at a time via fetch_page().
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

import structlog

from knowledge_lake.pipeline.ingest import validate_public_url, MAX_DOWNLOAD_BYTES
from knowledge_lake.plugins.protocols import CrawlJob, CrawlPageResult, CrawlerPlugin

log = structlog.get_logger(__name__)


class Crawl4AIAdapter:
    """Crawl4AI-backed CrawlerPlugin implementation.

    Satisfies the CrawlerPlugin Protocol (runtime_checkable).
    Uses AsyncWebCrawler with CrawlerRunConfig for page fetching.

    The adapter exposes a dual interface:
      - CrawlerPlugin methods (start_crawl/poll_status/get_results) for protocol
      - fetch_page(url) for the orchestrator's page-level loop (preferred path)

    Protocol attributes:
        name = 'crawl4ai'
    """

    name: str = "crawl4ai"

    def __init__(self) -> None:
        self._jobs: dict[str, CrawlJob] = {}
        self._results: dict[str, list[CrawlPageResult]] = {}

    def start_crawl(self, source_url: str, config: dict[str, Any]) -> CrawlJob:
        """Initiate a crawl job (protocol compliance).

        For in-process use, the orchestrator drives page iteration directly
        via fetch_page(). This method creates the job record.
        """
        from knowledge_lake.ids import new_id

        job_id = new_id("crawl_job")
        job = CrawlJob(
            job_id=job_id,
            source_url=source_url,
            crawler=self.name,
            status="running",
            config=config,
        )
        self._jobs[job_id] = job
        self._results[job_id] = []
        return job

    def poll_status(self, job_id: str) -> str:
        """Return current job status."""
        job = self._jobs.get(job_id)
        if job is None:
            return "unknown"
        return job.status

    def get_results(self, job_id: str) -> list[CrawlPageResult]:
        """Retrieve cached results for a completed job."""
        if job_id not in self._results:
            raise RuntimeError(f"No results for job {job_id}")
        return self._results[job_id]

    async def fetch_page(self, url: str) -> CrawlPageResult:
        """Fetch a single page via Crawl4AI with SSRF and robots guards.

        SECURITY (T-02-09): validate_public_url is called BEFORE any network
        request. If it raises, a ValueError propagates — the orchestrator must
        catch this to record an appropriate status.

        Args:
            url: The URL to fetch (must be https://).

        Returns:
            CrawlPageResult with status 'complete' or 'robots_blocked'.

        Raises:
            ValueError: If the URL fails SSRF validation.
        """
        # SSRF guard — MUST run before any fetch (T-02-09, Pitfall 2)
        validate_public_url(url)

        from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode

        config = CrawlerRunConfig(
            check_robots_txt=True,
            cache_mode=CacheMode.BYPASS,
        )

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url, config=config)

        # Detect robots block: Crawl4AI signals robots-blocked via
        # success=False with status_code 403 (Assumption A3 from RESEARCH)
        if not result.success:
            status_code = getattr(result, "status_code", None)
            if status_code == 403:
                log.info("crawl4ai.robots_blocked", url=url)
                return CrawlPageResult(
                    url=url,
                    status="robots_blocked",
                    html=None,
                    markdown=None,
                )
            # Other failure
            error_msg = getattr(result, "error_message", None) or "Unknown error"
            log.warning("crawl4ai.fetch_failed", url=url, error=error_msg)
            return CrawlPageResult(
                url=url,
                status="failed",
                html=None,
                markdown=None,
                error=str(error_msg),
            )

        # Success — extract html and markdown
        html_str = result.html or ""
        html_bytes = html_str.encode("utf-8", errors="replace")

        # Size cap enforcement (T-02-12)
        if len(html_bytes) > MAX_DOWNLOAD_BYTES:
            log.warning(
                "crawl4ai.size_exceeded",
                url=url,
                size=len(html_bytes),
                cap=MAX_DOWNLOAD_BYTES,
            )
            return CrawlPageResult(
                url=url,
                status="failed",
                html=None,
                markdown=None,
                error=f"Response exceeded {MAX_DOWNLOAD_BYTES // (1024*1024)} MB cap",
            )

        markdown_text = str(result.markdown) if result.markdown else ""
        fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        log.info(
            "crawl4ai.page_complete",
            url=url,
            html_size=len(html_bytes),
            md_len=len(markdown_text),
        )

        return CrawlPageResult(
            url=url,
            status="complete",
            html=html_bytes,
            markdown=markdown_text,
            fetched_at=fetched_at,
        )

    def fetch_page_sync(self, url: str) -> CrawlPageResult:
        """Synchronous wrapper around fetch_page for non-async contexts."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # We're inside an existing event loop — use a new thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self.fetch_page(url))
                return future.result()
        else:
            return asyncio.run(self.fetch_page(url))
