"""Tests for pipeline/wiki.py — wiki compilation with IDF filtering and incremental rebuild.

Uses an in-memory SQLite engine (StaticPool pattern from test_tree_index.py)
with knowledge_lake.registry.db.get_engine monkeypatched so compile_wiki()'s
own get_session() calls resolve against the same in-memory database.
StorageBackend is patched at the wiki module level so no real S3 client is
constructed.

Tests cover KB-01..KB-04:
  KB-01 — per-document summary pages
  KB-02 — root index page
  KB-03 — IDF-filtered cross-document concept pages
  KB-04 — manifest-based incremental rebuild
"""

from __future__ import annotations

import io
import json
import tarfile
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.pipeline.wiki as wiki_module
import knowledge_lake.registry.db as registry_db
from knowledge_lake.config.settings import Settings, WikiSettings


# ── Fixtures ───────────────────────────────────────────────────────────────────


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


@pytest.fixture()
def mock_storage():
    """A mock StorageBackend with configurable get_object behaviour."""
    storage = MagicMock()
    # Default: no manifest exists (first run)
    from botocore.exceptions import ClientError
    storage.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": ""}}, "GetObject"
    )
    storage.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"
    return storage


@pytest.fixture()
def mock_storage_factory(mock_storage):
    """Patch wiki_module._make_storage to return mock_storage."""
    with patch.object(wiki_module, "_make_storage", return_value=mock_storage):
        yield mock_storage


@pytest.fixture()
def three_doc_corpus(session):
    """Seed 3 enriched documents in the same 'healthcare' domain.

    Entities 'insulin' and 'glucose' appear in 2/3 docs (qualify for concept
    pages). 'rare-entity' appears in 1 doc (excluded by min_entity_df=2).
    """
    from knowledge_lake.registry import repo as registry_repo

    source = registry_repo.create_source(
        session, name="Medical Journal", source_type="web"
    )
    # Store domain in source.config
    source.config = {"domain": "healthcare"}
    session.flush()

    # Create 3 doc chains: source -> raw -> parsed -> cleaned -> enriched
    enrichment_data = [
        {
            "title": "Diabetes Overview",
            "summary": "Overview of diabetes management.",
            "document_type": "article",
            "keywords": ["diabetes", "insulin"],
            "entities": ["insulin", "glucose", "rare-entity"],
            "quality_score": 0.9,
        },
        {
            "title": "Glucose Metabolism",
            "summary": "How glucose is metabolized.",
            "document_type": "article",
            "keywords": ["glucose", "metabolism"],
            "entities": ["insulin", "glucose"],
            "quality_score": 0.85,
        },
        {
            "title": "Hypertension Guide",
            "summary": "Managing hypertension.",
            "document_type": "guide",
            "keywords": ["hypertension", "blood pressure"],
            "entities": ["glucose"],
            "quality_score": 0.8,
        },
    ]

    enriched_artifacts = []
    for i, data in enumerate(enrichment_data):
        raw = registry_repo.create_raw_artifact(
            session,
            source_id=source.id,
            content_hash=f"raw_hash_{i}",
            storage_uri=f"s3://test/raw/doc{i}.pdf",
        )
        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash=f"parsed_hash_{i}",
            storage_uri=f"s3://test/parsed/doc{i}.json",
        )
        cleaned = registry_repo.create_cleaned_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=parsed.id,
            content_hash=f"cleaned_hash_{i}",
            storage_uri=f"s3://test/cleaned/doc{i}.json",
        )
        enriched = registry_repo.create_enriched_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=cleaned.id,
            content_hash=f"enriched_hash_{i}",
            metadata=data,
        )
        # Store title in metadata for wiki
        enriched.metadata_["title"] = data["title"]
        enriched_artifacts.append(enriched)

    session.commit()
    return {"source": source, "enriched": enriched_artifacts}


# ── Unit tests: pure functions ─────────────────────────────────────────────────


