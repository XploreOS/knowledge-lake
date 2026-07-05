"""Minimal JSON and XML parser for Knowledge Lake (PARSE-01).

Handles application/json, application/xml, text/xml using stdlib only —
no heavy dependencies. JSON values are extracted recursively; XML text
nodes are collected depth-first.

Security (T-03-04 XXE):
  - Uses defusedxml.ElementTree.fromstring() when available (XXE guard).
  - Falls back to stdlib xml.etree.ElementTree.fromstring() if defusedxml
    is absent; logs a warning but does NOT call xml.etree.ElementTree.parse()
    or resolve any external entities.
  - No DOCTYPE declarations, no external entity references in test fixtures.

Registered as entry point:
    [project.entry-points."knowledge_lake.parsers"]
    json_xml = "knowledge_lake.plugins.builtin.json_xml_parser:JsonXmlParser"
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as stdlib_ET
from typing import Any

import structlog

from knowledge_lake.plugins.protocols import ParsedDoc, Section

log = structlog.get_logger(__name__)

_SUPPORTED_MIME_TYPES = frozenset({
    "application/json",
    "application/xml",
    "text/xml",
})


class JsonXmlParser:
    """ParserPlugin for JSON and XML documents.

    Uses stdlib only (json, xml.etree.ElementTree). Produces a single-section
    ParsedDoc with all extracted string content concatenated as the document text.

    Usage:
        parser = JsonXmlParser()
        if parser.can_parse("application/json"):
            doc = parser.parse(json_bytes, "application/json")
    """

    def can_parse(self, mime_type: str) -> bool:
        """Return True for application/json, application/xml, text/xml."""
        return mime_type in _SUPPORTED_MIME_TYPES

    def parse(self, raw: bytes, mime_type: str) -> ParsedDoc:
        """Parse raw JSON or XML bytes into a ParsedDoc.

        For JSON: recursively extracts all string values from the parsed object.
        For XML:  extracts all .text and .tail values from all elements depth-first.

        Args:
            raw:       Raw document bytes (UTF-8 encoded JSON or XML).
            mime_type: Must be application/json, application/xml, or text/xml.

        Returns:
            ParsedDoc with full text and a single Section.

        Raises:
            ValueError: If mime_type is not supported.
        """
        if not self.can_parse(mime_type):
            raise ValueError(
                f"JsonXmlParser does not support mime_type {mime_type!r}. "
                f"Supported: {sorted(_SUPPORTED_MIME_TYPES)}"
            )

        # Decode bytes; use errors="replace" so garbled bytes never crash parsing
        text_raw = raw.decode("utf-8", errors="replace")

        if mime_type == "application/json":
            return self._parse_json(text_raw)
        else:
            # application/xml or text/xml
            return self._parse_xml(raw)

    # ------------------------------------------------------------------
    # JSON parsing
    # ------------------------------------------------------------------

    def _parse_json(self, text: str) -> ParsedDoc:
        """Extract all string values from a JSON document."""
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            log.warning("json_xml_parser.json_decode_error", error=str(exc))
            # Fall back to treating the raw text as the document content
            obj = text

        parts = _extract_json_text(obj)
        joined = "\n".join(parts)
        section = Section(
            heading="JSON Document",
            section_path="§1",
            page=1,
            text=joined,
        )
        return ParsedDoc(
            text=joined,
            sections=[section],
            metadata={"format": "application/json", "source": "json_xml_parser"},
        )

    # ------------------------------------------------------------------
    # XML parsing
    # ------------------------------------------------------------------

    def _parse_xml(self, raw: bytes) -> ParsedDoc:
        """Extract all text and tail values from an XML document (T-03-04 XXE guard)."""
        # Prefer defusedxml if available — prevents XXE attacks (T-03-04)
        try:
            import defusedxml.ElementTree as defused_ET  # type: ignore[import-untyped]
            root = defused_ET.fromstring(raw)
            log.debug("json_xml_parser.xml_using_defusedxml")
        except ImportError:
            log.warning(
                "json_xml_parser.defusedxml_absent",
                detail=(
                    "defusedxml not installed — falling back to stdlib xml.etree.ElementTree. "
                    "Only fromstring(bytes) is used; no external entities are resolved (T-03-04)."
                ),
            )
            root = stdlib_ET.fromstring(raw)  # type: ignore[arg-type]

        parts = _extract_xml_text(root)
        joined = "\n".join(parts)
        section = Section(
            heading="XML Document",
            section_path="§1",
            page=1,
            text=joined,
        )
        return ParsedDoc(
            text=joined,
            sections=[section],
            metadata={"format": "application/xml", "source": "json_xml_parser"},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_json_text(obj: Any) -> list[str]:
    """Recursively collect all string values from a JSON-deserialized object."""
    parts: list[str] = []
    if isinstance(obj, str):
        stripped = obj.strip()
        if stripped:
            parts.append(stripped)
    elif isinstance(obj, dict):
        for value in obj.values():
            parts.extend(_extract_json_text(value))
    elif isinstance(obj, list):
        for item in obj:
            parts.extend(_extract_json_text(item))
    # Non-string leaves (int, float, bool, None) are skipped — they rarely
    # add semantic content and would clutter the extracted text.
    return parts


def _extract_xml_text(element: stdlib_ET.Element) -> list[str]:
    """Recursively collect all .text and .tail values from an XML element tree."""
    parts: list[str] = []
    if element.text:
        stripped = element.text.strip()
        if stripped:
            parts.append(stripped)
    for child in element:
        parts.extend(_extract_xml_text(child))
        if child.tail:
            stripped = child.tail.strip()
            if stripped:
                parts.append(stripped)
    return parts
