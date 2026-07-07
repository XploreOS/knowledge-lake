"""Wave 0 test stubs for healthcare Jinja2 prompt templates (DOMAIN-03).

All tests are marked xfail until the domain pack content files are created in Task 3.
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    Environment = None  # type: ignore[assignment, misc]
    FileSystemLoader = None  # type: ignore[assignment]

# Project root → domains/healthcare/prompts/
DOMAINS_ROOT = Path(__file__).parent.parent.parent
HC_DIR = DOMAINS_ROOT / "domains" / "healthcare"
PROMPTS_DIR = HC_DIR / "prompts"


def _make_env() -> "Environment":
    """Create a Jinja2 Environment pointing to the healthcare prompts directory."""
    assert Environment is not None, "jinja2 not installed"
    assert FileSystemLoader is not None
    return Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), autoescape=False)


@pytest.mark.xfail(reason="Wave 0 stub — implementation pending")
def test_enrich_j2_renders() -> None:
    """enrich.j2 rendered with title='T', dates=[], headings=[], excerpt='text' returns str containing 'clinical_codes'."""
    assert PROMPTS_DIR.exists(), f"Prompts directory not found: {PROMPTS_DIR}"
    env = _make_env()
    rendered = env.get_template("enrich.j2").render(
        title="Test Title",
        dates=[],
        headings=[],
        excerpt="ICD-10 E11.9 diabetes mellitus type 2",
    )
    assert isinstance(rendered, str)
    assert len(rendered) > 0
    assert "clinical_codes" in rendered, "enrich.j2 must include 'clinical_codes' in output schema"


@pytest.mark.xfail(reason="Wave 0 stub — implementation pending")
def test_enrich_j2_no_autoescape() -> None:
    """Text '<E11.9>' in excerpt passes through without HTML-encoding."""
    assert PROMPTS_DIR.exists(), f"Prompts directory not found: {PROMPTS_DIR}"
    env = _make_env()
    rendered = env.get_template("enrich.j2").render(
        title="T",
        dates=[],
        headings=[],
        excerpt="<E11.9> diabetes",
    )
    # With autoescape=False, angle brackets should pass through verbatim
    assert "&lt;" not in rendered, "Angle brackets were HTML-escaped — autoescape must be False"
    assert "&gt;" not in rendered, "Angle brackets were HTML-escaped — autoescape must be False"


@pytest.mark.xfail(reason="Wave 0 stub — implementation pending")
def test_qa_generation_j2_renders() -> None:
    """qa_generation.j2 rendered with document_text='d', chunk_text='c' returns str containing 'question'."""
    assert PROMPTS_DIR.exists(), f"Prompts directory not found: {PROMPTS_DIR}"
    env = _make_env()
    rendered = env.get_template("qa_generation.j2").render(
        document_text="HIPAA requires administrative safeguards.",
        chunk_text="administrative safeguards must include access controls.",
    )
    assert isinstance(rendered, str)
    assert len(rendered) > 0
    assert "question" in rendered, "qa_generation.j2 must reference 'question' in output schema"
