"""
Integration tests for Alembic migration #1 (FOUND-09).

These tests connect to a real PostgreSQL database (the compose klake_test DB)
to verify that:
  1. ``alembic upgrade head`` creates the full core schema on an empty database
  2. All expected tables and indexes exist after upgrade
  3. ``alembic downgrade base`` then ``alembic upgrade head`` round-trips clean

The test database URL defaults to the test DSN; override with the
``KLAKE_TEST_DATABASE_URL`` environment variable.

NOTE: These tests require a running PostgreSQL instance.  Run with:
    uv run pytest tests/integration/test_migrations.py -x -q
"""

from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


# ── Helpers ───────────────────────────────────────────────────────────────────

DEFAULT_TEST_DB_URL = "postgresql+psycopg://klake:klake@localhost:5432/klake_test"


def _test_db_url() -> str:
    """Return the migration test database URL.

    Reads KLAKE_TEST_DATABASE_URL env var or falls back to the default test DSN.
    """
    return os.environ.get("KLAKE_TEST_DATABASE_URL", DEFAULT_TEST_DB_URL)


def _alembic_cfg(db_url: str) -> Config:
    """Build an Alembic Config object pointing at our alembic.ini."""
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _clean_schema(engine) -> None:
    """Drop all public-schema tables so the migration starts from an empty DB."""
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                DO $$
                DECLARE
                    r RECORD;
                BEGIN
                    FOR r IN (SELECT tablename FROM pg_tables
                              WHERE schemaname = 'public') LOOP
                        EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename)
                                || ' CASCADE';
                    END LOOP;
                END $$;
                """
            )
        )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def test_db_url() -> str:
    return _test_db_url()


@pytest.fixture(scope="module")
def engine(test_db_url: str):
    """Synchronous engine connected to the migration test database."""
    eng = create_engine(test_db_url, echo=False)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module", autouse=True)
def clean_and_migrate(test_db_url: str, engine):
    """Module-scoped fixture: wipe the schema and run upgrade head once."""
    _clean_schema(engine)
    cfg = _alembic_cfg(test_db_url)
    command.upgrade(cfg, "head")
    yield
    # No teardown — the schema persists for all tests in this module.


# ── Table existence tests ─────────────────────────────────────────────────────


class TestTablesExist:
    """All core tables must exist after upgrade head."""

    EXPECTED_TABLES = [
        "sources",
        "artifacts",
        "lineage_events",
        "jobs",
        "datasets",
        "llm_spend",
        "vector_collections",
    ]

    def test_all_core_tables_exist(self, engine) -> None:
        insp = inspect(engine)
        actual_tables = insp.get_table_names(schema="public")
        for table in self.EXPECTED_TABLES:
            assert table in actual_tables, (
                f"Table '{table}' missing after alembic upgrade head. "
                f"Found: {actual_tables}"
            )

    def test_alembic_version_table_exists(self, engine) -> None:
        """Alembic's own version table must be present."""
        insp = inspect(engine)
        assert "alembic_version" in insp.get_table_names(schema="public")


# ── Sources table tests ───────────────────────────────────────────────────────


class TestSourcesSchema:
    """Sources table has the required columns."""

    REQUIRED_COLUMNS = [
        "id", "name", "source_type", "url", "license_type",
        "license_url", "robots_checked", "config", "created_at",
        # Phase 11 (crawl-scheduling) columns — Alembic 0009
        "crawl_schedule", "last_crawled_at", "last_content_hash",
    ]

    def test_sources_columns(self, engine) -> None:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("sources")}
        for col in self.REQUIRED_COLUMNS:
            assert col in cols, f"sources.{col} missing"


# ── Artifacts table tests ─────────────────────────────────────────────────────