class TestSlugify:
    """slugify() produces deterministic ASCII slugs (D-02)."""

    def test_typical_title(self):
        assert wiki_module.slugify("Mayo Clinic - Diabetes Overview") == "mayo-clinic-diabetes-overview"

    def test_punctuation_stripped(self):
        assert wiki_module.slugify("Type 2 Diabetes!!!") == "type-2-diabetes"

    def test_empty_string_returns_untitled(self):
        assert wiki_module.slugify("") == "untitled"

    def test_spaces_collapsed(self):
        assert wiki_module.slugify("  Multiple   Spaces  ") == "multiple-spaces"

    def test_already_lowercase(self):
        assert wiki_module.slugify("simple title") == "simple-title"

    def test_numeric_ok(self):
        assert wiki_module.slugify("Phase 16 Plan 01") == "phase-16-plan-01"

    def test_unicode_stripped(self):
        # Non-ASCII chars become hyphens then collapsed
        result = wiki_module.slugify("Café René")
        assert result == result.encode("ascii", "ignore").decode()
        assert "--" not in result


class TestDisambiguateSlug:
    """disambiguate_slug() appends a hash suffix for collision avoidance (D-02)."""

    def test_appends_8_hex_chars(self):
        result = wiki_module.disambiguate_slug("my-slug", "abcdef1234567890")
        assert result == "my-slug-abcdef12"

    def test_different_hashes_give_different_suffixes(self):
        a = wiki_module.disambiguate_slug("slug", "aaa")
        b = wiki_module.disambiguate_slug("slug", "bbb")
        assert a != b

    def test_original_slug_preserved_as_prefix(self):
        result = wiki_module.disambiguate_slug("hello-world", "deadbeef0000")
        assert result.startswith("hello-world-")


class TestComputeEntityIdf:
    """compute_entity_idf() returns IDF for qualifying entities (D-03, D-05)."""

    def test_filters_low_df(self):
        idf = wiki_module.compute_entity_idf(
            {"insulin": 3, "patient": 10, "rare-term": 1},
            total_docs=10,
            min_entity_df=2,
        )
        assert "rare-term" not in idf, "df=1 entity must be excluded"

    def test_includes_qualifying_entities(self):
        idf = wiki_module.compute_entity_idf(
            {"insulin": 3, "patient": 10},
            total_docs=10,
            min_entity_df=2,
        )
        assert "insulin" in idf
        assert "patient" in idf

    def test_idf_formula(self):
        import math
        idf = wiki_module.compute_entity_idf(
            {"insulin": 2},
            total_docs=10,
            min_entity_df=2,
        )
        expected = math.log(10 / 2)
        assert abs(idf["insulin"] - expected) < 1e-9

    def test_empty_corpus(self):
        idf = wiki_module.compute_entity_idf({}, total_docs=0, min_entity_df=2)
        assert idf == {}

    def test_all_filtered_returns_empty(self):
        idf = wiki_module.compute_entity_idf(
            {"singleton": 1}, total_docs=5, min_entity_df=2
        )
        assert idf == {}


class TestIdentifyChangedPages:
    """_identify_changed_pages() diffs content hashes to find new/changed/removed."""

    def test_no_manifest_all_new(self):
        current = {"doc/page1.md": "hash1", "doc/page2.md": "hash2"}
        new, changed, removed = wiki_module._identify_changed_pages(current, {})
        assert new == {"doc/page1.md", "doc/page2.md"}
        assert changed == set()
        assert removed == set()

    def test_unchanged_pages_excluded(self):
        current = {"doc/page1.md": "hash1"}
        manifest = {"doc/page1.md": "hash1"}
        new, changed, removed = wiki_module._identify_changed_pages(current, manifest)
        assert new == set()
        assert changed == set()
        assert removed == set()

    def test_changed_hash_detected(self):
        current = {"doc/page1.md": "new_hash"}
        manifest = {"doc/page1.md": "old_hash"}
        new, changed, removed = wiki_module._identify_changed_pages(current, manifest)
        assert changed == {"doc/page1.md"}
        assert new == set()
        assert removed == set()

    def test_removed_page_detected(self):
        current = {}
        manifest = {"doc/old-page.md": "hash1"}
        new, changed, removed = wiki_module._identify_changed_pages(current, manifest)
        assert removed == {"doc/old-page.md"}
        assert new == set()
        assert changed == set()


