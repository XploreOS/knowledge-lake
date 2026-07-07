# Milestones

## v1.0 Knowledge Lake Framework MVP (Shipped: 2026-07-07)

**Phases completed:** 6 phases, 25 plans, 25 tasks

**Key accomplishments:**

- 1. [Rule 1 - Bug] Typer 0.26.8 incompatible with docling 2.108.0
- Wrote 20 failing tests across test_ids.py and test_version.py covering prefix assertions (src_/doc_/chk_/art_), UUIDv7 structure (version nibble == 7), time-sortability, unknown-kind ValueError, uniqueness, and pipeline_version format with/without git SHA, fallback to "0.0.0", never-raise contract.
- Wrote 17 failing tests across test_storage.py covering single-client assertion, put/get round-trips, exists() semantics, object_uri format, AWS-mode client construction (endpoint_url=None → amazonaws.com endpoint), and raw bucket bootstrap verification (versioning, object lock, delete-deny policy).
- `tests/unit/test_plugin_resolver.py` written with 15 tests covering:
- `tests/fixtures/hhs_security_rule.pdf` — locally generated PDF with real HIPAA Security Rule content (Administrative, Technical, Physical Safeguards sections). The hhs.gov direct PDF URL returned HTTP 403 during fixture creation; the equivalent content is preserved for hermetic testing. Docling parses it successfully into 4 sections.
- `api/schemas.py`
- 1. [Rule 1 - Version Mismatch] playwright version adjusted from 1.61.0 to 1.49.0
- 1. [Rule 3 - Blocking] Added source_type_override to register_source
- Multi-format parser fallback chain (Docling 6-format + JsonXmlParser) with weighted heuristic quality scoring, optional LLM gray-zone check, Alembic 0006 migration, and torture-test corpus validation across 5 healthcare document formats.
- Boilerplate removal with line-anchored regex patterns, lingua language detection, SHA256 exact dedup, and transient MinHash LSH near-dup flagging — all producing cleaned_document artifacts in the silver zone.
- Token-aware tiktoken chunker with table atomicity, clean_document Dagster asset inserted between parse and chunk stages, and klake parse/clean/chunk CLI commands with POST /parse, /clean, /chunk API endpoints.
- Migration 0007 (llm_spend + vector_collections tables), Artifact.quality_score mapped as a real ORM column, and 7 new repo.py functions plus EnrichSettings/IndexSettings for the enrichment and index/search vertical slices
- pipeline/deterministic.py + llm/pricing.py + pipeline/enrich.py deliver a cached, budget-capped single-call LiteLLM enrichment producing enriched_document artifacts, wired into klake enrich / POST /enrich / a parallel Dagster asset — the blocking live-Bedrock-smoke-test checkpoint is RESOLVED via a human-authorized live test (commit ac299e1)
- Qdrant alias-based collection management with zero-downtime reindex, an extended chunk payload carrying enrichment metadata, and filterable, backward-compatible semantic search across CLI/API — closing STATE.md's second Phase-4 blocker (Qdrant collection aliasing)
- `_build_filters(settings)`
- `QAPairResult(BaseModel)`
- `_GOLD_PREFIX = "gold"`
- DomainLoader class with path-traversal guard, YAML/Jinja2/importlib loading, and full 28-source healthcare domain pack (domain.yaml, sources.yaml, taxonomy.yaml, enrich.j2, qa_generation.j2, HealthcareValidator)
- DomainSettings nested config model (KLAKE_DOMAIN__ prefix) and optional domain_system_prompt kwarg on enrich_document/_build_enrichment_prompt enabling domain pack prompt injection without any pipeline redesign
- klake init --domain (bulk source registration) and klake index (reindex alias) CLI commands plus 8 additive REST endpoints completing the D-07 API surface gap audit
- RetryPolicy on all 12 Dagster assets with DRY constants, healthcare_e2e_job registered in Definitions, and 5-source E2E test infrastructure for DOMAIN-04 validation.

---
