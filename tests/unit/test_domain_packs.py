"""Generic coverage for every domain pack under domains/ (KL-03, Task 5).

Existing pack tests (test_healthcare_*.py, test_domain_loader.py) all
hardcode domains/healthcare — a second pack (aviation) shipped with zero
test coverage until this file existed. This test discovers every pack
directory at collection time (not hardcoded) and asserts the same baseline
contract for each one, so adding a pack automatically gets coverage.

A pack directory is any immediate child of domains/ that contains a
domain.yaml file. This naturally excludes domains/README.md and
domains/local/ (a container for git-ignored user packs with no
domain.yaml of its own — see domains/README.md and .gitignore).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_lake.domains.loader import DomainLoader

# Project root → domains/
PROJECT_ROOT = Path(__file__).parent.parent.parent
DOMAINS_DIR = PROJECT_ROOT / "domains"


def _discover_pack_names() -> list[str]:
    """Return every domains/{name}/ directory name that contains a domain.yaml.

    Discovered at collection time so a newly scaffolded/committed pack is
    automatically parametrized without editing this file.
    """
    if not DOMAINS_DIR.exists():
        return []
    return sorted(
        child.name
        for child in DOMAINS_DIR.iterdir()
        if child.is_dir() and (child / "domain.yaml").exists()
    )


PACK_NAMES = _discover_pack_names()


@pytest.fixture(params=PACK_NAMES, ids=PACK_NAMES)
def loader(request: pytest.FixtureRequest) -> DomainLoader:
    """A loaded DomainLoader for each discovered pack."""
    return DomainLoader.from_name(request.param, root=PROJECT_ROOT)


def test_at_least_two_packs_discovered() -> None:
    """Sanity check: this test must actually be parametrized over >= 2 packs.

    Guards against a discovery bug silently reducing this to a no-op suite.
    """
    assert len(PACK_NAMES) >= 2, (
        f"Expected at least 2 domain packs under {DOMAINS_DIR}, found: {PACK_NAMES}"
    )
    assert "healthcare" in PACK_NAMES
    assert "aviation" in PACK_NAMES


def test_manifest_name_matches_directory(loader: DomainLoader, request: pytest.FixtureRequest) -> None:
    """loader.manifest.name equals the pack's directory name."""
    pack_name = request.node.callspec.params["loader"]
    assert loader.manifest.name == pack_name


def test_sources_yaml_parses_into_source_entries(loader: DomainLoader) -> None:
    """sources.yaml parses into a list of SourceEntry models (possibly empty)."""
    assert isinstance(loader.sources, list)
    for source in loader.sources:
        assert hasattr(source, "name")
        assert hasattr(source, "url")
        assert hasattr(source, "source_type")


def test_enrich_prompt_renders(loader: DomainLoader) -> None:
    """enrich.j2 renders to a non-empty string with standard enrichment kwargs."""
    rendered = loader.render_prompt(
        "enrich.j2",
        title="Test Title",
        dates=[],
        headings=[],
        excerpt="Sample excerpt text for rendering.",
    )
    assert isinstance(rendered, str)
    assert len(rendered) > 0


def test_qa_generation_prompt_renders(loader: DomainLoader) -> None:
    """qa_generation.j2 renders to a non-empty string with standard QA kwargs."""
    rendered = loader.render_prompt(
        "qa_generation.j2",
        document_text="Sample document context.",
        chunk_text="Sample chunk to generate a question from.",
    )
    assert isinstance(rendered, str)
    assert len(rendered) > 0


def test_validator_loads_and_exposes_validate_document(loader: DomainLoader) -> None:
    """loader.validator exposes a callable validate_document()."""
    assert hasattr(loader.validator, "validate_document")
    assert callable(loader.validator.validate_document)

    # Exercise it once with a trivial document to confirm it returns without
    # raising and produces a result with the expected shape.
    result = loader.validator.validate_document({"text": "sample document text"})
    assert hasattr(result, "passed")
    assert hasattr(result, "warnings")
    assert hasattr(result, "errors")
