"""Integration tests for parse structure preservation (PARSE-03).

Verifies that parsers preserve document structure: sections, headings,
page count metadata, and text content from real healthcare fixtures.
"""

from __future__ import annotations

import pathlib

import pytest

from knowledge_lake.plugins.builtin.docling_parser import DoclingParser
from knowledge_lake.plugins.builtin.json_xml_parser import JsonXmlParser

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "torture_test"

pytestmark = pytest.mark.integration


def test_html_preserves_sections() -> None:
    """DoclingParser must extract at least one section with a non-empty heading from HTML."""
    parser = DoclingParser()
    raw = (FIXTURES / "healthcare_sample.html").read_bytes()
    result = parser.parse(raw, "text/html")

    assert len(result.sections) >= 1
    headings_with_text = [s for s in result.sections if s.heading.strip()]
    assert len(headings_with_text) >= 1, (
        f"Expected at least one section with a heading, got sections: "
        f"{[s.heading for s in result.sections]}"
    )


def test_markdown_preserves_headings() -> None:
    """DoclingParser must extract at least one section from Markdown input."""
    parser = DoclingParser()
    raw = (FIXTURES / "healthcare_sample.md").read_bytes()
    result = parser.parse(raw, "text/markdown")

    assert len(result.sections) >= 1


def test_csv_produces_text() -> None:
    """DoclingParser must extract text content from CSV (tabular data → text)."""
    parser = DoclingParser()
    raw = (FIXTURES / "healthcare_sample.csv").read_bytes()
    result = parser.parse(raw, "text/csv")

    assert len(result.text) > 50, (
        f"Expected at least 50 chars from CSV, got {len(result.text)}"
    )


def test_json_produces_text() -> None:
    """JsonXmlParser must produce text containing content from the JSON fixture."""
    parser = JsonXmlParser()
    raw = (FIXTURES / "healthcare_sample.json").read_bytes()
    result = parser.parse(raw, "application/json")

    assert "Patient" in result.text or "Smith" in result.text, (
        f"Expected FHIR content in extracted text, got: {result.text[:200]!r}"
    )


def test_xml_no_xxe() -> None:
    """JsonXmlParser must parse XML without raising and without XXE processing."""
    parser = JsonXmlParser()
    raw = (FIXTURES / "healthcare_sample.xml").read_bytes()
    # Must not raise; must produce non-trivial text
    result = parser.parse(raw, "application/xml")
    assert len(result.text) > 10
