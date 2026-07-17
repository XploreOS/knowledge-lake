"""Unit tests for pipeline/quality_audit.py (MEAS-01, QUAL-04, Phase 17 Plan 04).

Follows the in-memory SQLite + monkeypatched get_engine fixture pattern from
tests/unit/test_clean_silver_key.py. parse/load_parsed_doc/reparse_from_raw/
clean are mocked at their SOURCE modules (knowledge_lake.pipeline.parse,
knowledge_lake.pipeline.clean) because quality_audit.py uses function-local
imports (process.py convention) — each call re-resolves `from module import
name` against the current module attribute, so patching the source module
(not quality_audit's own namespace) is what actually takes effect.
"""

from __future__ import annotations

import datetime
from unittest.mock import patch

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


def _seed_source(session, *, name: str, domain: str | None, created_at=None):
    from knowledge_lake.registry import repo as registry_repo

    src = registry_repo.create_source(
        session,
        name=name,
        source_type="upload",
        domain=domain,
    )
    session.flush()
    if created_at is not None:
        src.created_at = created_at
    session.flush()
    session.commit()
    return src


def _seed_raw_artifact(session, source_id: str, content_hash: str):
    from knowledge_lake.registry import repo as registry_repo

    art = registry_repo.create_raw_artifact(
        session,
        source_id=source_id,
        content_hash=content_hash,
        storage_uri=f"s3://test-bucket/raw/{source_id}/{content_hash}.pdf",
        mime_type="application/pdf",
    )
    session.flush()
    session.commit()
    return art


def _seed_parsed_artifact(session, source_id: str, raw_id: str, content_hash: str):
    from knowledge_lake.registry import repo as registry_repo

    art = registry_repo.create_parsed_artifact(
        session,
        source_id=source_id,
        parent_artifact_id=raw_id,
        content_hash=content_hash,
        storage_uri=f"s3://test-bucket/silver/{source_id}/{content_hash}.md",
        mime_type="text/markdown",
    )
    session.flush()
    session.commit()
    return art


def _stub_parsed_doc(text: str = "stub text") -> object:
    from knowledge_lake.plugins.protocols import ParsedDoc

    return ParsedDoc(text=text, sections=[], metadata={})


def _clean_result(
    *,
    considered: int = 0,
    kept: int = 0,
    rejected: int = 0,
    reasons: dict | None = None,
) -> dict:
    return {
        "artifact_id": "art_cleaned_stub",
        "content_hash": "cleanedhash",
        "language": "en",
        "dedup_status": "new",
        "storage_uri": "s3://test-bucket/silver/cleaned_stub.md",
        "cleaned_doc": _stub_parsed_doc(),
        "sections_considered": considered,
        "sections_kept": kept,
        "sections_rejected": rejected,
        "rejection_reasons": reasons or {},
    }


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestRunQualityAuditDomainFiltering:
    def test_domain_filter_returns_only_matching_sources(self, session, engine):
        """Two healthcare sources + one legal source -> exactly 2 rows for domain='healthcare'."""
        from knowledge_lake.pipeline.quality_audit import run_quality_audit

        src_a = _seed_source(session, name="Source A", domain="healthcare")
        src_b = _seed_source(session, name="Source B", domain="healthcare")
        _seed_source(session, name="Source C", domain="legal")

        settings = _make_settings(engine)
        rows = run_quality_audit(domain="healthcare", settings=settings)

        assert len(rows) == 2
        names = {row["source_name"] for row in rows}
        assert names == {src_a.name, src_b.name}


class TestRunQualityAuditOrdering:
    def test_rows_ordered_by_created_at_ascending(self, session, engine):
        """Rows are ordered matching Source.created_at ascending (reproducible ordering)."""
        from knowledge_lake.pipeline.quality_audit import run_quality_audit

        base = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        # Insert out of chronological order to prove the query sorts, not insertion order.
        src_third = _seed_source(
            session, name="Third", domain="healthcare", created_at=base + datetime.timedelta(days=2)
        )
        src_first = _seed_source(
            session, name="First", domain="healthcare", created_at=base
        )
        src_second = _seed_source(
            session, name="Second", domain="healthcare", created_at=base + datetime.timedelta(days=1)
        )

        settings = _make_settings(engine)
        rows = run_quality_audit(domain="healthcare", settings=settings)

        assert [r["source_name"] for r in rows] == [
            src_first.name,
            src_second.name,
            src_third.name,
        ]


