"""Deterministic (non-LLM) metadata extraction for enrichment (ENRICH-02, D-02).

Reuses already-computed ParsedDoc data (metadata dict + Section list) plus a
regex pass over the cleaned text. No re-parsing, no LLM calls, no network I/O,
no database session — this is a pure transform (D-02).

Functions:
    extract_title                — title from parsed_metadata or first section heading
    extract_dates                — US-style date strings found in the text
    extract_headings             — non-empty section headings, in order
    extract_deterministic_fields — bundles all three into a single dict
"""

from __future__ import annotations

import re
from typing import Any

from knowledge_lake.plugins.protocols import Section

# Matches either "MM/DD/YYYY" (or 2-digit year) or "Month DD, YYYY" style dates.
# Both alternatives are written without capturing groups so findall() returns
# plain strings (never tuples) regardless of which alternative matches.
_DATE_PATTERN = re.compile(
    r"(?:\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\b(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December) \d{1,2}, \d{4}\b)"
)


def extract_title(parsed_metadata: dict[str, Any], sections: list[Section]) -> str:
    """Return the document title from deterministic sources only.

    Priority: parsed_metadata["title"] (if truthy) -> first section's heading
    (if truthy) -> "".
    """
    if parsed_metadata.get("title"):
        return str(parsed_metadata["title"])
    if sections and sections[0].heading:
        return sections[0].heading
    return ""


def extract_dates(text: str) -> list[str]:
    """Return all US-style dates found in text, as plain strings (never tuples)."""
    return _DATE_PATTERN.findall(text)


def extract_headings(sections: list[Section]) -> list[str]:
    """Return the heading of every section that has a non-empty heading, in order."""
    return [s.heading for s in sections if s.heading]


def extract_deterministic_fields(
    parsed_metadata: dict[str, Any], sections: list[Section], text: str
) -> dict[str, Any]:
    """Bundle title/dates/headings extraction into a single dict.

    Pure transform: makes no network or LLM call, opens no database session,
    and does not open an S3/storage client (ENRICH-02).

    Returns:
        dict with exactly the keys "title", "dates", "headings".
    """
    return {
        "title": extract_title(parsed_metadata, sections),
        "dates": extract_dates(text),
        "headings": extract_headings(sections),
    }
