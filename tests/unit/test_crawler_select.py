"""Unit tests for crawler auto-selection (INGEST-05, D-04).

Tests the select_crawler table logic and probe_site sitemap detection.

Coverage:
  - has_sitemap=True short-circuits to 'scrapy' (sitemap wins over SPA markers)
  - static HTML, no sitemap → 'crawl4ai'
  - SPA-marker HTML, no sitemap → 'playwright' (02-05 reserved path; test asserts it)
  - probe_site (mocked httpx) returns has_sitemap=True when /sitemap.xml is HTTP 200
  - probe_site returns has_sitemap=False when both robots.txt and /sitemap.xml are absent
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from knowledge_lake.crawl.select import probe_site, select_crawler

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

STATIC_HTML = """<!DOCTYPE html>
<html><head><title>Static Site</title></head>
<body><h1>Hello</h1><p>Some content here</p></body>
</html>"""

SPA_MARKER_HTML = """<!DOCTYPE html>
<html><head><title>SPA</title></head>
<body>
<div id="root"></div>
<script src="/main.js"></script>
<script src="/vendor.js"></script>
<script src="/runtime.js"></script>
<script>window.__NEXT_DATA__ = {};</script>
</body>
</html>"""

# "near-empty" body with heavy scripts — reinforces SPA signal
SPA_MARKER_MINIMAL_BODY_HTML = """<!DOCTYPE html>
<html><head></head>
<body>
<div id="app"></div>
<script src="/chunk1.js"></script>
<script src="/chunk2.js"></script>
<script src="/chunk3.js"></script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# select_crawler table tests
# ---------------------------------------------------------------------------


class TestSelectCrawlerTable:
    """Table-driven tests for the select_crawler routing function."""

    @pytest.mark.parametrize(
        "url, html, has_sitemap, expected",
        [
            # has_sitemap=True must always route to scrapy, regardless of html
            (
                "https://example.com",
                STATIC_HTML,
                True,
                "scrapy",
            ),
            (
                "https://spa-site.com",
                SPA_MARKER_HTML,
                True,
                "scrapy",  # sitemap wins over SPA markers
            ),
            (
                "https://empty.com",
                None,
                True,
                "scrapy",  # sitemap wins even with no html
            ),
            # No sitemap + static HTML → crawl4ai
            (
                "https://static.com",
                STATIC_HTML,
                False,
                "crawl4ai",
            ),
            # No sitemap + SPA-marker HTML → playwright (02-05 reserved)
            (
                "https://spa.com",
                SPA_MARKER_HTML,
                False,
                "playwright",
            ),
            (
                "https://spa2.com",
                SPA_MARKER_MINIMAL_BODY_HTML,
                False,
                "playwright",
            ),
            # No sitemap + no html → crawl4ai (default)
            (
                "https://nohtml.com",
                None,
                False,
                "crawl4ai",
            ),
        ],
    )
    def test_select_crawler(
        self,
        url: str,
        html: str | None,
        has_sitemap: bool,
        expected: str,
    ) -> None:
        result = select_crawler(url, html=html, has_sitemap=has_sitemap)
        assert result == expected, (
            f"select_crawler({url!r}, has_sitemap={has_sitemap}) returned {result!r}, "
            f"expected {expected!r}"
        )


# ---------------------------------------------------------------------------
# probe_site (mocked httpx) tests
# ---------------------------------------------------------------------------


def _make_mock_response(status_code: int, text: str = "") -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


class TestProbeSite:
    """Tests for probe_site with mocked httpx calls."""

    @patch("knowledge_lake.crawl.select.httpx")
    def test_has_sitemap_from_sitemap_xml_200(self, mock_httpx: Any) -> None:
        """probe_site returns has_sitemap=True when /sitemap.xml responds 200."""
        # Entry URL GET → 200 + minimal HTML
        entry_resp = _make_mock_response(200, STATIC_HTML)
        # /robots.txt GET → 200, no Sitemap: directive
        robots_resp = _make_mock_response(200, "User-agent: *\nDisallow: /private/\n")
        # /sitemap.xml GET → 200
        sitemap_resp = _make_mock_response(200, "<?xml version='1.0'?>...")

        # Sequence: entry GET, robots GET, sitemap GET
        mock_httpx.get.side_effect = [entry_resp, robots_resp, sitemap_resp]

        html, has_sitemap = probe_site("https://example.com")
        assert has_sitemap is True
        assert html == STATIC_HTML

    @patch("knowledge_lake.crawl.select.httpx")
    def test_has_sitemap_from_robots_directive(self, mock_httpx: Any) -> None:
        """probe_site returns has_sitemap=True when robots.txt has Sitemap: directive."""
        entry_resp = _make_mock_response(200, STATIC_HTML)
        # /robots.txt contains Sitemap: directive
        robots_resp = _make_mock_response(
            200,
            "User-agent: *\nDisallow:\nSitemap: https://example.com/sitemap.xml\n",
        )
        # /sitemap.xml is 404 (but robots.txt Sitemap: is enough)
        sitemap_resp = _make_mock_response(404, "")

        mock_httpx.get.side_effect = [entry_resp, robots_resp, sitemap_resp]

        html, has_sitemap = probe_site("https://example.com")
        assert has_sitemap is True

    @patch("knowledge_lake.crawl.select.httpx")
    def test_no_sitemap(self, mock_httpx: Any) -> None:
        """probe_site returns has_sitemap=False when both robots.txt and /sitemap.xml are absent."""
        entry_resp = _make_mock_response(200, STATIC_HTML)
        # /robots.txt → no Sitemap: directive
        robots_resp = _make_mock_response(200, "User-agent: *\nDisallow:\n")
        # /sitemap.xml → 404
        sitemap_resp = _make_mock_response(404, "")

        mock_httpx.get.side_effect = [entry_resp, robots_resp, sitemap_resp]

        html, has_sitemap = probe_site("https://example.com")
        assert has_sitemap is False

    @patch("knowledge_lake.crawl.select.httpx")
    def test_robots_404_sitemap_404(self, mock_httpx: Any) -> None:
        """probe_site returns has_sitemap=False when robots.txt is 404 and /sitemap.xml is 404."""
        entry_resp = _make_mock_response(200, STATIC_HTML)
        robots_resp = _make_mock_response(404, "")
        sitemap_resp = _make_mock_response(404, "")

        mock_httpx.get.side_effect = [entry_resp, robots_resp, sitemap_resp]

        html, has_sitemap = probe_site("https://example.com")
        assert has_sitemap is False

    @patch("knowledge_lake.crawl.select.httpx")
    def test_raises_on_private_ip(self, mock_httpx: Any) -> None:
        """probe_site raises ValueError for private/SSRF-blocked URLs."""
        with pytest.raises(ValueError):
            probe_site("https://192.168.1.1/")
