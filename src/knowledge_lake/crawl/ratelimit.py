"""Three-tier rate-limit resolver and per-host async limiter (INGEST-09, D-12, T-02-07).

The resolver enforces politeness by selecting the strictest applicable delay:
  Tier 1: Source.config['crawl_config']['rate_limit_seconds'] or ['rate_limit_rps']
          (per-source operator override; rate_limit_seconds wins if both present — D-03)
  Tier 2: robots.txt Crawl-delay (site-wide signal from the target)
  Tier 3: CrawlSettings.rate_limit_seconds (global default)

The per-host limiter tracks last-fetch time keyed by registrable domain (via
tldextract) so multi-host crawls throttle independently per host.  It also
tracks consecutive error counts per host for exponential backoff (CRAWL-03,
D-10 through D-13).

Constants:
    MAX_BACKOFF_SECONDS — cap for per-host exponential backoff (CRAWL-03, D-11)
    COOLDOWN_SECONDS    — minimum post-429 wait before re-querying a host (D-13)

Functions:
    resolve_delay  — tier-ordered delay resolution with optional backoff_extra floor
    _domain_key    — extract registrable domain from a URL (limiter key)

Classes:
    PerHostLimiter — async-aware per-host rate limiter with adaptive backoff state
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional
from urllib.parse import urlparse

import tldextract

log = logging.getLogger(__name__)

# ── Module-level constants (CRAWL-03, D-11, D-13) ────────────────────────────

MAX_BACKOFF_SECONDS: float = 60.0
"""Maximum per-host exponential backoff cap (D-11). Callers may override."""

COOLDOWN_SECONDS: float = 30.0
"""Minimum per-host wait after a 429/403 response (D-13). Callers may override."""


def resolve_delay(
    source_config: Optional[dict[str, Any]],
    robots_crawl_delay: Optional[float],
    global_default: float,
    backoff_extra: float = 0.0,
) -> float:
    """Resolve the effective crawl delay using the three-tier priority (D-12).

    Tier order (first match wins):
      1. source_config['rate_limit_seconds'] — per-source operator override
         Fallback: source_config['rate_limit_rps'] converted via 1/rps (D-03).
         If both present, rate_limit_seconds wins.
         T-08-02-01: rps <= 0 falls through to global_default (zero-division guard).
      2. robots_crawl_delay — Crawl-delay from robots.txt
      3. global_default — CrawlSettings.rate_limit_seconds

    The backoff_extra parameter is an additive floor raiser (D-12).  The
    effective return is max(tier_result, tier_result + backoff_extra).  When
    backoff_extra is 0.0 (default) behaviour is identical to the pre-Phase-8
    three-tier logic so all existing callers are unaffected.

    Parameters
    ----------
    source_config:
        The crawl_config sub-dict returned by get_source_crawl_config()
        (may be None or empty).  Must NOT be the full Source.config — the
        caller must traverse the 'crawl_config' nesting first (D-05).
    robots_crawl_delay:
        Crawl-delay extracted from robots.txt (None if absent).
    global_default:
        The global default from CrawlSettings.rate_limit_seconds.
    backoff_extra:
        Additional seconds to add to the tier result as an exponential-backoff
        floor (CRAWL-03, D-12).  Defaults to 0.0 (no extra delay).

    Returns
    -------
    float
        The resolved delay in seconds, with backoff_extra applied as floor.
    """
    # Tier 1: source config override
    if source_config:
        if "rate_limit_seconds" in source_config:
            tier_result = float(source_config["rate_limit_seconds"])
            return max(tier_result, tier_result + backoff_extra)
        if "rate_limit_rps" in source_config:
            rps = float(source_config["rate_limit_rps"])
            # T-08-02-01: guard against zero/negative rps — fall through to global default
            tier_result = (1.0 / rps) if rps > 0 else float(global_default)
            return max(tier_result, tier_result + backoff_extra)

    # Tier 2: robots.txt Crawl-delay
    if robots_crawl_delay is not None:
        tier_result = float(robots_crawl_delay)
        return max(tier_result, tier_result + backoff_extra)

    # Tier 3: global default
    tier_result = float(global_default)
    return max(tier_result, tier_result + backoff_extra)


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
    """Async-aware per-host rate limiter with adaptive backoff state (CRAWL-03).

    Tracks the last fetch time per registrable domain and enforces a minimum
    delay between requests to the same host.  Also tracks consecutive error
    counts per host (D-10, D-11) and per-host cooldown windows (D-13).

    Thread-safe for asyncio (but NOT for multi-threaded use without locks).

    New in Phase 8 (CRAWL-03):
        _consecutive_errors  — per-host error count for exponential backoff
        _cooldown_until      — per-host cooldown deadline (monotonic clock)
        record_error(url)    — increment error count + set cooldown deadline
        reset_errors(url)    — clear error count and cooldown
        backoff_extra(url)   — compute additional delay from error state
        consecutive_errors   — read-only property exposing the error dict
    """

    def __init__(self) -> None:
        self._last_fetch: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        # Phase 8 adaptive backoff state (CRAWL-03, D-10/D-11/D-13)
        self._consecutive_errors: dict[str, int] = {}
        self._cooldown_until: dict[str, float] = {}

    @property
    def consecutive_errors(self) -> dict[str, int]:
        """Read-only snapshot of consecutive error counts per domain key.

        L-02 fix: returns a shallow copy so callers cannot mutate internal
        backoff state directly (e.g. del limiter.consecutive_errors['host']
        would bypass reset_errors and leave _cooldown_until stale).
        """
        return dict(self._consecutive_errors)

    def _get_lock(self, key: str) -> asyncio.Lock:
        """Get or create an asyncio lock for the given domain key."""
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    def record_error(self, url: str) -> None:
        """Increment consecutive error count for this host and set cooldown.

        Call this on every 429/403 response from the target host.  The cooldown
        deadline is set to time.monotonic() + COOLDOWN_SECONDS (D-13).

        Parameters
        ----------
        url:
            Any URL from the affected host (domain key is extracted automatically).
        """
        key = _domain_key(url)
        self._consecutive_errors[key] = self._consecutive_errors.get(key, 0) + 1
        self._cooldown_until[key] = time.monotonic() + COOLDOWN_SECONDS

    def reset_errors(self, url: str) -> None:
        """Reset consecutive error count and cooldown for this host.

        Call this on any successful (non-4xx) response from the target host.

        Parameters
        ----------
        url:
            Any URL from the affected host (domain key is extracted automatically).
        """
        key = _domain_key(url)
        self._consecutive_errors.pop(key, None)
        self._cooldown_until.pop(key, None)

    def backoff_extra(self, url: str, base_delay: float = 1.0) -> float:
        """Return additional backoff seconds based on consecutive error count.

        Formula: min(base_delay * (2 ** n), MAX_BACKOFF_SECONDS) where n is
        the number of consecutive errors for this host (D-11).  Returns 0.0
        when there are no errors.

        Parameters
        ----------
        url:
            Any URL from the affected host.
        base_delay:
            Base delay in seconds for the first backoff step.  Defaults to 1.0.

        Returns
        -------
        float
            Additional seconds to add to the resolved delay, capped at
            MAX_BACKOFF_SECONDS.
        """
        key = _domain_key(url)
        n = self._consecutive_errors.get(key, 0)
        if n == 0:
            return 0.0
        backoff = base_delay * (2 ** n)
        return min(backoff, MAX_BACKOFF_SECONDS)

    async def wait(self, url: str, delay: float) -> None:
        """Wait until the resolved delay has elapsed since the last fetch.

        Per-host cooldown (D-13) is enforced first: if the host is in its
        cooldown window, the limiter sleeps until the cooldown expires before
        applying the normal last-fetch delay.

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
            # D-13: cooldown check precedes normal _last_fetch sleep
            cooldown_deadline = self._cooldown_until.get(key)
            if cooldown_deadline is not None:
                remaining = cooldown_deadline - time.monotonic()
                if remaining > 0:
                    log.debug(
                        "rate-limit cooldown",
                        domain=key,
                        cooldown_remaining=remaining,
                    )
                    await asyncio.sleep(remaining)

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
