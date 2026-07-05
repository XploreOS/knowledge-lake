"""Torture-test corpus quality gates (PARSE-05).

Validates that all five required document formats score >= 0.35 quality
after parsing, proving the parser chain is ready for bulk healthcare
document ingestion.

Five formats tested:
  - PDF  (hhs_security_rule.pdf via DoclingParser)
  - HTML (healthcare_sample.html via DoclingParser)
  - MD   (healthcare_sample.md via DoclingParser)
  - CSV  (healthcare_sample.csv via DoclingParser)
  - JSON (healthcare_sample.json via JsonXmlParser)
"""

from __future__ import annotations

import pathlib

import pytest

from knowledge_lake.config.settings import Settings
from knowledge_lake.plugins.builtin.docling_parser import DoclingParser
from knowledge_lake.plugins.builtin.json_xml_parser import JsonXmlParser
from knowledge_lake.plugins.resolver import parse_with_fallback
from knowledge_lake.quality.scorer import compute_quality_score

FIXTURES_DIR = pathlib.Path(__file__).parent.parent / "fixtures"
TORTURE_DIR = FIXTURES_DIR / "torture_test"

# Minimum acceptable quality score (PARSE-05 acceptance gate)
_MIN_QUALITY = 0.35

# (fixture_path, mime_type, parser_class)
_CORPUS = [
    (FIXTURES_DIR / "hhs_security_rule.pdf", "application/pdf", DoclingParser),
    (TORTURE_DIR / "healthcare_sample.html", "text/html", DoclingParser),
    (TORTURE_DIR / "healthcare_sample.md", "text/markdown", DoclingParser),
    (TORTURE_DIR / "healthcare_sample.csv", "text/csv", DoclingParser),
    (TORTURE_DIR / "healthcare_sample.json", "application/json", JsonXmlParser),
]

_CORPUS_IDS = [
    "pdf",
    "html",
    "markdown",
    "csv",
    "json",
]


@pytest.mark.parametrize("fixture_path,mime_type,parser_cls", _CORPUS, ids=_CORPUS_IDS)
def test_torture_corpus_quality_gates(
    fixture_path: pathlib.Path,
    mime_type: str,
    parser_cls: type,
) -> None:
    """Each fixture must produce quality_score >= 0.35 via the direct parser (PARSE-05)."""
    raw = fixture_path.read_bytes()
    parser = parser_cls()
    parsed_doc = parser.parse(raw, mime_type)
    score = compute_quality_score(parsed_doc, mime_type)
    assert score >= _MIN_QUALITY, (
        f"Fixture {fixture_path.name!r} (mime={mime_type}) scored {score:.3f} < "
        f"{_MIN_QUALITY} — parser quality gate failed (PARSE-05)"
    )


def test_fallback_chain_torture_pass() -> None:
    """All five fixtures must pass through the fallback chain with score >= 0.35.

    Uses a two-parser chain [docling, json_xml] so each fixture is handled by
    the appropriate parser without needing optional heavy deps.
    """
    settings = Settings(
        _env_file=None,
        parse={
            "chain": ["docling", "json_xml"],
            "quality_threshold": 0.35,
            "quality_gray_zone": [0.3, 0.6],
            "llm_spot_check": False,  # No LLM proxy in test environment
            "max_file_bytes": 104857600,
        },
    )

    for fixture_path, mime_type, _ in _CORPUS:
        raw = fixture_path.read_bytes()
        parsed_doc, parser_used, quality_score = parse_with_fallback(
            raw, mime_type, settings=settings
        )
        assert quality_score >= _MIN_QUALITY, (
            f"Fixture {fixture_path.name!r}: fallback chain scored {quality_score:.3f} "
            f"< {_MIN_QUALITY}"
        )
        assert parser_used in settings.parse.chain, (
            f"Parser {parser_used!r} not in chain {settings.parse.chain}"
        )
