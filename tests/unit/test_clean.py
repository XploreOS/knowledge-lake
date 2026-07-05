"""Tests for clean stage — boilerplate removal, language detection (CLEAN-01, CLEAN-02)."""

from knowledge_lake.pipeline.clean import (
    remove_boilerplate,
    _normalize_whitespace,
    detect_language,
)


def test_boilerplate_removal_page_header() -> None:
    """Page header 'Page N of M' on its own line must be removed."""
    text = "Introduction\n\nPage 3 of 10\n\nAdministrative safeguards are required."
    result = remove_boilerplate(text)
    assert "Page 3 of 10" not in result


def test_boilerplate_removal_preserves_body() -> None:
    """Body text after a boilerplate line must survive intact."""
    text = "Page 1 of 5\n\nAdministrative safeguards are the policies and procedures..."
    result = remove_boilerplate(text)
    assert "Administrative safeguards are the policies and procedures" in result


def test_boilerplate_preserves_citations() -> None:
    """Inline citations like '(Smith, 2023)' must not be removed."""
    text = "Per (Smith, 2023) the standard requires annual training."
    result = remove_boilerplate(text)
    assert "(Smith, 2023)" in result


def test_boilerplate_preserves_section_refs() -> None:
    """Section references like '§3.2' must not be removed."""
    text = "See §3.2 Administrative Safeguards for details."
    result = remove_boilerplate(text)
    assert "§3.2" in result


def test_whitespace_normalization_collapses_blank_lines() -> None:
    """Four or more consecutive blank lines must collapse to at most two."""
    text = "First paragraph.\n\n\n\n\nSecond paragraph."
    result = _normalize_whitespace(text)
    # Should not contain 3+ consecutive newlines
    assert "\n\n\n" not in result
    # Body text should be preserved
    assert "First paragraph." in result
    assert "Second paragraph." in result


def test_whitespace_strips_trailing_spaces() -> None:
    """Lines with trailing spaces must have them stripped."""
    text = "Line one   \nLine two  \nLine three   "
    result = _normalize_whitespace(text)
    for line in result.splitlines():
        assert line == line.rstrip(), f"Line has trailing whitespace: {line!r}"


def test_language_detection_english() -> None:
    """English healthcare text must be detected as 'en'."""
    text = "The patient requires immediate treatment for acute conditions and hypertension."
    result = detect_language(text)
    assert result == "en"


def test_language_detection_short_text_no_crash() -> None:
    """Short text must not raise — may return 'unknown' but must be a string."""
    result = detect_language("ok")
    assert isinstance(result, str)


def test_language_detection_empty_string() -> None:
    """Empty string must return 'unknown' gracefully."""
    result = detect_language("")
    assert result == "unknown"
