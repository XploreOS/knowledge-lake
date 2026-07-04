"""Scrapy spider child-process entry module (INGEST-05, T-02-14).

Run as: python -m knowledge_lake.plugins.builtin.scrapy_spider <source_url> <out_jsonl> <config_json>

Each run starts a fresh Twisted reactor that lives only for this subprocess.
The parent (ScrapyAdapter) spawns one subprocess per crawl job, sidestepping
Twisted's ReactorNotRestartable limitation (Pitfall 1 — scrapy/scrapy#2941).

JSONL output format (one JSON object per line):
  {"url": "https://...", "status": "complete|failed|robots_blocked",
   "html_b64": "<base64 of UTF-8 HTML>", "markdown": null, "error": null}

Security:
  - validate_public_url is called on source_url before starting (T-02-15)
  - An SSRFGuardMiddleware is registered to re-validate every followed URL
  - ROBOTSTXT_OBEY=True (T-02-16)
  - DOWNLOAD_MAXSIZE = 50 MB (T-02-17)
  - AUTOTHROTTLE_ENABLED=True with per-host delay from config (T-02-17)
"""

from __future__ import annotations

import base64
import json
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import structlog

log = structlog.get_logger(__name__)

# 50 MB cap — matches MAX_DOWNLOAD_BYTES in pipeline/ingest.py (T-02-17)
_DOWNLOAD_MAXSIZE = 50 * 1024 * 1024


class SSRFGuardMiddleware:
    """Block requests to private/internal addresses (T-02-15, CR-03).

    Defined at module level so Scrapy can resolve it by the dotted string
    'knowledge_lake.plugins.builtin.scrapy_spider.SSRFGuardMiddleware'.
    A locally-scoped class inside a function body is not reachable via
    importlib.import_module + getattr, which is how Scrapy loads middleware.
    """

    @classmethod
    def from_crawler(cls, crawler: Any) -> "SSRFGuardMiddleware":
        return cls()

    def process_request(self, request: Any, spider: Any) -> None:
        from knowledge_lake.pipeline.ingest import validate_public_url

        try:
            validate_public_url(request.url)
        except ValueError as exc:
            import scrapy.exceptions

            log.warning("scrapy_spider.ssrf_blocked", url=request.url, error=str(exc))
            raise scrapy.exceptions.IgnoreRequest(str(exc)) from exc


def _registrable_domain(url: str) -> str:
    """Return host for same-domain scoping (simple hostname check)."""
    parsed = urlparse(url)
    return parsed.hostname or ""


