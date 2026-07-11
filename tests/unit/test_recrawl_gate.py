"""RED scaffold for SCHED-02 change gate (recrawl_source).

Tests validate that the content-hash change detection gate:
  - Skips crawl when normalized content is unchanged
  - Triggers crawl when content changes
  - Normalizes away nonce/dynamic noise before hashing
  - Forces crawl when last_content_hash is NULL
  - Forces crawl when staleness exceeds max_staleness_days

All tests are guarded by a try/except import so the module collects cleanly
before the target symbol `recrawl_source` exists (Plan 11-03).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Guarded import ────────────────────────────────────────────────────────────

try:
    from knowledge_lake.pipeline.crawl import recrawl_source, _signature  # noqa: F401

    _HAS_GATE = True
except Exception:
    _HAS_GATE = False

pytestmark = pytest.mark.skipif(
    not _HAS_GATE, reason="recrawl_source pending (Plan 11-03)"
)


# ── Helpers ───────────────────────────────────────────────────────────────────

# _signature is imported from the gate (knowledge_lake.pipeline.crawl) so the
# tests can never drift from the real gate implementation.


class _FakePage:
    """Fake crawl page result with a .markdown attribute."""

    def __init__(self, markdown: str) -> None:
        self.markdown = markdown


class _FakeCrawler:
    """Fake crawler adapter returning controlled page content."""

    def __init__(self, markdown: str) -> None:
        self._page = _FakePage(markdown)

    async def fetch_page(self, url: str) -> _FakePage:
        return self._page


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unchanged_skips_no_raw() -> None:
    """When seed page signature matches last_content_hash, crawl_source is NOT called.

    Only touch_source_crawl should bump last_crawled_at (skip path).
    """
    seed_text = "# Important Health Guidance\n\nContent that does not change."
    sig = _signature(seed_text)
    source_id = "src_test_unchanged"

    fake_crawler = _FakeCrawler(seed_text)
    mock_crawl_source = AsyncMock()
    mock_touch = MagicMock()
    mock_validate = MagicMock()

    with (
        patch(
            "knowledge_lake.pipeline.crawl.get_crawler",
            return_value=fake_crawler,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.crawl_source",
            mock_crawl_source,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.validate_public_url",
            mock_validate,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.touch_source_crawl",
            mock_touch,
        ),
        patch(
            "knowledge_lake.pipeline.crawl._get_source_for_recrawl",
            return_value={
                "id": source_id,
                "url": "http://example.com/health",
                "last_content_hash": sig,
                "last_crawled_at": datetime.now(timezone.utc) - timedelta(hours=1),
                "crawl_schedule": "0 3 * * *",
            },
        ),
    ):
        await recrawl_source(source_id)

    mock_validate.assert_called_once()
    mock_crawl_source.assert_not_called()
    mock_touch.assert_called_once()


@pytest.mark.asyncio
async def test_changed_recrawls() -> None:
    """When seed page content differs from last_content_hash, crawl_source IS called.

    The new hash is written via touch_source_crawl.
    """
    old_text = "# Old Content\n\nOriginal information."
    new_text = "# Updated Content\n\nRevised information with new data."
    old_sig = _signature(old_text)
    new_sig = _signature(new_text)
    source_id = "src_test_changed"

    fake_crawler = _FakeCrawler(new_text)
    mock_crawl_source = AsyncMock(return_value={"pages_complete": 1, "pages_failed": 0})
    mock_touch = MagicMock()
    mock_validate = MagicMock()

    with (
        patch(
            "knowledge_lake.pipeline.crawl.get_crawler",
            return_value=fake_crawler,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.crawl_source",
            mock_crawl_source,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.validate_public_url",
            mock_validate,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.touch_source_crawl",
            mock_touch,
        ),
        patch(
            "knowledge_lake.pipeline.crawl._get_source_for_recrawl",
            return_value={
                "id": source_id,
                "url": "http://example.com/health",
                "last_content_hash": old_sig,
                "last_crawled_at": datetime.now(timezone.utc) - timedelta(hours=1),
                "crawl_schedule": "0 3 * * *",
            },
        ),
    ):
        await recrawl_source(source_id)

    mock_validate.assert_called_once()
    mock_crawl_source.assert_called_once()
    # Verify that new hash is written
    call_kwargs = mock_touch.call_args
    assert new_sig in str(call_kwargs), (
        f"Expected new signature {new_sig} in touch_source_crawl call, got {call_kwargs}"
    )


@pytest.mark.asyncio
async def test_nonce_noise_unchanged() -> None:
    """Two pages differing only by dynamic tokens that remove_boilerplate normalizes away
    produce the same signature, so the gate skips.
    """
    base_content = "# Clinical Guidelines 2026\n\nEvidence-based recommendations for care."
    # Simulate nonce noise: trailing timestamp line that boilerplate removal strips
    text_a = base_content + "\n\nPage generated at 2026-07-09T10:00:00Z"
    text_b = base_content + "\n\nPage generated at 2026-07-10T14:30:00Z"

    # Both should produce the same signature after remove_boilerplate
    sig_a = _signature(text_a)
    sig_b = _signature(text_b)

    # If remove_boilerplate normalizes correctly, they are equal.
    # The test verifies the gate's behavior: stored sig_a, fetched text_b
    source_id = "src_test_nonce"
    fake_crawler = _FakeCrawler(text_b)
    mock_crawl_source = AsyncMock()
    mock_touch = MagicMock()
    mock_validate = MagicMock()

    with (
        patch(
            "knowledge_lake.pipeline.crawl.get_crawler",
            return_value=fake_crawler,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.crawl_source",
            mock_crawl_source,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.validate_public_url",
            mock_validate,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.touch_source_crawl",
            mock_touch,
        ),
        patch(
            "knowledge_lake.pipeline.crawl._get_source_for_recrawl",
            return_value={
                "id": source_id,
                "url": "http://example.com/clinical",
                "last_content_hash": sig_a,
                "last_crawled_at": datetime.now(timezone.utc) - timedelta(hours=1),
                "crawl_schedule": "0 3 * * *",
            },
        ),
    ):
        await recrawl_source(source_id)

    # The gate's volatile-token suppression MUST neutralize the timestamp
    # delta, so both crawls yield the SAME signature (SCHED-02 anti-thrash).
    # Asserted unconditionally — the previous if/else passed in both branches,
    # giving false confidence for the anti-thrash clause.
    assert sig_a == sig_b, (
        "volatile timestamp not suppressed by the change gate; a nonce-only "
        "delta would thrash the WORM raw zone on every tick"
    )
    mock_validate.assert_called_once()
    mock_crawl_source.assert_not_called()
    mock_touch.assert_called_once()


@pytest.mark.asyncio
async def test_null_hash_forces_crawl() -> None:
    """When last_content_hash is NULL, the gate always triggers a full crawl."""
    seed_text = "# New Source\n\nFirst time crawling this content."
    source_id = "src_test_null_hash"

    fake_crawler = _FakeCrawler(seed_text)
    mock_crawl_source = AsyncMock(return_value={"pages_complete": 1, "pages_failed": 0})
    mock_touch = MagicMock()
    mock_validate = MagicMock()

    with (
        patch(
            "knowledge_lake.pipeline.crawl.get_crawler",
            return_value=fake_crawler,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.crawl_source",
            mock_crawl_source,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.validate_public_url",
            mock_validate,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.touch_source_crawl",
            mock_touch,
        ),
        patch(
            "knowledge_lake.pipeline.crawl._get_source_for_recrawl",
            return_value={
                "id": source_id,
                "url": "http://example.com/new-source",
                "last_content_hash": None,  # NULL hash
                "last_crawled_at": None,
                "crawl_schedule": "0 3 * * *",
            },
        ),
    ):
        await recrawl_source(source_id)

    mock_validate.assert_called_once()
    mock_crawl_source.assert_called_once()


@pytest.mark.asyncio
async def test_staleness_forces_refresh() -> None:
    """When last_crawled_at is older than max_staleness_days, crawl is forced
    even when the content hash matches.
    """
    seed_text = "# Stable Content\n\nThis page never changes but is stale."
    sig = _signature(seed_text)
    source_id = "src_test_stale"

    fake_crawler = _FakeCrawler(seed_text)
    mock_crawl_source = AsyncMock(return_value={"pages_complete": 1, "pages_failed": 0})
    mock_touch = MagicMock()
    mock_validate = MagicMock()

    # Set last_crawled_at to 60 days ago (well beyond default 30-day max_staleness)
    stale_time = datetime.now(timezone.utc) - timedelta(days=60)

    with (
        patch(
            "knowledge_lake.pipeline.crawl.get_crawler",
            return_value=fake_crawler,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.crawl_source",
            mock_crawl_source,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.validate_public_url",
            mock_validate,
        ),
        patch(
            "knowledge_lake.pipeline.crawl.touch_source_crawl",
            mock_touch,
        ),
        patch(
            "knowledge_lake.pipeline.crawl._get_source_for_recrawl",
            return_value={
                "id": source_id,
                "url": "http://example.com/stable",
                "last_content_hash": sig,  # Hash matches
                "last_crawled_at": stale_time,  # But stale
                "crawl_schedule": "0 3 * * *",
            },
        ),
        patch(
            "knowledge_lake.config.settings.get_settings",
            return_value=MagicMock(
                crawl=MagicMock(max_staleness_days=30)
            ),
        ),
    ):
        await recrawl_source(source_id)

    mock_validate.assert_called_once()
    mock_crawl_source.assert_called_once()
