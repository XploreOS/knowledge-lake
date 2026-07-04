"""Crawler selection logic (INGEST-04, D-02).

Provides a simple resolver that maps a URL + signals to a crawler adapter name.
Default is always "crawl4ai". The escalation hook (near-empty markdown detection)
is documented here for 02-05 (Playwright escalation) to fill in.

Functions:
    select_crawler(url, html, has_sitemap) -> str
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


def select_crawler(
    url: str,
    html: Optional[str] = None,
    has_sitemap: bool = False,
) -> str:
    """Select the appropriate crawler adapter name for a URL.

    Default strategy: always "crawl4ai".

    Escalation hook (02-05 will fill this in):
      If html is provided and its markdown conversion is near-empty (< 50 chars
      after whitespace strip), escalate to "playwright" for JS-rendered pages.

    Parameters
    ----------
    url:
        The URL to crawl.
    html:
        Optional HTML content from a prior fetch attempt (for escalation check).
    has_sitemap:
        Whether the site has a sitemap (reserved for future volume-based selection).

    Returns
    -------
    str
        Crawler adapter name (e.g. 'crawl4ai', 'scrapy', 'playwright').
    """
    # Escalation hook stub — 02-05 fills this in with Playwright detection
    # if html is not None:
    #     stripped = (html or "").strip()
    #     if len(stripped) < 50:
    #         log.info("select_crawler.escalate", url=url, reason="near_empty_html")
    #         return "playwright"

    return "crawl4ai"
