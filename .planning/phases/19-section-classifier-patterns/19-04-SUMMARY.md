---
phase: 19-section-classifier-patterns
plan: 04
subsystem: pipeline
tags: [clean-04, section-classifier, boilerplate, allowlist, tdd]

# Dependency graph
requires:
  - phase: 19-section-classifier-patterns
    provides: "pipeline/quality/ predicate module (PredicateResult, run_predicates, compute_substance_signals, check_* predicates) — Plan 19-01"
  - phase: 19-section-classifier-patterns
    provides: "DomainFilters model + DomainLoader.filters optional load — Plan 19-02"
  - phase: 19-section-classifier-patterns
    provides: "BOILERPLATE_PATTERNS extended to 9 entries — Plan 19-03"
provides:
  - "classify_sections() — pure, standalone per-section substance classifier (CLEAN-04, D-01) combining BOILERPLATE_PATTERNS/domain-extra-pattern matching with pipeline.quality predicates and an unconditional domain-allowlist override"
  - "_clean_sections()/clean() now actually DROP sections classified as boilerplate from cleaned_doc.sections — supersedes Phase 17's placeholder 'annotate all, drop none' behavior"
  - "section_annotations persisted for every input section (kept and rejected) in clean()'s result dict and cleaned_document.metadata_"
  - "clean() gains an optional domain_filters keyword param (default None, existing callers unaffected)"
