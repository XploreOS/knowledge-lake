"""Tests for clean stage — boilerplate removal, language detection (CLEAN-01, CLEAN-02)."""

from __future__ import annotations

import copy
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from knowledge_lake.pipeline.clean import (
    remove_boilerplate,
    _normalize_whitespace,
    detect_language,
)


def test_boilerplate_removal_page_header() -> None:
    """Page header 'Page N of M' on its own line must be removed."""
    text = "Introduction\n\nPage 3 of 10\n\nAdministrative safeguards are required."
    result = remove_boilerplate(text)
    assert "Page 3 of 10" not in result


def test_boilerplate_removal_preserves_body() -> None:
    """Body text after a boilerplate line must survive intact."""
    text = "Page 1 of 5\n\nAdministrative safeguards are the policies and procedures..."
    result = remove_boilerplate(text)
    assert "Administrative safeguards are the policies and procedures" in result


def test_boilerplate_preserves_citations() -> None:
    """Inline citations like '(Smith, 2023)' must not be removed."""
    text = "Per (Smith, 2023) the standard requires annual training."
    result = remove_boilerplate(text)
    assert "(Smith, 2023)" in result


def test_boilerplate_preserves_section_refs() -> None:
    """Section references like '§3.2' must not be removed."""
    text = "See §3.2 Administrative Safeguards for details."
    result = remove_boilerplate(text)
    assert "§3.2" in result


def test_whitespace_normalization_collapses_blank_lines() -> None:
    """Four or more consecutive blank lines must collapse to at most two."""
    text = "First paragraph.\n\n\n\n\nSecond paragraph."
    result = _normalize_whitespace(text)
    # Should not contain 3+ consecutive newlines
    assert "\n\n\n" not in result
    # Body text should be preserved
    assert "First paragraph." in result
    assert "Second paragraph." in result


def test_whitespace_strips_trailing_spaces() -> None:
    """Lines with trailing spaces must have them stripped."""
    text = "Line one   \nLine two  \nLine three   "
    result = _normalize_whitespace(text)
    for line in result.splitlines():
        assert line == line.rstrip(), f"Line has trailing whitespace: {line!r}"


def test_language_detection_english() -> None:
    """English healthcare text must be detected as 'en'."""
    text = "The patient requires immediate treatment for acute conditions and hypertension."
    result = detect_language(text)
    assert result == "en"


def test_language_detection_short_text_no_crash() -> None:
    """Short text must not raise — may return 'unknown' but must be a string."""
    result = detect_language("ok")
    assert isinstance(result, str)


def test_language_detection_empty_string() -> None:
    """Empty string must return 'unknown' gracefully."""
    result = detect_language("")
    assert result == "unknown"


# ── Fixtures for clean()'s parsed_doc threading + WR-05 hash tests ─────────────
#
# Mirrors tests/unit/test_clean_silver_key.py's in-memory-SQLite + mocked-storage
# pattern (Pitfall 2 in 17-RESEARCH.md): StorageBackend is mocked so get_object()
# calls never touch real S3, and registry.db.get_engine() is monkeypatched to a
# fresh in-memory SQLite engine per test.


@pytest.fixture()
def clean_engine():
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


def _make_clean_settings(engine):
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


def _seed_clean_source(session, name: str):
    from knowledge_lake.registry import repo as registry_repo

    src = registry_repo.create_source(
        session,
        name=name,
        source_type="upload",
        config={},
    )
    session.flush()
    return src


def _seed_clean_parsed_artifact(session, source_id: str, content_hash: str):
    from knowledge_lake.registry import repo as registry_repo

    raw_art = registry_repo.create_raw_artifact(
        session,
        source_id=source_id,
        content_hash=f"raw-{content_hash}",
        storage_uri=f"s3://test-bucket/raw/{content_hash}.html",
        mime_type="text/html",
    )
    session.flush()

    parsed_art = registry_repo.create_parsed_artifact(
        session,
        source_id=source_id,
        parent_artifact_id=raw_art.id,
        content_hash=f"parsed-{content_hash}",
        storage_uri=f"s3://test-bucket/silver/{content_hash}.md",
        mime_type="text/markdown",
    )
    session.flush()
    session.commit()
    return parsed_art


def _mock_clean_storage() -> MagicMock:
    mock_storage_instance = MagicMock()
    mock_storage_instance.get_object.return_value = b"Fallback parsed text for legacy path."
    mock_storage_instance.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"
    mock_storage_instance.put_object.side_effect = lambda *a, **kw: None
    return mock_storage_instance