# ── Integration tests: compile_wiki ───────────────────────────────────────────


class TestCompileWiki:
    """compile_wiki() integration tests using mocked storage and in-memory DB."""

    def test_returns_page_counts(self, mock_storage_factory, three_doc_corpus):
        """compile_wiki with 3 enriched docs returns pages_created >= 5 (3 doc + concepts + index)."""
        settings = Settings(wiki=WikiSettings(min_entity_idf=0.0, min_entity_df=2))
        result = wiki_module.compile_wiki(
            domain="healthcare", settings=settings
        )
        # 3 doc pages + at least 1 concept page + 1 index = 5+
        assert result["pages_created"] >= 5
        assert result["concept_pages"] >= 1
        assert result["manifest_uri"].startswith("s3://")

    def test_doc_pages_written_to_s3(self, mock_storage_factory, three_doc_corpus):
        """Each document gets its own .md page written to S3."""
        settings = Settings(wiki=WikiSettings(min_entity_idf=0.0, min_entity_df=2))
        wiki_module.compile_wiki(domain="healthcare", settings=settings)
        calls = mock_storage_factory.put_object.call_args_list
        written_keys = [c[0][0] for c in calls]
        doc_keys = [k for k in written_keys if "wiki/doc/" in k]
        assert len(doc_keys) == 3

    def test_doc_page_contains_wikilinks(self, mock_storage_factory, three_doc_corpus):
        """Document pages contain [[concept-slug|Entity Name]] wikilinks for qualifying entities."""
        settings = Settings(wiki=WikiSettings(min_entity_idf=0.0, min_entity_df=2))
        wiki_module.compile_wiki(domain="healthcare", settings=settings)
        calls = mock_storage_factory.put_object.call_args_list
        # Find a doc page call and inspect its content
        doc_page_calls = [
            c for c in calls if len(c[0]) >= 2 and "wiki/doc/" in c[0][0]
        ]
        assert len(doc_page_calls) >= 1
        content = doc_page_calls[0][0][1].decode("utf-8")
        assert "[[" in content, "Document page should contain [[wikilinks]]"

    def test_concept_page_backlinks(self, mock_storage_factory, three_doc_corpus):
        """Concept pages link back to all containing document pages."""
        settings = Settings(wiki=WikiSettings(min_entity_idf=0.0, min_entity_df=2))
        wiki_module.compile_wiki(domain="healthcare", settings=settings)
        calls = mock_storage_factory.put_object.call_args_list
        concept_calls = [
            c for c in calls if len(c[0]) >= 2 and "wiki/concept/" in c[0][0]
        ]
        assert len(concept_calls) >= 1
        # At least one concept page has backlinks
        for c in concept_calls:
            content = c[0][1].decode("utf-8")
            if "[[" in content:
                return
        pytest.fail("No concept page contains backlinks")

    def test_index_page_written(self, mock_storage_factory, three_doc_corpus):
        """A root index.md page is written to S3."""
        settings = Settings(wiki=WikiSettings(min_entity_idf=0.0, min_entity_df=2))
        wiki_module.compile_wiki(domain="healthcare", settings=settings)
        calls = mock_storage_factory.put_object.call_args_list
        written_keys = [c[0][0] for c in calls]
        index_keys = [k for k in written_keys if k.endswith("wiki/index.md")]
        assert len(index_keys) == 1

    def test_low_df_entity_no_concept_page(self, mock_storage_factory, three_doc_corpus):
        """Entity with df=1 does NOT get a concept page (filtered by min_entity_df=2)."""
        settings = Settings(wiki=WikiSettings(min_entity_idf=0.0, min_entity_df=2))
        wiki_module.compile_wiki(domain="healthcare", settings=settings)
        calls = mock_storage_factory.put_object.call_args_list
        written_keys = [c[0][0] for c in calls]
        concept_keys = [k for k in written_keys if "wiki/concept/" in k]
        # 'rare-entity' only appears in 1 doc — should not have a concept page
        rare_keys = [k for k in concept_keys if "rare" in k]
        assert len(rare_keys) == 0, f"rare-entity should not have concept page, found: {rare_keys}"

    def test_high_idf_threshold_filters_concepts(self, mock_storage_factory, three_doc_corpus):
        """Entity with IDF below threshold does NOT get a concept page."""
        # Set IDF threshold very high so nothing qualifies
        settings = Settings(wiki=WikiSettings(min_entity_idf=99.0, min_entity_df=2))
        result = wiki_module.compile_wiki(domain="healthcare", settings=settings)
        assert result["concept_pages"] == 0

    def test_dry_run_no_writes(self, mock_storage_factory, three_doc_corpus):
        """dry_run=True returns non-zero counts but storage.put_object is never called."""
        settings = Settings(wiki=WikiSettings(min_entity_idf=0.0, min_entity_df=2))
        result = wiki_module.compile_wiki(
            domain="healthcare", dry_run=True, settings=settings
        )
        assert result["pages_created"] >= 5
        mock_storage_factory.put_object.assert_not_called()

    def test_incremental_rebuild_unchanged(self, mock_storage_factory, three_doc_corpus):
        """Second invocation with unchanged manifest returns pages_updated=0."""
        settings = Settings(wiki=WikiSettings(min_entity_idf=0.0, min_entity_df=2))
        # First run: capture what was written to build a manifest
        first_result = wiki_module.compile_wiki(domain="healthcare", settings=settings)
        assert first_result["pages_created"] > 0

        # Build manifest from what was written
        calls = mock_storage_factory.put_object.call_args_list
        manifest_data: dict[str, str] = {}
        import hashlib
        for c in calls:
            key = c[0][0]
            data = c[0][1]
            if not key.endswith("_manifest.json") and not key.endswith(".tar.gz"):
                manifest_data[key] = hashlib.sha256(data).hexdigest()

        # Now mock get_object to return this manifest
        mock_storage_factory.put_object.reset_mock()
        mock_storage_factory.get_object.side_effect = None
        mock_storage_factory.get_object.return_value = json.dumps(manifest_data).encode("utf-8")

        second_result = wiki_module.compile_wiki(domain="healthcare", settings=settings)
        assert second_result["pages_updated"] == 0
        assert second_result["pages_unchanged"] > 0

    def test_force_true_rebuilds_all(self, mock_storage_factory, three_doc_corpus):
        """force=True always rebuilds all pages regardless of manifest."""
        settings = Settings(wiki=WikiSettings(min_entity_idf=0.0, min_entity_df=2))
        # First run
        wiki_module.compile_wiki(domain="healthcare", settings=settings)
        first_call_count = mock_storage_factory.put_object.call_count

        # Set up manifest that says everything is up-to-date
        calls = mock_storage_factory.put_object.call_args_list
        manifest_data: dict[str, str] = {}
        import hashlib
        for c in calls:
            key = c[0][0]
            data = c[0][1]
            if not key.endswith("_manifest.json") and not key.endswith(".tar.gz"):
                manifest_data[key] = hashlib.sha256(data).hexdigest()

        mock_storage_factory.put_object.reset_mock()
        mock_storage_factory.get_object.side_effect = None
        mock_storage_factory.get_object.return_value = json.dumps(manifest_data).encode("utf-8")

        # Force rebuild
        result = wiki_module.compile_wiki(
            domain="healthcare", force=True, settings=settings
        )
        # All pages should be rebuilt
        assert result["pages_unchanged"] == 0

    def test_archive_produces_tar_gz(self, mock_storage_factory, three_doc_corpus):
        """archive=True calls storage.put_object with a key ending in .tar.gz."""
        settings = Settings(wiki=WikiSettings(min_entity_idf=0.0, min_entity_df=2))
        result = wiki_module.compile_wiki(
            domain="healthcare", archive=True, settings=settings
        )
        assert result["archive_uri"] is not None
        calls = mock_storage_factory.put_object.call_args_list
        written_keys = [c[0][0] for c in calls]
        tar_keys = [k for k in written_keys if k.endswith(".tar.gz")]
        assert len(tar_keys) == 1

    def test_archive_false_no_tar_gz(self, mock_storage_factory, three_doc_corpus):
        """archive=False (default) does NOT write a .tar.gz."""
        settings = Settings(wiki=WikiSettings(min_entity_idf=0.0, min_entity_df=2))
        result = wiki_module.compile_wiki(domain="healthcare", settings=settings)
        assert result["archive_uri"] is None
        calls = mock_storage_factory.put_object.call_args_list
        written_keys = [c[0][0] for c in calls]
        tar_keys = [k for k in written_keys if k.endswith(".tar.gz")]
        assert len(tar_keys) == 0

    def test_manifest_written(self, mock_storage_factory, three_doc_corpus):
        """compile_wiki always writes a _manifest.json to S3."""
        settings = Settings(wiki=WikiSettings(min_entity_idf=0.0, min_entity_df=2))
        wiki_module.compile_wiki(domain="healthcare", settings=settings)
        calls = mock_storage_factory.put_object.call_args_list
        written_keys = [c[0][0] for c in calls]
        manifest_keys = [k for k in written_keys if "_manifest.json" in k]
        assert len(manifest_keys) == 1

    def test_malformed_manifest_triggers_full_rebuild(
        self, mock_storage_factory, three_doc_corpus
    ):
        """Malformed manifest JSON triggers a full rebuild with a warning (T-16-05)."""
        mock_storage_factory.get_object.side_effect = None
        mock_storage_factory.get_object.return_value = b"not valid json {{{"
        settings = Settings(wiki=WikiSettings(min_entity_idf=0.0, min_entity_df=2))
        result = wiki_module.compile_wiki(domain="healthcare", settings=settings)
        # Should still complete (full rebuild)
        assert result["pages_created"] >= 5


