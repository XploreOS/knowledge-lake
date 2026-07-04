"""
Integration tests for Crawl4AIAdapter (INGEST-04, T-02-09, T-02-12).

Tests verify:
  - A complete page yields both html (bytes) and markdown (str)
  - A robots-blocked signal (success=False, status_code=403) maps to status="robots_blocked"
  - A private-IP URL raises ValueError before the crawler runs (validate_public_url)
  - Protocol compliance: isinstance(adapter, CrawlerPlugin) is True
  - Entry-point resolution works via get_crawler(settings)

Uses mocked AsyncWebCrawler to avoid live network access.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────


@dataclass
class FakeCrawlResult:
    """Minimal mock of a Crawl4AI CrawlResult."""

    success: bool
    html: str | None = None
    markdown: str | None = None
    status_code: int | None = None
    error_message: str | None = None


@pytest.fixture()
def adapter():
    """Return a fresh Crawl4AIAdapter instance."""
    from knowledge_lake.plugins.builtin.crawl4ai_adapter import Crawl4AIAdapter

    return Crawl4AIAdapter()


# ── Protocol compliance ───────────────────────────────────────────────────────


class TestProtocolCompliance:
    """Crawl4AIAdapter satisfies the CrawlerPlugin protocol."""

    def test_isinstance_crawler_plugin(self, adapter):
        from knowledge_lake.plugins.protocols import CrawlerPlugin

        assert isinstance(adapter, CrawlerPlugin)

    def test_name_is_crawl4ai(self, adapter):
        assert adapter.name == "crawl4ai"


# ── SSRF guard ────────────────────────────────────────────────────────────────


class TestSSRFGuard:
    """validate_public_url is called before any fetch (T-02-09)."""

    def test_private_ip_raises_before_fetch(self, adapter):
        """A private-IP URL raises ValueError before the crawler runs."""
        # 10.0.0.1 is RFC-1918 private — should fail SSRF validation
        with pytest.raises(ValueError, match="private"):
            asyncio.run(adapter.fetch_page("https://10.0.0.1/secret"))

    def test_localhost_raises_before_fetch(self, adapter):
        """A localhost URL raises ValueError before the crawler runs."""
        with pytest.raises(ValueError, match="private|loopback"):
            asyncio.run(adapter.fetch_page("https://127.0.0.1/admin"))

    def test_http_scheme_raises(self, adapter):
        """Non-https scheme raises ValueError."""
        with pytest.raises(ValueError, match="https"):
            asyncio.run(adapter.fetch_page("http://example.com/page"))


# ── Complete page fetch ───────────────────────────────────────────────────────


class TestCompleteFetch:
    """A successful fetch yields both html bytes and markdown string."""

    @pytest.mark.asyncio
    async def test_complete_page_returns_html_and_markdown(self, adapter):
        """Mock a successful crawl and verify CrawlPageResult fields."""
        fake_result = FakeCrawlResult(
            success=True,
            html="<html><body><h1>Hello</h1></body></html>",
            markdown="# Hello",
            status_code=200,
        )

        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=fake_result)
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "knowledge_lake.plugins.builtin.crawl4ai_adapter.validate_public_url"
        ), patch(
            "crawl4ai.AsyncWebCrawler",
            return_value=mock_crawler,
        ):
            result = await adapter.fetch_page("https://example.com/page")

        assert result.status == "complete"
        assert result.html is not None
        assert isinstance(result.html, bytes)
        assert b"Hello" in result.html
        assert result.markdown == "# Hello"
        assert result.url == "https://example.com/page"
        assert result.fetched_at is not None

    @pytest.mark.asyncio
    async def test_complete_page_html_is_bytes(self, adapter):
        """html field is bytes (not str) as required by CrawlPageResult."""
        fake_result = FakeCrawlResult(
            success=True,
            html="<p>Test</p>",
            markdown="Test",
            status_code=200,
        )

        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=fake_result)
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "knowledge_lake.plugins.builtin.crawl4ai_adapter.validate_public_url"
        ), patch(
            "crawl4ai.AsyncWebCrawler",
            return_value=mock_crawler,
        ):
            result = await adapter.fetch_page("https://example.com/test")

        assert isinstance(result.html, bytes)


# ── Robots blocked ────────────────────────────────────────────────────────────


class TestRobotsBlocked:
    """Robots-blocked signal maps to CrawlPageResult.status == 'robots_blocked'."""

    @pytest.mark.asyncio
    async def test_robots_blocked_403_signal(self, adapter):
        """success=False + status_code=403 → status='robots_blocked' with no html/md."""
        fake_result = FakeCrawlResult(
            success=False,
            html=None,
            markdown=None,
            status_code=403,
            error_message="Blocked by robots.txt",
        )

        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=fake_result)
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "knowledge_lake.plugins.builtin.crawl4ai_adapter.validate_public_url"
        ), patch(
            "crawl4ai.AsyncWebCrawler",
            return_value=mock_crawler,
        ):
            result = await adapter.fetch_page("https://example.com/blocked")

        assert result.status == "robots_blocked"
        assert result.html is None
        assert result.markdown is None
        assert result.url == "https://example.com/blocked"

    @pytest.mark.asyncio
    async def test_non_robots_failure_returns_failed(self, adapter):
        """A non-403 failure returns status='failed' with error message."""
        fake_result = FakeCrawlResult(
            success=False,
            html=None,
            markdown=None,
            status_code=500,
            error_message="Internal server error",
        )

        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=fake_result)
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "knowledge_lake.plugins.builtin.crawl4ai_adapter.validate_public_url"
        ), patch(
            "crawl4ai.AsyncWebCrawler",
            return_value=mock_crawler,
        ):
            result = await adapter.fetch_page("https://example.com/error")

        assert result.status == "failed"
        assert result.error is not None
        assert "Internal server error" in result.error


# ── Size cap ──────────────────────────────────────────────────────────────────


class TestSizeCap:
    """Responses exceeding 50 MB are rejected (T-02-12)."""

    @pytest.mark.asyncio
    async def test_oversized_response_returns_failed(self, adapter):
        """HTML exceeding MAX_DOWNLOAD_BYTES yields status='failed'."""
        from knowledge_lake.pipeline.ingest import MAX_DOWNLOAD_BYTES

        # Create a response that exceeds the size cap
        oversized_html = "x" * (MAX_DOWNLOAD_BYTES + 1)
        fake_result = FakeCrawlResult(
            success=True,
            html=oversized_html,
            markdown="big",
            status_code=200,
        )

        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=fake_result)
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "knowledge_lake.plugins.builtin.crawl4ai_adapter.validate_public_url"
        ), patch(
            "crawl4ai.AsyncWebCrawler",
            return_value=mock_crawler,
        ):
            result = await adapter.fetch_page("https://example.com/huge")

        assert result.status == "failed"
        assert "cap" in (result.error or "").lower()


# ── Entry-point resolution ─────────────────────────────────────────────────────


class TestEntryPointResolution:
    """get_crawler(settings) resolves to Crawl4AIAdapter."""

    def test_resolver_returns_crawl4ai(self):
        """get_crawler with crawler='crawl4ai' returns a Crawl4AIAdapter."""
        from knowledge_lake.plugins.resolver import get_crawler

        # Create a minimal mock settings with crawler="crawl4ai"
        mock_settings = MagicMock()
        mock_settings.crawler = "crawl4ai"

        adapter = get_crawler(mock_settings)
        assert adapter.name == "crawl4ai"

        from knowledge_lake.plugins.protocols import CrawlerPlugin

        assert isinstance(adapter, CrawlerPlugin)
