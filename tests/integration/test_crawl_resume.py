"""
Integration tests for crawl resume (INGEST-09, D-03).

Tests verify:
  - After an interrupted run, crawl_states has N complete + M pending
  - The re-run's fetch spy is called only for the M pending URLs
  - Completed URLs are NOT re-requested (resume invariant)
  - validate_public_url is called before the fetch for every URL (ordering)
  - A completed page produces raw+bronze artifacts with lineage (D-01)

Uses an in-memory SQLite database with mocked adapter and storage.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from knowledge_lake.registry.models import Base, CrawlState, Job, Source, Artifact


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine."""
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    """Provide a session and patch get_session to use it."""
    from contextlib import contextmanager

    session = Session(engine)

    @contextmanager
    def mock_get_session():
        try:
            yield session
            session.flush()
        except Exception:
            session.rollback()
            raise

    with patch("knowledge_lake.pipeline.crawl.get_session", mock_get_session), \
         patch("knowledge_lake.registry.db.get_session", mock_get_session), \
         patch("knowledge_lake.pipeline.ingest.get_session", mock_get_session), \
         patch("knowledge_lake.storage.s3.StorageBackend"):
        yield session

    session.close()


@pytest.fixture()
def mock_adapter():
    """Mock crawler adapter with fetch_page that tracks calls."""
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


