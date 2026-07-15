"""Tests for healthcare sources.yaml content (DOMAIN-02)."""

from __future__ import annotations

from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

# Project root → domains/healthcare/sources.yaml
DOMAINS_ROOT = Path(__file__).parent.parent.parent
HC_DIR = DOMAINS_ROOT / "domains" / "healthcare"
SOURCES_YAML = HC_DIR / "sources.yaml"

_VALID_LICENSE_VALUES = {"public-domain", "CC", "open", "unknown"}
_REQUIRED_SOURCE_FIELDS = {"name", "url", "source_type", "license", "tags", "crawl_config", "ingest_type"}


def test_sources_yaml_parses() -> None:
    """yaml.safe_load(sources_yaml_text) returns a list."""
    assert yaml is not None, "pyyaml not installed"
    assert SOURCES_YAML.exists(), f"sources.yaml not found at {SOURCES_YAML}"
    sources = yaml.safe_load(SOURCES_YAML.read_text())
    assert isinstance(sources, list)


def test_sources_count_gte_25() -> None:
    """len(sources) >= 25 (per D-03 ≥25 requirement)."""
    assert yaml is not None
    assert SOURCES_YAML.exists(), f"sources.yaml not found at {SOURCES_YAML}"
    sources = yaml.safe_load(SOURCES_YAML.read_text())
    assert isinstance(sources, list)
    assert len(sources) >= 25, f"Expected ≥25 sources, got {len(sources)}"


def test_each_source_has_required_fields() -> None:
    """Every entry has name, url, source_type, license, tags, crawl_config, ingest_type keys."""
    assert yaml is not None
    assert SOURCES_YAML.exists(), f"sources.yaml not found at {SOURCES_YAML}"
    sources = yaml.safe_load(SOURCES_YAML.read_text())
    assert isinstance(sources, list)
    for i, source in enumerate(sources):
        missing = _REQUIRED_SOURCE_FIELDS - set(source.keys())
        assert not missing, f"Source #{i} ({source.get('name', '?')!r}) missing fields: {missing}"


def test_upload_sources_flagged() -> None:
    """At least 3 entries have ingest_type == 'upload' (NPPES, LOINC, NDC bulk, etc.)."""
    assert yaml is not None
    assert SOURCES_YAML.exists(), f"sources.yaml not found at {SOURCES_YAML}"
    sources = yaml.safe_load(SOURCES_YAML.read_text())
    assert isinstance(sources, list)
    upload_sources = [s for s in sources if s.get("ingest_type") == "upload"]
    assert len(upload_sources) >= 3, (
        f"Expected ≥3 upload sources (NPPES, LOINC, NDC), got {len(upload_sources)}: "
        f"{[s.get('name') for s in upload_sources]}"
    )


def test_license_values_valid() -> None:
    """License values are in {'public-domain', 'CC', 'open', 'unknown'}."""
    assert yaml is not None
    assert SOURCES_YAML.exists(), f"sources.yaml not found at {SOURCES_YAML}"
    sources = yaml.safe_load(SOURCES_YAML.read_text())
    assert isinstance(sources, list)
    for source in sources:
        lic = source.get("license", "")
        assert lic in _VALID_LICENSE_VALUES, (
            f"Source {source.get('name', '?')!r} has invalid license {lic!r}; "
            f"must be one of {_VALID_LICENSE_VALUES}"
        )