class TestArtifactsSchema:
    """Artifacts table has the required columns, indexes, and unique constraint."""

    REQUIRED_COLUMNS = [
        "id", "source_id", "parent_artifact_id", "artifact_type",
        "content_hash", "pipeline_version", "storage_uri",
        "mime_type", "page_ref", "section_path", "metadata", "created_at",
    ]

    def test_artifacts_columns(self, engine) -> None:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("artifacts")}
        for col in self.REQUIRED_COLUMNS:
            assert col in cols, f"artifacts.{col} missing"

    def test_artifacts_content_hash_index(self, engine) -> None:
        insp = inspect(engine)
        indexes = {idx["name"] for idx in insp.get_indexes("artifacts")}
        assert "ix_artifacts_content_hash" in indexes, (
            f"ix_artifacts_content_hash index missing. Indexes: {indexes}"
        )

    def test_artifacts_source_id_index(self, engine) -> None:
        insp = inspect(engine)
        indexes = {idx["name"] for idx in insp.get_indexes("artifacts")}
        assert "ix_artifacts_source_id" in indexes

    def test_artifacts_parent_artifact_id_index(self, engine) -> None:
        insp = inspect(engine)
        indexes = {idx["name"] for idx in insp.get_indexes("artifacts")}
        assert "ix_artifacts_parent_artifact_id" in indexes

    def test_artifacts_created_at_index(self, engine) -> None:
        insp = inspect(engine)
        indexes = {idx["name"] for idx in insp.get_indexes("artifacts")}
        assert "ix_artifacts_created_at" in indexes

    def test_artifacts_unique_constraint_exists(self, engine) -> None:
        insp = inspect(engine)
        # Unique constraints appear both in unique_constraints and indexes
        unique_names = {
            uc["name"] for uc in insp.get_unique_constraints("artifacts")
        }
        assert "uq_artifacts_hash_type" in unique_names, (
            f"uq_artifacts_hash_type constraint missing. Unique constraints: {unique_names}"
        )


# ── Lineage events table tests ────────────────────────────────────────────────


class TestLineageEventsSchema:
    """Lineage events table has the required columns."""

    REQUIRED_COLUMNS = [
        "id", "artifact_id", "parent_artifact_id", "relationship",
        "pipeline_version", "created_at",
    ]

    def test_lineage_events_columns(self, engine) -> None:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("lineage_events")}
        for col in self.REQUIRED_COLUMNS:
            assert col in cols, f"lineage_events.{col} missing"


# ── LLM spend / vector collections table tests (ENRICH-05, INDEX-02) ─────────


class TestLlmSpendAndVectorCollectionsSchema:
    """llm_spend and vector_collections tables have the required columns."""

    def test_llm_spend_columns(self, engine) -> None:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("llm_spend")}
        for col in ("id", "scope", "total_cost_usd", "updated_at"):
            assert col in cols, f"llm_spend.{col} missing"

    def test_vector_collections_columns(self, engine) -> None:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("vector_collections")}
        for col in (
            "id", "alias_name", "physical_collection", "dim",
            "is_current", "created_at",
        ):
            assert col in cols, f"vector_collections.{col} missing"


# ── Round-trip tests ──────────────────────────────────────────────────────────


class TestMigrationRoundTrip:
    """downgrade base then upgrade head must succeed cleanly."""

    def test_downgrade_then_upgrade_roundtrip(self, test_db_url: str, engine) -> None:
        """alembic downgrade base → upgrade head round-trips without error."""
        cfg = _alembic_cfg(test_db_url)

        # Downgrade to base (empty schema)
        command.downgrade(cfg, "base")

        # Verify all tables are gone (except alembic_version, which may linger)
        insp = inspect(engine)
        remaining = {
            t for t in insp.get_table_names(schema="public")
            if t != "alembic_version"
        }
        assert remaining == set(), f"Tables remain after downgrade base: {remaining}"

        # Upgrade back to head
        command.upgrade(cfg, "head")

        # Verify tables are back
        insp = inspect(engine)
        tables = insp.get_table_names(schema="public")
        for expected in (
            "sources", "artifacts", "lineage_events", "jobs", "datasets",
            "llm_spend", "vector_collections",
        ):
            assert expected in tables, f"{expected} missing after re-upgrade"


# ── Migration head chain assertion (Phase 11) ────────────────────────────────

try:
    from knowledge_lake.registry.alembic.versions import (
        _0009_crawl_scheduling as _mig_0009,  # type: ignore[attr-defined]
    )
    _HAS_0009 = True
except Exception:
    _HAS_0009 = False


@pytest.mark.skipif(not _HAS_0009, reason="0009 migration not yet created (Plan 11-02)")
class TestMigrationHeadChain:
    """Migration 0009 must chain correctly from 0008."""

    def test_0009_revision_is_0009(self) -> None:
        """Migration module declares revision == '0009'."""
        assert _mig_0009.revision == "0009", (
            f"Expected revision='0009', got {_mig_0009.revision!r}"
        )

    def test_0009_down_revision_is_0008(self) -> None:
        """Migration 0009 must declare down_revision == '0008'."""
        assert _mig_0009.down_revision == "0008", (
            f"Expected down_revision='0008', got {_mig_0009.down_revision!r}"
        )