affects: [20-chunk-substance-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "classify_sections() runs independently of remove_boilerplate() — classification always inspects section.text (raw), never the boilerplate-stripped text, so pattern/predicate decisions are made before any stripping side effects"
    - "Precedence in _clean_sections(): empty-after-strip check first, then classify_sections()'s is_boilerplate flag, then keep — an empty-after-strip section is rejected regardless of allowlist status since there is no content left to keep"
    - "Domain allowlist as an unconditional override: check_domain_allowlist() is evaluated before any BOILERPLATE_PATTERNS/predicate check and short-circuits classify_sections() entirely when it passes"

key-files:
  created: []
  modified:
    - src/knowledge_lake/pipeline/clean.py
    - tests/unit/test_clean.py

key-decisions:
  - "For a KEPT section's annotation, 'reason' is set to classification['reason'] (typically 'substance_ok', or the allowlist's own match reason) rather than a new literal — the plan's 'reason string used for that branch' language only names explicit reasons for the two rejection branches, so the kept branch reuses classify_sections()'s own computed reason for a coherent, non-redundant audit trail"
  - "TDD RED phase used two new direct unit tests against classify_sections() itself (distinguishing nav vs. clinical, and the allowlist override) rather than reusing Task 2's clean()-level acceptance tests verbatim — keeps the RED/GREEN cycle focused on the pure function's contract, with Task 2 then adding the full clean()-level integration tests as ordinary (non-TDD) test additions per the plan's task split"
  - "GREEN commit intentionally left 4 pre-existing Phase-17 tests failing (by plan design — the plan explicitly identifies these 4 as needing an update in Task 2); this is expected TDD-task-boundary behavior, not a broken build, since Task 2 fixes them in the same plan before any external verification gate runs"

patterns-established:
  - "Section-level classification always operates on raw section.text, decoupled from remove_boilerplate()'s line-level stripping which still runs afterward on survivors"

requirements-completed: [CLEAN-04]

coverage:
  - id: D1
    description: "classify_sections() computes per-section substance signals, is_boilerplate, allowlisted, and reason for every input section without mutating or dropping any (D-01 separation of concerns)"
    requirement: "CLEAN-04"
    verification:
      - kind: unit
        ref: "tests/unit/test_clean.py::test_classify_sections_distinguishes_boilerplate_from_clinical"
        status: pass
      - kind: unit
        ref: "tests/unit/test_clean.py::test_classify_sections_allowlist_override"
        status: pass
    human_judgment: false
  - id: D2
    description: "_clean_sections()/clean() actually drop sections classified as boilerplate from cleaned_doc.sections — a document with nav, footer, and clinical sections retains only the clinical one"
    requirement: "CLEAN-04"
    verification:
      - kind: unit
        ref: "tests/unit/test_clean.py::TestClassifySectionsCleanIntegration::test_classify_sections_drops_nav_and_footer_keeps_clinical"
        status: pass
      - kind: unit
        ref: "tests/unit/test_clean.py::TestCleanParsedDocThreading::test_cleaned_doc_preserves_section_count"
        status: pass
    human_judgment: false
  - id: D3
    description: "A domain allowlist match unconditionally overrides is_boilerplate for short clinical codes (ICD-10) and dosage patterns (mg), even when they would otherwise fail check_token_floor"
    requirement: "CLEAN-04"
    verification:
      - kind: unit
        ref: "tests/unit/test_clean.py::TestClassifySectionsCleanIntegration::test_classify_sections_allowlist_overrides_short_clinical_code"
        status: pass
      - kind: unit
        ref: "tests/unit/test_clean.py::TestClassifySectionsCleanIntegration::test_classify_sections_allowlist_overrides_dosage_pattern"
        status: pass
    human_judgment: false
  - id: D4
    description: "section_annotations is persisted in clean()'s result dict for every input section (kept and rejected alike), each entry carrying index/signals/allowlisted/decision/reason"
    requirement: "CLEAN-04"
    verification:
      - kind: unit
        ref: "tests/unit/test_clean.py::TestClassifySectionsCleanIntegration::test_section_annotations_persisted_for_all_sections"
        status: pass
    human_judgment: false
  - id: D5
    description: "_clean_sections([]) edge-probe and idempotency (exact-dup branch) invariants continue to hold under the new 6-tuple signature"
    requirement: "CLEAN-04"
    verification:
      - kind: unit
        ref: "tests/unit/test_clean.py::TestCleanConservationInvariant::test_clean_sections_empty_input_no_raise"
        status: pass
      - kind: unit
        ref: "tests/unit/test_clean.py::TestCleanConservationInvariant::test_unconditional_counting_on_exact_dup_branch"
        status: pass
    human_judgment: false
  - id: D6
    description: "Cross-file regression set (quality_audit, process_crawled_clean, gate_signature_pin, domain_loader, quality_predicates) remains green — clean()'s new optional domain_filters parameter and 6th internal return value do not affect callers that only read clean_result by dict key"
    requirement: "CLEAN-04"
    verification:
      - kind: unit
        ref: "uv run pytest tests/unit/test_clean.py tests/unit/test_quality_audit.py tests/unit/test_process_crawled_clean.py tests/unit/test_gate_signature_pin.py tests/unit/test_domain_loader.py tests/unit/test_quality_predicates.py -x -q"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 4: Section Classifier Integration Summary

**`classify_sections()` wired into `clean.py`'s `_clean_sections()`/`clean()` flow via full TDD (RED→GREEN), actually dropping boilerplate sections from `cleaned_doc.sections` while an unconditional domain-allowlist override protects clinical codes and dosage patterns — the integration point where Plans 19-01/02/03's mechanisms become load-bearing (CLEAN-04).**

## Performance

- **Duration:** 12 min
- **Started:** 2026-07-16T17:24:58Z
- **Completed:** 2026-07-16T17:37:10Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added `classify_sections()` to `clean.py` — a new, standalone, pure function computing per-section substance signals (`compute_substance_signals()`), an `is_boilerplate` flag, and an `allowlisted` flag/reason for every section, using `pipeline.quality`'s predicates (Plan 19-01) with `check_domain_allowlist` as an unconditional Pitfall-3 override ahead of `BOILERPLATE_PATTERNS`/domain-extra-pattern matching and the threshold-predicate chain
- `_clean_sections()` now calls `classify_sections()` once upfront and, per section, applies the precedence (1) empty-after-boilerplate-strip → reject, (2) classified as boilerplate → reject, (3) else → keep — actually dropping rejected sections from the returned list (CLEAN-04's core behavioral change, superseding Phase 17's placeholder). Gained a `domain_filters` keyword param and a 6th return value, `section_annotations`, recorded for every section regardless of outcome
- `clean()` gained an optional `domain_filters: DomainFilters | None = None` keyword param (existing callers unaffected — `process.py`, `dagster_defs/assets.py`, `quality_audit.py` continue to omit it), threaded through to `_clean_sections()`, with `section_annotations` persisted in all three of clean()'s dict-building sites (exact-dup branch, registry metadata, final result)
- Updated stale Phase-17 docstrings/comments referencing "CLEAN-04 section removal is Phase 19's job" across `_clean_sections()` and `clean()` to describe the new drop-on-classify contract
- Updated the 4 identified pre-existing tests to match the new signature/behavior, and added 6 new tests: 2 direct `classify_sections()` unit tests (TDD RED/GREEN) plus 4 `clean()`-level integration tests (nav/footer drop, ICD-10 allowlist override, dosage-pattern allowlist override, section_annotations persistence)

## Task Commits

Each task was committed atomically (Task 1 followed full TDD RED→GREEN):

1. **Task 1 RED: add failing tests for classify_sections()** - `277c05e` (test)
2. **Task 1 GREEN: implement classify_sections() and wire drop-on-classify into _clean_sections()/clean()** - `f0a4d60` (feat)
3. **Task 2: update Phase-17 tests and add clean()-level classifier tests** - `0e738ec` (test)

**Plan metadata:** (this commit)

## TDD Gate Compliance

Task 1 (`tdd="true"`) followed RED→GREEN:
- RED commit `277c05e`: `test_classify_sections_distinguishes_boilerplate_from_clinical` and `test_classify_sections_allowlist_override` added, confirmed failing with `ImportError: cannot import name 'classify_sections'` (feature did not exist yet — correct failure reason).
- GREEN commit `f0a4d60`: `classify_sections()` implemented plus `_clean_sections()`/`clean()` wiring; both RED tests re-run and confirmed passing.
- No REFACTOR commit — implementation matched the plan's behavior spec directly with no obvious cleanup needed after GREEN.
- Gate check: `git log --oneline --grep="^test(19-04)"` → 2 hits (`277c05e`, `0e738ec`); `git log --oneline --grep="^feat(19-04)"` → 1 hit (`f0a4d60`). RED precedes GREEN. Compliant.

Note: the GREEN commit intentionally left 4 pre-existing Phase-17 tests failing — this was by plan design (Task 2's explicit job is to update those 4 tests for the new drop-on-classify behavior), not a TDD violation; Task 2's commit restored the full suite to green before this plan's verification ran.

## Files Created/Modified
- `src/knowledge_lake/pipeline/clean.py` - Added `classify_sections()`; changed `_clean_sections()` signature (+`domain_filters`, 6th return value `section_annotations`) and drop-on-classify behavior; changed `clean()` signature (+`domain_filters`), call site, and 3 dict-building sites (+`section_annotations`); updated docstrings/comments
- `tests/unit/test_clean.py` - 2 new direct `classify_sections()` tests (RED/GREEN), 4 pre-existing tests updated for the new signature/behavior, 4 new `clean()`-level integration tests in a new `TestClassifySectionsCleanIntegration` class

## Decisions Made
- Kept-section annotations use `classification["reason"]` (e.g. `"substance_ok"` or the allowlist match reason) rather than inventing a new literal, since the plan only names explicit reason strings for the two rejection branches
- TDD RED tests target `classify_sections()` directly (pure-function contract) rather than duplicating Task 2's `clean()`-level acceptance tests, keeping the RED/GREEN cycle tight and avoiding redundant test authorship
- No REFACTOR commit — GREEN implementation followed the plan's exact behavior spec with no cleanup opportunity identified

## Deviations from Plan

None - plan executed exactly as written. The GREEN-phase interim test failures (4 pre-existing tests) were explicitly anticipated and assigned to Task 2 by the plan itself, not an unplanned deviation.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- CLEAN-04 is now fully wired: `classify_sections()` is load-bearing in `clean()`'s section-granularity path, and `section_annotations` is available in both the returned dict and `cleaned_document.metadata_` for downstream quality-audit tooling
- Full unit suite verified green after this plan: `uv run pytest tests/unit -q` → 837 passed, 1 xfailed (pre-existing), 0 failed — up from 831 passed after Plan 19-03, exactly +6 new tests, no regressions
- Automatic `DomainLoader`-based resolution of `domain_filters` into `process.py`/`dagster_defs/assets.py`/`quality_audit.py` call sites remains explicitly out of scope for Phase 19 (per D-12's framing) — flagged as follow-up work for a later phase, consistent with Phase 19's mandate to build the mechanism only
- This is Phase 19's final plan (4 of 4) — Wave 2 complete, phase ready for phase-level verification

---
*Phase: 19-section-classifier-patterns*
*Completed: 2026-07-16*
