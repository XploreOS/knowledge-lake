"""Robots.txt parsing via Protego (INGEST-09, T-02-06, D-11).

Uses the Protego library (maintained by the Scrapy team) for robust robots.txt
parsing.  Handles wildcards, $-terminated patterns, Crawl-delay, and agent
precedence without hand-rolling a parser.

Classes:
    RobotsPolicy — wraps a parsed robots.txt; exposes is_allowed + crawl_delay

Functions:
    fetch_robots(base_url) — HTTP GET /robots.txt with retry; returns RobotsPolicy

Unreachable-robots policy:
    If /robots.txt is unreachable after retries (network error, 5xx), the crawl
    treats the site as ALLOW-ALL (RFC 9309 Section 2.3: "If the robots.txt file
    is unreachable due to server problems, a robot MAY assume that access is
    allowed"). This is documented and logged at WARNING level.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from protego import Protego
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)


class RobotsPolicy:
    """Wraps a Protego-parsed robots.txt for is_allowed + crawl_delay queries.

    Construct via the ``from_robots_txt`` class method (parses a robots.txt body
    string) or via ``fetch_robots`` (HTTP GET + parse).
    """

    def __init__(self, parser: Protego) -> None:
        self._parser = parser

    @classmethod
    def from_robots_txt(cls, body: str) -> "RobotsPolicy":
        """Parse a robots.txt body string and return a RobotsPolicy.

        Parameters
        ----------
        body:
            The full text content of a robots.txt file.

        Returns
        -------
        RobotsPolicy
            A policy object exposing is_allowed() and crawl_delay().
        """
        parser = Protego.parse(body)
        return cls(parser)

    def is_allowed(self, path: str, user_agent: str = "*") -> bool:
        """Check whether the given path is allowed for the given user agent.

        Parameters
        ----------
        path:
            URL path to check (e.g. '/private/data').
        user_agent:
            User-agent string to check against (default: '*').

        Returns
        -------
        bool
            True if the path is allowed, False if disallowed.
        """
        # Protego expects a full URL for can_fetch; we construct one with a
        # dummy base since we only care about the path matching.
        url = f"http://example.com{path}"
        return self._parser.can_fetch(url, user_agent)

    def crawl_delay(self, user_agent: str = "*") -> Optional[float]:
        """Extract the Crawl-delay for the given user agent.

        Parameters
        ----------
        user_agent:
            User-agent string to look up (default: '*').

        Returns
        -------
        float | None
            The Crawl-delay in seconds, or None if not specified.
        """
        delay = self._parser.crawl_delay(user_agent)
        if delay is None:
            return None
        return float(delay)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
    reraise=True,
)
def _fetch_robots_text(base_url: str) -> str:
    """Internal: HTTP GET /robots.txt with tenacity retries."""
    url = f"{base_url.rstrip('/')}/robots.txt"
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        resp = client.get(url)
        if resp.status_code == 404:
            # No robots.txt = allow everything
            return ""
        resp.raise_for_status()
        return resp.text


def fetch_robots(base_url: str) -> RobotsPolicy:
    """Fetch and parse robots.txt from the given base URL.

    Applies the tenacity retry config (3 attempts, exponential backoff).
    If robots.txt is unreachable after retries, returns an allow-all policy
    (RFC 9309 Section 2.3).

    Parameters
    ----------
    base_url:
        The base URL of the site (e.g. 'https://example.com').

    Returns
    -------
    RobotsPolicy
        A parsed policy; allow-all if robots.txt was unreachable.
    """
    try:
        body = _fetch_robots_text(base_url)
        return RobotsPolicy.from_robots_txt(body)
    except Exception as exc:
        log.warning(
            "robots.txt unreachable after retries — treating as allow-all (RFC 9309 2.3)",
            base_url=base_url,
            error=str(exc),
        )
        return RobotsPolicy.from_robots_txt("")
