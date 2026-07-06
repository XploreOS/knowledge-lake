"""Unit tests for pipeline/search.py's additive domain/document_type/min_quality_score
filters (INDEX-03).

Mocks get_embedder()/get_vectorstore() at the pipeline.search module level
(mirrors tests/unit/test_builtin_plugins.py's mocking style) so no real
embedding model or Qdrant server is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

import knowledge_lake.pipeline.search as search_module


@pytest.fixture(autouse=True)
def fake_embedder(monkeypatch):
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2, 0.3, 0.4]]
    monkeypatch.setattr(search_module, "get_embedder", lambda _s: embedder)
    return embedder


@pytest.fixture()
def fake_vstore(monkeypatch):
    vstore = MagicMock()
    vstore.search.return_value = []
    monkeypatch.setattr(search_module, "get_vectorstore", lambda _s: vstore)
    return vstore


class TestSearchNoFilters:
    def test_search_no_filters_passes_none_query_filter(self, fake_vstore) -> None:
        search_module.search("q", collection="c", top_k=5)

        call_kwargs = fake_vstore.search.call_args.kwargs
        assert call_kwargs["query_filter"] is None

    def test_search_backward_compatible_no_kwargs(self, fake_vstore) -> None:
        # Exact pre-Phase-4 positional/keyword shape must still work with no TypeError.
        hits = search_module.search("q", collection="c", top_k=5)
        assert hits == []


class TestSearchDomainFilter:
    def test_search_domain_filter_builds_field_condition(self, fake_vstore) -> None:
        search_module.search("q", collection="c", top_k=5, domain="healthcare")

        query_filter = fake_vstore.search.call_args.kwargs["query_filter"]
        assert isinstance(query_filter, Filter)
        assert len(query_filter.must) == 1
        condition = query_filter.must[0]
        assert isinstance(condition, FieldCondition)
        assert condition.key == "domain"
        assert isinstance(condition.match, MatchValue)
        assert condition.match.value == "healthcare"


class TestSearchMinQualityScoreFilter:
    def test_search_min_quality_score_builds_range_condition(self, fake_vstore) -> None:
        search_module.search("q", collection="c", top_k=5, min_quality_score=0.5)

        query_filter = fake_vstore.search.call_args.kwargs["query_filter"]
        assert isinstance(query_filter, Filter)
        assert len(query_filter.must) == 1
        condition = query_filter.must[0]
        assert condition.key == "quality_score"
        assert isinstance(condition.range, Range)
        assert condition.range.gte == 0.5


class TestSearchCombinedFilters:
    def test_search_combined_filters_produce_single_filter_with_all_conditions(
        self, fake_vstore
    ) -> None:
        search_module.search(
            "q",
            collection="c",
            top_k=5,
            domain="healthcare",
            document_type="regulation",
            min_quality_score=0.7,
        )

        query_filter = fake_vstore.search.call_args.kwargs["query_filter"]
        assert isinstance(query_filter, Filter)
        assert len(query_filter.must) == 3
        keys = {c.key for c in query_filter.must}
        assert keys == {"domain", "document_type", "quality_score"}
