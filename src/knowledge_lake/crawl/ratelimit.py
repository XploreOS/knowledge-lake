"""Three-tier rate-limit resolver and per-host async limiter (INGEST-09, D-12, T-02-07).

The resolver enforces politeness by selecting the strictest applicable delay:
  Tier 1: Source.config['rate_limit_seconds'] (per-source operator override)
  Tier 2: robots.txt Crawl-delay (site-wide signal from the target)
  Tier 3: CrawlSettings.rate_limit_seconds (global default)

The per-host limiter tracks last-fetch time keyed by registrable domain (via
tldextract) so multi-host crawls throttle independently per host.

Functions:
    resolve_delay  — tier-ordered delay resolution
    _domain_key    — extract registrable domain from a URL (limiter key)

Classes:
    PerHostLimiter — async-aware per-host rate limiter (asyncio.sleep-based)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional
from urllib.parse import urlparse

import tldextract

log = logging.getLogger(__name__)


def resolve_delay(
    source_config: Optional[dict[str, Any]],
    robots_crawl_delay: Optional[float],
    global_default: float,
) -> float:
    """Resolve the effective crawl delay using the three-tier priority (D-12).

    Tier order (first match wins):
      1. source_config['rate_limit_seconds'] — per-source operator override
      2. robots_crawl_delay — Crawl-delay from robots.txt
      3. global_default — CrawlSettings.rate_limit_seconds

    Parameters
    ----------
    source_config:
        The Source.config dict (may be None or empty).
    robots_crawl_delay:
        Crawl-delay extracted from robots.txt (None if absent).
    global_default:
        The global default from CrawlSettings.rate_limit_seconds.

    Returns
    -------
    float
        The resolved delay in seconds.
    """
    # Tier 1: source config override
    if source_config and "rate_limit_seconds" in source_config:
        return float(source_config["rate_limit_seconds"])

    # Tier 2: robots.txt Crawl-delay
    if robots_crawl_delay is not None:
        return float(robots_crawl_delay)

    # Tier 3: global default
    return float(global_default)


def _domain_key(url: str) -> str:
    """Extract the registrable domain from a URL for per-host rate limiting.

    Uses tldextract to get the registrable domain (domain + suffix), which
    groups subdomains together under the same rate limiter key.

    Parameters
    ----------
    url:
        Full URL (e.g. 'https://www.example.com/page').

    Returns
    -------
    str
        Registrable domain (e.g. 'example.com').
    """
    extracted = tldextract.extract(url)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}"
    # Raw IP or bare hostname (no public suffix) — use the full hostname as the
    # bucket key to avoid trailing-dot keys like "localhost." or "10." that would
    # incorrectly group unrelated hosts under the same rate-limit bucket.
    return urlparse(url).hostname or url


class PerHostLimiter:
    """Async-aware per-host rate limiter.

    Tracks the last fetch time per registrable domain and enforces a minimum
    delay between requests to the same host.  Thread-safe for asyncio (but
    NOT for multi-threaded use without locks).
    """

    def __init__(self) -> None:
        self._last_fetch: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, key: str) -> asyncio.Lock:
        """Get or create an asyncio lock for the given domain key."""
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def wait(self, url: str, delay: float) -> None:
        """Wait until the resolved delay has elapsed since the last fetch.

        Parameters
        ----------
        url:
            The URL about to be fetched (used to extract the domain key).
        delay:
            The resolved delay in seconds (from resolve_delay).
        """
        key = _domain_key(url)
        lock = self._get_lock(key)

        async with lock:
            now = time.monotonic()
            last = self._last_fetch.get(key, 0.0)
            elapsed = now - last
            if elapsed < delay:
                sleep_time = delay - elapsed
                log.debug(
                    "rate-limit sleep",
                    domain=key,
                    sleep_seconds=sleep_time,
                )
                await asyncio.sleep(sleep_time)
            self._last_fetch[key] = time.monotonic()
