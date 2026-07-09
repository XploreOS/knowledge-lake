"""RED-state tests for domain-scoped silver key construction in pipeline/clean.py (STORE-01).

Tests are xfail(strict=False) until Plan 09-04 moves cleaned_key inside the session block
and adds domain resolution via get_domain_for_source().

Currently clean.py builds the cleaned key at line 300 as:
    cleaned_key = f"{_SILVER_PREFIX}/{source_id}/cleaned/{content_hash}.md"

After Plan 09-04 it will be:
    domain = registry_repo.get_domain_for_source(session, source_id) or "_unclassified"
    cleaned_key = f"{_SILVER_PREFIX}/{domain}/{source_id}/cleaned/{content_hash}.md"
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.registry.db as registry_db


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine, shared connection via StaticPool."""
    from knowledge_lake.registry.models import Base

    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def _patch_engine(monkeypatch, engine):
    """Route registry.db.get_session() to the in-memory test engine."""
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess


def _make_settings(engine):
    """Build a Settings instance pointing at the test DB."""
    from knowledge_lake.config.settings import Settings, StorageSettings

    ss = StorageSettings(
        endpoint_url="http://localhost:9000",
        bucket="test-bucket",
        access_key_id="test",
        secret_access_key="test",
    )
    return Settings(
        database_url=str(engine.url),
        storage=ss,
        _env_file=None,  # type: ignore[call-arg]
    )


@pytest.fixture()
def source_with_domain(session):
    """Seed a Source row with config={"domain": "healthcare"}."""
    from knowledge_lake.registry import repo as registry_repo

    src = registry_repo.create_source(
        session,
        name="test-source-clean",
        source_type="upload",
        config={"domain": "healthcare"},
    )
    session.flush()
    return src


@pytest.fixture()
def source_no_domain(session):
    """Seed a Source row with no domain in config (config={})."""
    from knowledge_lake.registry import repo as registry_repo

    src = registry_repo.create_source(
        session,
        name="test-source-clean-nodomain",
        source_type="upload",
        config={},
    )
    session.flush()
    return src


def _seed_parsed_artifact(session, source_id: str) -> Any:
    """Create a parsed_document artifact with a fake storage_uri."""
    from knowledge_lake.registry import repo as registry_repo

    raw_art = registry_repo.create_raw_artifact(
        session,
        source_id=source_id,
        content_hash="rawclean123456789abcdef",
        storage_uri="s3://test-bucket/raw/test-source/rawclean123456789abcdef.pdf",
        mime_type="application/pdf",
    )
    session.flush()

    parsed_art = registry_repo.create_parsed_artifact(
        session,
        source_id=source_id,
        parent_artifact_id=raw_art.id,
        content_hash="parsedclean123456789abcdef",
        storage_uri="s3://test-bucket/silver/test-source/parsedclean123456789abcdef.md",
        mime_type="text/markdown",
    )
    session.flush()
    session.commit()
    return parsed_art


# ── Test class ────────────────────────────────────────────────────────────────


class TestCleanSilverKeyDomain:
    """RED-state: domain segment must appear in cleaned silver key after Plan 09-04."""

    @pytest.mark.xfail(
        strict=False,
        reason="STORE-01: cleaned key domain segment pending Plan 09-04",
    )
    def test_domain_segment_in_cleaned_key(self, session, source_with_domain, engine):
        """clean() must write cleaned document to silver/healthcare/{source_id}/cleaned/{hash}.md.

        Currently writes to silver/{source_id}/cleaned/{hash}.md — will xfail until Plan 09-04
        moves key construction inside the session block and adds domain resolution.
        """
        import knowledge_lake.pipeline.clean as clean_module

        parsed_art = _seed_parsed_artifact(session, source_with_domain.id)
        settings = _make_settings(engine)

        captured_keys: list[str] = []

        # Mock StorageBackend to intercept put_object and get_object calls
        mock_storage_instance = MagicMock()
        # Return fake markdown text for get_object (used to retrieve parsed content)
        mock_storage_instance.get_object.return_value = b"Parsed markdown text content for testing."
        mock_storage_instance.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"

        def capture_put_object(key, data, **kwargs):
            captured_keys.append(key)

        mock_storage_instance.put_object.side_effect = capture_put_object

        with patch.object(clean_module, "StorageBackend", return_value=mock_storage_instance):
            clean_module.clean(
                parsed_artifact_id=parsed_art.id,
                source_id=source_with_domain.id,
                settings=settings,
            )

        assert len(captured_keys) == 1, f"Expected 1 put_object call, got {len(captured_keys)}"
        cleaned_key = captured_keys[0]
        # After Plan 09-04: key should be silver/healthcare/{source_id}/cleaned/{hash}.md
        assert "silver/healthcare/" in cleaned_key, (
            f"Expected 'silver/healthcare/' in cleaned key, got: {cleaned_key!r}"
        )
        assert "/cleaned/" in cleaned_key, (
            f"Expected '/cleaned/' sub-path in cleaned key, got: {cleaned_key!r}"
        )

    @pytest.mark.xfail(
        strict=False,
        reason="STORE-01: cleaned key domain segment pending Plan 09-04",
    )
    def test_none_domain_uses_unclassified_segment(self, session, source_no_domain, engine):
        """clean() with a domain-less source must use silver/_unclassified/{source_id}/cleaned/{hash}.md.

        Currently writes to silver/{source_id}/cleaned/{hash}.md (no domain segment at all).
        After Plan 09-04: _unclassified fallback segment must appear in the key.
        """
        import knowledge_lake.pipeline.clean as clean_module

        parsed_art = _seed_parsed_artifact(session, source_no_domain.id)
        settings = _make_settings(engine)

        captured_keys: list[str] = []

        mock_storage_instance = MagicMock()
        mock_storage_instance.get_object.return_value = b"Parsed markdown text content for testing."
        mock_storage_instance.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"

        def capture_put_object(key, data, **kwargs):
            captured_keys.append(key)

        mock_storage_instance.put_object.side_effect = capture_put_object

        with patch.object(clean_module, "StorageBackend", return_value=mock_storage_instance):
            clean_module.clean(
                parsed_artifact_id=parsed_art.id,
                source_id=source_no_domain.id,
                settings=settings,
            )

        assert len(captured_keys) == 1, f"Expected 1 put_object call, got {len(captured_keys)}"
        cleaned_key = captured_keys[0]
        # After Plan 09-04: key should contain _unclassified segment
        assert "silver/_unclassified/" in cleaned_key, (
            f"Expected 'silver/_unclassified/' in cleaned key, got: {cleaned_key!r}"
        )
        assert "/cleaned/" in cleaned_key, (
            f"Expected '/cleaned/' sub-path in cleaned key, got: {cleaned_key!r}"
        )
