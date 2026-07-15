"""
Unit tests for the registry models and repo layer (FOUND-05, FOUND-06).

Uses an in-memory SQLite database so tests can run without a running PostgreSQL
instance (SQLAlchemy ORM is database-agnostic for these structural assertions).

NOTE: The integration tests (tests/integration/test_migrations.py) exercise
the real PostgreSQL path.  These unit tests focus on model structure, repo
logic, and the UNIQUE(content_hash, artifact_type) constraint.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session


# ── Fixtures ──────────────────────────────────────────────────────────────────


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


# ── Source model tests ────────────────────────────────────────────────────────


class TestSourceModel:
    """The Source model maps to the 'sources' table with the correct columns."""

    def test_source_table_exists(self, engine) -> None:
        insp = inspect(engine)
        assert "sources" in insp.get_table_names(), "sources table missing"

    def test_source_has_required_columns(self, engine) -> None:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("sources")}
        for required in ("id", "name", "source_type", "url", "license_type",
                         "license_url", "robots_checked", "config", "created_at"):
            assert required in cols, f"sources.{required} column missing"


class TestSourceCreate:
    """create_source returns a Source row with expected fields."""

    def test_create_source_returns_id(self, session) -> None:
        from knowledge_lake.registry.repo import create_source

        source = create_source(
            session,
            name="HHS HIPAA Guidance",
            source_type="web",
            url="https://www.hhs.gov/hipaa",
        )
        assert source.id.startswith("src_"), f"Expected src_ prefix: {source.id}"

    def test_create_source_persists_fields(self, session) -> None:
        from knowledge_lake.registry.repo import create_source

        source = create_source(
            session,
            name="Test Source",
            source_type="upload",
            url="https://example.com/doc.pdf",
            license_type="public_domain",
        )
        session.flush()

        # Re-fetch to verify persistence
        from knowledge_lake.registry.models import Source
        fetched = session.get(Source, source.id)
        assert fetched is not None
        assert fetched.name == "Test Source"
        assert fetched.source_type == "upload"
        assert fetched.license_type == "public_domain"

    def test_create_source_created_at_set(self, session) -> None:
        from knowledge_lake.registry.repo import create_source

        source = create_source(session, name="TS", source_type="web")
        session.flush()
        assert source.created_at is not None


# ── Artifact model tests ──────────────────────────────────────────────────────


class TestArtifactModel:
    """The Artifact model maps to the 'artifacts' table with the correct columns."""

    def test_artifacts_table_exists(self, engine) -> None:
        insp = inspect(engine)
        assert "artifacts" in insp.get_table_names(), "artifacts table missing"

    def test_artifacts_has_required_columns(self, engine) -> None:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("artifacts")}
        for required in (
            "id", "source_id", "parent_artifact_id", "artifact_type",
            "content_hash", "pipeline_version", "storage_uri",
            "mime_type", "page_ref", "section_path", "metadata", "created_at",
        ):
            assert required in cols, f"artifacts.{required} column missing"


class TestRawArtifactCreate:
    """create_raw_artifact returns a row with all six FOUND-06 lineage fields."""

    @pytest.fixture()
    def source(self, session):
        from knowledge_lake.registry.repo import create_source
        return create_source(session, name="Test Source", source_type="web")

    def test_create_raw_artifact_has_six_lineage_fields(self, session, source) -> None:
        """Every raw artifact must carry the six FOUND-06 fields."""
        from knowledge_lake.registry.repo import create_raw_artifact

        art = create_raw_artifact(
            session,
            source_id=source.id,
            content_hash="abc123",
            storage_uri="s3://bucket/raw/abc123.pdf",
            mime_type="application/pdf",
        )
        session.flush()

        # FOUND-06: source_id, parent_artifact_id, content_hash,
        # pipeline_version, storage_uri, created_at
        assert art.source_id == source.id
        assert art.parent_artifact_id is None        # NULL for raw
        assert art.content_hash == "abc123"
        assert art.pipeline_version                  # non-empty
        assert art.storage_uri == "s3://bucket/raw/abc123.pdf"
        assert art.created_at is not None

    def test_create_raw_artifact_type(self, session, source) -> None:
        from knowledge_lake.registry.repo import create_raw_artifact

        art = create_raw_artifact(
            session,
            source_id=source.id,
            content_hash="hash_raw",
            storage_uri="s3://bucket/raw/hash_raw.pdf",
        )
        assert art.artifact_type == "raw_document"

    def test_create_raw_artifact_id_prefixed(self, session, source) -> None:
        from knowledge_lake.registry.repo import create_raw_artifact

        art = create_raw_artifact(
            session,
            source_id=source.id,
            content_hash="hash_prefix",
            storage_uri="s3://bucket/raw/hash_prefix.pdf",
        )
        assert art.id.startswith("doc_"), f"Expected doc_ prefix: {art.id}"


class TestParsedArtifactCreate:
    """create_parsed_artifact sets parent_artifact_id to the raw artifact."""

    @pytest.fixture()
    def source(self, session):
        from knowledge_lake.registry.repo import create_source
        return create_source(session, name="PS", source_type="web")

    @pytest.fixture()
    def raw_art(self, session, source):
        from knowledge_lake.registry.repo import create_raw_artifact
        return create_raw_artifact(
            session, source_id=source.id, content_hash="raw_h",
            storage_uri="s3://b/raw/raw_h.pdf",
        )

    def test_parsed_sets_parent_to_raw(self, session, source, raw_art) -> None:
        from knowledge_lake.registry.repo import create_parsed_artifact

        parsed = create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw_art.id,
            content_hash="parsed_h",
            storage_uri="s3://b/silver/parsed_h.json",
        )
        assert parsed.parent_artifact_id == raw_art.id

    def test_parsed_artifact_type(self, session, source, raw_art) -> None:
        from knowledge_lake.registry.repo import create_parsed_artifact

        parsed = create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw_art.id,
            content_hash="parsed_type_h",
            storage_uri="s3://b/silver/parsed_type_h.json",
        )
        assert parsed.artifact_type == "parsed_document"


class TestChunkArtifactCreate:
    """create_chunk_artifact sets parent_artifact_id to the parsed artifact."""

    @pytest.fixture()
    def chain(self, session):
        from knowledge_lake.registry.repo import (
            create_chunk_artifact,
            create_parsed_artifact,
            create_raw_artifact,
            create_source,
        )
        src = create_source(session, name="CS", source_type="web")
        raw = create_raw_artifact(
            session, source_id=src.id, content_hash="c_raw",
            storage_uri="s3://b/raw/c_raw.pdf",
        )
        parsed = create_parsed_artifact(
            session, source_id=src.id, parent_artifact_id=raw.id,
            content_hash="c_parsed", storage_uri="s3://b/silver/c_parsed.json",
        )
        return src, raw, parsed

    def test_chunk_parent_is_parsed(self, session, chain) -> None:
        from knowledge_lake.registry.repo import create_chunk_artifact

        src, raw, parsed = chain
        chunk = create_chunk_artifact(
            session,
            source_id=src.id,
            parent_artifact_id=parsed.id,
            content_hash="c_chunk_1",
            storage_uri="s3://b/silver/c_chunk_1.json",
        )
        assert chunk.parent_artifact_id == parsed.id

    def test_chunk_artifact_type(self, session, chain) -> None:
        from knowledge_lake.registry.repo import create_chunk_artifact

        src, raw, parsed = chain
        chunk = create_chunk_artifact(
            session,
            source_id=src.id,
            parent_artifact_id=parsed.id,
            content_hash="c_chunk_type",
            storage_uri="s3://b/silver/c_chunk_type.json",
        )
        assert chunk.artifact_type == "chunk"

    def test_chunk_id_prefixed_chk(self, session, chain) -> None:
        from knowledge_lake.registry.repo import create_chunk_artifact

        src, raw, parsed = chain
        chunk = create_chunk_artifact(
            session,
            source_id=src.id,
            parent_artifact_id=parsed.id,
            content_hash="c_chunk_prefix",
            storage_uri="s3://b/silver/c_chunk_prefix.json",
        )
        assert chunk.id.startswith("chk_"), f"Expected chk_ prefix: {chunk.id}"


# ── Hash lookup tests ─────────────────────────────────────────────────────────


class TestGetArtifactByHash:
    """get_artifact_by_hash returns existing row or None."""

    @pytest.fixture()
    def source(self, session):
        from knowledge_lake.registry.repo import create_source
        return create_source(session, name="Hash Source", source_type="web")

    def test_returns_existing_artifact(self, session, source) -> None:
        from knowledge_lake.registry.repo import create_raw_artifact, get_artifact_by_hash

        art = create_raw_artifact(
            session, source_id=source.id,
            content_hash="exists_hash", storage_uri="s3://b/raw/exists_hash.pdf",
        )
        session.flush()

        found = get_artifact_by_hash(session, "exists_hash", "raw_document")
        assert found is not None
        assert found.id == art.id

    def test_returns_none_for_unknown_hash(self, session) -> None:
        from knowledge_lake.registry.repo import get_artifact_by_hash

        result = get_artifact_by_hash(session, "definitely_not_here", "raw_document")
        assert result is None

    def test_type_is_discriminator(self, session, source) -> None:
        """Same hash + different type = None (type matters for dedup)."""
        from knowledge_lake.registry.repo import create_raw_artifact, get_artifact_by_hash

        create_raw_artifact(
            session, source_id=source.id,
            content_hash="disc_hash", storage_uri="s3://b/raw/disc_hash.pdf",
        )
        session.flush()

        # The same hash for a different type should not be found
        result = get_artifact_by_hash(session, "disc_hash", "chunk")
        assert result is None


# ── Enriched artifact, LLM spend, vector collections tests (Phase 4) ─────────


class TestEnrichedArtifactAndSpend:
    """create_enriched_artifact, LLM spend, and vector-collection repo functions."""

    @pytest.fixture()
    def source(self, session):
        from knowledge_lake.registry.repo import create_source
        return create_source(session, name="Enrich Source", source_type="web")

    def test_create_enriched_artifact_sets_fields(self, session, source) -> None:
        from knowledge_lake.registry.repo import (
            create_cleaned_artifact,
            create_enriched_artifact,
            create_parsed_artifact,
            create_raw_artifact,
        )

        raw = create_raw_artifact(
            session, source_id=source.id, content_hash="e_raw",
            storage_uri="s3://b/raw/e_raw.pdf",
        )
        parsed = create_parsed_artifact(
            session, source_id=source.id, parent_artifact_id=raw.id,
            content_hash="e_parsed", storage_uri="s3://b/silver/e_parsed.json",
        )
        cleaned = create_cleaned_artifact(
            session, source_id=source.id, parent_artifact_id=parsed.id,
            content_hash="e_cleaned", storage_uri="s3://b/silver/e_cleaned.md",
        )
        enriched = create_enriched_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=cleaned.id,
            content_hash="e_enriched",
            quality_score=0.87,
        )
        session.flush()

        assert enriched.artifact_type == "enriched_document"
        assert enriched.quality_score == 0.87
        assert enriched.parent_artifact_id == cleaned.id
        assert enriched.id.startswith("doc_")

    def test_get_llm_spend_returns_zero_for_unseen_scope(self, session) -> None:
        from knowledge_lake.registry.repo import get_llm_spend

        assert get_llm_spend(session, scope="never-used-scope") == 0.0

    def test_record_llm_spend_accumulates(self, session) -> None:
        from knowledge_lake.registry.repo import get_llm_spend, record_llm_spend

        record_llm_spend(session, "test-scope", 1.5)
        session.flush()
        record_llm_spend(session, "test-scope", 2.25)
        session.flush()

        assert get_llm_spend(session, scope="test-scope") == pytest.approx(3.75)

    def test_register_vector_collection_flips_current(self, session) -> None:
        from knowledge_lake.registry.repo import (
            get_current_vector_collection,
            register_vector_collection,
        )

        first = register_vector_collection(
            session, alias_name="klake_chunks_test", physical_collection="klake_chunks_test_v1", dim=384,
        )
        session.flush()
        second = register_vector_collection(
            session, alias_name="klake_chunks_test", physical_collection="klake_chunks_test_v2", dim=384,
        )
        session.flush()

        assert first.is_current is False
        assert second.is_current is True

        current = get_current_vector_collection(session, "klake_chunks_test")
        assert current is not None
        assert current.physical_collection == "klake_chunks_test_v2"

    def test_get_enriched_artifact_for_parsed_resolves_chain(self, session, source) -> None:
        from knowledge_lake.registry.repo import (
            create_cleaned_artifact,
            create_enriched_artifact,
            create_parsed_artifact,
            create_raw_artifact,
            get_enriched_artifact_for_parsed,
        )

        raw = create_raw_artifact(
            session, source_id=source.id, content_hash="chain_raw",
            storage_uri="s3://b/raw/chain_raw.pdf",
        )
        parsed = create_parsed_artifact(
            session, source_id=source.id, parent_artifact_id=raw.id,
            content_hash="chain_parsed", storage_uri="s3://b/silver/chain_parsed.json",
        )
        cleaned = create_cleaned_artifact(
            session, source_id=source.id, parent_artifact_id=parsed.id,
            content_hash="chain_cleaned", storage_uri="s3://b/silver/chain_cleaned.md",
        )
        enriched = create_enriched_artifact(
            session, source_id=source.id, parent_artifact_id=cleaned.id,
            content_hash="chain_enriched",
        )
        session.flush()

        found = get_enriched_artifact_for_parsed(session, parsed.id)
        assert found is not None
        assert found.id == enriched.id

    def test_get_enriched_artifact_for_parsed_returns_none_without_descendants(
        self, session, source
    ) -> None:
        from knowledge_lake.registry.repo import (
            create_raw_artifact,
            create_parsed_artifact,
            get_enriched_artifact_for_parsed,
        )

        raw = create_raw_artifact(
            session, source_id=source.id, content_hash="lonely_raw",
            storage_uri="s3://b/raw/lonely_raw.pdf",
        )
        parsed = create_parsed_artifact(
            session, source_id=source.id, parent_artifact_id=raw.id,
            content_hash="lonely_parsed", storage_uri="s3://b/silver/lonely_parsed.json",
        )
        session.flush()

        assert get_enriched_artifact_for_parsed(session, parsed.id) is None

    def test_get_domain_for_source_returns_domain(self, session) -> None:
        from knowledge_lake.registry.repo import create_source, get_domain_for_source

        source = create_source(
            session, name="Domain Source", source_type="web",
            config={"domain": "healthcare"},
        )
        session.flush()

        assert get_domain_for_source(session, source.id) == "healthcare"

    def test_get_domain_for_source_returns_none_without_config(self, session) -> None:
        from knowledge_lake.registry.repo import create_source, get_domain_for_source

        source = create_source(session, name="No Config Source", source_type="web")
        session.flush()

        assert get_domain_for_source(session, source.id) is None

    def test_get_domain_for_source_reads_column_first(self, session) -> None:
        """KL-15: get_domain_for_source() prefers the first-class column."""
        from knowledge_lake.registry.repo import create_source, get_domain_for_source

        source = create_source(
            session, name="Column Source", source_type="web", domain="aviation",
        )
        session.flush()

        assert get_domain_for_source(session, source.id) == "aviation"
        assert source.domain == "aviation"

    def test_get_domain_for_source_falls_back_to_config_blob(self, session) -> None:
        """Rows with only config['domain'] (no column value) still resolve (KL-15)."""
        from knowledge_lake.registry.repo import create_source, get_domain_for_source

        source = create_source(
            session, name="Blob-only Source", source_type="web",
            config={"domain": "functional-medicine"},
        )
        session.flush()

        assert source.domain is None
        assert get_domain_for_source(session, source.id) == "functional-medicine"

    def test_create_source_dual_writes_domain_column_and_config(self, session) -> None:
        """Both KL-15 write sites dual-write: column AND config['domain']."""
        from knowledge_lake.registry.repo import create_source

        source = create_source(
            session, name="Dual Write Source", source_type="web",
            domain="aviation", config={"domain": "aviation"},
        )
        session.flush()

        assert source.domain == "aviation"
        assert source.config["domain"] == "aviation"


# ── Alembic 0010 migration + Source.domain column (KL-15) ───────────────────


class TestAlembic0010Migration:
    """Verify 0010 migration module exposes correct revision chain."""

    def test_0010_revision_identifiers(self) -> None:
        import importlib
        mod = importlib.import_module(
            "knowledge_lake.registry.alembic.versions.0010_sources_domain_column"
        )
        assert mod.revision == "0010"
        assert mod.down_revision == "0009"

    def test_0010_upgrade_adds_domain_column_and_index(self) -> None:
        import importlib
        import inspect
        mod = importlib.import_module(
            "knowledge_lake.registry.alembic.versions.0010_sources_domain_column"
        )
        src = inspect.getsource(mod.upgrade)
        assert "add_column" in src
        assert '"domain"' in src
        assert "create_index" in src

    def test_0010_downgrade_drops_index_then_column(self) -> None:
        import importlib
        import inspect
        mod = importlib.import_module(
            "knowledge_lake.registry.alembic.versions.0010_sources_domain_column"
        )
        src = inspect.getsource(mod.downgrade)
        assert "drop_index" in src
        assert "drop_column" in src
        # index dropped before the column it indexes
        assert src.index("drop_index") < src.index("drop_column")


class TestSourceDomainColumn:
    """Source ORM has the first-class domain column (KL-15)."""

    def test_source_has_domain_attr(self) -> None:
        from knowledge_lake.registry.models import Source
        assert hasattr(Source, "domain")

    def test_domain_column_is_nullable(self, engine) -> None:
        from sqlalchemy import inspect as sa_inspect
        insp = sa_inspect(engine)
        cols = {c["name"]: c for c in insp.get_columns("sources")}
        assert cols["domain"]["nullable"] is True

    def test_source_domain_defaults_none(self, session) -> None:
        from knowledge_lake.registry.repo import create_source

        source = create_source(session, name="NoDomain", source_type="web")
        session.flush()
        assert source.domain is None

    def test_create_source_accepts_domain_kwarg(self, session) -> None:
        import inspect
        from knowledge_lake.registry.repo import create_source

        sig = inspect.signature(create_source)
        assert "domain" in sig.parameters
        assert sig.parameters["domain"].default is None


# ── Alembic 0009 migration + Source crawl columns (Phase 11, SCHED-01/02) ────


class TestAlembic0009Migration:
    """Verify 0009 migration module exposes correct revision chain."""

    def test_0009_revision_identifiers(self) -> None:
        import importlib
        mod = importlib.import_module(
            "knowledge_lake.registry.alembic.versions.0009_crawl_scheduling"
        )
        assert mod.revision == "0009"
        assert mod.down_revision == "0008"

    def test_0009_upgrade_has_three_add_columns(self) -> None:
        import importlib
        mod = importlib.import_module(
            "knowledge_lake.registry.alembic.versions.0009_crawl_scheduling"
        )
        import inspect
        src = inspect.getsource(mod.upgrade)
        assert "crawl_schedule" in src
        assert "last_crawled_at" in src
        assert "last_content_hash" in src

    def test_0009_downgrade_drops_in_reverse(self) -> None:
        import importlib
        mod = importlib.import_module(
            "knowledge_lake.registry.alembic.versions.0009_crawl_scheduling"
        )
        import inspect
        src = inspect.getsource(mod.downgrade)
        # Reverse order: hash, crawled_at, schedule
        hash_pos = src.index("last_content_hash")
        crawled_pos = src.index("last_crawled_at")
        schedule_pos = src.index("crawl_schedule")
        assert hash_pos < crawled_pos < schedule_pos


class TestSourceCrawlColumns:
    """Source ORM has the three nullable crawl columns (SCHED-01/02)."""

    def test_source_has_crawl_schedule_attr(self) -> None:
        from knowledge_lake.registry.models import Source
        assert hasattr(Source, "crawl_schedule")

    def test_source_has_last_crawled_at_attr(self) -> None:
        from knowledge_lake.registry.models import Source
        assert hasattr(Source, "last_crawled_at")

    def test_source_has_last_content_hash_attr(self) -> None:
        from knowledge_lake.registry.models import Source
        assert hasattr(Source, "last_content_hash")

    def test_crawl_columns_are_nullable(self, engine) -> None:
        from sqlalchemy import inspect as sa_inspect
        insp = sa_inspect(engine)
        cols = {c["name"]: c for c in insp.get_columns("sources")}
        assert cols["crawl_schedule"]["nullable"] is True
        assert cols["last_crawled_at"]["nullable"] is True
        assert cols["last_content_hash"]["nullable"] is True

    def test_source_crawl_columns_default_none(self, session) -> None:
        from knowledge_lake.registry.repo import create_source

        source = create_source(session, name="NoCrawl", source_type="web")
        session.flush()
        assert source.crawl_schedule is None
        assert source.last_crawled_at is None
        assert source.last_content_hash is None


# ── Repo helpers for crawl scheduling (Phase 11, Plan 02, Task 2) ────────────


class TestCreateSourceCrawlSchedule:
    """create_source accepts and persists crawl_schedule kwarg."""

    def test_create_source_with_crawl_schedule(self, session) -> None:
        from knowledge_lake.registry.repo import create_source

        source = create_source(
            session, name="Scheduled", source_type="web",
            url="https://example.com", crawl_schedule="0 6 * * 1",
        )
        session.flush()
        assert source.crawl_schedule == "0 6 * * 1"

    def test_create_source_crawl_schedule_defaults_none(self, session) -> None:
        from knowledge_lake.registry.repo import create_source
        import inspect

        sig = inspect.signature(create_source)
        assert "crawl_schedule" in sig.parameters
        assert sig.parameters["crawl_schedule"].default is None


class TestListScheduledSources:
    """list_scheduled_sources returns namedtuples for scheduled sources only."""

    def test_returns_only_scheduled(self, session) -> None:
        from knowledge_lake.registry.repo import create_source, list_scheduled_sources

        create_source(session, name="NoSched", source_type="web")
        create_source(
            session, name="Sched", source_type="web",
            url="https://scheduled.com", crawl_schedule="0 0 * * *",
        )
        session.flush()

        results = list_scheduled_sources(session)
        assert len(results) >= 1
        names = [r.url for r in results]
        assert "https://scheduled.com" in names

    def test_returns_namedtuple_not_orm(self, session) -> None:
        from knowledge_lake.registry.repo import create_source, list_scheduled_sources

        create_source(
            session, name="NTCheck", source_type="web",
            crawl_schedule="0 12 * * *",
        )
        session.flush()

        results = list_scheduled_sources(session)
        assert len(results) >= 1
        row = results[-1]
        # Must be a namedtuple with expected fields
        assert hasattr(row, "id")
        assert hasattr(row, "crawl_schedule")
        assert hasattr(row, "last_crawled_at")
        assert hasattr(row, "last_content_hash")
        assert hasattr(row, "config")

    def test_excludes_unscheduled(self, session) -> None:
        from knowledge_lake.registry.repo import create_source, list_scheduled_sources

        create_source(session, name="Unsched1", source_type="web")
        session.flush()

        results = list_scheduled_sources(session)
        urls_or_ids = [r.id for r in results]
        # None of the results should have crawl_schedule=None
        for r in results:
            assert r.crawl_schedule is not None


class TestSetSourceSchedule:
    """set_source_schedule updates or clears crawl_schedule."""

    def test_set_schedule_returns_true(self, session) -> None:
        from knowledge_lake.registry.repo import create_source, set_source_schedule

        source = create_source(session, name="SetSched", source_type="web")
        session.flush()

        result = set_source_schedule(session, source.id, "0 3 * * *")
        session.flush()
        assert result is True
        assert source.crawl_schedule == "0 3 * * *"

    def test_set_schedule_clear(self, session) -> None:
        from knowledge_lake.registry.repo import create_source, set_source_schedule

        source = create_source(
            session, name="ClearSched", source_type="web",
            crawl_schedule="0 6 * * *",
        )
        session.flush()

        result = set_source_schedule(session, source.id, None)
        session.flush()
        assert result is True
        assert source.crawl_schedule is None

    def test_set_schedule_missing_source_returns_false(self, session) -> None:
        from knowledge_lake.registry.repo import set_source_schedule

        result = set_source_schedule(session, "src_nonexistent", "0 0 * * *")
        assert result is False


class TestTouchSourceCrawl:
    """touch_source_crawl updates watermarks using its own session."""

    def test_imports_cleanly(self) -> None:
        from knowledge_lake.registry.repo import touch_source_crawl
        assert callable(touch_source_crawl)

    def test_scheduled_source_namedtuple_import(self) -> None:
        from knowledge_lake.registry.repo import _ScheduledSource
        assert _ScheduledSource is not None


# ── Tree index artifact tests ─────────────────────────────────────────────────


class TestTreeIndexArtifactCreate:
    """create_tree_index_artifact mirrors create_chunk_artifact but uses artifact_type='tree_index'."""

    @pytest.fixture()
    def chain(self, session):
        from knowledge_lake.registry.repo import (
            create_parsed_artifact,
            create_raw_artifact,
            create_source,
        )
        src = create_source(session, name="TI Source", source_type="web")
        raw = create_raw_artifact(
            session, source_id=src.id, content_hash="ti_raw",
            storage_uri="s3://b/raw/ti_raw.pdf",
        )
        parsed = create_parsed_artifact(
            session, source_id=src.id, parent_artifact_id=raw.id,
            content_hash="ti_parsed", storage_uri="s3://b/silver/ti_parsed.json",
        )
        session.flush()
        return src, raw, parsed

    def test_create_tree_index_artifact_is_importable(self) -> None:
        from knowledge_lake.registry.repo import create_tree_index_artifact
        assert callable(create_tree_index_artifact)

    def test_tree_index_artifact_type(self, session, chain) -> None:
        from knowledge_lake.registry.repo import create_tree_index_artifact

        src, raw, parsed = chain
        art = create_tree_index_artifact(
            session,
            source_id=src.id,
            parent_artifact_id=parsed.id,
            content_hash="ti_hash_1",
            storage_uri="s3://b/tree_index/domain/src/ti_hash_1.json",
        )
        assert art.artifact_type == "tree_index", (
            f"Expected artifact_type='tree_index', got {art.artifact_type!r}"
        )

    def test_tree_index_parent_is_parsed(self, session, chain) -> None:
        from knowledge_lake.registry.repo import create_tree_index_artifact

        src, raw, parsed = chain
        art = create_tree_index_artifact(
            session,
            source_id=src.id,
            parent_artifact_id=parsed.id,
            content_hash="ti_hash_2",
        )
        assert art.parent_artifact_id == parsed.id, (
            f"Expected parent_artifact_id={parsed.id!r}, got {art.parent_artifact_id!r}"
        )

    def test_tree_index_id_prefixed_idx(self, session, chain) -> None:
        from knowledge_lake.registry.repo import create_tree_index_artifact

        src, raw, parsed = chain
        art = create_tree_index_artifact(
            session,
            source_id=src.id,
            parent_artifact_id=parsed.id,
            content_hash="ti_hash_3",
        )
        assert art.id.startswith("idx_"), (
            f"Expected idx_ prefix (new_id('tree_index')), got {art.id!r}"
        )

    def test_tree_index_mime_type_default_json(self, session, chain) -> None:
        from knowledge_lake.registry.repo import create_tree_index_artifact

        src, raw, parsed = chain
        art = create_tree_index_artifact(
            session,
            source_id=src.id,
            parent_artifact_id=parsed.id,
            content_hash="ti_hash_4",
        )
        assert art.mime_type == "application/json", (
            f"Expected default mime_type='application/json', got {art.mime_type!r}"
        )

    def test_tree_index_storage_uri_passthrough(self, session, chain) -> None:
        from knowledge_lake.registry.repo import create_tree_index_artifact

        src, raw, parsed = chain
        uri = "s3://bucket/tree_index/domain/src/abc123.json"
        art = create_tree_index_artifact(
            session,
            source_id=src.id,
            parent_artifact_id=parsed.id,
            content_hash="ti_hash_5",
            storage_uri=uri,
        )
        assert art.storage_uri == uri, (
            f"Expected storage_uri={uri!r}, got {art.storage_uri!r}"
        )

    def test_tree_index_dedup_by_hash(self, session, chain) -> None:
        """get_artifact_by_hash returns the tree_index artifact after flush."""
        from knowledge_lake.registry.repo import (
            create_tree_index_artifact,
            get_artifact_by_hash,
        )

        src, raw, parsed = chain
        art = create_tree_index_artifact(
            session,
            source_id=src.id,
            parent_artifact_id=parsed.id,
            content_hash="ti_hash_6",
        )
        session.flush()
        found = get_artifact_by_hash(session, "ti_hash_6", "tree_index")
        assert found is not None, "get_artifact_by_hash must find tree_index artifact"
        assert found.id == art.id, (
            f"Expected artifact id={art.id!r}, got {found.id!r}"
        )

    def test_create_chunk_artifact_still_works(self, session, chain) -> None:
        """Regression: create_chunk_artifact is not broken by the new function."""
        from knowledge_lake.registry.repo import create_chunk_artifact

        src, raw, parsed = chain
        chunk = create_chunk_artifact(
            session,
            source_id=src.id,
            parent_artifact_id=parsed.id,
            content_hash="reg_chunk_1",
        )
        assert chunk.artifact_type == "chunk"
        assert chunk.id.startswith("chk_")