class TestCrawlResume:
    """Resume interrupted crawls without re-fetching completed URLs."""

    def test_resume_fetches_only_pending_urls(self, engine, mock_adapter):
        """After partial crawl, re-run fetches only pending URLs."""
        from contextlib import contextmanager

        session = Session(engine)

        @contextmanager
        def mock_get_session():
            try:
                yield session
                session.flush()
            except Exception:
                session.rollback()
                raise

        # Setup: create source & job with 2 complete + 2 pending states
        source = Source(
            id="src_resume_test",
            name="Resume Test",
            source_type="web",
            url="https://example.com",
            normalized_url="https://example.com",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(source)
        session.flush()

        job = Job(
            id="job_resume_test",
            status="running",
            source_id=source.id,
            job_type="crawl",
            crawler="crawl4ai",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(job)
        session.flush()

        # 2 completed states
        for i in range(2):
            state = CrawlState(
                id=f"cst_complete_{i}",
                job_id=job.id,
                url=f"https://example.com/done-{i}",
                normalized_url=f"https://example.com/done-{i}",
                status="complete",
                raw_artifact_id=f"doc_fake_{i}",
                created_at=datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(state)

        # 2 pending states
        pending_urls = [
            "https://example.com/pending-0",
            "https://example.com/pending-1",
        ]
        for i, url in enumerate(pending_urls):
            state = CrawlState(
                id=f"cst_pending_{i}",
                job_id=job.id,
                url=url,
                normalized_url=url,
                status="pending",
                created_at=datetime.datetime.now(datetime.timezone.utc),
            )
            session.add(state)
        session.flush()

        # Patch everything for the resume run
        mock_storage = MagicMock()
        mock_raw_artifact = MagicMock()
        mock_raw_artifact.id = "doc_new_raw"
        mock_bronze_artifact = MagicMock()
        mock_bronze_artifact.id = "doc_new_bronze"
        mock_storage.put_raw.return_value = mock_raw_artifact
        mock_storage.put_bronze.return_value = mock_bronze_artifact

        with patch("knowledge_lake.pipeline.crawl.get_session", mock_get_session), \
             patch("knowledge_lake.registry.db.get_session", mock_get_session), \
             patch("knowledge_lake.pipeline.ingest.get_session", mock_get_session), \
             patch("knowledge_lake.pipeline.crawl.get_crawler", return_value=mock_adapter), \
             patch("knowledge_lake.pipeline.crawl.validate_public_url"), \
             patch("knowledge_lake.pipeline.crawl.fetch_robots") as mock_robots, \
             patch("knowledge_lake.pipeline.crawl.register_source", return_value={"source_id": source.id, "is_new": False}), \
             patch("knowledge_lake.pipeline.crawl._find_or_create_job", return_value=job.id), \
             patch("knowledge_lake.pipeline.crawl.StorageBackend", return_value=mock_storage):

            mock_robots_policy = MagicMock()
            mock_robots_policy.is_allowed.return_value = True
            mock_robots_policy.crawl_delay.return_value = None
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

        # Verify: adapter was called only for the 2 pending URLs
        fetched_urls = [c.args[0] for c in mock_adapter.fetch_page.call_args_list]
        assert len(fetched_urls) == 2
        assert set(fetched_urls) == set(pending_urls)

        # Completed URLs were NOT re-requested
        assert "https://example.com/done-0" not in fetched_urls
        assert "https://example.com/done-1" not in fetched_urls

        session.close()

    def test_validate_public_url_called_before_fetch(self, engine, mock_adapter):
        """validate_public_url is called for every URL before the adapter fetches."""
        from contextlib import contextmanager

        session = Session(engine)

        @contextmanager
        def mock_get_session():
            try:
                yield session
                session.flush()
            except Exception:
                session.rollback()
                raise

        # Setup source & job with one pending URL
        source = Source(
            id="src_order_test",
            name="Order Test",
            source_type="web",
            url="https://example.com",
            normalized_url="https://example.com",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(source)
        session.flush()

        job = Job(
            id="job_order_test",
            status="running",
            source_id=source.id,
            job_type="crawl",
            crawler="crawl4ai",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(job)
        session.flush()

        state = CrawlState(
            id="cst_order_0",
            job_id=job.id,
            url="https://example.com/page",
            normalized_url="https://example.com/page",
            status="pending",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(state)
        session.flush()

        call_order = []

        def track_validate(url):
            call_order.append(("validate", url))

        async def track_fetch(url):
            call_order.append(("fetch", url))
            from knowledge_lake.plugins.protocols import CrawlPageResult

            return CrawlPageResult(
                url=url,
                status="complete",
                html=b"<html>test</html>",
                markdown="# test",
                fetched_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )

        mock_adapter.fetch_page = AsyncMock(side_effect=track_fetch)

        mock_storage = MagicMock()
        mock_raw = MagicMock()
        mock_raw.id = "doc_order_raw"
        mock_bronze = MagicMock()
        mock_bronze.id = "doc_order_bronze"
        mock_storage.put_raw.return_value = mock_raw
        mock_storage.put_bronze.return_value = mock_bronze

        with patch("knowledge_lake.pipeline.crawl.get_session", mock_get_session), \
             patch("knowledge_lake.registry.db.get_session", mock_get_session), \
             patch("knowledge_lake.pipeline.ingest.get_session", mock_get_session), \
             patch("knowledge_lake.pipeline.crawl.get_crawler", return_value=mock_adapter), \
             patch("knowledge_lake.pipeline.crawl.validate_public_url", side_effect=track_validate), \
             patch("knowledge_lake.pipeline.crawl.fetch_robots") as mock_robots, \
             patch("knowledge_lake.pipeline.crawl.register_source", return_value={"source_id": source.id, "is_new": False}), \
             patch("knowledge_lake.pipeline.crawl._find_or_create_job", return_value=job.id), \
             patch("knowledge_lake.pipeline.crawl.StorageBackend", return_value=mock_storage):

            mock_robots_policy = MagicMock()
            mock_robots_policy.is_allowed.return_value = True
            mock_robots_policy.crawl_delay.return_value = None
            mock_robots.return_value = mock_robots_policy

            from knowledge_lake.pipeline.crawl import crawl_source

            crawl_source(
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

        # Validate is called BEFORE fetch for the page URL
        page_actions = [(action, url) for action, url in call_order
                        if url == "https://example.com/page"]
        assert len(page_actions) >= 2
        validate_idx = next(i for i, (a, _) in enumerate(page_actions) if a == "validate")
        fetch_idx = next(i for i, (a, _) in enumerate(page_actions) if a == "fetch")
        assert validate_idx < fetch_idx, "validate_public_url must be called before fetch"

        session.close()

    def test_complete_page_has_raw_bronze_lineage(self, engine, mock_adapter):
        """A completed page produces bronze with parent_artifact_id == raw.id (D-01)."""
        from contextlib import contextmanager

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
            id="src_lineage_test",
            name="Lineage Test",
            source_type="web",
            url="https://example.com",
            normalized_url="https://example.com",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(source)
        session.flush()

        job = Job(
            id="job_lineage_test",
            status="running",
            source_id=source.id,
            job_type="crawl",
            crawler="crawl4ai",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(job)
        session.flush()

        state = CrawlState(
            id="cst_lineage_0",
            job_id=job.id,
            url="https://example.com/page",
            normalized_url="https://example.com/page",
            status="pending",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(state)
        session.flush()

        mock_storage = MagicMock()
        mock_raw = MagicMock()
        mock_raw.id = "doc_raw_lineage"
        mock_bronze = MagicMock()
        mock_bronze.id = "doc_bronze_lineage"
        mock_storage.put_raw.return_value = mock_raw
        mock_storage.put_bronze.return_value = mock_bronze

        with patch("knowledge_lake.pipeline.crawl.get_session", mock_get_session), \
             patch("knowledge_lake.registry.db.get_session", mock_get_session), \
             patch("knowledge_lake.pipeline.ingest.get_session", mock_get_session), \
             patch("knowledge_lake.pipeline.crawl.get_crawler", return_value=mock_adapter), \
             patch("knowledge_lake.pipeline.crawl.validate_public_url"), \
             patch("knowledge_lake.pipeline.crawl.fetch_robots") as mock_robots, \
             patch("knowledge_lake.pipeline.crawl.register_source", return_value={"source_id": source.id, "is_new": False}), \
             patch("knowledge_lake.pipeline.crawl._find_or_create_job", return_value=job.id), \
             patch("knowledge_lake.pipeline.crawl.StorageBackend", return_value=mock_storage):

            mock_robots_policy = MagicMock()
            mock_robots_policy.is_allowed.return_value = True
            mock_robots_policy.crawl_delay.return_value = None
            mock_robots.return_value = mock_robots_policy

            from knowledge_lake.pipeline.crawl import crawl_source

            crawl_source(
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

        # Verify put_bronze was called with parent_artifact_id == raw.id
        mock_storage.put_bronze.assert_called_once()
        call_kwargs = mock_storage.put_bronze.call_args
        assert call_kwargs.kwargs["parent_artifact_id"] == "doc_raw_lineage"

        session.close()
