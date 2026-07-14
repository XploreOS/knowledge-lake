"""Unit tests for pipeline/route.py — query router dispatch (ROUTE-01..03, D-01..D-06).

Wave 0 scaffold: knowledge_lake.pipeline.route does not exist until Plan 15-01
Task 3 ships it. The resulting ImportError at collection time is the expected
Wave 0 RED state (mirrors test_tree_search.py's Wave 0 scaffold from Phase 14).

search() and tree_search() are mocked at module-level patch targets:
  knowledge_lake.pipeline.route.search
  knowledge_lake.pipeline.route.tree_search

so no real embedder, Qdrant server, or tree index is contacted.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

import knowledge_lake.pipeline.route as route_module
from knowledge_lake.pipeline.route import classify_route, routed_search


# ── Classifier tests (ROUTE-02, ROUTE-03, D-04) ───────────────────────────────


@pytest.mark.parametrize("query,expected_category", [
    # section_page_ref triggers
    ("show me section 3 of the document", "section_page_ref"),
    ("go to page 5 of the report", "section_page_ref"),
    ("open chapter 2 findings", "section_page_ref"),
    ("explain paragraph in § 4.1", "section_page_ref"),
    # comparison_multihop triggers
    ("compare treatment A with treatment B", "comparison_multihop"),
    ("what is the difference between HIPAA and HITECH", "comparison_multihop"),
    ("HIPAA vs HITECH", "comparison_multihop"),
    ("how does aspirin affect platelet aggregation", "comparison_multihop"),
    # structural_breadth triggers
    ("give me an outline of the document", "structural_breadth"),
    ("show the table of contents", "structural_breadth"),
    ("list all sections of the report", "structural_breadth"),
    ("summarize the entire document", "structural_breadth"),
    ("summarize all chapters", "structural_breadth"),
])
def test_classify_tree_categories(query: str, expected_category: str) -> None:
    """classify_route returns ('tree', category) for each D-04 trigger category."""
    route_result, category = classify_route(query)
    assert route_result == "tree", (
        f"Expected route='tree' for {query!r}, got {route_result!r}"
    )
    assert category == expected_category, (
        f"Expected category={expected_category!r} for {query!r}, got {category!r}"
    )


@pytest.mark.parametrize("query", [
    "what is diabetes",
    "treatment options for hypertension",
    "explain insulin resistance",
    "benefits of exercise",
])
def test_classify_no_match(query: str) -> None:
    """classify_route returns ('chunk', 'no_match') for queries with no structural signal."""
    route_result, category = classify_route(query)
    assert route_result == "chunk", (
        f"Expected route='chunk' for {query!r}, got {route_result!r}"
    )
    assert category == "no_match", (
        f"Expected category='no_match' for {query!r}, got {category!r}"
    )


# ── Alias equivalence (D-01) ──────────────────────────────────────────────────


def test_alias_equivalence() -> None:
    """route='tree' and route='two_stage' dispatch identically to tree_search (D-01)."""
    mock_tree = MagicMock(return_value=[MagicMock()])
    mock_search = MagicMock(return_value=[])

    with (
        patch.object(route_module, "tree_search", mock_tree),
        patch.object(route_module, "search", mock_search),
    ):
        routed_search("test query", route="tree")
        routed_search("test query", route="two_stage")

    assert mock_tree.call_count == 2, (
        f"tree_search should be called twice (once per alias), got {mock_tree.call_count}"
    )
    # Both calls should have same args (query + same kwargs)
    calls = mock_tree.call_args_list
    assert calls[0].args == calls[1].args, "route='tree' and 'two_stage' must call tree_search with same args"
    assert calls[0].kwargs == calls[1].kwargs, "route='tree' and 'two_stage' must call tree_search with same kwargs"
    mock_search.assert_not_called()


# ── Settings precedence (ROUTE-01, D-07) ──────────────────────────────────────


def test_settings_precedence_none_uses_default() -> None:
    """route=None resolves to settings.router.default_route (ROUTE-01, D-07)."""
    mock_search = MagicMock(return_value=[])
    mock_tree = MagicMock(return_value=[])

    # Settings with default_route="chunk"
    mock_settings = MagicMock()
    mock_settings.router.default_route = "chunk"

    with (
        patch.object(route_module, "search", mock_search),
        patch.object(route_module, "tree_search", mock_tree),
    ):
        routed_search("what is diabetes", route=None, settings=mock_settings)

    mock_search.assert_called_once()
    mock_tree.assert_not_called()


def test_settings_precedence_explicit_overrides() -> None:
    """Explicit route overrides settings.router.default_route."""
    mock_search = MagicMock(return_value=[])
    mock_tree = MagicMock(return_value=[MagicMock()])

    # Settings say "chunk" but explicit route="tree" should win
    mock_settings = MagicMock()
    mock_settings.router.default_route = "chunk"

    with (
        patch.object(route_module, "search", mock_search),
        patch.object(route_module, "tree_search", mock_tree),
    ):
        routed_search("what is diabetes", route="tree", settings=mock_settings)

    mock_tree.assert_called_once()
    mock_search.assert_not_called()


# ── Fallback semantics (D-05) ─────────────────────────────────────────────────


def test_fallback_auto_tree_empty() -> None:
    """Auto classifies to tree, tree_search returns [], fallback to search (D-05)."""
    mock_tree = MagicMock(return_value=[])
    mock_search = MagicMock(return_value=[MagicMock()])

    mock_settings = MagicMock()
    mock_settings.router.default_route = "auto"

    with (
        patch.object(route_module, "tree_search", mock_tree),
        patch.object(route_module, "search", mock_search),
    ):
        result = routed_search("section 3 of the document", route=None, settings=mock_settings)

    mock_tree.assert_called_once()
    mock_search.assert_called_once()
    assert len(result) > 0, "Expected non-empty result after fallback to search"


def test_fallback_auto_both_empty() -> None:
    """Auto tree returns [], chunk also returns [] — result is [] (no exception, D-05)."""
    mock_tree = MagicMock(return_value=[])
    mock_search = MagicMock(return_value=[])

    mock_settings = MagicMock()
    mock_settings.router.default_route = "auto"

    with (
        patch.object(route_module, "tree_search", mock_tree),
        patch.object(route_module, "search", mock_search),
    ):
        result = routed_search("section 3 of the document", route=None, settings=mock_settings)

    assert result == [], f"Expected [] when both tree and chunk return empty, got {result}"
    mock_tree.assert_called_once()
    mock_search.assert_called_once()


def test_no_fallback_explicit_tree() -> None:
    """Explicit route='tree', tree_search returns [] — search is NOT called (D-05)."""
    mock_tree = MagicMock(return_value=[])
    mock_search = MagicMock(return_value=[MagicMock()])

    mock_settings = MagicMock()
    mock_settings.router.default_route = "tree"

    with (
        patch.object(route_module, "tree_search", mock_tree),
        patch.object(route_module, "search", mock_search),
    ):
        result = routed_search("test query", route="tree", settings=mock_settings)

    mock_tree.assert_called_once()
    mock_search.assert_not_called()
    assert result == [], "Expected [] when explicit tree returns empty (no fallback)"


# ── Structlog emission (D-06) ─────────────────────────────────────────────────


def test_log_emission_chunk_dispatch() -> None:
    """routed_search emits one structlog event per call with route, trigger, fallback keys."""
    mock_search = MagicMock(return_value=[])
    mock_settings = MagicMock()
    mock_settings.router.default_route = "chunk"

    log_events: list[dict] = []

    def capture_log(**kwargs):
        log_events.append(kwargs)

    with (
        patch.object(route_module, "search", mock_search),
        patch.object(route_module, "log") as mock_log,
    ):
        mock_log.info.side_effect = lambda event, **kw: log_events.append({"event": event, **kw})
        routed_search("what is diabetes", route=None, settings=mock_settings)

    dispatch_events = [e for e in log_events if e.get("event") == "route.dispatch"]
    assert len(dispatch_events) == 1, (
        f"Expected exactly 1 'route.dispatch' log event, got {len(dispatch_events)}: {dispatch_events}"
    )
    ev = dispatch_events[0]
    assert "route" in ev, f"Log event missing 'route' key: {ev}"
    assert "trigger" in ev, f"Log event missing 'trigger' key: {ev}"
    assert "fallback" in ev, f"Log event missing 'fallback' key: {ev}"


def test_log_emission_tree_dispatch() -> None:
    """routed_search emits structlog event with route='tree' and trigger='operator_override'."""
    mock_tree = MagicMock(return_value=[MagicMock()])
    mock_settings = MagicMock()
    mock_settings.router.default_route = "auto"

    log_events: list[dict] = []

    with (
        patch.object(route_module, "tree_search", mock_tree),
        patch.object(route_module, "log") as mock_log,
    ):
        mock_log.info.side_effect = lambda event, **kw: log_events.append({"event": event, **kw})
        routed_search("test query", route="tree", settings=mock_settings)

    dispatch_events = [e for e in log_events if e.get("event") == "route.dispatch"]
    assert len(dispatch_events) == 1
    ev = dispatch_events[0]
    assert ev["route"] == "tree", f"Expected route='tree', got {ev['route']!r}"
    assert ev["trigger"] == "operator_override", f"Expected trigger='operator_override', got {ev['trigger']!r}"
    assert ev["fallback"] is False, f"Expected fallback=False, got {ev['fallback']!r}"
