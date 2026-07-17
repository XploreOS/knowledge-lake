---
phase: 20-chunk-substance-gate-export-gate
plan: 01
subsystem: pipeline
tags: [chunk, quality-gate, datatrove, fineweb, pydantic-settings, wr-05, cache-versioning]

# Dependency graph
requires:
  - phase: 19-section-classifier-patterns
    provides: pipeline/quality/ pure predicate module (run_predicates, check_* predicates), DomainFilters model, healthcare filters.yaml
provides:
  - ChunkQualitySettings Pydantic model (settings.chunk_quality)
  - chunk()'s composite substance gate (FineWebQualityFilter + Phase 19 predicates + domain allowlist exemption)
  - chunk()'s new domain_filters keyword parameter
  - PIPE-01 filter_config_version-sensitive WR-05 content hash
  - substance_passed/rejection_reason persisted on every chunk artifact (both cache-hit and new-artifact branches)
affects: [20-02 (Dagster/CLI DomainLoader wiring, cache-check call sites), 20-03 (export_rag_corpus substance_passed filter, datasets.py version tagging)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deferred-import factory for stateful DataTrove filters (_build_fineweb_filter), mirrors curate.py::_build_filters()"
    - "Pure, DB-free gate helper (_apply_substance_gate) extracted from chunk() for independent unit-testability without Postgres/S3 fixtures"
    - "QUAL-05 conservation invariant as its own testable helper (_assert_chunk_conservation_invariant), mirrors clean.py's log-then-RuntimeError shape"

key-files:
  created:
    - tests/unit/test_chunk_substance_gate.py
  modified:
    - src/knowledge_lake/config/settings.py
    - src/knowledge_lake/pipeline/chunk.py
    - tests/unit/test_chunk_storage.py

key-decisions:
  - "Extracted gate logic into _apply_substance_gate(), a pure/DB-free internal helper, rather than inlining it into chunk()'s body — makes gate-decision unit tests fast and independent of Postgres/S3 fixtures, and cleanly hands off substance_passed/rejection_reason-annotated raw dicts to the existing persistence loop"
  - "filter_config_version default '1.0' (ChunkQualitySettings) deliberately differs from CurateSettings.filter_config_version's 'v1' default — the two caches are intentionally independent (RESEARCH.md Assumption A3)"
  - "Added a defensive `import importlib.metadata` at module top per RESEARCH.md Pitfall 4, even though empirically a non-issue in chunk.py's actual import order"

patterns-established:
  - "Pattern: wrap a stateful DataTrove filter class as a run_predicates()-compatible predicate via functools.partial + a thin adapter function that handles the bool|tuple[bool,str] outcome shape"

requirements-completed: [QUAL-02, QUAL-03, PIPE-01]

coverage:
  - id: D1
    description: "ChunkQualitySettings model with 9 fields at stated defaults, registered as Settings.chunk_quality, env-var overridable"
    requirement: "QUAL-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_chunk_substance_gate.py (module import + settings assertions run inline during Task 1 verify)"
        status: pass
    human_judgment: false
  - id: D2
    description: "chunk() gates every produced chunk through a composite substance predicate (FineWebQualityFilter + domain allowlist + Phase 19 threshold predicates); is_table always exempt; enforce/report modes behave per D-13"
    requirement: "QUAL-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_chunk_substance_gate.py#test_apply_substance_gate_allowlist_exemption_passes"
        status: pass
      - kind: unit
        ref: "tests/unit/test_chunk_substance_gate.py#test_apply_substance_gate_is_table_exempt_regardless_of_text"
        status: pass
      - kind: unit
        ref: "tests/unit/test_chunk_substance_gate.py#test_apply_substance_gate_enforce_mode_excludes_nav_junk"
        status: pass
      - kind: unit
        ref: "tests/unit/test_chunk_substance_gate.py#test_apply_substance_gate_report_mode_annotates_but_keeps_nav_junk"
        status: pass
      - kind: unit
        ref: "tests/unit/test_chunk_substance_gate.py#test_fineweb_predicate_exact_line_punct_boundary_passes"
        status: pass
      - kind: unit
        ref: "tests/unit/test_chunk_substance_gate.py#test_apply_substance_gate_is_deterministic_across_repeated_calls"
        status: pass
    human_judgment: false
  - id: D3
    description: "QUAL-05 conservation invariant enforced with RuntimeError (not bare assert), chunk-level rejections logged unconditionally via chunk.substance_gate.complete"
    verification:
      - kind: unit
        ref: "tests/unit/test_chunk_substance_gate.py#test_chunk_conservation_invariant_raises_runtime_error_on_violation"
        status: pass
    human_judgment: false
  - id: D4
    description: "filter_config_version folded into the WR-05 per-chunk content hash (PIPE-01) — a version bump produces a new content_hash/artifact; same-version calls still hit the pre-existing single-write cache"
    requirement: "PIPE-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_chunk_storage.py#test_chunk_different_filter_config_version_produces_different_content_hash"
        status: pass
      - kind: unit
        ref: "tests/unit/test_chunk_storage.py#test_chunk_same_filter_config_version_hits_existing_cache"
        status: pass
    human_judgment: false
  - id: D5
    description: "Both the existing-hit and new-artifact persistence branches carry substance_passed/rejection_reason sourced fresh from the gate computation, never stale metadata"
    verification:
      - kind: unit
        ref: "tests/unit/test_chunk_storage.py#test_chunk_existing_hit_branch_carries_substance_gate_keys"
        status: pass
    human_judgment: false

duration: 13min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 01: Chunk Substance Gate Wiring Summary

**Wires DataTrove's FineWebQualityFilter and Phase 19's pure predicate module into `chunk()` as a composite substance gate (enforce/report modes, `is_table`/domain-allowlist exemptions), and folds `filter_config_version` into the WR-05 per-chunk content hash so a threshold change forces re-processing.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-07-17T02:47:33Z
- **Completed:** 2026-07-17T03:00:13Z
- **Tasks:** 3 completed
- **Files modified:** 3 (1 created: test_chunk_substance_gate.py; 2 modified: settings.py, chunk.py; test_chunk_storage.py extended)

## Accomplishments
- `ChunkQualitySettings` Pydantic model (gate_mode, 4 threshold overrides, 3 FineWebQualityFilter params, filter_config_version) registered as `settings.chunk_quality`
- `chunk()` gains a `domain_filters: DomainFilters | None = None` keyword parameter and now runs every produced chunk through a composite substance gate before persistence
- Gate predicate order `[check_table_exemption, domain_allowlist, fineweb, token_floor, alpha_ratio, link_density, stopword_ratio, terminal_punct_ratio]` — exemptions short-circuit first, mirroring `classify_sections()`'s ordering discipline
- QUAL-05 conservation invariant (`kept + rejected == total_generated`) enforced via `RuntimeError`, mirroring `clean.py`'s log-then-raise shape
- Every rejection is logged unconditionally (`chunk.substance_gate.complete`, both enforce and report mode) — closes the chunk-level rejection audit-trail gap
- PIPE-01: `filter_config_version` folded into the existing WR-05 per-chunk content hash; a config bump produces new `content_hash`/artifacts, same-version calls still hit the pre-existing single-write cache
- Both persistence branches (cache-hit and new-artifact) now carry `substance_passed`/`rejection_reason`, sourced fresh from the gate computation every call — idempotent by construction

## Task Commits

Each task was committed atomically (Tasks 2 and 3 are `tdd="true"`, split into RED/GREEN commits):

1. **Task 1: Add ChunkQualitySettings model** - `3143328` (feat)
2. **Task 2: Wire the composite substance gate into chunk()** - `3a02948` (test, RED) → `2230eba` (feat, GREEN)
3. **Task 3: Fold filter_config_version into hash, persist gate outcome** - `85e8e9c` (test, RED) → `3baa22b` (feat, GREEN)

**Additional test coverage (Rule 2):** `5aac19a` (test) — pinned FineWebQualityFilter's empty-lines `(False, "empty")` rejection behavior, a must-have truth in the plan frontmatter not covered by any task's explicit test list.

_Note: TDD tasks produced test → feat commit pairs, matching the plan's task boundaries._

## TDD Gate Compliance

Both `tdd="true"` tasks (2, 3) followed the RED/GREEN cycle:
- Task 2: `test(20-01)` commit `3a02948` (RED, confirmed failing via `ImportError` before implementation) → `feat(20-01)` commit `2230eba` (GREEN, 18/18 new tests pass)
- Task 3: `test(20-01)` commit `85e8e9c` (RED, confirmed failing assertion before hash-formula change) → `feat(20-01)` commit `3baa22b` (GREEN, 3/3 new tests pass)

No REFACTOR commits were needed — no cleanup required after either GREEN phase.

## Files Created/Modified
- `src/knowledge_lake/config/settings.py` - `ChunkQualitySettings` class + `Settings.chunk_quality` field
- `src/knowledge_lake/pipeline/chunk.py` - `_build_fineweb_filter()`, `_fineweb_predicate()`, `_assert_chunk_conservation_invariant()`, `_apply_substance_gate()`, `chunk()`'s new `domain_filters` param and gate wiring, PIPE-01 hash formula, gate-outcome persistence in both branches
- `tests/unit/test_chunk_substance_gate.py` - new file: 19 tests covering gate logic, exemptions, enforce/report modes, FineWebQualityFilter boundary/empty-lines pinning, conservation invariant, end-to-end `chunk()` wiring
- `tests/unit/test_chunk_storage.py` - extended with 3 PIPE-01 cache-versioning tests

## Decisions Made
- Extracted `_apply_substance_gate()` as a pure, DB-free helper (Claude's discretion per CONTEXT.md "internal wiring... left to Claude's discretion") rather than inlining the gate loop directly in `chunk()`'s body. This let Task 2's tests exercise gate-decision logic (including the "substance_passed/rejection_reason in its dict" acceptance criterion) without needing the full Postgres/S3 fixture stack that `chunk()`'s persistence loop requires — while `chunk()` itself still calls the helper exactly where the plan specified (immediately after `_build_token_chunks()`, before the persistence loop).
- `ChunkQualitySettings.filter_config_version` default `"1.0"` deliberately differs from `CurateSettings.filter_config_version`'s `"v1"` default (RESEARCH.md Assumption A3) — the two caches are intentionally independent.
- Added a defensive `import importlib.metadata` at chunk.py's module top (RESEARCH.md Pitfall 4) — zero-downside belt-and-suspenders even though empirically a non-issue given chunk.py's actual import order (structlog/tiktoken already trigger the binding).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added a direct regression test for FineWebQualityFilter's "empty" rejection reason**
- **Found during:** Final review against the plan's `must_haves.truths` list
- **Issue:** The plan's frontmatter explicitly lists "An empty-lines chunk ... returns (False, 'empty') per datatrove's own filter() source ... NOT an exemption" as a must-have truth, but none of Task 2's named test cases (allowlist exemption, is_table exemption, clinical-prose pass, nav-junk enforce/report modes, boundary pass, determinism) covered it.
- **Fix:** Added `test_fineweb_predicate_empty_lines_fails_with_empty_reason`, verified empirically against the installed `datatrove==0.9.0` wrapper before writing the assertion.
- **Files modified:** `tests/unit/test_chunk_substance_gate.py`
- **Verification:** `pytest tests/unit/test_chunk_substance_gate.py -x` (19/19 pass)
- **Committed in:** `5aac19a`

---

**Total deviations:** 1 auto-fixed (1 missing test coverage for a stated must-have truth)
**Impact on plan:** No scope creep — pure test-coverage addition confirming already-correct behavior of the wrapper built in Task 2. No production code changed by this deviation.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. `datatrove==0.9.0` was already installed and pinned; no new dependencies.

## Next Phase Readiness

- `chunk()`'s `domain_filters` parameter exists and is exercised end-to-end in this plan's own tests, but is **not yet resolved automatically** by `chunk_document` (Dagster asset) or `process_crawled` (CLI/API path) — that DomainLoader-based resolution wiring is explicitly Plan 20-02's scope (RESEARCH.md Pattern 2, Pitfall 1). Until 20-02 lands, production pipeline runs will call `chunk()` with `domain_filters=None`, meaning MEAS-02's clinical-code protection is inert end-to-end even though the mechanism itself (this plan) is complete and tested.
- `substance_passed`/`rejection_reason` are now persisted in every chunk artifact's `metadata_` — ready for Plan 20-03's `export_rag_corpus()` pre-filter (EXPORT-01) to consume directly, no further chunk.py changes needed for that integration.
- `ChunkQualitySettings.filter_config_version` is ready for Plan 20-03's eval-dataset version tagging (EXPORT-02, D-12) to derive from.
- Full test suite (1076 tests, 0 failed, 3 skipped, 6 xfailed) verified green after all 3 tasks — no regressions introduced.

---
*Phase: 20-chunk-substance-gate-export-gate*
*Completed: 2026-07-17*

## Self-Check: PASSED

All 4 modified/created files confirmed present on disk; all 6 task commit hashes confirmed present in `git log`. Full test suite (`pytest tests/`) verified green (1076 passed, 3 skipped, 6 xfailed, 0 failed) after the final task commit.
