"""Tests for DomainLoader (DOMAIN-01).

Import uses a try/except guard so pytest can collect the file before the module exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    from knowledge_lake.domains.loader import DomainLoader
except ImportError:
    DomainLoader = None  # type: ignore[assignment, misc]

try:
    from knowledge_lake.domains.models import DomainFilters
except ImportError:
    DomainFilters = None  # type: ignore[assignment, misc]

try:
    from pydantic import ValidationError
except ImportError:
    ValidationError = None  # type: ignore[assignment, misc]

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


def test_domain_loader_healthcare_has_filters() -> None:
    """healthcare pack's filters.yaml loads into a DomainFilters instance with ICD-10."""
    assert DomainLoader is not None
    assert DomainFilters is not None
    loader = DomainLoader.from_name("healthcare", root=DOMAINS_ROOT)
    assert loader.filters is not None
    assert isinstance(loader.filters, DomainFilters)
    assert "ICD-10" in loader.filters.normative_allowlists


def test_domain_loader_aviation_has_no_filters() -> None:
    """Loading a domain pack WITHOUT filters.yaml (aviation) raises nothing and
    yields filters is None — Pitfall-4 regression guard for the optional-file
    convention (CLEAN-06, D-07)."""
    assert DomainLoader is not None
    loader = DomainLoader.from_name("aviation", root=DOMAINS_ROOT)
    assert loader.filters is None


def test_domain_filters_model_defaults() -> None:
    """DomainFilters() with no args defaults all three fields to empty containers."""
    assert DomainFilters is not None
    filters = DomainFilters()
    assert filters.boilerplate_patterns == []
    assert filters.normative_allowlists == []
    assert filters.thresholds == {}


def test_domain_filters_rejects_unknown_key() -> None:
    """CR-02 regression guard: a misspelled/unknown filters.yaml key (e.g.
    'normative_alowlists' typo for 'normative_allowlists') must raise
    pydantic.ValidationError instead of silently being dropped, which would
    otherwise leave the ICD-10/LOINC/RxNorm allowlist empty with no error."""
    assert DomainFilters is not None
    assert ValidationError is not None
    with pytest.raises(ValidationError):
        DomainFilters.model_validate({"normative_alowlists": ["ICD-10"]})


def test_domain_loader_healthcare_and_aviation_still_load_with_forbid_extra() -> None:
    """CR-02 regression guard: adding extra='forbid' to the domain-pack schema
    models must not break loading the existing healthcare/aviation packs —
    their domain.yaml/sources.yaml/filters.yaml must contain no unrecognized
    keys."""
    assert DomainLoader is not None
    hc_loader = DomainLoader.from_name("healthcare", root=DOMAINS_ROOT)
    assert hc_loader.filters is not None
    av_loader = DomainLoader.from_name("aviation", root=DOMAINS_ROOT)
    assert av_loader.filters is None
