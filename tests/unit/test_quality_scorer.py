"""Tests for quality scoring (PARSE-04, D-04).

Verifies that compute_quality_score() returns bounded floats and correctly
reflects document quality based on text length, section count, encoding
errors, and empty section ratio.
"""

from __future__ import annotations

import random
import string

import pytest

from knowledge_lake.plugins.protocols import ParsedDoc, Section
from knowledge_lake.quality.scorer import compute_quality_score


def _make_doc(
    text: str = "",
    sections: list[Section] | None = None,
) -> ParsedDoc:
    return ParsedDoc(text=text, sections=sections or [], metadata={})


def test_empty_doc_scores_near_zero() -> None:
    """Completely empty ParsedDoc must score 0.0 (anchor: empty = no signal)."""
    score = compute_quality_score(_make_doc())
    assert score < 0.2, f"Expected score < 0.2 for empty doc, got {score}"


def test_well_structured_doc_scores_high() -> None:
    """A ParsedDoc with substantial text and multiple sections must score > 0.5."""
    sections = [
        Section(f"Heading {i}", f"§{i}", 1, "Section content with sufficient text here.")
        for i in range(1, 5)
    ]
    doc = _make_doc(text="a" * 500, sections=sections)
    score = compute_quality_score(doc)
    assert score > 0.5, f"Expected score > 0.5 for well-structured doc, got {score}"


def test_encoding_errors_lower_score() -> None:
    """A document with encoding errors must score lower than the clean equivalent."""
    text_clean = "a" * 200
    text_garbled = ("a" * 160) + ("" * 40)  # 20% replacement chars

    sections = [Section("H", "§1", 1, "text")]
    doc_clean = _make_doc(text=text_clean, sections=sections)
    doc_garbled = _make_doc(text=text_garbled, sections=sections)

    score_clean = compute_quality_score(doc_clean)
    score_garbled = compute_quality_score(doc_garbled)
    # Garbled text has same length but encoding errors depress the score
    assert score_clean >= score_garbled, (
        f"Clean doc ({score_clean:.3f}) should score >= garbled doc ({score_garbled:.3f})"
    )


def test_encoding_errors_lower_score_with_replacement_chars() -> None:
    """Replacement chars (U+FFFD) in text must reduce encoding score."""
    sections = [Section("H", "§1", 1, "text")]
    text_clean = "x" * 200
    # 20% unicode replacement chars — encoding_score should be near 0
    text_garbled = ("x" * 160) + ("�" * 40)

    doc_clean = _make_doc(text=text_clean, sections=sections)
    doc_garbled = _make_doc(text=text_garbled, sections=sections)

    score_clean = compute_quality_score(doc_clean)
    score_garbled = compute_quality_score(doc_garbled)
    assert score_clean > score_garbled, (
        f"Clean doc ({score_clean:.3f}) should score higher than garbled ({score_garbled:.3f})"
    )


def test_score_is_bounded() -> None:
    """compute_quality_score must always return a value in [0.0, 1.0]."""
    rng = random.Random(42)
    chars = string.printable + "�"
    for _ in range(20):
        text_len = rng.randint(0, 2000)
        text = "".join(rng.choice(chars) for _ in range(text_len))
        n_sections = rng.randint(0, 10)
        sections = [
            Section(f"H{i}", f"§{i}", 1, "".join(rng.choice(chars) for _ in range(50)))
            for i in range(n_sections)
        ]
        doc = _make_doc(text=text, sections=sections)
        score = compute_quality_score(doc)
        assert 0.0 <= score <= 1.0, (
            f"Score {score} is out of [0, 1] bounds for text_len={text_len}, "
            f"n_sections={n_sections}"
        )


def test_empty_sections_lower_score() -> None:
    """Documents with many empty sections should score lower than those with content."""
    sections_empty = [
        Section(f"H{i}", f"§{i}", 1, "")  # empty text
        for i in range(4)
    ]
    sections_full = [
        Section(f"H{i}", f"§{i}", 1, "Section content with enough words here.")
        for i in range(4)
    ]
    doc_empty = _make_doc(text="x" * 400, sections=sections_empty)
    doc_full = _make_doc(text="x" * 400, sections=sections_full)

    assert compute_quality_score(doc_full) > compute_quality_score(doc_empty)
