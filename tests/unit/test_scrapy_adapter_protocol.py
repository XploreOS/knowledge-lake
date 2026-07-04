"""Verify ScrapyAdapter satisfies the CrawlerPlugin protocol (WR-02).

This replaces the module-level assert that was removed from scrapy_adapter.py.
Running as a test ensures the protocol check survives Python -O optimised builds
and surfaces as a clear test failure rather than an import-time AssertionError.
"""
from knowledge_lake.plugins.builtin.scrapy_adapter import ScrapyAdapter
from knowledge_lake.plugins.protocols import CrawlerPlugin


def test_scrapy_adapter_satisfies_protocol():
    """ScrapyAdapter must implement the full CrawlerPlugin protocol."""
    assert isinstance(ScrapyAdapter(), CrawlerPlugin), (
        "ScrapyAdapter does not satisfy CrawlerPlugin protocol — "
        "check start_crawl/poll_status/get_results signatures"
    )
