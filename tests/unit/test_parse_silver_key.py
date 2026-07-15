"""RED-state tests for domain-scoped silver key construction in pipeline/parse.py (STORE-01).

Tests are xfail(strict=False) until Plan 09-04 moves silver_key inside the session block
and adds domain resolution via get_domain_for_source().

Currently parse.py builds the silver key at line 100 as:
    silver_key = f"{_SILVER_PREFIX}/{source_id}/{content_hash}.md"

After Plan 09-04 it will be:
    domain = registry_repo.get_domain_for_source(session, source_id) or "_unclassified"
    silver_key = f"{_SILVER_PREFIX}/{domain}/{source_id}/{content_hash}.md"
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
        name="test-source-parse",
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
        name="test-source-parse-nodomain",
        source_type="upload",
        config={},
    )
    session.flush()
    return src


def _seed_raw_artifact(session, source_id: str) -> Any:
    """Create a raw_document artifact with a fake storage_uri."""
    from knowledge_lake.registry import repo as registry_repo

    art = registry_repo.create_raw_artifact(
        session,
        source_id=source_id,
        content_hash="rawcontent1234567890abcdef",
        storage_uri="s3://test-bucket/raw/test-source/rawcontent1234567890abcdef.pdf",
        mime_type="application/pdf",
    )
    session.flush()
    session.commit()
    return art


# ── Helper: build a fake ParsedDoc return value ───────────────────────────────


def _fake_parsed_doc():
    from knowledge_lake.plugins.protocols import ParsedDoc

    doc = ParsedDoc(text="Fake parsed text content for test.")
    return doc, "docling", 0.8


# ── Test class ────────────────────────────────────────────────────────────────


class TestParseSilverKeyDomain:
    """RED-state: domain segment must appear in silver key after Plan 09-04."""

    def test_domain_segment_in_silver_key(self, session, source_with_domain, engine):
        """parse() must write parsed document to silver/healthcare/{source_id}/{hash}.md.

        Currently writes to silver/{source_id}/{hash}.md — will xfail until Plan 09-04
        moves key construction inside the session block and adds domain resolution.
        """
        import knowledge_lake.pipeline.parse as parse_module

        raw_art = _seed_raw_artifact(session, source_with_domain.id)
        settings = _make_settings(engine)

        captured_keys: list[str] = []

        # Mock StorageBackend to intercept put_object and get_object calls
        mock_storage_instance = MagicMock()
        mock_storage_instance.get_object.return_value = b"%PDF-1.4 fake content"
        mock_storage_instance.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"

        def capture_put_object(key, data, **kwargs):
            captured_keys.append(key)

        mock_storage_instance.put_object.side_effect = capture_put_object

        with patch.object(parse_module, "StorageBackend", return_value=mock_storage_instance), \
             patch.object(parse_module, "parse_with_fallback", return_value=_fake_parsed_doc()):
            parse_module.parse(
                raw_artifact_id=raw_art.id,
                source_id=source_with_domain.id,
                mime_type="application/pdf",
                settings=settings,
            )

        # Task 8: parse() now writes TWO objects per call — the markdown and its
        # sections sidecar — both under the same domain-scoped silver key prefix.
        assert len(captured_keys) == 2, f"Expected 2 put_object calls, got {len(captured_keys)}"
        md_keys = [k for k in captured_keys if k.endswith(".md")]
        sidecar_keys = [k for k in captured_keys if k.endswith(".sections.json")]
        assert len(md_keys) == 1 and len(sidecar_keys) == 1
        # After Plan 09-04: key should be silver/healthcare/{source_id}/{hash}.md
        assert "silver/healthcare/" in md_keys[0], (
            f"Expected 'silver/healthcare/' in silver key, got: {md_keys[0]!r}"
        )
        assert "silver/healthcare/" in sidecar_keys[0], (
            f"Expected 'silver/healthcare/' in sections sidecar key, got: {sidecar_keys[0]!r}"
        )

    def test_none_domain_uses_unclassified_segment(self, session, source_no_domain, engine):
        """parse() with a domain-less source must use silver/_unclassified/{source_id}/{hash}.md.

        Currently writes to silver/{source_id}/{hash}.md (no domain segment at all).
        After Plan 09-04: _unclassified fallback segment must appear in the key.
        """
        import knowledge_lake.pipeline.parse as parse_module

        raw_art = _seed_raw_artifact(session, source_no_domain.id)
        settings = _make_settings(engine)

        captured_keys: list[str] = []

        mock_storage_instance = MagicMock()
        mock_storage_instance.get_object.return_value = b"%PDF-1.4 fake content"
        mock_storage_instance.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"

        def capture_put_object(key, data, **kwargs):
            captured_keys.append(key)

        mock_storage_instance.put_object.side_effect = capture_put_object

        with patch.object(parse_module, "StorageBackend", return_value=mock_storage_instance), \
             patch.object(parse_module, "parse_with_fallback", return_value=_fake_parsed_doc()):
            parse_module.parse(
                raw_artifact_id=raw_art.id,
                source_id=source_no_domain.id,
                mime_type="application/pdf",
                settings=settings,
            )

        # Task 8: parse() now writes TWO objects per call — the markdown and its
        # sections sidecar — both under the same domain-scoped silver key prefix.
        assert len(captured_keys) == 2, f"Expected 2 put_object calls, got {len(captured_keys)}"
        md_keys = [k for k in captured_keys if k.endswith(".md")]
        sidecar_keys = [k for k in captured_keys if k.endswith(".sections.json")]
        assert len(md_keys) == 1 and len(sidecar_keys) == 1
        # After Plan 09-04: key should contain _unclassified segment
        assert "silver/_unclassified/" in md_keys[0], (
            f"Expected 'silver/_unclassified/' in silver key, got: {md_keys[0]!r}"
        )
        assert "silver/_unclassified/" in sidecar_keys[0], (
            f"Expected 'silver/_unclassified/' in sections sidecar key, got: {sidecar_keys[0]!r}"
        )
