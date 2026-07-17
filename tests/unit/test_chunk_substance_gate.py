"""Tests for the chunk-level composite substance gate (QUAL-02, QUAL-03).

Covers:
  - Domain allowlist exemption (short-circuits before FineWebQualityFilter or
    any threshold predicate runs)
  - is_table=True unconditional exemption (D-03)
  - Clinical-prose chunks passing cleanly with default thresholds
  - Nav-junk chunks excluded in enforce mode, annotated-but-kept in report mode
  - FineWebQualityFilter's own exact-boundary (`<` not `<=`) semantics
  - Repeated-call determinism (gate always recomputes fresh, never reads stale
    metadata)
  - end-to-end wiring through chunk() (DomainLoader-style domain_filters param,
    enforce/report mode effect on the returned chunk list)

`_apply_substance_gate()` is the pure, DB-free internal helper introduced by
this plan (chunk.py) so gate-decision logic can be unit-tested directly,
without the Postgres/S3 fixtures `chunk()` itself requires. `chunk()`-level
tests below reuse test_chunk_storage.py's exact
engine/_patch_engine/fake_storage/test_settings/_seed_source_and_parsed
fixture style.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.registry.db as registry_db
from knowledge_lake.config.settings import Settings
from knowledge_lake.plugins.protocols import ParsedDoc, Section

NAV_JUNK_TEXT = "Home About Contact Sitemap Search"
CLINICAL_PROSE_TEXT = (
    "The patient presents with type 2 diabetes mellitus (ICD-10 E11.9) and was "
    "prescribed Metformin 500 mg PO BID. Follow-up labs showed HbA1c of 7.2%."
)


def _raw(text: str, *, is_table: bool = False, section_path: str = "§1") -> dict:
    return {
        "text": text,
        "section_path": section_path,
        "page": 1,
        "is_table": is_table,
        "oversized": False,
        "heading_prefix": "",
    }


# ── Fixtures (mirrors tests/unit/test_chunk_storage.py verbatim) ──────────────


@pytest.fixture()
def engine():
    """In-memory SQLite engine shared across sessions via StaticPool."""
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
    """Route chunk()'s internal get_session() to the in-memory test engine."""
    monkeypatch.setattr(registry_db, "get_engine", lambda: engine)


@pytest.fixture()
def fake_storage(monkeypatch):
    """Patch StorageBackend inside pipeline.chunk to capture put_object calls."""
    from knowledge_lake.pipeline.chunk import StorageBackend  # noqa: F401

    fake = MagicMock()
    fake.object_uri.side_effect = lambda key: f"s3://test-bucket/{key}"
    monkeypatch.setattr("knowledge_lake.pipeline.chunk.StorageBackend", lambda *_a, **_k: fake)
    return fake


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _seed_source_and_parsed(engine, *, domain: str | None):
    """Seed a Source (optionally with a config domain) + a parsed_document parent."""
    from knowledge_lake.registry import repo as registry_repo

    with Session(engine) as session:
        config = {"domain": domain} if domain else None
        source = registry_repo.create_source(
            session, name="Test Source", source_type="web", config=config
        )
        session.flush()
        raw = registry_repo.create_raw_artifact(
            session,
            source_id=source.id,
            content_hash="raw_h",
            storage_uri="s3://b/raw/raw_h.pdf",
        )
        session.flush()
        parsed = registry_repo.create_parsed_artifact(
            session,
            source_id=source.id,
            parent_artifact_id=raw.id,
            content_hash="parsed_h",
            storage_uri="s3://b/silver/parsed_h.md",
        )
        session.commit()
        return source.id, parsed.id


# ── _apply_substance_gate() unit tests (pure, no DB/storage needed) ──────────


def test_apply_substance_gate_allowlist_exemption_passes(test_settings):
    """A domain_filters allowlist match rescues a short clinical code far below
    token/alpha-ratio thresholds — the exemption short-circuits before any
    threshold predicate runs."""
    from knowledge_lake.domains.models import DomainFilters
    from knowledge_lake.pipeline.chunk import _apply_substance_gate

    domain_filters = DomainFilters(normative_allowlists=["ICD-10"])
    out = _apply_substance_gate(
        [_raw("ICD-10 E11.9")], test_settings, domain_filters, "parsed-1"
    )
    assert len(out) == 1
    assert out[0]["substance_passed"] is True
    assert out[0]["rejection_reason"] is None


def test_apply_substance_gate_without_domain_filters_rejects_same_code(test_settings):
    """The same bare code, with no domain_filters supplied, is rejected in
    enforce mode — proves the allowlist (not looser thresholds) is what
    rescues it above."""
    from knowledge_lake.pipeline.chunk import _apply_substance_gate

    out = _apply_substance_gate([_raw("ICD-10 E11.9")], test_settings, None, "parsed-1")
    assert out == []