# ── KB-05: CLI and API surface tests ──────────────────────────────────────────

_MOCK_COMPILE_RESULT = {
    "pages_created": 3,
    "pages_updated": 1,
    "pages_unchanged": 2,
    "concept_pages": 2,
    "manifest_uri": "s3://test-bucket/gold/healthcare/wiki/_manifest.json",
    "archive_uri": None,
}

_MOCK_COMPILE_RESULT_ARCHIVE = {
    **_MOCK_COMPILE_RESULT,
    "archive_uri": "s3://test-bucket/gold/healthcare/wiki/_archive.tar.gz",
}

_PATCH_TARGET = "knowledge_lake.pipeline.wiki.compile_wiki"


class TestCliExportWiki:
    """Surface tests for the `klake export-wiki` CLI command (KB-05)."""

    def test_cli_export_wiki_success(self):
        """Successful invocation prints result fields and exits 0."""
        from typer.testing import CliRunner

        from knowledge_lake.cli.app import app

        runner = CliRunner()
        with patch(_PATCH_TARGET, return_value=_MOCK_COMPILE_RESULT) as mock_fn:
            result = runner.invoke(app, ["export-wiki", "--domain", "healthcare"])

        assert result.exit_code == 0, result.output
        assert "pages_created" in result.output
        assert "manifest_uri" in result.output
        mock_fn.assert_called_once()
        call_kwargs = mock_fn.call_args[1] if mock_fn.call_args[1] else {}
        call_args = mock_fn.call_args[0] if mock_fn.call_args[0] else ()
        # domain can be positional or keyword
        assert "healthcare" in call_args or call_kwargs.get("domain") == "healthcare"

    def test_cli_export_wiki_force(self):
        """--force flag passes force=True to compile_wiki."""
        from typer.testing import CliRunner

        from knowledge_lake.cli.app import app

        runner = CliRunner()
        with patch(_PATCH_TARGET, return_value=_MOCK_COMPILE_RESULT) as mock_fn:
            result = runner.invoke(app, ["export-wiki", "--domain", "healthcare", "--force"])

        assert result.exit_code == 0, result.output
        _, kwargs = mock_fn.call_args
        assert kwargs.get("force") is True

    def test_cli_export_wiki_dry_run(self):
        """--dry-run flag passes dry_run=True to compile_wiki."""
        from typer.testing import CliRunner

        from knowledge_lake.cli.app import app

        runner = CliRunner()
        with patch(_PATCH_TARGET, return_value=_MOCK_COMPILE_RESULT) as mock_fn:
            result = runner.invoke(app, ["export-wiki", "--domain", "healthcare", "--dry-run"])

        assert result.exit_code == 0, result.output
        _, kwargs = mock_fn.call_args
        assert kwargs.get("dry_run") is True

    def test_cli_export_wiki_error(self):
        """ValueError from compile_wiki prints 'Error:' to output and exits 1."""
        from typer.testing import CliRunner

        from knowledge_lake.cli.app import app

        runner = CliRunner()
        with patch(_PATCH_TARGET, side_effect=ValueError("no docs found")):
            result = runner.invoke(app, ["export-wiki", "--domain", "healthcare"])

        assert result.exit_code == 1
        assert "Error:" in result.output

    def test_cli_export_wiki_archive_uri_shown(self):
        """archive_uri is printed when present in compile_wiki result."""
        from typer.testing import CliRunner

        from knowledge_lake.cli.app import app

        runner = CliRunner()
        with patch(_PATCH_TARGET, return_value=_MOCK_COMPILE_RESULT_ARCHIVE):
            result = runner.invoke(app, ["export-wiki", "--domain", "healthcare", "--archive"])

        assert result.exit_code == 0, result.output
        assert "archive_uri" in result.output


