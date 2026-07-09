"""Tests and Wave 0 xfail stubs for CRAWL-02.

Covers:
  - TestSourceCrawlConfig: repo.get_source_crawl_config and
    repo.list_sources_for_crawl_all (implemented in Plan 2).
  - Wave 0 xfail stubs for crawl_all_sources batch orchestrator (Plan 3).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Guard import so collection does not fail before Plan 3 adds crawl_all_sources.
try:
    from knowledge_lake.pipeline.crawl import crawl_all_sources  # noqa: F401
except ImportError:
    crawl_all_sources = None  # type: ignore[assignment]


# ── SQLite in-memory DB fixtures ─────────────────────────────────────────────


@pytest.fixture(scope="module")
def _engine():
    from knowledge_lake.registry.models import Base

    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def _session(_engine):
    with Session(_engine) as sess:
        yield sess
        sess.rollback()


# ── TestSourceCrawlConfig (CRAWL-01, D-01, D-05) ─────────────────────────────


class TestSourceCrawlConfig:
    """get_source_crawl_config returns the crawl_config sub-dict or {}.

    D-05: returns the inner crawl_config sub-dict, not the full Source.config.
    """

    def test_missing_source_returns_empty_dict(self, _session):
        """get_source_crawl_config on a nonexistent source_id returns {}."""
        from knowledge_lake.registry.repo import get_source_crawl_config

        result = get_source_crawl_config(_session, "nonexistent-id")
        assert result == {}

    def test_source_with_none_config_returns_empty_dict(self, _session):
        """Source with config=None returns {}."""
        from knowledge_lake.registry.repo import create_source, get_source_crawl_config

        src = create_source(_session, name="no-cfg", source_type="web")
        # Ensure config is None (it defaults to None)
        src.config = None
        _session.flush()

        result = get_source_crawl_config(_session, src.id)
        assert result == {}

    def test_source_with_no_crawl_config_key_returns_empty_dict(self, _session):
        """Source.config without crawl_config key returns {}."""
        from knowledge_lake.registry.repo import create_source, get_source_crawl_config

        src = create_source(_session, name="no-crawl-cfg", source_type="web")
        src.config = {"domain": "healthcare", "tags": ["a"]}
        _session.flush()

        result = get_source_crawl_config(_session, src.id)
        assert result == {}

    def test_source_with_crawl_config_returns_inner_dict(self, _session):
        """Source.config with crawl_config returns the inner sub-dict."""
        from knowledge_lake.registry.repo import create_source, get_source_crawl_config

        src = create_source(_session, name="with-crawl-cfg", source_type="web")
        src.config = {"domain": "healthcare", "crawl_config": {"rate_limit_rps": 2, "depth": 3}}
        _session.flush()

        result = get_source_crawl_config(_session, src.id)
        assert result == {"rate_limit_rps": 2, "depth": 3}


class TestListSourcesForCrawlAll:
    """list_sources_for_crawl_all returns all sources, optionally filtered by domain."""

    @pytest.fixture(scope="class")
    def _populated_engine(self):
        from knowledge_lake.registry.models import Base

        eng = create_engine("sqlite:///:memory:", echo=False)
        Base.metadata.create_all(eng)
        yield eng
        eng.dispose()

    @pytest.fixture()
    def _populated_session(self, _populated_engine):
        with Session(_populated_engine) as sess:
            yield sess
            sess.rollback()

    @pytest.fixture(autouse=True)
    def _seed(self, _populated_session):
        """Seed three sources: two healthcare, one other."""
        from knowledge_lake.registry.repo import create_source

        s1 = create_source(_populated_session, name="hc-source-1", source_type="web")
        s1.config = {"domain": "healthcare"}
        s2 = create_source(_populated_session, name="hc-source-2", source_type="web")
        s2.config = {"domain": "healthcare"}
        s3 = create_source(_populated_session, name="finance-source", source_type="web")
        s3.config = {"domain": "finance"}
        _populated_session.flush()

    def test_no_filter_returns_all(self, _populated_session):
        """list_sources_for_crawl_all(domain=None) returns all sources."""
        from knowledge_lake.registry.repo import list_sources_for_crawl_all

        result = list_sources_for_crawl_all(_populated_session)
        assert len(result) >= 3  # may have more from other fixtures

    def test_domain_filter_returns_matching(self, _populated_session):
        """list_sources_for_crawl_all(domain='healthcare') returns only healthcare sources."""
        from knowledge_lake.registry.repo import list_sources_for_crawl_all

        result = list_sources_for_crawl_all(_populated_session, domain="healthcare")
        assert all((s.config or {}).get("domain") == "healthcare" for s in result)
        assert len(result) >= 2

    def test_domain_filter_no_match_returns_empty(self, _populated_session):
        """list_sources_for_crawl_all(domain='nonexistent') returns []."""
        from knowledge_lake.registry.repo import list_sources_for_crawl_all

        result = list_sources_for_crawl_all(_populated_session, domain="nonexistent-domain")
        assert result == []


@pytest.mark.asyncio
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