class TestRunQualityAuditZeroDocs:
    def test_zero_raw_documents_yields_none_garbage_rate(self, session, engine):
        """A source with zero raw_document artifacts -> sections all 0, garbage_rate=None (N/A)."""
        from knowledge_lake.pipeline.quality_audit import run_quality_audit

        _seed_source(session, name="Empty Source", domain="healthcare")

        settings = _make_settings(engine)
        rows = run_quality_audit(domain="healthcare", settings=settings)

        assert len(rows) == 1
        row = rows[0]
        assert row["sections_considered"] == 0
        assert row["sections_kept"] == 0
        assert row["sections_rejected"] == 0
        assert row["garbage_rate"] is None
        assert row["documents_errored"] == 0


class TestRunQualityAuditRejectionReasonsSum:
    def test_rejection_reasons_summed_not_overwritten(self, session, engine):
        """Two raw docs each rejecting one section for the same reason -> counts sum to 2."""
        from knowledge_lake.pipeline.quality_audit import run_quality_audit

        src = _seed_source(session, name="Two Doc Source", domain="healthcare")
        _seed_raw_artifact(session, src.id, "rawhash1")
        _seed_raw_artifact(session, src.id, "rawhash2")

        settings = _make_settings(engine)

        parse_call_count = {"n": 0}

        def parse_stub(raw_id, source_id, *, mime_type=None, settings=None):
            parse_call_count["n"] += 1
            return (
                {"artifact_id": f"art_parsed_{parse_call_count['n']}", "content_hash": "h", "language": "en"},
                _stub_parsed_doc(),
            )

        clean_stub_result = _clean_result(
            considered=1,
            kept=0,
            rejected=1,
            reasons={"empty_after_boilerplate_removal": 1},
        )

        with patch("knowledge_lake.pipeline.parse.parse", side_effect=parse_stub), \
             patch("knowledge_lake.pipeline.clean.clean", return_value=clean_stub_result):
            rows = run_quality_audit(domain="healthcare", settings=settings)

        assert len(rows) == 1
        row = rows[0]
        assert row["rejection_reasons"] == {"empty_after_boilerplate_removal": 2}
        assert row["sections_considered"] == 2
        assert row["sections_kept"] == 0
        assert row["sections_rejected"] == 2


class TestRunQualityAuditGarbageRateFormula:
    def test_garbage_rate_equals_rejected_over_rejected_plus_kept(self, session, engine):
        """garbage_rate for rejected=1, kept=3 equals exactly 0.25 (D-10 frozen formula, unrounded)."""
        from knowledge_lake.pipeline.quality_audit import run_quality_audit

        src = _seed_source(session, name="Rate Source", domain="healthcare")
        raw = _seed_raw_artifact(session, src.id, "rawhash_rate")

        settings = _make_settings(engine)

        clean_stub_result = _clean_result(considered=4, kept=3, rejected=1)

        with patch("knowledge_lake.pipeline.parse.parse", return_value=(
                {"artifact_id": "art_parsed_rate", "content_hash": "h", "language": "en"},
                _stub_parsed_doc(),
            )), \
             patch("knowledge_lake.pipeline.clean.clean", return_value=clean_stub_result):
            rows = run_quality_audit(domain="healthcare", settings=settings)

        assert len(rows) == 1
        assert rows[0]["garbage_rate"] == 0.25


