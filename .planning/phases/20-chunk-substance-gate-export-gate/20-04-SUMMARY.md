---
phase: 20-chunk-substance-gate-export-gate
plan: 04
subsystem: pipeline
tags: [meas-02, ci-fixtures, chunk, substance-gate, domain-loader, must-not-reject]

# Dependency graph
requires:
  - phase: 20-chunk-substance-gate-export-gate
    provides: "20-01: chunk()'s domain_filters keyword parameter, composite substance gate; 20-02: chunk_document/process_crawled resolving domain_filters via DomainLoader in production, cardinality_constraint pattern added to filters.yaml"
provides:
  - "tests/fixtures/must_not_reject.yaml — 25 hand-labeled clinical fixtures (5 per MEAS-02 category)"
  - "tests/unit/test_must_not_reject.py — parametrized CI proof that every fixture survives the real chunk() substance gate with domain_filters resolved via the real DomainLoader"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-level fixture-count assertion (len(fixtures) >= 20) fires at pytest collection time, not per-test — an accidentally-emptied YAML fails loudly instead of silently collecting 0 parametrized cases"
    - "Every fixture text deliberately authored to match one of healthcare filters.yaml's 7 normative_allowlists patterns via re.search, guaranteeing the domain-allowlist EXEMPTION predicate short-circuits before any FineWebQualityFilter/threshold predicate runs — mirrors RESEARCH.md's own empirical proof (Pitfall 1) that bare ICD-10/dosage/etc. codes fail those predicates without the allowlist rescue"

key-files:
  created:
    - tests/fixtures/must_not_reject.yaml
    - tests/unit/test_must_not_reject.py
  modified: []

key-decisions:
  - "25 fixture entries (5 per category) rather than the plan's stated ~20 minimum — round, easy-to-audit distribution across all 5 MEAS-02 categories"
  - "Every fixture text intentionally matches one of the 7 domains/healthcare/filters.yaml normative_allowlists patterns (ICD-10, LOINC, RxNorm, §\\d+\\.\\d+, \\d+\\s*mg, PO\\s+BID, \\d+\\s*(?:of|/)\\s*\\d+) — makes the fixture set a direct, unambiguous proof of Plan 20-02's DomainLoader wiring rather than relying on some entries naturally clearing FineWebQualityFilter/threshold defaults on their own"
  - "Task 2's tdd=\"true\" cycle produced a single test commit, not a test->feat pair — writing the test passed immediately (GREEN) since the underlying machinery (chunk()'s domain_filters wiring from 20-01/20-02, and this plan's own Task 1 fixture data) was already fully implemented before Task 2 ran. Verified non-vacuous via local corruption (see TDD Gate Compliance)."

patterns-established: []

requirements-completed: [MEAS-02]

coverage:
  - id: D1
    description: "tests/fixtures/must_not_reject.yaml contains >= 20 entries (25 authored), each with label/text/category, spanning all 5 MEAS-02 categories with >= 4 entries each (5 each)"
    requirement: "MEAS-02"
    verification:
      - kind: unit
        ref: "Plan-specified verify script (yaml.safe_load + category/label/key assertions) — ran directly, OK 25 {'icd_code': 5, 'dosage': 5, 'loinc': 5, 'hipaa_ref': 5, 'cardinality_constraint': 5}"
        status: pass
    human_judgment: false
  - id: D2
    description: "A parametrized pytest test loads the YAML and calls the real chunk() (Plan 20-01) with domain_filters resolved via DomainLoader.from_name('healthcare').filters (Plan 20-02's production pattern), asserting every fixture entry survives with substance_passed=True"
    requirement: "MEAS-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_must_not_reject.py::test_fixture_survives_real_chunk_substance_gate (25/25 parametrized cases pass)"
        status: pass
    human_judgment: false
  - id: D3
    description: "CI fails (non-zero exit, red assertion) if any fixture entry is rejected — proven non-vacuous by deliberately corrupting one fixture entry's text to nav-junk locally (not committed) and confirming exactly that one parametrized case fails with a label/category/rejection_reason message while the other 24 still pass"
    requirement: "MEAS-02"
    verification:
      - kind: unit
        ref: "Manual local verification: temporarily replaced icd_diabetes_1's text with 'Home About Contact Sitemap Search', re-ran suite — 1 failed (icd_diabetes_1, rejection_reason=line_punct_ratio), 24 passed; file restored, git diff confirmed clean before commit"
        status: pass
    human_judgment: false
  - id: D4
    description: "The must_not_reject.yaml fixture list is asserted non-empty and >= 20 at test-collection time (module-level assertion), not a per-test assertion"
    requirement: "MEAS-02"
    verification:
      - kind: unit
        ref: "tests/unit/test_must_not_reject.py module-level assert (len(_FIXTURES) >= 20), fires before pytest.mark.parametrize builds the case list"
        status: pass
    human_judgment: false

