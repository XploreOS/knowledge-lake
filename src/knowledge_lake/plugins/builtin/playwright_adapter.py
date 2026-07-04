"""Playwright adapter — async headless-browser crawler for SPA/JS pages (INGEST-06).

Implements CrawlerPlugin using the async Playwright API with Chromium headless.

Security hardening (T-02-18, T-02-19, T-02-20, T-02-21):
  - SSRF guard: validate_public_url called BEFORE every navigation (T-02-19)
  - Robots: fetch_robots + is_allowed; disallowed → robots_blocked, no render (T-02-20, D-11)
  - Rate limit: three-tier per-host delay via crawl/ratelimit before navigation (T-02-21)
  - Downloads disabled in browser context (T-02-18)
  - Finite per-page navigation timeout (T-02-18)
  - Rendered-content size cap at MAX_DOWNLOAD_BYTES (T-02-21)

Entry point:
    [project.entry-points."knowledge_lake.crawlers"]
    playwright = "knowledge_lake.plugins.builtin.playwright_adapter:PlaywrightAdapter"

The adapter's CrawlerPlugin interface (start_crawl/poll_status/get_results) wraps
the single-page-at-a-time nature of Playwright: the orchestrator drives page-level
iteration; the adapter handles one URL at a time via fetch_page().
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any, Optional
from urllib.parse import urlparse

import structlog

from knowledge_lake.crawl.ratelimit import PerHostLimiter, resolve_delay
from knowledge_lake.crawl.robots import fetch_robots
from knowledge_lake.pipeline.ingest import validate_public_url, MAX_DOWNLOAD_BYTES
from knowledge_lake.plugins.protocols import CrawlJob, CrawlPageResult, CrawlerPlugin

log = structlog.get_logger(__name__)

# Per-page navigation timeout in milliseconds (D-11, T-02-18 hostile-page hardening).
# 30 seconds is generous for a JS-heavy SPA; prevents runaway page loads.
_NAV_TIMEOUT_MS = 30_000

def _html_to_markdown(html: str, url: str) -> str:
    """Convert rendered HTML to markdown using crawl4ai's DefaultMarkdownGenerator.

    Reuses the same markdown approach as the Crawl4AI adapter — no hand-rolling
    (plan spec, D-11).  If crawl4ai is unavailable, returns the raw HTML as
    plain text (fallback for unit tests that do not need the full library).
    """
    try:
        from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

        generator = DefaultMarkdownGenerator()
        result = generator.generate_markdown(html, base_url=url, citations=False)
        return result.raw_markdown or ""
    except ImportError:
        # Minimal fallback for test environments without crawl4ai installed
        import re
        return re.sub(r"<[^>]+>", " ", html).strip()


class PlaywrightAdapter:
    """Playwright-backed CrawlerPlugin for JavaScript-heavy / SPA pages.

    Satisfies the CrawlerPlugin Protocol (runtime_checkable).
    Launches Chromium headless with downloads disabled and a finite navigation
    timeout.  Robots and rate-limit checks happen BEFORE the browser navigates
    so no request is made to disallowed or unvalidated URLs.

    Protocol attributes:
        name = 'playwright'
    """

    name: str = "playwright"

    def __init__(
        self,
        nav_timeout_ms: int = _NAV_TIMEOUT_MS,
        global_rate_limit: float = 1.0,
    ) -> None:
        """Initialise the adapter.

        Args:
            nav_timeout_ms:      Per-page navigation timeout in ms (default: 30 000).
            global_rate_limit:   Global rate-limit default in seconds (Tier 3).
        """
        self._jobs: dict[str, CrawlJob] = {}
        self._results: dict[str, list[CrawlPageResult]] = {}
        self._nav_timeout_ms = nav_timeout_ms
        self._global_rate_limit = global_rate_limit
        # Per-instance limiter: asyncio.Lock objects are bound to the event loop
        # that created them.  A module-level singleton would hold stale locks
        # from a dead event loop when fetch_page_sync creates a new loop via
        # asyncio.run(), causing RuntimeError on the second call (WR-002).
        self._limiter = PerHostLimiter()

    # ── CrawlerPlugin protocol methods ────────────────────────────────────────

    def start_crawl(self, source_url: str, config: dict[str, Any]) -> CrawlJob:
        """Initiate a crawl job record (protocol compliance).

        For in-process use the orchestrator drives page iteration directly via
        fetch_page(). This method creates the job record only.
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

    # ── Primary async interface ───────────────────────────────────────────────

    async def fetch_page(
        self,
        url: str,
        source_config: Optional[dict[str, Any]] = None,
    ) -> CrawlPageResult:
        """Fetch a single page via Playwright headless Chromium.

        Security order (matches D-11, T-02-18, T-02-19, T-02-20, T-02-21):
          1. SSRF guard via validate_public_url (T-02-19) — no net request on fail
          2. Robots check via fetch_robots + is_allowed (T-02-20) — no render on fail
          3. Rate-limit wait via PerHostLimiter (T-02-21) — polite crawling
          4. Headless Chromium navigation with downloads disabled + timeout (T-02-18)
          5. Rendered-content size cap (T-02-21)
          6. HTML → markdown via crawl4ai DefaultMarkdownGenerator

        Args:
            url:           The URL to navigate to (must be https://).
            source_config: Optional per-source config dict for rate-limit override.

        Returns:
            CrawlPageResult with status 'complete', 'robots_blocked', or 'failed'.

        Raises:
            ValueError: If the URL fails SSRF validation.
        """
        # 1. SSRF guard — MUST run before any network request (T-02-19)
        validate_public_url(url)

        # 2. Robots check — MUST run before rendering (T-02-20, D-11)
        # fetch_robots uses httpx.Client (synchronous) — offload to a thread to
        # avoid blocking the event loop during robots.txt fetch (WR-004).
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        url_path = parsed.path or "/"

        robots_policy = await asyncio.get_running_loop().run_in_executor(None, fetch_robots, base_url)
        robots_delay = robots_policy.crawl_delay()

        if not robots_policy.is_allowed(url_path):
            log.info("playwright.robots_blocked", url=url)
            return CrawlPageResult(
                url=url,
                status="robots_blocked",
                html=None,
                markdown=None,
            )

        # 3. Rate-limit wait — before navigation (T-02-21)
        delay = resolve_delay(source_config, robots_delay, self._global_rate_limit)
        await self._limiter.wait(url, delay)

        # 4. Headless Chromium navigation
        try:
            html = await self._render_page(url)
        except Exception as exc:
            log.warning("playwright.render_failed", url=url, error=str(exc))
            return CrawlPageResult(
                url=url,
                status="failed",
                html=None,
                markdown=None,
                error=str(exc),
            )

        html_bytes = html.encode("utf-8", errors="replace")

        # 5. Size cap (T-02-21)
        if len(html_bytes) > MAX_DOWNLOAD_BYTES:
            log.warning(
                "playwright.size_exceeded",
                url=url,
                size=len(html_bytes),
                cap=MAX_DOWNLOAD_BYTES,
            )
            return CrawlPageResult(
                url=url,
                status="failed",
                html=None,
                markdown=None,
                error=f"Rendered content exceeded {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB cap",
            )

        # 6. HTML → markdown
        markdown_text = _html_to_markdown(html, url)
        fetched_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        log.info(
            "playwright.page_complete",
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

    async def _render_page(self, url: str) -> str:
        """Launch Chromium headless and navigate to url, returning rendered HTML.

        Hardening (T-02-18):
          - downloads disabled via accept_downloads=False
          - finite per-page navigation timeout (_nav_timeout_ms)
          - wait_until='networkidle' to capture JS-rendered content
        """
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    accept_downloads=False,
                )
                page = await context.new_page()

                # Navigate with finite timeout (hostile-page hardening)
                await page.goto(
                    url,
                    timeout=self._nav_timeout_ms,
                    wait_until="networkidle",
                )

                html = await page.content()
            finally:
                await browser.close()

        return html

    def fetch_page_sync(
        self,
        url: str,
        source_config: Optional[dict[str, Any]] = None,
    ) -> CrawlPageResult:
        """Synchronous wrapper around fetch_page for non-async contexts."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self.fetch_page(url, source_config))
                return future.result()
        else:
            return asyncio.run(self.fetch_page(url, source_config))
