"""Crawler selection logic (INGEST-04, D-02, D-04, INGEST-06).

Provides:
  select_crawler(url, html, has_sitemap) -> str
      Route to the right crawler adapter based on site signals.
      Priority: has_sitemap → scrapy; SPA markers → playwright; default → crawl4ai.

  should_escalate(markdown, status_code) -> bool
      Crawl4AI→Playwright escalation predicate (02-05, D-04).
      Returns True when a Crawl4AI result is near-empty and the page returned HTTP 200
      (suggesting JS-rendered content was not captured by the static crawler).

  probe_site(url) -> tuple[str, bool]
      Cheap one-off HTTP probe: fetch entry URL + robots.txt + /sitemap.xml HEAD,
      return (html, has_sitemap). Validates URL with SSRF guard before any fetch.

Security:
  probe_site calls validate_public_url before any network request (T-02-15).

Auto-selection heuristic (D-04):
  1. has_sitemap=True  → "scrapy"     (structured, enumerable site)
  2. SPA markers       → "playwright" (JS-rendered, Playwright escalation — 02-05)
  3. default           → "crawl4ai"   (static/server-rendered HTML)
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urljoin

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

# Near-empty escalation threshold in characters (A2 — tunable).
# Crawl4AI results below this length for a 200 page are escalated to Playwright.
ESCALATION_THRESHOLD_CHARS = 200

# SPA detection markers (Pattern 3 from RESEARCH.md)
_SPA_MARKERS = (
    "__NEXT_DATA__",
    "window.__NUXT__",
    "ng-version=",
    "data-reactroot",
    'id="root"',
    'id="app"',
)
_SPA_MIN_SCRIPTS = 3
_SPA_MAX_TEXT_LENGTH = 500

# Probe timeout — lightweight, should be fast
_PROBE_TIMEOUT = 10.0


def _looks_like_spa(html: str) -> bool:
    """Return True if the HTML has SPA framework markers.

    Uses Pattern 3 heuristic from RESEARCH.md:
      - Contains at least one SPA marker (framework fingerprint)
      - Body text is < 500 chars (near-empty visible content)
      - At least 3 <script> tags (heavy JS bundle loading)

    All three conditions must be true to classify as SPA.
    """
    if not html:
        return False

    has_marker = any(m in html for m in _SPA_MARKERS)
    if not has_marker:
        return False

    # Strip tags for a rough text-length estimate
    import re
    text = re.sub(r"<[^>]+>", " ", html)
    text_len = len(text.strip())
    script_count = html.count("<script")

    return text_len < _SPA_MAX_TEXT_LENGTH and script_count >= _SPA_MIN_SCRIPTS


def select_crawler(
    url: str,
    html: Optional[str] = None,
    has_sitemap: bool = False,
) -> str:
    """Select the appropriate crawler adapter name for a URL.

    Priority (D-04):
      1. has_sitemap=True → "scrapy"     (sitemap wins over everything)
      2. SPA markers      → "playwright" (02-05 escalation path)
      3. default          → "crawl4ai"   (static/server-rendered HTML)

    Parameters
    ----------
    url:
        The URL to crawl.
    html:
        Optional HTML content from a prior fetch attempt or probe.
    has_sitemap:
        Whether the site has a sitemap (from robots.txt Sitemap: or /sitemap.xml 200).

    Returns
    -------
    str
        Crawler adapter name: 'crawl4ai', 'scrapy', or 'playwright'.
    """
    # Priority 1: sitemap-bearing site → Scrapy (structured, enumerable)
    if has_sitemap:
        log.info("select_crawler.scrapy", url=url, reason="has_sitemap")
        return "scrapy"

    # Priority 2: SPA detection → Playwright escalation (02-05 fills this in)
    if html is not None and _looks_like_spa(html):
        log.info("select_crawler.playwright", url=url, reason="spa_markers")
        return "playwright"

    # Default: Crawl4AI for static/server-rendered HTML
    return "crawl4ai"


def should_escalate(markdown: str, status_code: int) -> bool:
    """Return True if a Crawl4AI result should be re-fetched with Playwright.

    Escalation logic (D-04, 02-05, Assumption A2):
      - Only escalate on HTTP 200 responses: a non-200 status indicates a genuine
        server-side error/redirect, not a JS-rendering gap.
      - Escalate when the markdown length is below ESCALATION_THRESHOLD_CHARS
        (default 200 chars, tunable via the module constant).

    This predicate lives in select.py so the orchestrator can call it after
    a Crawl4AI fetch and re-dispatch to the Playwright adapter (the orchestrator's
    escalation hook was reserved in 02-03).

    Parameters
    ----------
    markdown:
        The markdown text returned by Crawl4AI for the page.
    status_code:
        The HTTP status code of the Crawl4AI page fetch.

    Returns
    -------
    bool
        True if the result should be escalated to Playwright.
    """
    if status_code != 200:
        return False
    return len(markdown) < ESCALATION_THRESHOLD_CHARS


def _safe_get(url: str, timeout: float) -> httpx.Response:
    """GET url, re-validating the SSRF guard on every redirect hop (CR-04).

    ``follow_redirects=True`` on httpx bypasses the initial SSRF guard when a
    server responds with a 302 to an RFC-1918 or link-local address.  This
    function follows redirects manually and calls ``validate_public_url`` on
    each Location header before following it.

    Parameters
    ----------
    url:
        The URL to GET (caller must have validated the initial URL already).
    timeout:
        Request timeout in seconds.

    Returns
    -------
    httpx.Response
        The final non-redirect response.

    Raises
    ------
    ValueError
        If any redirect target fails the SSRF guard, or if more than 10
        redirects are encountered.
    """
    from knowledge_lake.pipeline.ingest import validate_public_url

    _MAX_HOPS = 10
    with httpx.Client(follow_redirects=False) as client:
        for _ in range(_MAX_HOPS):
            resp = client.get(url, timeout=timeout)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location", "")
                if not location:
                    return resp
                # Resolve relative Location against current URL
                resolved = urljoin(url, location)
                validate_public_url(resolved)  # raises on private IP
                url = resolved
                continue
            return resp
    raise ValueError("Too many redirects during probe")


def probe_site(url: str) -> tuple[str, bool]:
    """Probe a site to determine if it has a sitemap (for crawler auto-selection).

    Makes ONE cheap GET of the entry URL plus HEAD/GET of /robots.txt and
    /sitemap.xml. Returns (html, has_sitemap).

    Has-sitemap is True if either:
      - /robots.txt contains a 'Sitemap:' directive (case-insensitive)
      - /sitemap.xml returns HTTP 200

    SECURITY (T-02-15, CR-04): validate_public_url is called BEFORE any network
    request AND on every redirect hop so a 302 to an RFC-1918 address cannot
    bypass the guard.

    Parameters
    ----------
    url:
        The entry URL to probe (must be https://).

    Returns
    -------
    tuple[str, bool]
        (entry_html, has_sitemap)

    Raises
    ------
    ValueError
        If url fails SSRF validation (private IP, non-https).
    """
    from knowledge_lake.pipeline.ingest import validate_public_url
    from urllib.parse import urlparse

    # SSRF guard BEFORE any fetch (T-02-15)
    validate_public_url(url)

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # Fetch entry URL — re-validate on each redirect hop (CR-04)
    try:
        entry_resp = _safe_get(url, timeout=_PROBE_TIMEOUT)
        html = entry_resp.text
    except Exception as exc:
        log.warning("probe_site.entry_failed", url=url, error=str(exc))
        html = ""

    has_sitemap = False

    # Check robots.txt for Sitemap: directive.
    # Defense-in-depth: re-validate derived URLs before fetching (WR-007).
    # Even though base is derived from the already-validated entry URL, IPv6
    # bracket notation or user-info tricks could encode a different host after
    # urlparse round-tripping.
    robots_url = f"{base}/robots.txt"
    validate_public_url(robots_url)
    try:
        robots_resp = _safe_get(robots_url, timeout=_PROBE_TIMEOUT)
        if robots_resp.status_code == 200:
            robots_text = robots_resp.text
            # Case-insensitive check for 'Sitemap:' directive
            if any(
                line.strip().lower().startswith("sitemap:")
                for line in robots_text.splitlines()
            ):
                has_sitemap = True
                log.info("probe_site.sitemap_from_robots", url=url)
    except Exception as exc:
        log.warning("probe_site.robots_failed", url=robots_url, error=str(exc))

    # Check /sitemap.xml directly (only if not already detected)
    if not has_sitemap:
        sitemap_url = f"{base}/sitemap.xml"
        validate_public_url(sitemap_url)  # defense-in-depth: re-validate (WR-007)
        try:
            sitemap_resp = _safe_get(sitemap_url, timeout=_PROBE_TIMEOUT)
            if sitemap_resp.status_code == 200:
                has_sitemap = True
                log.info("probe_site.sitemap_from_xml", url=url)
        except Exception as exc:
            log.warning("probe_site.sitemap_failed", url=sitemap_url, error=str(exc))

    log.info("probe_site.complete", url=url, has_sitemap=has_sitemap, html_len=len(html))
    return html, has_sitemap
