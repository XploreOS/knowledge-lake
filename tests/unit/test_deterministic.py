"""Tests for pipeline/deterministic.py — non-LLM title/dates/headings extraction (ENRICH-02)."""

from __future__ import annotations

from knowledge_lake.pipeline.deterministic import (
    extract_deterministic_fields,
    extract_dates,
    extract_headings,
    extract_title,
)
from knowledge_lake.plugins.protocols import Section


class TestExtractTitle:
    def test_title_from_parsed_metadata_wins(self) -> None:
        sections = [Section(heading="Intro", section_path="§1", page=1)]
        result = extract_title({"title": "The Real Title"}, sections)
        assert result == "The Real Title"

    def test_falls_back_to_first_section_heading(self) -> None:
        sections = [
            Section(heading="Administrative Safeguards", section_path="§1", page=1),
            Section(heading="Physical Safeguards", section_path="§2", page=2),
        ]
        result = extract_title({}, sections)
        assert result == "Administrative Safeguards"

    def test_falls_back_to_empty_string(self) -> None:
        result = extract_title({}, [])
        assert result == ""

    def test_falls_back_to_empty_string_when_first_heading_empty(self) -> None:
        sections = [Section(heading="", section_path="§1", page=1)]
        result = extract_title({}, sections)
        assert result == ""


class TestExtractDates:
    def test_finds_numeric_date(self) -> None:
        result = extract_dates("Filed on 07/05/2026.")
        assert "07/05/2026" in result

    def test_finds_month_name_date(self) -> None:
        result = extract_dates("Effective July 5, 2026 this rule applies.")
        assert "July 5, 2026" in result

    def test_returns_empty_list_for_no_dates(self) -> None:
        result = extract_dates("There are no dates in this sentence at all.")
        assert result == []

    def test_every_returned_item_is_a_str(self) -> None:
        result = extract_dates("Dates: 01/02/2025 and January 5, 2026.")
        assert len(result) > 0
        for item in result:
            assert isinstance(item, str)


class TestExtractHeadings:
    def test_returns_headings_in_section_order(self) -> None:
        sections = [
            Section(heading="First", section_path="§1", page=1),
            Section(heading="Second", section_path="§2", page=2),
            Section(heading="Third", section_path="§3", page=3),
        ]
        result = extract_headings(sections)
        assert result == ["First", "Second", "Third"]

    def test_skips_sections_with_empty_heading(self) -> None:
        sections = [
            Section(heading="First", section_path="§1", page=1),
            Section(heading="", section_path="§2", page=2),
            Section(heading="Third", section_path="§3", page=3),
        ]
        result = extract_headings(sections)
        assert result == ["First", "Third"]


class TestExtractDeterministicFields:
    def test_returns_dict_with_exactly_three_keys(self) -> None:
        result = extract_deterministic_fields({}, [], "Filed on 07/05/2026.")
        assert set(result.keys()) == {"title", "dates", "headings"}

    def test_values_populated_correctly(self) -> None:
        sections = [Section(heading="Intro", section_path="§1", page=1)]
        result = extract_deterministic_fields(
            {"title": "My Title"}, sections, "Dated 01/01/2026."
        )
        assert result["title"] == "My Title"
        assert result["dates"] == ["01/01/2026"]
        assert result["headings"] == ["Intro"]
