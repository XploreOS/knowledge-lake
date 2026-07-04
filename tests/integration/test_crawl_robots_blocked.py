"""
Integration tests for robots-blocked crawl handling (INGEST-09, D-13).

Tests verify:
  - A URL disallowed by robots.txt gets crawl_states.status='robots_blocked'
  - No raw/bronze artifact is written for a robots-blocked URL
  - The crawl orchestrator respects the robots policy for individual paths

Uses an in-memory SQLite database with mocked adapter and storage.
"""

from __future__ import annotations

import datetime
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from knowledge_lake.registry.models import Base, CrawlState, Job, Source


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine."""
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def mock_adapter():
    """Mock crawler adapter."""
    adapter = MagicMock()
    adapter.name = "crawl4ai"

    async def _fetch(url):
        from knowledge_lake.plugins.protocols import CrawlPageResult

        return CrawlPageResult(
            url=url,
            status="complete",
            html=f"<html>{url}</html>".encode(),
            markdown=f"# {url}",
            fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )

    adapter.fetch_page = AsyncMock(side_effect=_fetch)
    return adapter


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestRobotsBlocked:
    """URLs disallowed by robots.txt are recorded as robots_blocked with no artifacts."""

    def test_robots_blocked_url_has_no_artifacts(self, engine, mock_adapter):
        """A URL disallowed by local robots policy -> status=robots_blocked, no artifacts."""
        session = Session(engine)

        @contextmanager
        def mock_get_session():
            try:
                yield session
                session.flush()
            except Exception:
                session.rollback()
                raise

        # Setup: source & job with one pending URL that will be robots-blocked
        source = Source(
            id="src_robots_test",
            name="Robots Test",
            source_type="web",
            url="https://example.com",
            normalized_url="https://example.com",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(source)
        session.flush()

        job = Job(
            id="job_robots_test",
            status="running",
            source_id=source.id,
            job_type="crawl",
            crawler="crawl4ai",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(job)
        session.flush()

        # Pending URL is /private/secret — will be blocked by robots
        state = CrawlState(
            id="cst_robots_0",
            job_id=job.id,
            url="https://example.com/private/secret",
            normalized_url="https://example.com/private/secret",
            status="pending",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(state)
        session.flush()

        mock_storage = MagicMock()

        # Robots policy: disallow /private/
        mock_robots_policy = MagicMock()

        def is_allowed(path):
            return not path.startswith("/private/")

        mock_robots_policy.is_allowed.side_effect = is_allowed
        mock_robots_policy.crawl_delay.return_value = None

        with patch("knowledge_lake.pipeline.crawl.get_session", mock_get_session), \
             patch("knowledge_lake.registry.db.get_session", mock_get_session), \
             patch("knowledge_lake.pipeline.ingest.get_session", mock_get_session), \
             patch("knowledge_lake.pipeline.crawl.get_crawler", return_value=mock_adapter), \
             patch("knowledge_lake.pipeline.crawl.validate_public_url"), \
             patch("knowledge_lake.pipeline.crawl.fetch_robots") as mock_robots, \
             patch("knowledge_lake.pipeline.crawl.register_source", return_value={"source_id": source.id, "is_new": False}), \
             patch("knowledge_lake.pipeline.crawl._find_or_create_job", return_value=job.id), \
             patch("knowledge_lake.pipeline.crawl.StorageBackend", return_value=mock_storage):

            mock_robots.return_value = mock_robots_policy

            from knowledge_lake.pipeline.crawl import crawl_source

            result = crawl_source(
                "https://example.com",
                settings=MagicMock(
                    crawler="crawl4ai",
                    crawl=MagicMock(
                        max_pages=50,
                        rate_limit_seconds=0.0,
                        same_domain_only=True,
                    ),
                    storage=MagicMock(),
                ),
            )

        # The URL should be recorded as robots_blocked
        stmt = select(CrawlState).where(
            CrawlState.url == "https://example.com/private/secret"
        )
        blocked_state = session.execute(stmt).scalar_one()
        assert blocked_state.status == "robots_blocked"

        # No artifacts should have been written for the blocked URL
        assert blocked_state.raw_artifact_id is None
        assert blocked_state.bronze_artifact_id is None

        # put_raw and put_bronze should NOT have been called
        mock_storage.put_raw.assert_not_called()
        mock_storage.put_bronze.assert_not_called()

        # The adapter fetch_page should NOT have been called (blocked before fetch)
        mock_adapter.fetch_page.assert_not_called()

        # Stats should reflect 1 robots_blocked
        assert result["pages_robots_blocked"] == 1
        assert result["pages_complete"] == 0

        session.close()

    def test_mixed_allowed_and_blocked_urls(self, engine, mock_adapter):
        """Mix of allowed and blocked URLs: only allowed get artifacts."""
        session = Session(engine)

        @contextmanager
        def mock_get_session():
            try:
                yield session
                session.flush()
            except Exception:
                session.rollback()
                raise

        source = Source(
            id="src_mixed_test",
            name="Mixed Test",
            source_type="web",
            url="https://example.com",
            normalized_url="https://example.com",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(source)
        session.flush()

        job = Job(
            id="job_mixed_test",
            status="running",
            source_id=source.id,
            job_type="crawl",
            crawler="crawl4ai",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(job)
        session.flush()

        # Two URLs: one allowed, one blocked
        allowed_state = CrawlState(
            id="cst_mixed_allowed",
            job_id=job.id,
            url="https://example.com/public/page",
            normalized_url="https://example.com/public/page",
            status="pending",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        blocked_state = CrawlState(
            id="cst_mixed_blocked",
            job_id=job.id,
            url="https://example.com/private/data",
            normalized_url="https://example.com/private/data",
            status="pending",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(allowed_state)
        session.add(blocked_state)
        session.flush()

        mock_storage = MagicMock()
        mock_raw = MagicMock()
        mock_raw.id = "doc_mixed_raw"
        mock_bronze = MagicMock()
        mock_bronze.id = "doc_mixed_bronze"
        mock_storage.put_raw.return_value = mock_raw
        mock_storage.put_bronze.return_value = mock_bronze

        mock_robots_policy = MagicMock()

        def is_allowed(path):
            return not path.startswith("/private/")

        mock_robots_policy.is_allowed.side_effect = is_allowed
        mock_robots_policy.crawl_delay.return_value = None

        with patch("knowledge_lake.pipeline.crawl.get_session", mock_get_session), \
             patch("knowledge_lake.registry.db.get_session", mock_get_session), \
             patch("knowledge_lake.pipeline.ingest.get_session", mock_get_session), \
             patch("knowledge_lake.pipeline.crawl.get_crawler", return_value=mock_adapter), \
             patch("knowledge_lake.pipeline.crawl.validate_public_url"), \
             patch("knowledge_lake.pipeline.crawl.fetch_robots") as mock_robots, \
             patch("knowledge_lake.pipeline.crawl.register_source", return_value={"source_id": source.id, "is_new": False}), \
             patch("knowledge_lake.pipeline.crawl._find_or_create_job", return_value=job.id), \
             patch("knowledge_lake.pipeline.crawl.StorageBackend", return_value=mock_storage):

            mock_robots.return_value = mock_robots_policy

            from knowledge_lake.pipeline.crawl import crawl_source

            result = crawl_source(
                "https://example.com",
                settings=MagicMock(
                    crawler="crawl4ai",
                    crawl=MagicMock(
                        max_pages=50,
                        rate_limit_seconds=0.0,
                        same_domain_only=True,
                    ),
                    storage=MagicMock(),
                ),
            )

        # Verify allowed URL got fetched
        assert result["pages_complete"] == 1
        assert result["pages_robots_blocked"] == 1

        # put_raw was called exactly once (for the allowed URL only)
        assert mock_storage.put_raw.call_count == 1

        # Check crawl_states
        stmt = select(CrawlState).where(
            CrawlState.url == "https://example.com/private/data"
        )
        blocked = session.execute(stmt).scalar_one()
        assert blocked.status == "robots_blocked"
        assert blocked.raw_artifact_id is None

        session.close()