def test_apply_substance_gate_is_table_exempt_regardless_of_text(test_settings):
    """is_table=True always passes, even for nav-junk text (D-03)."""
    from knowledge_lake.pipeline.chunk import _apply_substance_gate

    out = _apply_substance_gate(
        [_raw(NAV_JUNK_TEXT, is_table=True)], test_settings, None, "parsed-1"
    )
    assert len(out) == 1
    assert out[0]["substance_passed"] is True
    assert out[0]["rejection_reason"] is None


def test_apply_substance_gate_clinical_prose_passes(test_settings):
    """A multi-sentence clinical-prose chunk passes cleanly with no domain_filters."""
    from knowledge_lake.pipeline.chunk import _apply_substance_gate

    out = _apply_substance_gate(
        [_raw(CLINICAL_PROSE_TEXT)], test_settings, None, "parsed-1"
    )
    assert len(out) == 1
    assert out[0]["substance_passed"] is True


def test_apply_substance_gate_enforce_mode_excludes_nav_junk(test_settings):
    """Nav-junk fails FineWebQualityFilter's line_punct_ratio check and is
    EXCLUDED from the returned list under the default gate_mode='enforce'."""
    from knowledge_lake.pipeline.chunk import _apply_substance_gate

    assert test_settings.chunk_quality.gate_mode == "enforce"
    out = _apply_substance_gate([_raw(NAV_JUNK_TEXT)], test_settings, None, "parsed-1")
    assert out == []


def test_apply_substance_gate_report_mode_annotates_but_keeps_nav_junk(test_settings):
    """Under gate_mode='report', the same nav-junk chunk is NOT excluded — it
    is kept with substance_passed=False and a non-null rejection_reason in
    its (raw) dict."""
    from knowledge_lake.pipeline.chunk import _apply_substance_gate

    report_settings = test_settings.model_copy(deep=True)
    report_settings.chunk_quality.gate_mode = "report"

    out = _apply_substance_gate([_raw(NAV_JUNK_TEXT)], report_settings, None, "parsed-1")
    assert len(out) == 1
    assert out[0]["substance_passed"] is False
    assert out[0]["rejection_reason"] is not None


def test_apply_substance_gate_is_deterministic_across_repeated_calls(test_settings):
    """Calling the gate twice on identical raw chunk dicts yields identical
    substance_passed/rejection_reason both times — the gate always recomputes
    fresh from raw chunk text."""
    from knowledge_lake.pipeline.chunk import _apply_substance_gate

    report_settings = test_settings.model_copy(deep=True)
    report_settings.chunk_quality.gate_mode = "report"

    out1 = _apply_substance_gate([_raw(NAV_JUNK_TEXT)], report_settings, None, "parsed-1")
    out2 = _apply_substance_gate([_raw(NAV_JUNK_TEXT)], report_settings, None, "parsed-1")
    assert out1[0]["substance_passed"] == out2[0]["substance_passed"] is False
    assert out1[0]["rejection_reason"] == out2[0]["rejection_reason"]
    assert out1[0]["rejection_reason"] is not None


def test_chunk_conservation_invariant_raises_runtime_error_on_violation():
    """chunk() raises RuntimeError (never a bare assert) if
    kept_count + rejected_count != total_generated (QUAL-05), mirroring
    clean.py's established log-then-raise shape."""
    from knowledge_lake.pipeline.chunk import _assert_chunk_conservation_invariant

    with pytest.raises(RuntimeError, match="conservation invariant violated"):
        _assert_chunk_conservation_invariant(
            kept_count=1, rejected_count=1, total_generated=3, parsed_artifact_id="parsed-1"
        )


def test_chunk_conservation_invariant_passes_silently_when_balanced():
    from knowledge_lake.pipeline.chunk import _assert_chunk_conservation_invariant

    # No exception raised.
    _assert_chunk_conservation_invariant(
        kept_count=2, rejected_count=1, total_generated=3, parsed_artifact_id="parsed-1"
    )


def test_apply_substance_gate_never_violates_conservation_invariant(test_settings):
    """Regression guard: the real predicate chain, run over a mixed batch of
    passing/failing chunks, never trips the conservation invariant."""
    from knowledge_lake.pipeline.chunk import _apply_substance_gate

    out = _apply_substance_gate(
        [_raw(NAV_JUNK_TEXT), _raw(CLINICAL_PROSE_TEXT)], test_settings, None, "parsed-1"
    )
    assert isinstance(out, list)


# ── FineWebQualityFilter exact-boundary pin (datatrove==0.9.0 `<` semantics) ──


