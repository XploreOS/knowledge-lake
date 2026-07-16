---
phase: 19-section-classifier-patterns
plan: 02
subsystem: domains
tags: [domain-pack, filters-yaml, pydantic, optional-load, allowlist]

# Dependency graph
requires: []
provides:
  - "DomainFilters model (boilerplate_patterns, normative_allowlists, thresholds) in domains/models.py"
  - "DomainLoader.filters (DomainFilters | None) — optional filters.yaml load, never raises for absence"
  - "domains/healthcare/filters.yaml fixture with clinical-code allowlist (ICD-10, LOINC, RxNorm, section refs, dosage patterns)"
affects: [19-04-section-classifier]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Optional-file loading branch alongside DomainLoader's four mandatory-file loads: filters.yaml existence is checked with .exists() and set to None on absence rather than raising FileNotFoundError, an explicit divergence from the domain.yaml/sources.yaml/taxonomy.yaml/prompts/validators pattern in the same __init__"

key-files:
  created:
    - domains/healthcare/filters.yaml
  modified:
    - src/knowledge_lake/domains/models.py
    - src/knowledge_lake/domains/loader.py
    - tests/unit/test_domain_loader.py

key-decisions:
  - "DomainFilters is a plain BaseModel (not BaseSettings), matching DomainManifest/SourceEntry's exact style — no Field(default_factory=...) needed since Pydantic v2 clones mutable defaults safely"
  - "thresholds: dict[str, float] validated and available on DomainFilters but intentionally NOT consumed by classify_sections() in this phase (RESOLVED ASSUMPTION, RESEARCH.md A3) — reserved for a future phase's override-vs-compose wiring"
  - "filters.yaml loading placed as step 3b, after taxonomy.yaml (step 3) and before the Jinja2 environment (step 4), to keep the four mandatory-file loads visually grouped ahead of the one optional load"

patterns-established:
  - "Domain-pack optional-file convention: a file absent from a pack's directory sets the corresponding DomainLoader attribute to None rather than raising, distinct from the four mandatory files which raise FileNotFoundError"

requirements-completed: [CLEAN-06]

coverage:
  - id: D1
    description: "DomainFilters model exists with boilerplate_patterns/normative_allowlists/thresholds fields, each defaulting to an empty container"
    requirement: "CLEAN-06"
    verification:
      - kind: unit
        ref: "tests/unit/test_domain_loader.py::test_domain_filters_model_defaults"
        status: pass
    human_judgment: false
  - id: D2
    description: "DomainLoader.filters is None (no exception) for packs without filters.yaml (aviation); is a populated DomainFilters instance for healthcare"
    requirement: "CLEAN-06"
    verification:
      - kind: unit
        ref: "tests/unit/test_domain_loader.py::test_domain_loader_aviation_has_no_filters, test_domain_loader_healthcare_has_filters"
        status: pass
    human_judgment: false
  - id: D3
    description: "healthcare filters.yaml's normative_allowlists contains ICD-10, LOINC, RxNorm and decodes UTF-8 regex strings (including the § section-symbol pattern) correctly via yaml.safe_load"
    requirement: "CLEAN-06"
    verification:
      - kind: unit
        ref: "tests/unit/test_domain_loader.py::test_domain_loader_healthcare_has_filters"
        status: pass
    human_judgment: false

duration: 8min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 2: Domain Filters Loader Summary

**`DomainLoader` gains optional `filters.yaml` support (CLEAN-06): a new `DomainFilters` Pydantic model, a never-raise-on-absence load in `DomainLoader.__init__`, and a `domains/healthcare/filters.yaml` fixture carrying the healthcare pack's clinical-code allowlist — the domain-pack-contributed half of the allowlist mechanism Plan 19-04's `classify_sections()` will consume.**

## Performance

- **Duration:** 8 min
- **Tasks:** 2
- **Files modified:** 4 (1 new, 3 modified)

## Accomplishments
- Added `DomainFilters(BaseModel)` to `src/knowledge_lake/domains/models.py` — `boilerplate_patterns: list[str] = []`, `normative_allowlists: list[str] = []`, `thresholds: dict[str, float] = {}`, with a class docstring warning pack authors against broad allowlist patterns (`.*`) and degenerate threshold overrides (`min_token_count: 0`)
- Wired `DomainLoader.__init__` to load `filters.yaml` as step 3b: an explicit `if filters_yaml_path.exists()` branch that sets `self.filters = None` on absence — never `raise FileNotFoundError`, unlike the four mandatory files (domain.yaml, sources.yaml, taxonomy.yaml, prompts/, validators/validate.py) loaded earlier in the same method
- Created `domains/healthcare/filters.yaml` with `normative_allowlists: ["ICD-10", "LOINC", "RxNorm", "§\\d+\\.\\d+", "\\d+\\s*mg", "PO\\s+BID"]`, empty `boilerplate_patterns` and `thresholds`
- Extended `tests/unit/test_domain_loader.py` with 3 new tests: `test_domain_loader_healthcare_has_filters`, `test_domain_loader_aviation_has_no_filters` (the Pitfall-4 regression guard proving a pack without `filters.yaml` still loads cleanly), `test_domain_filters_model_defaults`

## Task Commits

Each task was committed atomically:

1. **Task 1: Add DomainFilters model and optional filters.yaml loading** - `563d0f8` (feat)
2. **Task 2: Add healthcare filters.yaml fixture and extend domain loader tests** - `a5021ec` (test)

**Plan metadata:** (this commit)

## Files Created/Modified
- `src/knowledge_lake/domains/models.py` - New `DomainFilters` class
- `src/knowledge_lake/domains/loader.py` - Import update, `self.filters` optional load (step 3b), docstring update
- `domains/healthcare/filters.yaml` - New fixture, clinical-code allowlist
- `tests/unit/test_domain_loader.py` - 3 new tests (9 total in file)

## Decisions Made
- `DomainFilters` as plain `BaseModel` matching `DomainManifest`/`SourceEntry` style exactly (no `Field(default_factory=...)`)
- `thresholds` validated but intentionally unconsumed by `classify_sections()` in this phase (RESOLVED ASSUMPTION per RESEARCH.md A3) — reserved field for a later phase
- `filters.yaml` load placed as step 3b (after taxonomy.yaml, before the Jinja2 environment) to keep it visually distinct from the four mandatory loads

## Deviations from Plan
None. Implementation followed the plan's exact field names, docstring content, YAML structure, and test names.

## Issues Encountered
None.

## Verification
- `uv run pytest tests/unit/test_domain_loader.py -x -q` → 9 passed (6 pre-existing + 3 new)
- `uv run python -c "from knowledge_lake.domains.models import DomainFilters; assert DomainFilters().thresholds == {}"` → passes
- Full unit suite: `uv run pytest tests/unit -q` → 824 passed, 1 xfailed (pre-existing), 0 failed — up from 821 passed in Plan 19-01, exactly +3 new tests, no regressions

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `DomainLoader.filters` (`DomainFilters | None`) is ready for Plan 19-04's `classify_sections()` to accept as an explicit `domain_filters` parameter and read `.normative_allowlists` / `.boilerplate_patterns` from
- `domains/healthcare/filters.yaml`'s clinical-code allowlist is in place to protect content like "ICD-10 E11.9" or "Metformin 500 mg PO BID" from boilerplate misclassification once Plan 19-04 wires the consumption
- `thresholds` remains reserved, unconsumed infrastructure — no follow-up required for Phase 19, flagged for a future phase per the RESOLVED ASSUMPTION

---
*Phase: 19-section-classifier-patterns*
*Completed: 2026-07-16*
