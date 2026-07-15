"""Wave 0 RED scaffold: input model schema assertions (D-02, SKILL-03).

Asserts that extended ``SearchParams`` and new input models (StatsInput,
ProcessCrawledInput, ListSourcesInput, LineageInput, IngestUrlInput, CrawlAllInput)
are importable with fields that map to the target pipeline function kwargs.

All tests are xfail until Plan 02 creates the input models in ``api/schemas.py``.
"""

from __future__ import annotations

import pytest

# Extended SearchParams (D-02: additional filter fields added)
try:
    from knowledge_lake.api.schemas import SearchParams
    _SEARCH_OK = True
except ImportError:
    SearchParams = None  # type: ignore[assignment]
    _SEARCH_OK = False

# New input models (Plan 02 adds these)
try:
    from knowledge_lake.api.schemas import (
        StatsInput,
        ProcessCrawledInput,
        ListSourcesInput,
        LineageInput,
        IngestUrlInput,
        CrawlAllInput,
    )
    _MODELS_OK = True
except ImportError:
    StatsInput = None  # type: ignore[assignment]
    ProcessCrawledInput = None  # type: ignore[assignment]
    ListSourcesInput = None  # type: ignore[assignment]
    LineageInput = None  # type: ignore[assignment]
    IngestUrlInput = None  # type: ignore[assignment]
    CrawlAllInput = None  # type: ignore[assignment]
    _MODELS_OK = False

_IMPORT_OK = _SEARCH_OK and _MODELS_OK


# ── SearchParams extensions ──────────────────────────────────────────────────


def test_search_params_has_filter_fields() -> None:
    """Extended SearchParams must include domain, document_type, min_quality_score, source_name, format, tags, source_id (Pitfall 4)."""
    assert SearchParams is not None
    fields = SearchParams.model_fields
    expected_extra_fields = [
        "domain",
        "document_type",
        "min_quality_score",
        "source_name",
        "format",
        "tags",
        "source_id",
    ]
    missing = [f for f in expected_extra_fields if f not in fields]
    assert not missing, (
        f"SearchParams missing filter fields: {missing}. "
        "These must be added to match search() kwargs (Pitfall 4)."
    )


@pytest.mark.xfail(not _SEARCH_OK, reason="Wave 0 scaffold — SearchParams not importable", strict=False)
def test_search_params_existing_fields_preserved() -> None:
    """Extended SearchParams must still have the original q, top_k, collection, mode fields."""
    assert SearchParams is not None
    fields = SearchParams.model_fields
    for field in ("q", "top_k", "collection", "mode"):
        assert field in fields, f"SearchParams lost original field {field!r}"


# ── StatsInput ────────────────────────────────────────────────────────────────


@pytest.mark.xfail(not _MODELS_OK, reason="Wave 0 scaffold — input models not yet added (Plan 02)", strict=False)
def test_stats_input_importable() -> None:
    """StatsInput must be importable from api.schemas."""
    assert StatsInput is not None
    assert hasattr(StatsInput, "model_json_schema")


@pytest.mark.xfail(not _MODELS_OK, reason="Wave 0 scaffold — input models not yet added (Plan 02)", strict=False)
def test_stats_input_has_collection_field() -> None:
    """StatsInput must have an optional 'collection' field mapping to stats(collection=...)."""
    assert StatsInput is not None
    assert "collection" in StatsInput.model_fields, "StatsInput missing 'collection' field"


# ── ProcessCrawledInput ──────────────────────────────────────────────────────


@pytest.mark.xfail(not _MODELS_OK, reason="Wave 0 scaffold — input models not yet added (Plan 02)", strict=False)
def test_process_crawled_input_fields() -> None:
    """ProcessCrawledInput must have source_id, limit, collection fields."""
    assert ProcessCrawledInput is not None
    fields = ProcessCrawledInput.model_fields
    for f in ("source_id", "limit", "collection"):
        assert f in fields, f"ProcessCrawledInput missing field {f!r}"


# ── ListSourcesInput ─────────────────────────────────────────────────────────


@pytest.mark.xfail(not _MODELS_OK, reason="Wave 0 scaffold — input models not yet added (Plan 02)", strict=False)
def test_list_sources_input_fields() -> None:
    """ListSourcesInput must have domain, offset, limit fields."""
    assert ListSourcesInput is not None
    fields = ListSourcesInput.model_fields
    for f in ("domain", "offset", "limit"):
        assert f in fields, f"ListSourcesInput missing field {f!r}"


# ── LineageInput ──────────────────────────────────────────────────────────────


@pytest.mark.xfail(not _MODELS_OK, reason="Wave 0 scaffold — input models not yet added (Plan 02)", strict=False)
def test_lineage_input_has_artifact_id() -> None:
    """LineageInput must have an artifact_id field."""
    assert LineageInput is not None
    assert "artifact_id" in LineageInput.model_fields, "LineageInput missing 'artifact_id' field"


# ── IngestUrlInput ────────────────────────────────────────────────────────────


@pytest.mark.xfail(not _MODELS_OK, reason="Wave 0 scaffold — input models not yet added (Plan 02)", strict=False)
def test_ingest_url_input_has_url_and_source_name() -> None:
    """IngestUrlInput must have url and source_name fields (maps to ingest_url(url, source_name)).

    Rule 1 fix: original scaffold used 'source_id' but ingest_url() takes 'source_name'
    as the human-readable name for the source registry entry.  'source_id' is an
    output of ingest_url(), not an input.
    """
    assert IngestUrlInput is not None
    fields = IngestUrlInput.model_fields
    assert "url" in fields, "IngestUrlInput missing 'url' field"
    assert "source_name" in fields, "IngestUrlInput missing 'source_name' field"


# ── CrawlAllInput ─────────────────────────────────────────────────────────────


@pytest.mark.xfail(not _MODELS_OK, reason="Wave 0 scaffold — input models not yet added (Plan 02)", strict=False)
def test_crawl_all_input_has_domain_field() -> None:
    """CrawlAllInput must have an optional 'domain' field."""
    assert CrawlAllInput is not None
    assert "domain" in CrawlAllInput.model_fields, "CrawlAllInput missing 'domain' field"


# ── Schema parity sanity ──────────────────────────────────────────────────────


@pytest.mark.xfail(not _MODELS_OK, reason="Wave 0 scaffold — input models not yet added (Plan 02)", strict=False)
def test_all_input_models_have_json_schema() -> None:
    """All input models must produce a valid model_json_schema()."""
    models = [StatsInput, ProcessCrawledInput, ListSourcesInput, LineageInput, IngestUrlInput, CrawlAllInput]
    assert all(m is not None for m in models)
    for model in models:
        schema = model.model_json_schema()  # type: ignore[union-attr]
        assert isinstance(schema, dict), f"{model.__name__} schema is not a dict"
        assert "type" in schema or "properties" in schema, (
            f"{model.__name__} schema missing 'type' or 'properties'"
        )
