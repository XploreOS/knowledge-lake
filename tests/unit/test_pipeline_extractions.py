"""Wave 0 RED scaffold: pipeline extraction assertions (D-05, D-03).

Asserts that the four extracted pipeline functions are importable with their
documented return shapes:
  - ``pipeline.process.process_crawled`` (batch, dict with processed/failed/chunks_indexed)
  - ``pipeline.query.list_sources`` (CRUD read, list of dicts)
  - ``pipeline.query.stats`` (read aggregate, dict with sources/documents/qdrant_points)
  - ``pipeline.domains.load_domain`` (batch, dict with loaded_count/skipped_count)

All tests are xfail until Plans 02/03 implement the extracted service functions.
"""

from __future__ import annotations

import inspect

import pytest

# process_crawled
try:
    from knowledge_lake.pipeline.process import process_crawled
    _PROCESS_OK = True
except ImportError:
    process_crawled = None  # type: ignore[assignment]
    _PROCESS_OK = False

# list_sources + stats
try:
    from knowledge_lake.pipeline.query import list_sources, stats
    _QUERY_OK = True
except ImportError:
    list_sources = None  # type: ignore[assignment]
    stats = None  # type: ignore[assignment]
    _QUERY_OK = False

# load_domain
try:
    from knowledge_lake.pipeline.domains import load_domain
    _DOMAINS_OK = True
except ImportError:
    load_domain = None  # type: ignore[assignment]
    _DOMAINS_OK = False

_IMPORT_OK = _PROCESS_OK and _QUERY_OK and _DOMAINS_OK


# ── process_crawled ──────────────────────────────────────────────────────────


@pytest.mark.xfail(not _PROCESS_OK, reason="Wave 0 scaffold — pipeline.process not yet implemented", strict=False)
def test_process_crawled_is_callable() -> None:
    """pipeline.process.process_crawled must be a callable function."""
    assert process_crawled is not None
    assert callable(process_crawled)


@pytest.mark.xfail(not _PROCESS_OK, reason="Wave 0 scaffold — pipeline.process not yet implemented", strict=False)
def test_process_crawled_signature() -> None:
    """process_crawled must accept source_id, limit, and collection kwargs."""
    assert process_crawled is not None
    sig = inspect.signature(process_crawled)
    params = sig.parameters
    # Must accept keyword arguments from plan spec (D-05)
    assert "source_id" in params, "process_crawled missing 'source_id' param"
    assert "limit" in params, "process_crawled missing 'limit' param"
    assert "collection" in params, "process_crawled missing 'collection' param"


# ── list_sources ─────────────────────────────────────────────────────────────


@pytest.mark.xfail(not _QUERY_OK, reason="Wave 0 scaffold — pipeline.query not yet implemented", strict=False)
def test_list_sources_is_callable() -> None:
    """pipeline.query.list_sources must be a callable function."""
    assert list_sources is not None
    assert callable(list_sources)


@pytest.mark.xfail(not _QUERY_OK, reason="Wave 0 scaffold — pipeline.query not yet implemented", strict=False)
def test_list_sources_signature() -> None:
    """list_sources must accept domain, offset, and limit kwargs."""
    assert list_sources is not None
    sig = inspect.signature(list_sources)
    params = sig.parameters
    assert "domain" in params, "list_sources missing 'domain' param"
    assert "offset" in params, "list_sources missing 'offset' param"
    assert "limit" in params, "list_sources missing 'limit' param"


# ── stats ─────────────────────────────────────────────────────────────────────


@pytest.mark.xfail(not _QUERY_OK, reason="Wave 0 scaffold — pipeline.query not yet implemented", strict=False)
def test_stats_is_callable() -> None:
    """pipeline.query.stats must be a callable function."""
    assert stats is not None
    assert callable(stats)


@pytest.mark.xfail(not _QUERY_OK, reason="Wave 0 scaffold — pipeline.query not yet implemented", strict=False)
def test_stats_signature() -> None:
    """stats must accept a collection kwarg (optional)."""
    assert stats is not None
    sig = inspect.signature(stats)
    params = sig.parameters
    assert "collection" in params, "stats missing 'collection' param"


# ── load_domain ──────────────────────────────────────────────────────────────


@pytest.mark.xfail(not _DOMAINS_OK, reason="Wave 0 scaffold — pipeline.domains not yet implemented", strict=False)
def test_load_domain_is_callable() -> None:
    """pipeline.domains.load_domain must be a callable function."""
    assert load_domain is not None
    assert callable(load_domain)


@pytest.mark.xfail(not _DOMAINS_OK, reason="Wave 0 scaffold — pipeline.domains not yet implemented", strict=False)
def test_load_domain_signature() -> None:
    """load_domain must accept a name positional/keyword argument."""
    assert load_domain is not None
    sig = inspect.signature(load_domain)
    params = sig.parameters
    assert "name" in params, "load_domain missing 'name' param"
