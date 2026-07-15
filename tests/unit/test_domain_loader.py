"""Tests for DomainLoader (DOMAIN-01).

Import uses a try/except guard so pytest can collect the file before the module exists.
"""

from __future__ import annotations

from pathlib import Path

try:
    from knowledge_lake.domains.loader import DomainLoader
except ImportError:
    DomainLoader = None  # type: ignore[assignment, misc]

# Project root → domains/healthcare/ directory
DOMAINS_ROOT = Path(__file__).parent.parent.parent  # project root
HC_DIR = DOMAINS_ROOT / "domains" / "healthcare"


def test_domain_loader_from_name_returns_loader() -> None:
    """DomainLoader.from_name('healthcare', root=project_root) returns a DomainLoader instance."""
    assert DomainLoader is not None, "DomainLoader not yet implemented"
    loader = DomainLoader.from_name("healthcare", root=DOMAINS_ROOT)
    assert loader is not None
    assert isinstance(loader, DomainLoader)


def test_domain_loader_manifest_fields() -> None:
    """loader.manifest.name == 'healthcare' and loader.manifest.version is non-empty."""
    assert DomainLoader is not None
    loader = DomainLoader.from_name("healthcare", root=DOMAINS_ROOT)
    assert loader.manifest.name == "healthcare"
    assert isinstance(loader.manifest.version, str)
    assert len(loader.manifest.version) > 0


def test_domain_loader_sources_count() -> None:
    """len(loader.sources) >= 25."""
    assert DomainLoader is not None
    loader = DomainLoader.from_name("healthcare", root=DOMAINS_ROOT)
    assert len(loader.sources) >= 25


def test_domain_loader_taxonomy_has_entity_types() -> None:
    """'entity_types' key in loader.taxonomy."""
    assert DomainLoader is not None
    loader = DomainLoader.from_name("healthcare", root=DOMAINS_ROOT)
    assert "entity_types" in loader.taxonomy


def test_domain_loader_validator_has_method() -> None:
    """hasattr(loader.validator, 'validate_document')."""
    assert DomainLoader is not None
    loader = DomainLoader.from_name("healthcare", root=DOMAINS_ROOT)
    assert hasattr(loader.validator, "validate_document")
    assert callable(loader.validator.validate_document)


def test_domain_loader_render_enrich_prompt() -> None:
    """render_prompt('enrich.j2', ...) returns non-empty string containing 'clinical_codes'."""
    assert DomainLoader is not None
    loader = DomainLoader.from_name("healthcare", root=DOMAINS_ROOT)
    rendered = loader.render_prompt(
        "enrich.j2",
        title="Test Document",
        dates=[],
        headings=[],
        excerpt="ICD-10 E11.9 diabetes mellitus",
    )
    assert isinstance(rendered, str)
    assert len(rendered) > 0
    assert "clinical_codes" in rendered