class TestRunQualityAuditErrorIsolation:
    def test_one_document_failure_does_not_abort_audit(self, session, engine):
        """One raw doc's clean() failure is caught/counted; other docs and sources still processed."""
        from knowledge_lake.pipeline.quality_audit import run_quality_audit

        src_a = _seed_source(session, name="Source A", domain="healthcare")
        _seed_raw_artifact(session, src_a.id, "rawhash_fail")
        _seed_raw_artifact(session, src_a.id, "rawhash_ok")

        src_b = _seed_source(session, name="Source B", domain="healthcare")
        _seed_raw_artifact(session, src_b.id, "rawhash_b_ok")

        settings = _make_settings(engine)

        parse_call_count = {"n": 0}

        def parse_stub(raw_id, source_id, *, mime_type=None, settings=None):
            parse_call_count["n"] += 1
            return (
                {"artifact_id": f"art_parsed_{parse_call_count['n']}", "content_hash": "h", "language": "en"},
                _stub_parsed_doc(),
            )

        def clean_stub(parsed_artifact_id, source_id, *, parsed_doc=None, settings=None, domain_filters=None):
            if parsed_artifact_id == "art_parsed_1":
                raise RuntimeError("boom")
            return _clean_result(considered=1, kept=1, rejected=0)

        with patch("knowledge_lake.pipeline.parse.parse", side_effect=parse_stub), \
             patch("knowledge_lake.pipeline.clean.clean", side_effect=clean_stub):
            rows = run_quality_audit(domain="healthcare", settings=settings)

        assert len(rows) == 2
        row_a = next(r for r in rows if r["source_name"] == "Source A")
        row_b = next(r for r in rows if r["source_name"] == "Source B")

        assert row_a["documents_errored"] == 1
        # The other raw doc in Source A was still processed.
        assert row_a["sections_considered"] == 1
        assert row_a["sections_kept"] == 1

        # Source B unaffected.
        assert row_b["documents_errored"] == 0
        assert row_b["sections_considered"] == 1
        assert row_b["sections_kept"] == 1


class TestRunQualityAuditDomainFiltersGap:
    def test_domain_filters_threaded_into_existing_clean_call(self, session, engine):
        """run_quality_audit()'s existing clean() call site threads domain_filters
        (Pitfall 1 fix) — resolved once via DomainLoader.from_name(...).filters."""
        from knowledge_lake.config.settings import DomainSettings, Settings, StorageSettings
        from knowledge_lake.domains.models import DomainFilters
        from knowledge_lake.pipeline.quality_audit import run_quality_audit

        src = _seed_source(session, name="Healthcare Source", domain="healthcare")
        _seed_raw_artifact(session, src.id, "rawhash_domain_filters")

        ss = StorageSettings(
            endpoint_url="http://localhost:9000",
            bucket="test-bucket",
            access_key_id="test",
            secret_access_key="test",
        )
        settings = Settings(
            database_url=str(engine.url),
            storage=ss,
            domain=DomainSettings(domain_name="healthcare"),
            _env_file=None,  # type: ignore[call-arg]
        )

        fake_filters = DomainFilters(normative_allowlists=["ICD-10"])

        class _StubLoader:
            filters = fake_filters

        clean_stub_result = _clean_result(considered=1, kept=1, rejected=0)

        with patch(
            "knowledge_lake.pipeline.parse.parse",
            return_value=(
                {"artifact_id": "art_parsed_df", "content_hash": "h", "language": "en"},
                _stub_parsed_doc(),
            ),
        ), patch(
            "knowledge_lake.domains.loader.DomainLoader.from_name",
            return_value=_StubLoader(),
        ) as mock_from_name, patch(
            "knowledge_lake.pipeline.clean.clean",
            return_value=clean_stub_result,
        ) as mock_clean:
            run_quality_audit(domain="healthcare", settings=settings)

        mock_from_name.assert_called_once_with("healthcare")
        assert mock_clean.call_args.kwargs["domain_filters"] is fake_filters