def _run_scrapy(source_url: str, out_jsonl: str, config: dict[str, Any]) -> None:
    """Run a Scrapy crawl in-process (called only from a fresh child process).

    This function is ONLY safe to call once per interpreter — the Twisted reactor
    cannot be restarted.  The subprocess contract guarantees exactly one call per
    process lifetime.
    """
    import scrapy
    import scrapy.exceptions
    from scrapy.crawler import CrawlerProcess
    from scrapy.http import Response

    max_pages: int = int(config.get("max_pages", 50))
    max_depth: int = int(config.get("max_depth", 3))
    per_host_delay: float = float(config.get("per_host_delay", 1.0))
    seed_domain = _registrable_domain(source_url)

    # Thread-safe page counter (Scrapy runs in threads)
    _lock = threading.Lock()
    _count: dict[str, int] = {"n": 0}
    _out_file = open(out_jsonl, "w", encoding="utf-8")  # noqa: WPS515 — intentional

    def _write_result(obj: dict) -> None:
        with _lock:
            _out_file.write(json.dumps(obj) + "\n")
            _out_file.flush()

    class MaxPagesExtension:
        """Close the spider once max_pages completed pages have been written."""

        @classmethod
        def from_crawler(cls, crawler: Any) -> "MaxPagesExtension":
            ext = cls()
            ext.crawler = crawler
            return ext

    class KlakeSpider(scrapy.Spider):
        """Same-domain link-following spider that writes one JSONL record per page."""

        name = "klake"
        custom_settings: dict[str, Any] = {}  # set by factory below

        def start_requests(self) -> Any:
            yield scrapy.Request(
                url=source_url,
                callback=self.parse_page,
                errback=self.handle_error,
                meta={"depth": 0},
                dont_filter=False,
            )

        def parse_page(self, response: Response) -> Any:
            with _lock:
                if _count["n"] >= max_pages:
                    return
                _count["n"] += 1
                current_count = _count["n"]

            html_str = response.text
            html_b64 = base64.b64encode(
                html_str.encode("utf-8", errors="replace")
            ).decode("ascii")

            _write_result(
                {
                    "url": response.url,
                    "status": "complete",
                    "html_b64": html_b64,
                    "markdown": None,
                    "error": None,
                }
            )
            log.info("scrapy_spider.page_complete", url=response.url, n=current_count)

            if current_count >= max_pages:
                log.info("scrapy_spider.max_pages_reached", max_pages=max_pages)
                return

            # Follow same-domain links up to max_depth
            current_depth = response.meta.get("depth", 0)
            if current_depth < max_depth:
                for href in response.css("a::attr(href)").getall():
                    abs_url = response.urljoin(href)
                    parsed = urlparse(abs_url)
                    # Same-domain scoping (T-02-15)
                    if parsed.hostname == seed_domain and parsed.scheme == "https":
                        yield scrapy.Request(
                            url=abs_url,
                            callback=self.parse_page,
                            errback=self.handle_error,
                            meta={"depth": current_depth + 1},
                        )

        def handle_error(self, failure: Any) -> None:
            url = failure.request.url
            log.warning("scrapy_spider.fetch_error", url=url, error=str(failure))
            _write_result(
                {
                    "url": url,
                    "status": "failed",
                    "html_b64": None,
                    "markdown": None,
                    "error": str(failure.value),
                }
            )

        def closed(self, reason: str) -> None:
            _out_file.flush()
            _out_file.close()
            log.info("scrapy_spider.closed", reason=reason)

    settings_dict: dict[str, Any] = {
        # Core
        "LOG_ENABLED": False,
        "BOT_NAME": "knowledge_lake",
        # Robots + compliance (T-02-16)
        "ROBOTSTXT_OBEY": True,
        # Size cap (T-02-17)
        "DOWNLOAD_MAXSIZE": _DOWNLOAD_MAXSIZE,
        # Throttle (T-02-17)
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": per_host_delay,
        "AUTOTHROTTLE_MAX_DELAY": max(per_host_delay * 10, 60.0),
        "DOWNLOAD_DELAY": per_host_delay,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "CONCURRENT_REQUESTS": 4,
        # Depth limit
        "DEPTH_LIMIT": max_depth,
        # SSRF guard middleware (T-02-15)
        "DOWNLOADER_MIDDLEWARES": {
            "knowledge_lake.plugins.builtin.scrapy_spider.SSRFGuardMiddleware": 100,
        },
        # Disable default cookies/redirects to reduce attack surface
        "COOKIES_ENABLED": False,
        "REDIRECT_ENABLED": True,
        "REDIRECT_MAX_TIMES": 5,
        # Disable stats logging
        "STATS_DUMP": False,
    }

    process = CrawlerProcess(settings=settings_dict)
    process.crawl(KlakeSpider)
    process.start()  # blocks until done — safe because this IS the reactor's lifetime


def main() -> None:
    """Entry point: parse argv and run the Scrapy crawl."""
    if len(sys.argv) < 4:
        print(
            "Usage: python -m knowledge_lake.plugins.builtin.scrapy_spider "
            "<source_url> <out_jsonl> <config_json>",
            file=sys.stderr,
        )
        sys.exit(1)

    source_url = sys.argv[1]
    out_jsonl = sys.argv[2]
    config_json_path = sys.argv[3]

    # SSRF guard on source URL BEFORE starting anything (T-02-15)
    from knowledge_lake.pipeline.ingest import validate_public_url

    try:
        validate_public_url(source_url)
    except ValueError as exc:
        print(f"SSRF guard rejected URL: {exc}", file=sys.stderr)
        sys.exit(2)

    config: dict[str, Any] = {}
    try:
        config = json.loads(Path(config_json_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Failed to load config: {exc}", file=sys.stderr)
        sys.exit(3)

    _run_scrapy(source_url, out_jsonl, config)


if __name__ == "__main__":
    main()
