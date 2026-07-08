"""Unit tests for pipeline/search.py's additive domain/document_type/min_quality_score
filters (INDEX-03).

Mocks get_embedder()/get_vectorstore() at the pipeline.search module level
(mirrors tests/unit/test_builtin_plugins.py's mocking style) so no real
embedding model or Qdrant server is required.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue, Range

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


class TestSearchSourceFilters:
    """Verify search() builds correct FieldConditions for source_name, format,
    source_id, and tags filter kwargs (D-10, D-11, PAYLOAD-02).

    All tests use the fake_vstore fixture (autouse fake_embedder is active).
    """

    def test_source_name_filter_builds_field_condition(self, fake_vstore) -> None:
        """search with source_name builds a FieldCondition with MatchValue."""
        search_module.search("q", collection="c", source_name="IFM")

        query_filter = fake_vstore.search.call_args.kwargs["query_filter"]
        assert isinstance(query_filter, Filter)
        assert len(query_filter.must) == 1
        condition = query_filter.must[0]
        assert isinstance(condition, FieldCondition)
        assert condition.key == "source_name"
        assert isinstance(condition.match, MatchValue)
        assert condition.match.value == "IFM"

    def test_format_filter_builds_field_condition(self, fake_vstore) -> None:
        """search with format builds a FieldCondition with MatchValue."""
        search_module.search("q", collection="c", format="pdf")

        query_filter = fake_vstore.search.call_args.kwargs["query_filter"]
        assert isinstance(query_filter, Filter)
        assert len(query_filter.must) == 1
        condition = query_filter.must[0]
        assert condition.key == "format"
        assert isinstance(condition.match, MatchValue)
        assert condition.match.value == "pdf"

    def test_source_id_filter_builds_field_condition(self, fake_vstore) -> None:
        """search with source_id builds a FieldCondition with MatchValue."""
        search_module.search("q", collection="c", source_id="src_abc123")

        query_filter = fake_vstore.search.call_args.kwargs["query_filter"]
        assert isinstance(query_filter, Filter)
        assert len(query_filter.must) == 1
        condition = query_filter.must[0]
        assert condition.key == "source_id"
        assert isinstance(condition.match, MatchValue)
        assert condition.match.value == "src_abc123"

    def test_tags_single_tag_uses_match_value(self, fake_vstore) -> None:
        """search with a single tag uses MatchValue (D-11)."""
        search_module.search("q", collection="c", tags=["fhir"])

        query_filter = fake_vstore.search.call_args.kwargs["query_filter"]
        assert isinstance(query_filter, Filter)
        assert len(query_filter.must) == 1
        condition = query_filter.must[0]
        assert condition.key == "tags"
        assert isinstance(condition.match, MatchValue)
        assert condition.match.value == "fhir"

    def test_tags_multiple_tags_uses_match_any(self, fake_vstore) -> None:
        """search with multiple tags uses MatchAny (D-11)."""
        search_module.search("q", collection="c", tags=["fhir", "hl7"])

        query_filter = fake_vstore.search.call_args.kwargs["query_filter"]
        assert isinstance(query_filter, Filter)
        assert len(query_filter.must) == 1
        condition = query_filter.must[0]
        assert condition.key == "tags"
        assert isinstance(condition.match, MatchAny)
        assert set(condition.match.any) == {"fhir", "hl7"}

    def test_search_all_new_filters_combined(self, fake_vstore) -> None:
        """search with all 4 new filter kwargs produces 4 must conditions."""
        search_module.search(
            "q",
            collection="c",
            source_name="X",
            format="html",
            source_id="src_1",
            tags=["a", "b"],
        )

        query_filter = fake_vstore.search.call_args.kwargs["query_filter"]
        assert isinstance(query_filter, Filter)
        assert len(query_filter.must) == 4
        keys = {condition.key for condition in query_filter.must}
        assert keys == {"source_name", "format", "source_id", "tags"}

    def test_backward_compatible_no_new_kwargs(self, fake_vstore) -> None:
        """search without any new kwargs produces no query_filter (D-13 backward compat)."""
        search_module.search("q", collection="c")

        call_kwargs = fake_vstore.search.call_args.kwargs
        assert call_kwargs["query_filter"] is None
