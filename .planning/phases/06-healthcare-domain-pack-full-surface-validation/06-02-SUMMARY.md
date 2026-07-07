---
phase: "06-healthcare-domain-pack-full-surface-validation"
plan: "02"
subsystem: "config/pipeline"
status: complete
tags: ["domain-pack", "settings", "enrich", "pydantic", "tdd"]
dependency_graph:
  requires:
    - "knowledge_lake.config.settings.Settings (pre-existing)"
    - "knowledge_lake.pipeline.enrich.enrich_document (pre-existing)"
  provides:
    - "knowledge_lake.config.settings.DomainSettings"
    - "knowledge_lake.config.settings.Settings.domain"
    - "knowledge_lake.pipeline.enrich._build_enrichment_prompt(domain_system_prompt=None)"
    - "knowledge_lake.pipeline.enrich.enrich_document(domain_system_prompt=None)"
  affects:
    - "src/knowledge_lake/config/settings.py"
    - "src/knowledge_lake/pipeline/enrich.py"
    - "tests/unit/test_settings.py"
    - "tests/unit/test_enrich_domain_override.py"
tech_stack:
  added: []
  patterns:
    - "Optional[str] = None kwarg with 'or' fallback for domain_system_prompt in _build_enrichment_prompt"
    - "DomainSettings nested BaseModel following StorageSettings/CrawlSettings pattern"
    - "KLAKE_DOMAIN__ env var prefix via pydantic-settings env_nested_delimiter"
key_files:
  created:
    - tests/unit/test_enrich_domain_override.py
  modified:
    - src/knowledge_lake/config/settings.py
    - src/knowledge_lake/pipeline/enrich.py
    - tests/unit/test_settings.py
decisions:
  - "domain_system_prompt is an Optional[str] kwarg with default None — not a Settings read inside enrich.py (keeps enrichment side-effect-free, as per PLAN.md key_link)"
  - "DomainSettings placed after ExportSettings and before IndexSettings in settings.py for grouping clarity"
  - "'system = domain_system_prompt or _ENRICHMENT_SYSTEM_PROMPT' pattern — falsy override (empty string) falls back to generic; operator-authored templates will always be non-empty"
metrics:
  duration: "4 minutes"
  completed_date: "2026-07-07"
  tasks_completed: 2
  files_created: 1
  files_modified: 3
  tests_passing: 9
---

# Phase 06 Plan 02: DomainSettings + Enrich Domain Prompt Override Summary

**One-liner:** DomainSettings nested config model (KLAKE_DOMAIN__ prefix) and optional domain_system_prompt kwarg on enrich_document/_build_enrichment_prompt enabling domain pack prompt injection without any pipeline redesign

## What Was Built

Additive changes only — no existing caller signatures broken, no existing behavior changed:

1. **`DomainSettings` in `config/settings.py`** — Pydantic BaseModel with `domain_name: Optional[str] = None` and `domains_root: str = "domains"`. Nested under `Settings.domain` with KLAKE_DOMAIN__ env var prefix. Follows the existing StorageSettings/CrawlSettings pattern.

2. **`domain_system_prompt` kwarg in `pipeline/enrich.py`** — Two additive changes:
   - `_build_enrichment_prompt(excerpt, deterministic, domain_system_prompt=None)`: when `domain_system_prompt` is not None, uses it as system prompt instead of `_ENRICHMENT_SYSTEM_PROMPT`
   - `enrich_document(..., domain_system_prompt=None)`: threads the kwarg through to `_build_enrichment_prompt`

3. **`tests/unit/test_enrich_domain_override.py`** — 4 tests covering the override path and the default path, both at the `enrich_document` integration level and the `_build_enrichment_prompt` unit level.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | DomainSettings in settings.py (TDD: RED then GREEN) | f183e96 (test RED), 8507362 (feat GREEN) | test_settings.py, settings.py |
| 2 | domain_system_prompt in enrich.py + new test file (TDD: RED then GREEN) | 820a34c (test RED), 2dfb946 (feat GREEN) | test_enrich_domain_override.py, enrich.py |

## Test Results

All 9 new tests pass. Full unit test suite: 317 passed + 17 xpassed (9 new vs prior 308 + 17 xpassed baseline).

- `test_settings.py::TestDomainSettings`: 5 tests — defaults, env var overrides, class instantiation
- `test_enrich_domain_override.py`: 4 tests — domain_system_prompt replaces generic, default uses generic, _build_enrichment_prompt unit (with/without override)
- All 8 existing `test_enrich.py` tests continue to pass without modification

## Plan Verification Checklist

- [x] All tests/unit/test_enrich.py tests continue to pass without modification
- [x] tests/unit/test_enrich_domain_override.py has 4 passing tests (exceeds 2+ requirement)
- [x] DomainSettings exists in settings.py with `domain_name: Optional[str] = None`, `domains_root: str = "domains"`
- [x] Settings.domain field exists and is accessible
- [x] enrich_document() accepts domain_system_prompt kwarg that overrides system prompt when provided
- [x] No existing caller of enrich_document() requires changes (kwarg defaults to None)

## Deviations from Plan

None — plan executed exactly as written. All changes are strictly additive.

## Known Stubs

None — both modified files contain full implementations, not stubs.

## Threat Flags

None — no new network endpoints, auth paths, or trust boundary changes. Threat T-06-06 (domain_system_prompt as LLM system prompt injection vector) is accepted per the plan: domain_system_prompt is rendered from operator-authored Jinja2 templates, not user-submitted at runtime.

## Self-Check: PASSED

All created/modified files verified on disk:
- src/knowledge_lake/config/settings.py — DomainSettings class present, Settings.domain field present
- src/knowledge_lake/pipeline/enrich.py — domain_system_prompt in _build_enrichment_prompt and enrich_document signatures
- tests/unit/test_enrich_domain_override.py — 4 tests present
- tests/unit/test_settings.py — TestDomainSettings class with 5 tests present

All 4 task commits verified in git log: f183e96, 8507362, 820a34c, 2dfb946.
Full unit test suite: 317 passed + 17 xpassed.
