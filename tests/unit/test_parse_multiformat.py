"""Tests for multi-format parsing (PARSE-01, PARSE-03).

Verifies that DoclingParser and JsonXmlParser correctly declare their
supported MIME types and produce well-formed ParsedDoc output.
"""

from __future__ import annotations

import pathlib

import pytest

from knowledge_lake.plugins.builtin.docling_parser import DoclingParser
from knowledge_lake.plugins.builtin.json_xml_parser import JsonXmlParser
from knowledge_lake.plugins.protocols import ParsedDoc

# Path helpers
FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "torture_test"

# Six Docling-native MIME types (PARSE-01)
DOCLING_MIMES = [
    "application/pdf",
    "text/html",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/markdown",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
]


@pytest.mark.parametrize("mime_type", DOCLING_MIMES)
def test_docling_can_parse_all_six_formats(mime_type: str) -> None:
    """DoclingParser must accept all six Docling-native MIME types (D-02)."""
    assert DoclingParser().can_parse(mime_type) is True


def test_docling_cannot_parse_json_xml() -> None:
    """DoclingParser must reject JSON and XML — those go to JsonXmlParser."""
    parser = DoclingParser()
    assert parser.can_parse("application/json") is False
    assert parser.can_parse("application/xml") is False
    assert parser.can_parse("text/xml") is False


def test_json_parser_can_parse() -> None:
    """JsonXmlParser must accept JSON and both XML MIME types."""
    parser = JsonXmlParser()
    assert parser.can_parse("application/json") is True
    assert parser.can_parse("application/xml") is True
    assert parser.can_parse("text/xml") is True


def test_json_parser_produces_parseddoc() -> None:
    """JsonXmlParser must return a valid ParsedDoc for JSON input (PARSE-01)."""
    parser = JsonXmlParser()
    raw = (FIXTURES / "healthcare_sample.json").read_bytes()
    result = parser.parse(raw, "application/json")
    assert isinstance(result, ParsedDoc)
    assert len(result.text) > 10
    assert len(result.sections) == 1


def test_xml_parser_produces_parseddoc() -> None:
    """JsonXmlParser must return a valid ParsedDoc for XML input (PARSE-01)."""
    parser = JsonXmlParser()
    raw = (FIXTURES / "healthcare_sample.xml").read_bytes()
    result = parser.parse(raw, "application/xml")
    assert isinstance(result, ParsedDoc)
    assert len(result.text) > 10
    assert len(result.sections) == 1


def test_parse_preserves_section_structure() -> None:
    """DoclingParser must preserve at least one section and page_count metadata (PARSE-03)."""
    parser = DoclingParser()
    raw = (FIXTURES / "healthcare_sample.html").read_bytes()
    result = parser.parse(raw, "text/html")
    assert isinstance(result, ParsedDoc)
    assert len(result.sections) >= 1
    assert result.metadata.get("page_count") is not None
