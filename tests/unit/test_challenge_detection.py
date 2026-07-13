"""Tests for deterministic challenge-page detection in the parse gate (Finding 3).

Two layers:
  1. Unit tests for is_challenge_page() across known challenge snippets (reason)
     and ordinary healthcare prose (None).
  2. Integration tests mirroring test_fallback_chain.py: parse_with_fallback must
     REJECT a challenge page (raise ValueError) even when its heuristic quality
     score would otherwise pass — reproducing the 0.867-PASSED case — and must
     still return success for a normal high-quality parse.
"""

from __future__ import annotations

from importlib.metadata import entry_points as real_entry_points
from unittest.mock import MagicMock, patch

import pytest

from knowledge_lake.config.settings import Settings
from knowledge_lake.plugins.protocols import ParsedDoc, Section
from knowledge_lake.plugins.resolver import parse_with_fallback
from knowledge_lake.quality.challenge import is_challenge_page


# ── Layer 1: is_challenge_page unit tests ─────────────────────────────────────

CHALLENGE_SNIPPETS = [
    "Just a moment...\nPlease wait while we verify your request.",
    "Checking your browser before accessing example.com.",
    "Please confirm you are human by completing the action below.",
    "Verify you are not a bot to continue.",
    "Please complete the security check before continuing.",
    "Please enable JavaScript and cookies to continue.",
    "Attention Required! | Cloudflare",
    "Error: Incapsula incident ID: 1234-567890",
    "Access Denied You don't have permission. Reference #18.abcd",
]

NORMAL_TEXT = (
    "The HIPAA Security Rule requires covered entities to implement administrative, "
    "physical, and technical safeguards to protect electronic protected health "
    "information (ePHI). Risk analysis is a foundational requirement."
)


@pytest.mark.parametrize("snippet", CHALLENGE_SNIPPETS)
def test_is_challenge_page_flags_known_markers(snippet: str) -> None:
    reason = is_challenge_page(snippet)
    assert reason is not None, f"expected a challenge reason for: {snippet!r}"
    assert isinstance(reason, str) and reason


def test_is_challenge_page_passes_normal_text() -> None:
    assert is_challenge_page(NORMAL_TEXT) is None


def test_is_challenge_page_empty_text_is_none() -> None:
    assert is_challenge_page("") is None


# ── Layer 2: parse_with_fallback integration (mirrors test_fallback_chain.py) ──


def _make_settings(chain: list[str], quality_threshold: float = 0.4) -> Settings:
    return Settings(
        _env_file=None,
        parse={
            "chain": chain,
            "quality_threshold": quality_threshold,
            "quality_gray_zone": [0.3, 0.6],
            "llm_spot_check": False,
            "max_file_bytes": 104857600,
        },
    )


def _good_parseddoc() -> ParsedDoc:
    return ParsedDoc(
        text="x" * 500,
        sections=[Section("Heading", "§1", 1, "section text content here with enough words")],
        metadata={},
    )


def _challenge_parseddoc() -> ParsedDoc:
    text = (
        "Just a moment...\n"
        "Checking your browser before accessing the site. "
        "Please enable JavaScript and cookies to continue. " + ("filler text " * 40)
    )
    return ParsedDoc(
        text=text,
        sections=[Section("Attention Required", "§1", 1, text)],
        metadata={},
    )


def _make_mock_parser(parse_result: ParsedDoc) -> MagicMock:
    mock = MagicMock()
    mock.can_parse.return_value = True
    mock.parse.return_value = parse_result
    return mock


class _FakeEP:
    def __init__(self, name: str, factory):
        self.name = name
        self._factory = factory

    def load(self):
        return self._factory


def _make_entry_points_mock(ep_map: dict):
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


def test_challenge_page_rejected_even_at_high_score() -> None:
    """A challenge page is rejected (ValueError) even when the heuristic score
    would pass (0.867) — the gate fires BEFORE scoring so the page never indexes."""
    settings = _make_settings(chain=["a"])
    mock_a = _make_mock_parser(_challenge_parseddoc())

    with patch(
        "knowledge_lake.plugins.resolver.entry_points",
        side_effect=_make_entry_points_mock({"a": mock_a}),
    ):
        # Force a passing score to prove rejection is score-independent.
        with patch(
            "knowledge_lake.quality.scorer.compute_quality_score", return_value=0.867
        ):
            with pytest.raises(ValueError, match="anti-bot/challenge page"):
                parse_with_fallback(b"data", "text/html", settings=settings)


def test_normal_page_still_succeeds() -> None:
    """A normal high-quality parse is unaffected by the challenge gate."""
    settings = _make_settings(chain=["a"], quality_threshold=0.4)
    mock_a = _make_mock_parser(_good_parseddoc())

    with patch(
        "knowledge_lake.plugins.resolver.entry_points",
        side_effect=_make_entry_points_mock({"a": mock_a}),
    ):
        parsed_doc, parser_name, score = parse_with_fallback(
            b"data", "text/html", settings=settings
        )

    assert parser_name == "a"
    assert score >= settings.parse.quality_threshold
    assert is_challenge_page(parsed_doc.text) is None