class TestCleanParsedDocThreading:
    """Tests for clean()'s optional in-memory parsed_doc parameter (CLEAN-01/02/03)."""

    def test_distinct_content_hash_across_parents(self, clean_engine, monkeypatch) -> None:
        """Two clean() calls with identical cleaned_text but different
        parsed_artifact_id values must produce two distinct content_hash values
        (WR-05 parent-scoped hash, CLEAN-03)."""
        import knowledge_lake.registry.db as registry_db
        import knowledge_lake.pipeline.clean as clean_module
        from knowledge_lake.plugins.protocols import ParsedDoc, Section

        monkeypatch.setattr(registry_db, "get_engine", lambda: clean_engine)

        with Session(clean_engine) as session:
            source_a = _seed_clean_source(session, "source-a")
            source_b = _seed_clean_source(session, "source-b")
            parsed_a = _seed_clean_parsed_artifact(session, source_a.id, "hasha")
            parsed_b = _seed_clean_parsed_artifact(session, source_b.id, "hashb")
            source_a_id, source_b_id = source_a.id, source_b.id
            parsed_a_id, parsed_b_id = parsed_a.id, parsed_b.id

        settings = _make_clean_settings(clean_engine)
        doc = ParsedDoc(
            text="Shared identical body text.",
            sections=[Section(heading="H", section_path="§1", page=1, text="Body text.")],
        )

        with patch.object(clean_module, "StorageBackend", return_value=_mock_clean_storage()):
            result_a = clean_module.clean(
                parsed_a_id, source_a_id, parsed_doc=doc, settings=settings
            )
            result_b = clean_module.clean(
                parsed_b_id, source_b_id, parsed_doc=doc, settings=settings
            )

        assert result_a["content_hash"] != result_b["content_hash"]

    def test_cleaned_doc_preserves_section_count(self, clean_engine, monkeypatch) -> None:
        """cleaned_doc must retain every section (list length preserved), even
        sections whose text becomes empty after boilerplate stripping — CLEAN-04
        section removal is Phase 19's job, not this plan's."""
        import knowledge_lake.registry.db as registry_db
        import knowledge_lake.pipeline.clean as clean_module
        from knowledge_lake.plugins.protocols import ParsedDoc, Section

        monkeypatch.setattr(registry_db, "get_engine", lambda: clean_engine)

        with Session(clean_engine) as session:
            source = _seed_clean_source(session, "source-sections")
            parsed = _seed_clean_parsed_artifact(session, source.id, "hashsections")
            source_id, parsed_id = source.id, parsed.id

        settings = _make_clean_settings(clean_engine)
        doc = ParsedDoc(
            text="Full doc text.",
            sections=[
                Section(heading="Real", section_path="§1", page=1, text="Real content here."),
                Section(heading="Boilerplate", section_path="§2", page=1, text="Page 1 of 5"),
            ],
        )

        with patch.object(clean_module, "StorageBackend", return_value=_mock_clean_storage()):
            result = clean_module.clean(parsed_id, source_id, parsed_doc=doc, settings=settings)

        assert result["cleaned_doc"] is not None
        assert len(result["cleaned_doc"].sections) == len(doc.sections)

    def test_no_in_place_mutation_of_caller_sections(self, clean_engine, monkeypatch) -> None:
        """clean() must never mutate the caller's original Section objects in
        place — it must build new instances via dataclasses.replace()."""
        import knowledge_lake.registry.db as registry_db
        import knowledge_lake.pipeline.clean as clean_module
        from knowledge_lake.plugins.protocols import ParsedDoc, Section

        monkeypatch.setattr(registry_db, "get_engine", lambda: clean_engine)

        with Session(clean_engine) as session:
            source = _seed_clean_source(session, "source-mutation")
            parsed = _seed_clean_parsed_artifact(session, source.id, "hashmutation")
            source_id, parsed_id = source.id, parsed.id

        settings = _make_clean_settings(clean_engine)
        original_sections = [
            Section(heading="Boilerplate", section_path="§1", page=1, text="Page 1 of 5"),
        ]
        doc = ParsedDoc(text="Page 1 of 5", sections=original_sections)
        pre_call_copy = copy.deepcopy(original_sections)

        with patch.object(clean_module, "StorageBackend", return_value=_mock_clean_storage()):
            clean_module.clean(parsed_id, source_id, parsed_doc=doc, settings=settings)

        assert doc.sections == pre_call_copy

    def test_legacy_path_no_parsed_doc_returns_none_cleaned_doc(
        self, clean_engine, monkeypatch
    ) -> None:
        """clean() called without parsed_doc (existing call signature) must keep
        the existing single storage.get_object() call and return
        cleaned_doc: None in the result."""
        import knowledge_lake.registry.db as registry_db
        import knowledge_lake.pipeline.clean as clean_module

        monkeypatch.setattr(registry_db, "get_engine", lambda: clean_engine)

        with Session(clean_engine) as session:
            source = _seed_clean_source(session, "source-legacy")
            parsed = _seed_clean_parsed_artifact(session, source.id, "hashlegacy")
            source_id, parsed_id = source.id, parsed.id

        settings = _make_clean_settings(clean_engine)
        mock_storage = _mock_clean_storage()

        with patch.object(clean_module, "StorageBackend", return_value=mock_storage):
            result = clean_module.clean(parsed_id, source_id, settings=settings)

        assert result["cleaned_doc"] is None
        assert mock_storage.get_object.call_count == 1