def test_fineweb_predicate_exact_line_punct_boundary_passes(test_settings):
    """A chunk whose line-punctuation ratio is EXACTLY fineweb_line_punct_thr
    (0.12 default) PASSES — datatrove's own source uses strict `<`
    ('if ratio < self.line_punct_thr'), so equality passes. Pins this against
    a future datatrove upgrade silently changing the comparison."""
    from knowledge_lake.pipeline.chunk import _build_fineweb_filter, _fineweb_predicate

    lines = [
        f"Line number {i} contains unique clinical content without any terminal marks here"
        for i in range(22)
    ]
    lines += [
        f"Line number {i + 100} contains unique clinical content and it ends properly."
        for i in range(3)
    ]
    text = "\n".join(lines)

    filter_instance = _build_fineweb_filter(test_settings.chunk_quality)
    result = _fineweb_predicate(text, {"is_table": False}, filter_instance=filter_instance)
    assert result.passed is True


def test_fineweb_predicate_nav_junk_fails_line_punct_ratio(test_settings):
    """A single-line nav-junk chunk (no terminal punctuation) fails
    FineWebQualityFilter's line_punct_ratio check directly."""
    from knowledge_lake.pipeline.chunk import _build_fineweb_filter, _fineweb_predicate

    filter_instance = _build_fineweb_filter(test_settings.chunk_quality)
    result = _fineweb_predicate(NAV_JUNK_TEXT, {"is_table": False}, filter_instance=filter_instance)
    assert result.passed is False


# ── chunk()-level end-to-end wiring tests (DB/storage fixtures) ──────────────


def test_chunk_domain_filters_param_defaults_to_none_and_is_backward_compatible(
    engine, fake_storage, test_settings
):
    """chunk()'s signature accepts domain_filters as an optional keyword-only
    param; existing callers that omit it are unaffected."""
    from knowledge_lake.pipeline.chunk import chunk

    source_id, parsed_id = _seed_source_and_parsed(engine, domain=None)
    parsed_doc = ParsedDoc(text=CLINICAL_PROSE_TEXT, sections=[], metadata={})

    results = chunk(parsed_id, source_id, parsed_doc, settings=test_settings)
    assert len(results) == 1


def test_chunk_excludes_nav_junk_in_enforce_mode(engine, fake_storage, test_settings):
    from knowledge_lake.pipeline.chunk import chunk

    source_id, parsed_id = _seed_source_and_parsed(engine, domain=None)
    parsed_doc = ParsedDoc(text=NAV_JUNK_TEXT, sections=[], metadata={})

    results = chunk(parsed_id, source_id, parsed_doc, settings=test_settings)
    assert results == []


def test_chunk_keeps_nav_junk_in_report_mode(engine, fake_storage, test_settings):
    from knowledge_lake.pipeline.chunk import chunk

    report_settings = test_settings.model_copy(deep=True)
    report_settings.chunk_quality.gate_mode = "report"

    source_id, parsed_id = _seed_source_and_parsed(engine, domain=None)
    parsed_doc = ParsedDoc(text=NAV_JUNK_TEXT, sections=[], metadata={})

    results = chunk(parsed_id, source_id, parsed_doc, settings=report_settings)
    assert len(results) == 1


def test_chunk_is_table_exempt_at_pipeline_level(engine, fake_storage, test_settings):
    from knowledge_lake.pipeline.chunk import chunk

    source_id, parsed_id = _seed_source_and_parsed(engine, domain=None)
    parsed_doc = ParsedDoc(
        text="ignored",
        sections=[
            Section(heading="", section_path="§1", page=1, text=NAV_JUNK_TEXT, is_table=True)
        ],
        metadata={},
    )

    results = chunk(parsed_id, source_id, parsed_doc, settings=test_settings)
    assert len(results) == 1


def test_chunk_domain_filters_rescue_short_clinical_code(engine, fake_storage, test_settings):
    from knowledge_lake.domains.models import DomainFilters
    from knowledge_lake.pipeline.chunk import chunk

    source_id, parsed_id = _seed_source_and_parsed(engine, domain=None)
    parsed_doc = ParsedDoc(text="ICD-10 E11.9", sections=[], metadata={})
    domain_filters = DomainFilters(normative_allowlists=["ICD-10"])

    results = chunk(
        parsed_id, source_id, parsed_doc, settings=test_settings, domain_filters=domain_filters
    )
    assert len(results) == 1


def test_chunk_repeated_calls_produce_identical_membership(engine, fake_storage, test_settings):
    """Calling chunk() twice on the identical ParsedDoc yields identical
    returned-chunk membership both times (second call takes the cache-hit
    branch, but the gate decision is unaffected)."""
    from knowledge_lake.pipeline.chunk import chunk

    source_id, parsed_id = _seed_source_and_parsed(engine, domain=None)
    parsed_doc = ParsedDoc(text=CLINICAL_PROSE_TEXT, sections=[], metadata={})

    results1 = chunk(parsed_id, source_id, parsed_doc, settings=test_settings)
    results2 = chunk(parsed_id, source_id, parsed_doc, settings=test_settings)

    assert len(results1) == len(results2) == 1
    assert results1[0]["content_hash"] == results2[0]["content_hash"]
