"""Pydantic models for the domain pack loader (DOMAIN-01).

Validates YAML content from domain.yaml, sources.yaml, and taxonomy.yaml
using clear Pydantic error messages.

All models are plain BaseModel (not BaseSettings) — they are constructed
from pre-loaded YAML dicts, not from environment variables.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict


class SourceEntry(BaseModel):
    """A single source entry from sources.yaml.

    Validated at DomainLoader construction time to give clear errors if
    sources.yaml is malformed. All fields that have defaults are optional
    in the YAML.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    """Human-readable source name (e.g. 'HL7 FHIR R4 Specification')."""

    url: str
    """Canonical source URL."""

    source_type: str
    """Document format: 'html', 'pdf', 'csv', 'json', etc."""

    license: str
    """License classification: 'public-domain', 'CC', 'open', or 'unknown'."""

    tags: list[str] = []
    """Domain taxonomy tags for this source."""

    crawl_config: dict = {}
    """Crawler configuration overrides (depth, rate_limit_rps, robots_txt, etc.)."""

    crawl_schedule: str | None = None
    """Optional 5-field UTC cron string from sources.yaml (D-05a). NULL means no auto-recrawl."""

    ingest_type: str = "crawl"
    """How to ingest: 'crawl' (auto-crawl) or 'upload' (manual bulk file download)."""

    requires_registration: bool = False
    """True if the source requires user registration before downloading (e.g. LOINC)."""


class DomainManifest(BaseModel):
    """Top-level metadata from domain.yaml (DOMAIN-01 schema)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    """Domain pack name (e.g. 'healthcare'). Must match the directory name."""

    version: str
    """Semantic version string (e.g. '1.0.0')."""

    description: str
    """Human-readable description of this domain pack."""


class DomainFilters(BaseModel):
    """Optional clinical/domain-specific filter overrides from filters.yaml (CLEAN-06).

    Unlike DomainManifest/SourceEntry/TaxonomyManifest, filters.yaml itself is OPTIONAL —
    a domain pack with no filters.yaml loads with DomainLoader.filters = None. When present,
    this model validates the pack's boilerplate/allowlist/threshold overrides.

    WARNING to pack authors: a broad allowlist pattern (e.g. a bare '.*' or an empty-string
    regex) in normative_allowlists will silently exempt ALL section content from boilerplate
    classification for this domain, defeating the quality gate entirely — author narrow,
    specific patterns only (e.g. 'ICD-10', not '.*'). Similarly, a thresholds override such as
    {"min_token_count": 0} silently weakens the framework's substance-check floor to a
    degenerate value; there is no framework-side clamping today, so any override here is an
    explicit, visible choice that must be deliberate, not a stray default.
    """

    model_config = ConfigDict(extra="forbid")

    boilerplate_patterns: list[str] = []
    """Additional regex pattern strings identifying domain-specific boilerplate. Compiled by
    the caller (e.g. classify_sections()), not by this model."""

    normative_allowlists: list[str] = []
    """Regex patterns that must never be classified as boilerplate regardless of substance
    signals (e.g. clinical codes like 'ICD-10', 'LOINC', 'RxNorm', dosage patterns)."""

    thresholds: dict[str, float] = {}
    """Domain-specific substance threshold overrides, keyed by the same names as
    pipeline.quality.predicates's DEFAULT_* constants (e.g. 'min_token_count'). RESERVED,
    NOT YET CONSUMED: validated and available here for pack authors to specify, but Plan
    19-04's classify_sections() does not read this field as of Phase 19 — no acceptance
    criterion requires per-domain threshold overrides yet. The field exists so a future phase
    can wire override-vs-compose semantics without a schema-breaking change."""


class TaxonomyManifest(BaseModel):
    """Structured taxonomy from taxonomy.yaml."""

    model_config = ConfigDict(extra="forbid")

    entity_types: list[str]
    """Ordered list of entity type names (e.g. Condition, Medication, ...)."""

    categories: list[str] = []
    """Domain category labels (e.g. clinical_terminology, federal_regulation)."""


@dataclass
class ValidationResult:
    """Result from a domain pack's ``<Pascal>Validator.validate_document()``.

    Every domain pack ships its own validator (e.g. HealthcareValidator,
    AviationValidator) with a standalone dataclass of this shape defined in
    its own domains/<domain>/validators/validate.py (no knowledge_lake
    imports allowed in that module per Pitfall 7 — self-contained stdlib-only
    validator). This copy is exposed from the framework, domain-neutral, for
    type-checking callers that import from knowledge_lake.domains.models.
    """

    passed: bool
    """True if the document passed all validation checks (no errors)."""

    warnings: list[str] = field(default_factory=list)
    """Non-fatal warnings (e.g. PHI heuristic triggered, unknown code system)."""

    errors: list[str] = field(default_factory=list)
    """Fatal errors that caused passed=False."""