duration: 10min
completed: 2026-07-17
status: complete
---

# Phase 20 Plan 04: Must-Not-Reject CI Fixture Set Summary

**Ships `tests/fixtures/must_not_reject.yaml` (25 hand-labeled clinical fixtures across ICD-10, dosage, LOINC, HIPAA §-reference, and cardinality-constraint categories) and `tests/unit/test_must_not_reject.py`, a parametrized CI test proving every entry survives the real `chunk()` substance gate with `domain_filters` resolved exactly as production resolves it via `DomainLoader.from_name("healthcare")`.**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-07-17
- **Tasks:** 2 completed
- **Files created:** 2 (tests/fixtures/must_not_reject.yaml, tests/unit/test_must_not_reject.py)

## Accomplishments

- `tests/fixtures/must_not_reject.yaml` — 25 entries (5 per category: `icd_code`, `dosage`, `loinc`, `hipaa_ref`, `cardinality_constraint`), each with exactly `label`/`text`/`category` keys, unique labels, leading YAML comment documenting the representative-sample (not exhaustive) scope boundary
- Every fixture text was deliberately authored to match one of `domains/healthcare/filters.yaml`'s 7 `normative_allowlists` patterns (verified via a standalone `re.search` script before committing) — this makes the fixture set a direct proof of Plan 20-02's `DomainLoader` wiring, mirroring RESEARCH.md's own empirical finding (Pitfall 1) that bare clinical codes fail `check_alpha_ratio`/`FineWebQualityFilter` without the allowlist exemption
- `tests/unit/test_must_not_reject.py` — module-level `len(fixtures) >= 20` assertion fires at pytest collection time (not per-test); `pytest.mark.parametrize("entry", fixtures, ids=[...])` preserves YAML list order; each parametrized case seeds a source+parsed artifact, builds a `ParsedDoc` with the fixture text as a single `Section`, resolves `domain_filters = DomainLoader.from_name("healthcare").filters` (real filesystem load, not mocked), calls the real `chunk()`, and asserts every returned chunk has `substance_passed=True` with a label/category/rejection_reason-inclusive failure message
- All 25 parametrized cases pass; iterates every chunk returned per fixture (not just the first) per the plan's stated defensive requirement
- Proved the test is not vacuously green: locally (not committed) corrupted one fixture entry's text to nav-junk and confirmed exactly that one parametrized case failed with a clear diagnostic message, while the other 24 remained green
- Full suite verified green after both tasks: 1114 passed, 3 skipped, 6 xfailed, 0 failed (up from 1079 at the start of Phase 20 — 35 new tests across the phase's 4 plans, no regressions)

## Task Commits

1. **Task 1: Author the must_not_reject.yaml fixture set** - `0fdffa4` (feat)
2. **Task 2: Parametrized CI test proving the fixture set survives chunk()'s gate** - `f736e47` (test)

_Note: Task 2 is `tdd="true"` but produced a single `test` commit rather than a RED→GREEN pair — see TDD Gate Compliance below._

## TDD Gate Compliance

Task 2 carries `tdd="true"` with a `<behavior>` block. Writing the test and running it immediately produced 25/25 passing cases (GREEN on first run, not RED) — because the underlying machinery this test exercises (`chunk()`'s `domain_filters` parameter and composite substance gate from Plan 20-01; `chunk_document`/`process_crawled`'s production `DomainLoader` resolution and the `cardinality_constraint` allowlist pattern from Plan 20-02; and this plan's own Task 1 fixture data, committed immediately prior) was already fully implemented and correct before Task 2 ran.

This is the same situation documented in `17-02-SUMMARY.md`'s TDD Gate Compliance section: a plan that deliberately splits implementation/data-authoring (Task 1) from proof-of-behavior (Task 2, `tdd="true"`) will see Task 2's test pass immediately rather than fail first, and that is the intended task decomposition — not a stale/no-op test. Per the fail-fast rule's own carve-out ("the feature may already exist"), this was investigated rather than blindly accepted: the test was proven non-vacuous by deliberately corrupting one fixture entry's text to a nav-junk string locally (temporarily, never committed — `tests/fixtures/must_not_reject.yaml`'s `git diff` was confirmed clean before the Task 2 commit) and re-running the suite. Result: exactly the corrupted case (`icd_diabetes_1`) failed with `rejection_reason=line_punct_ratio`, while the other 24 fixtures still passed — confirming the test genuinely exercises the gate mechanism rather than trivially passing regardless of input.

No REFACTOR commit was needed.

## Files Created

- `tests/fixtures/must_not_reject.yaml` — 25 clinical fixture entries across 5 MEAS-02 categories, with a leading YAML comment documenting the representative-sample scope boundary (satisfies the plan's prohibition-recall requirement)
- `tests/unit/test_must_not_reject.py` — parametrized test module; reuses `tests/unit/test_chunk_storage.py`'s exact `engine`/`_patch_engine`/`fake_storage`/`test_settings`/`_seed_source_and_parsed` fixture style for a real in-memory-SQLite + mocked-StorageBackend `chunk()` call

## Decisions Made

- Authored 25 fixture entries (5 per category) instead of the plan's stated ~20 minimum, for a clean, easy-to-audit 5-per-category distribution.
- Deliberately made every fixture text match one of the 7 `normative_allowlists` patterns in `domains/healthcare/filters.yaml`, rather than relying on some fixtures naturally clearing `FineWebQualityFilter`/threshold-predicate defaults without the allowlist. This makes every single entry a direct proof that Plan 20-02's `DomainLoader` wiring is what rescues it, matching RESEARCH.md's own empirical Pitfall-1 finding rather than leaving ambiguity about which mechanism (thresholds vs. allowlist) protected which entry.
- `Section(is_table=False)` used for every fixture (plan-specified) rather than exercising the `check_table_exemption` path — that predicate is intentionally out of this plan's scope (it's a known no-op for real parsers per Phase 19's research finding, tracked separately in PROJECT.md tech debt).

## Deviations from Plan

None — plan executed exactly as written. Both tasks' acceptance criteria and verify commands ran unmodified and passed.

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, file-access patterns, or schema changes introduced. `tests/fixtures/must_not_reject.yaml` is a test-only, developer-committed fixture file with no attacker-controlled input path, consistent with the plan's own threat_model disposition (T-20-08: accept, fixture-set completeness is a documented representative-sample scope boundary, not a security gap).

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. No new dependencies (`pyyaml` already pinned).

## Next Phase Readiness

- MEAS-02 is fully closed: the CI safety net proves, end-to-end, that Plan 20-01's substance gate + Plan 20-02's production `DomainLoader` wiring genuinely protect all 5 categories of clinical content named in the milestone's explicit backstop requirement ("Must-not-reject fixtures pass — no clinical codes, dosage instructions, or normative statements dropped").
- This was the final plan (04 of 4) in Phase 20 (chunk-substance-gate-export-gate). Phase 20 is now complete pending orchestrator-level phase closeout (STATE.md/ROADMAP.md/PROJECT.md updates).
- Full test suite verified green: 1114 passed, 3 skipped, 6 xfailed, 0 failed.

---
*Phase: 20-chunk-substance-gate-export-gate*
*Completed: 2026-07-17*

## Self-Check: PASSED

All 2 created files confirmed present on disk; both task commit hashes (`0fdffa4`, `f736e47`) confirmed present in `git log`. Full test suite (`pytest tests/`) verified green (1114 passed, 3 skipped, 6 xfailed, 0 failed) after both task commits.