class TestApiExportWiki:
    """Surface tests for the POST /export-wiki API endpoint (KB-05)."""

    def test_api_export_wiki_success(self):
        """POST /export-wiki with valid domain returns 200 with WikiExportResponse fields."""
        from fastapi.testclient import TestClient

        from knowledge_lake.api.app import app

        client = TestClient(app)
        with patch(_PATCH_TARGET, return_value=_MOCK_COMPILE_RESULT):
            response = client.post("/export-wiki", json={"domain": "healthcare"})

        assert response.status_code == 200
        body = response.json()
        assert body["pages_created"] == 3
        assert body["pages_updated"] == 1
        assert body["pages_unchanged"] == 2
        assert body["concept_pages"] == 2
        assert "manifest_uri" in body
        assert body["archive_uri"] is None

    def test_api_export_wiki_force(self):
        """POST /export-wiki with force=true passes force=True to compile_wiki."""
        from fastapi.testclient import TestClient

        from knowledge_lake.api.app import app

        client = TestClient(app)
        with patch(_PATCH_TARGET, return_value=_MOCK_COMPILE_RESULT) as mock_fn:
            response = client.post("/export-wiki", json={"domain": "healthcare", "force": True})

        assert response.status_code == 200
        _, kwargs = mock_fn.call_args
        assert kwargs.get("force") is True

    def test_api_export_wiki_error(self):
        """ValueError from compile_wiki returns HTTP 422."""
        from fastapi.testclient import TestClient

        from knowledge_lake.api.app import app

        client = TestClient(app)
        with patch(_PATCH_TARGET, side_effect=ValueError("no docs found")):
            response = client.post("/export-wiki", json={"domain": "healthcare"})

        assert response.status_code == 422
