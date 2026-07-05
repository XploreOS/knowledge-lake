"""Tests for parser fallback chain (PARSE-02, D-01, D-02).

Verifies that parse_with_fallback() correctly:
  - Stops on first success (D-02)
  - Falls back on exception (D-01)
  - Falls back on quality gate failure (D-01)
  - Raises ValueError when all parsers exhausted
  - Skips unavailable parsers gracefully (Pitfall 5)
"""

from __future__ import annotations

import json
from importlib.metadata import entry_points as real_entry_points
from unittest.mock import MagicMock, patch

import pytest

from knowledge_lake.config.settings import Settings
from knowledge_lake.plugins.protocols import ParsedDoc, Section
from knowledge_lake.plugins.resolver import parse_with_fallback


def _make_settings(
    chain: list[str],
    quality_threshold: float = 0.4,
) -> Settings:
    """Build a minimal Settings instance with the given parse chain."""
    return Settings(
        _env_file=None,
        parse={
            "chain": chain,
            "quality_threshold": quality_threshold,
            "quality_gray_zone": [0.3, 0.6],
            "llm_spot_check": False,  # Disable LLM calls in unit tests
            "max_file_bytes": 104857600,
        },
    )


def _good_parseddoc() -> ParsedDoc:
    """Return a ParsedDoc that scores well above the 0.4 threshold."""
    return ParsedDoc(
        text="x" * 500,
        sections=[Section("Heading", "§1", 1, "section text content here with enough words")],
        metadata={},
    )


def _empty_parseddoc() -> ParsedDoc:
    """Return a ParsedDoc that scores 0.0 (triggers quality gate fallback)."""
    return ParsedDoc(text="", sections=[], metadata={})


def _make_mock_parser(
    *,
    can_parse_result: bool = True,
    parse_result: ParsedDoc | None = None,
    parse_raises: Exception | None = None,
) -> MagicMock:
    """Build a mock parser plugin."""
    mock = MagicMock()
    mock.can_parse.return_value = can_parse_result
    if parse_raises is not None:
        mock.parse.side_effect = parse_raises
    else:
        mock.parse.return_value = parse_result or _good_parseddoc()
    return mock


class _FakeEP:
    """Minimal entry-point stand-in with .name and .load() for parse_with_fallback."""

    def __init__(self, name: str, factory):
        self.name = name
        self._factory = factory

    def load(self):
        return self._factory


def _make_entry_points_mock(ep_map: dict):
    """Return a side_effect callable for patching knowledge_lake.plugins.resolver.entry_points.

    *ep_map* maps entry-point name -> mock parser instance.  For each name a
    factory wrapper is created so that .load()() returns the mock regardless of
    whether the caller passes constructor kwargs (e.g. tika_server_url=...).
    Only the 'knowledge_lake.parsers' group is intercepted; all other groups
    are forwarded to the real entry_points().
    """
    fake_eps = []
    for name, mock_instance in ep_map.items():
        def _make_factory(inst):
            def _factory(**kwargs):
                return inst
            return _factory
        fake_eps.append(_FakeEP(name, _make_factory(mock_instance)))

    def _mock_entry_points(group):
        if group != "knowledge_lake.parsers":
            return real_entry_points(group=group)
        return fake_eps

    return _mock_entry_points


def test_fallback_stops_on_first_success() -> None:
    """Chain stops at first parser that succeeds (D-02)."""
    settings = _make_settings(chain=["a", "b"])
    mock_a = _make_mock_parser(parse_raises=RuntimeError("parser a failed"))
    mock_b = _make_mock_parser(parse_result=_good_parseddoc())

    raw = json.dumps({"key": "value"}).encode()
    with patch(
        "knowledge_lake.plugins.resolver.entry_points",
        side_effect=_make_entry_points_mock({"a": mock_a, "b": mock_b}),
    ):
        parsed_doc, parser_name, quality_score = parse_with_fallback(
            raw, "application/json", settings=settings
        )

    assert parser_name == "b"
    assert quality_score >= 0.0
    mock_a.parse.assert_called_once()
    mock_b.parse.assert_called_once()


def test_fallback_on_low_quality() -> None:
    """Chain falls back when parser returns a quality score below threshold (D-01)."""
    settings = _make_settings(chain=["a", "b"], quality_threshold=0.4)
    mock_a = _make_mock_parser(parse_result=_empty_parseddoc())  # scores 0.0
    mock_b = _make_mock_parser(parse_result=_good_parseddoc())   # scores high

    raw = b"any bytes"
    with patch(
        "knowledge_lake.plugins.resolver.entry_points",
        side_effect=_make_entry_points_mock({"a": mock_a, "b": mock_b}),
    ):
        _, parser_name, quality_score = parse_with_fallback(
            raw, "application/json", settings=settings
        )

    assert parser_name == "b"
    assert quality_score >= settings.parse.quality_threshold


def test_all_parsers_exhausted_raises() -> None:
    """ValueError is raised when every parser in the chain fails (PARSE-02)."""
    settings = _make_settings(chain=["a"])
    mock_a = _make_mock_parser(parse_raises=RuntimeError("always fails"))

    with patch(
        "knowledge_lake.plugins.resolver.entry_points",
        side_effect=_make_entry_points_mock({"a": mock_a}),
    ):
        with pytest.raises(ValueError, match="exhausted"):
            parse_with_fallback(b"data", "application/json", settings=settings)


def test_unavailable_parser_skipped() -> None:
    """LookupError for a missing parser is caught and chain continues (Pitfall 5)."""
    settings = _make_settings(chain=["missing", "b"])
    mock_b = _make_mock_parser(parse_result=_good_parseddoc())

    # "missing" is intentionally absent from ep_map so entry-point lookup
    # raises LookupError (the for/else in parse_with_fallback fires) and
    # parse_with_fallback continues to "b".
    raw = json.dumps({"key": "val"}).encode()
    with patch(
        "knowledge_lake.plugins.resolver.entry_points",
        side_effect=_make_entry_points_mock({"b": mock_b}),
    ):
        _, parser_name, _ = parse_with_fallback(
            raw, "application/json", settings=settings
        )

    assert parser_name == "b"
