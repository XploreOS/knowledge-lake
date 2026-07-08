"""Wave 0 xfail stubs for CRAWL-02: crawl_all_sources batch orchestrator.

All tests are marked xfail(strict=False) — they will be implemented in Plan 3
when crawl_all_sources is added to knowledge_lake.pipeline.crawl.
"""

from __future__ import annotations

import pytest

# Guard import so collection does not fail before Plan 3 adds crawl_all_sources.
try:
    from knowledge_lake.pipeline.crawl import crawl_all_sources  # noqa: F401
except ImportError:
    crawl_all_sources = None  # type: ignore[assignment]


@pytest.mark.asyncio
@pytest.mark.xfail(strict=False, reason="Phase 8 CRAWL-02 — not yet implemented")
async def test_crawl_all_sources_returns_summary():
    """crawl_all_sources() returns dict with keys total, succeeded, failed, results."""
    from knowledge_lake.pipeline.crawl import crawl_all_sources as _crawl_all

    result = await _crawl_all()
    assert isinstance(result, dict)
    assert "total" in result
    assert "succeeded" in result
    assert "failed" in result
    assert "results" in result


@pytest.mark.asyncio
@pytest.mark.xfail(strict=False, reason="Phase 8 CRAWL-02 — not yet implemented")
async def test_crawl_all_sources_failure_does_not_abort():
    """One source raises, others are still processed; failed count == 1."""
    from unittest.mock import AsyncMock, patch

    from knowledge_lake.pipeline.crawl import crawl_all_sources as _crawl_all

    # Patch list_sources_for_crawl_all to return two sources.
    # The first crawl_source call raises, the second succeeds.
    fake_sources = [
        {"id": "src-1", "url": "http://bad.example.com"},
        {"id": "src-2", "url": "http://good.example.com"},
    ]

    async def _failing_crawl(url, **_kwargs):
        if "bad" in url:
            raise RuntimeError("network error")
        return {"pages_complete": 1, "pages_failed": 0}

    with patch(
        "knowledge_lake.pipeline.crawl.list_sources_for_crawl_all",
        return_value=fake_sources,
    ), patch(
        "knowledge_lake.pipeline.crawl.crawl_source",
        side_effect=_failing_crawl,
    ):
        result = await _crawl_all()

    assert result["failed"] == 1
    assert result["succeeded"] >= 1


@pytest.mark.asyncio
@pytest.mark.xfail(strict=False, reason="Phase 8 CRAWL-02 — not yet implemented")
async def test_crawl_all_sources_domain_filter():
    """Passing domain='healthcare' calls list_sources_for_crawl_all with domain='healthcare'."""
    from unittest.mock import AsyncMock, patch

    from knowledge_lake.pipeline.crawl import crawl_all_sources as _crawl_all

    with patch(
        "knowledge_lake.pipeline.crawl.list_sources_for_crawl_all",
        return_value=[],
    ) as mock_list:
        await _crawl_all(domain="healthcare")

    mock_list.assert_called_once_with(domain="healthcare")