class TestRunFullPipelineAuditChunkTally:
    def test_chunk_audit_tallies_kept_rejected_from_gate(self, session, engine):
        """run_full_pipeline_audit() tallies chunk-level kept/rejected/reasons
        purely from the in-memory _build_token_chunks()+_apply_substance_gate()
        annotation — one clinical-prose section kept, one nav-junk section
        rejected -> chunks_considered=2, chunks_kept=1, chunks_rejected=1,
        chunk_garbage_rate=0.5 (frozen rejected/(rejected+kept) formula)."""
        from knowledge_lake.pipeline.quality_audit import run_full_pipeline_audit
        from knowledge_lake.plugins.protocols import ParsedDoc, Section

        src = _seed_source(session, name="Chunk Tally Source", domain="healthcare")
        _seed_raw_artifact(session, src.id, "rawhash_chunk_tally")

        settings = _make_settings(engine)

        clinical_prose_text = (
            "The patient presents with type 2 diabetes mellitus (ICD-10 E11.9) and was "
            "prescribed Metformin 500 mg PO BID. Follow-up labs showed HbA1c of 7.2%."
        )
        nav_junk_text = "Home About Contact Sitemap Search"

        cleaned_doc = ParsedDoc(
            text="",
            sections=[
                Section(
                    heading="Overview",
                    section_path="§1",
                    page=1,
                    text=clinical_prose_text,
                    is_table=False,
                ),
                Section(
                    heading="Nav",
                    section_path="§2",
                    page=1,
                    text=nav_junk_text,
                    is_table=False,
                ),
            ],
            metadata={},
        )
        clean_stub_result = _clean_result(considered=2, kept=2, rejected=0)
        clean_stub_result["cleaned_doc"] = cleaned_doc

        with patch(
            "knowledge_lake.pipeline.parse.parse",
            return_value=(
                {"artifact_id": "art_parsed_chunk_tally", "content_hash": "h", "language": "en"},
                _stub_parsed_doc(),
            ),
        ), patch(
            "knowledge_lake.pipeline.clean.clean", return_value=clean_stub_result
        ) as mock_clean:
            result = run_full_pipeline_audit(domain="healthcare", settings=settings)

        assert "domain_filters" in mock_clean.call_args.kwargs

        assert len(result["rows"]) == 1
        row = result["rows"][0]
        assert row["chunks_considered"] == 2
        assert row["chunks_kept"] == 1
        assert row["chunks_rejected"] == 1
        assert sum(row["chunk_rejection_reasons"].values()) == 1
        assert row["chunk_garbage_rate"] == 0.5

    def test_chunk_audit_zero_chunks_yields_none_rate(self, session, engine):
        """A source whose cleaned_doc has empty sections and empty text ->
        chunks_considered=0, chunk_garbage_rate=None (never 0.0, never
        ZeroDivisionError) — mirrors the existing zero-docs section-level
        test's contract."""
        from knowledge_lake.pipeline.quality_audit import run_full_pipeline_audit
        from knowledge_lake.plugins.protocols import ParsedDoc

        src = _seed_source(session, name="Zero Chunk Source", domain="healthcare")
        _seed_raw_artifact(session, src.id, "rawhash_zero_chunk")

        settings = _make_settings(engine)

        cleaned_doc = ParsedDoc(text="   ", sections=[], metadata={})
        clean_stub_result = _clean_result(considered=0, kept=0, rejected=0)
        clean_stub_result["cleaned_doc"] = cleaned_doc

        with patch(
            "knowledge_lake.pipeline.parse.parse",
            return_value=(
                {"artifact_id": "art_parsed_zero_chunk", "content_hash": "h", "language": "en"},
                _stub_parsed_doc(),
            ),
        ), patch("knowledge_lake.pipeline.clean.clean", return_value=clean_stub_result):
            result = run_full_pipeline_audit(domain="healthcare", settings=settings)

        assert len(result["rows"]) == 1
        row = result["rows"][0]
        assert row["chunks_considered"] == 0
        assert row["chunk_garbage_rate"] is None


class TestRunQualityAuditParsedDocReuse:
    def test_existing_parsed_child_skips_parse_call(self, session, engine):
        """A raw doc with an existing parsed_document child never calls parse(); one without does."""
        from knowledge_lake.pipeline.quality_audit import run_quality_audit

        src = _seed_source(session, name="Reuse Source", domain="healthcare")
        raw_with_child = _seed_raw_artifact(session, src.id, "rawhash_with_child")
        _seed_parsed_artifact(session, src.id, raw_with_child.id, "parsedhash_existing")
        _seed_raw_artifact(session, src.id, "rawhash_no_child")

        settings = _make_settings(engine)

        clean_stub_result = _clean_result(considered=0, kept=0, rejected=0)

        with patch(
            "knowledge_lake.pipeline.parse.load_parsed_doc",
            return_value=_stub_parsed_doc(),
        ) as mock_load, \
             patch(
                 "knowledge_lake.pipeline.parse.reparse_from_raw",
             ) as mock_reparse, \
             patch(
                 "knowledge_lake.pipeline.parse.parse",
                 return_value=(
                     {"artifact_id": "art_parsed_new", "content_hash": "h", "language": "en"},
                     _stub_parsed_doc(),
                 ),
             ) as mock_parse, \
             patch("knowledge_lake.pipeline.clean.clean", return_value=clean_stub_result):
            run_quality_audit(domain="healthcare", settings=settings)

        assert mock_load.call_count == 1
        assert mock_reparse.call_count == 0
        assert mock_parse.call_count == 1
