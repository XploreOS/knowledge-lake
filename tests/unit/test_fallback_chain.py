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


def test_fallback_stops_on_first_success() -> None:
    """Chain stops at first parser that succeeds (D-02)."""
    settings = _make_settings(chain=["a", "b"])
    mock_a = _make_mock_parser(parse_raises=RuntimeError("parser a failed"))
    mock_b = _make_mock_parser(parse_result=_good_parseddoc())

    def _side_resolve(group: str, name: str) -> MagicMock:
        if name == "a":
            return mock_a
        if name == "b":
            return mock_b
        raise LookupError(name)

    raw = json.dumps({"key": "value"}).encode()
    with patch("knowledge_lake.plugins.resolver.resolve", side_effect=_side_resolve):
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

    def _side_resolve(group: str, name: str) -> MagicMock:
        if name == "a":
            return mock_a
        if name == "b":
            return mock_b
        raise LookupError(name)

    raw = b"any bytes"
    with patch("knowledge_lake.plugins.resolver.resolve", side_effect=_side_resolve):
        _, parser_name, quality_score = parse_with_fallback(
            raw, "application/json", settings=settings
        )

    assert parser_name == "b"
    assert quality_score >= settings.parse.quality_threshold


def test_all_parsers_exhausted_raises() -> None:
    """ValueError is raised when every parser in the chain fails (PARSE-02)."""
    settings = _make_settings(chain=["a"])
    mock_a = _make_mock_parser(parse_raises=RuntimeError("always fails"))

    def _side_resolve(group: str, name: str) -> MagicMock:
        if name == "a":
            return mock_a
        raise LookupError(name)

    with patch("knowledge_lake.plugins.resolver.resolve", side_effect=_side_resolve):
        with pytest.raises(ValueError, match="exhausted"):
            parse_with_fallback(b"data", "application/json", settings=settings)


def test_unavailable_parser_skipped() -> None:
    """LookupError for a missing parser is caught and chain continues (Pitfall 5)."""
    settings = _make_settings(chain=["missing", "b"])
    mock_b = _make_mock_parser(parse_result=_good_parseddoc())

    def _side_resolve(group: str, name: str) -> MagicMock:
        if name == "missing":
            raise LookupError("missing parser not installed")
        if name == "b":
            return mock_b
        raise LookupError(name)

    raw = json.dumps({"key": "val"}).encode()
    with patch("knowledge_lake.plugins.resolver.resolve", side_effect=_side_resolve):
        _, parser_name, _ = parse_with_fallback(
            raw, "application/json", settings=settings
        )

    assert parser_name == "b"
