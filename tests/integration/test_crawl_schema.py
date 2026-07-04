"""
Integration tests for crawl schema (migration 0003, INGEST-04, T-02-05).

Tests verify:
  - Migration 0003 applies correctly (revision, down_revision)
  - crawl_states table exists with UNIQUE(job_id, normalized_url)
  - Inserting duplicate (job_id, normalized_url) raises IntegrityError
  - Identical content under two different URLs yields two crawl_states rows
  - Jobs table has the new columns (source_id, job_type, crawler, config, stats, updated_at)

Uses an in-memory SQLite database via ORM metadata.create_all (structural test).
"""

from __future__ import annotations

import datetime

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture(scope="module")
def engine():
    """In-memory SQLite engine with all tables created via ORM."""
    from knowledge_lake.registry.models import Base

    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    """Fresh session per test; rolls back on teardown."""
    with Session(engine) as sess:
        yield sess
        sess.rollback()


class TestMigration0003Metadata:
    """Migration 0003 has correct revision identifiers."""

    def test_revision_is_0003(self):
        import importlib

        mod = importlib.import_module(
            "knowledge_lake.registry.alembic.versions.0003_crawl_jobs_states"
        )
        assert mod.revision == "0003"

    def test_down_revision_is_0002(self):
        import importlib

        mod = importlib.import_module(
            "knowledge_lake.registry.alembic.versions.0003_crawl_jobs_states"
        )
        assert mod.down_revision == "0002"


class TestCrawlStatesTable:
    """crawl_states table exists with the expected columns and constraints."""

    def test_crawl_states_table_exists(self, engine):
        insp = inspect(engine)
        assert "crawl_states" in insp.get_table_names()

    def test_crawl_states_has_required_columns(self, engine):
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("crawl_states")}
        for required in (
            "id",
            "job_id",
            "url",
            "normalized_url",
            "status",
            "raw_artifact_id",
            "bronze_artifact_id",
            "fetched_at",
            "created_at",
        ):
            assert required in cols, f"crawl_states.{required} column missing"


class TestCrawlStatesUniqueConstraint:
    """UNIQUE(job_id, normalized_url) is enforced (T-02-05, Pitfall 4)."""

    def test_duplicate_job_url_raises_integrity_error(self, session):
        """Inserting two rows with the same (job_id, normalized_url) raises IntegrityError."""
        from knowledge_lake.registry.models import CrawlState, Job, Source

        # Create prerequisites
        source = Source(
            id="src_test_dup",
            name="Dup Test",
            source_type="web",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(source)
        session.flush()

        job = Job(
            id="job_test_dup",
            status="pending",
            source_id=source.id,
            job_type="crawl",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(job)
        session.flush()

        # First state row
        state1 = CrawlState(
            id="cst_dup_1",
            job_id=job.id,
            url="https://example.com/page",
            normalized_url="https://example.com/page",
            status="pending",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(state1)
        session.flush()

        # Second state row with same (job_id, normalized_url)
        state2 = CrawlState(
            id="cst_dup_2",
            job_id=job.id,
            url="https://example.com/page",
            normalized_url="https://example.com/page",
            status="complete",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(state2)

        with pytest.raises(IntegrityError):
            session.flush()

    def test_identical_content_different_urls_succeeds(self, session):
        """Same content under two URLs yields two crawl_states rows (Pitfall 4).

        The UNIQUE constraint is on (job_id, normalized_url) NOT on content_hash,
        so identical content under different URLs is allowed.
        """
        from knowledge_lake.registry.models import CrawlState, Job, Source

        source = Source(
            id="src_test_multi",
            name="Multi URL Test",
            source_type="web",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(source)
        session.flush()

        job = Job(
            id="job_test_multi",
            status="running",
            source_id=source.id,
            job_type="crawl",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(job)
        session.flush()

        # Two different URLs, same content (same raw_artifact_id)
        state1 = CrawlState(
            id="cst_multi_1",
            job_id=job.id,
            url="https://example.com/page-a",
            normalized_url="https://example.com/page-a",
            status="complete",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        state2 = CrawlState(
            id="cst_multi_2",
            job_id=job.id,
            url="https://example.com/page-b",
            normalized_url="https://example.com/page-b",
            status="complete",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(state1)
        session.add(state2)
        session.flush()  # Should NOT raise

        # Both rows exist
        from sqlalchemy import select

        stmt = select(CrawlState).where(CrawlState.job_id == job.id)
        results = list(session.execute(stmt).scalars())
        assert len(results) == 2


class TestJobsExtended:
    """Jobs table has the new Phase 2 columns."""

    def test_jobs_has_new_columns(self, engine):
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("jobs")}
        for required in ("source_id", "job_type", "crawler", "config", "stats", "updated_at"):
            assert required in cols, f"jobs.{required} column missing"

    def test_job_type_default_is_crawl(self, session):
        from knowledge_lake.registry.models import Job, Source

        source = Source(
            id="src_job_test",
            name="Job Test",
            source_type="web",
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(source)
        session.flush()

        job = Job(
            id="job_type_test",
            status="pending",
            source_id=source.id,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
        session.add(job)
        session.flush()

        assert job.job_type == "crawl"
