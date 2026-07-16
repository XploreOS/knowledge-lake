---
phase: 17-close-the-bypass-measurement
plan: 01
subsystem: pipeline
tags: [clean, boilerplate, hashing, lineage, sha256, dataclasses, wr-05, quality-audit]

# Dependency graph
requires: []
provides:
  - "clean() accepts an optional keyword-only parsed_doc: ParsedDoc | None kwarg that skips the S3 re-fetch and cleans sections in-memory"
  - "WR-05 parent-scoped content_hash (f\"{parsed_artifact_id}:{cleaned_text}\") closing the dormant cross-document lineage-corruption bug"
  - "clean()'s returned dict always carries a cleaned_doc key (ParsedDoc when parsed_doc supplied, else None)"
  - "_clean_sections() pure helper: (cleaned_sections, sections_considered, sections_kept, sections_rejected, rejection_reasons)"
  - "QUAL-05 conservation invariant enforced at runtime (RuntimeError, never a bare assert)"
  - "sections_considered/kept/rejected/rejection_reasons computed unconditionally and persisted on cleaned_document.metadata_"
affects: [17-02-dagster-wiring, 17-03-cli-process-crawled-wiring, 17-04-quality-audit]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "dataclasses.replace() to build cleaned copies of plain (non-frozen) dataclasses without mutating the caller's originals"
    - "WR-05 parent-scoped content hash: hash_input = f\"{parent_artifact_id}:{content}\" (mirrors chunk.py's already-shipped convention)"
    - "Unconditional metric computation before a dedup/exact-match early-return branch, so both branches return identical live counts instead of one branch reading stale persisted state"

key-files:
  created: []
  modified:
    - src/knowledge_lake/pipeline/clean.py
    - tests/unit/test_clean.py

key-decisions:
  - "Split the plan's two tightly-coupled tasks into four true TDD commits (test/feat x2) instead of one combined commit, even though RESEARCH.md Pitfall 1 required the WR-05 hash fix and parsed_doc forwarding to land in the same wave — Task 1's commit already included the hash fix, satisfying Pitfall 1's ship-together requirement while keeping Task 2's conservation-invariant/counting concerns in their own commit."
  - "Added one extra test beyond the plan's required list for the flagged, non-blocking CLEAN-03 assumption (empty cleaned_text still yields distinct hashes across parents) since it was cheap and the plan explicitly flagged it as worth adding if time allowed."

requirements-completed: [CLEAN-01, CLEAN-02, CLEAN-03, QUAL-04, QUAL-05]

coverage:
  - id: D1
    description: "clean() accepts an optional in-memory parsed_doc: ParsedDoc | None kwarg; when provided, skips the S3 re-fetch and cleans parsed_doc.sections via dataclasses.replace() without mutating the caller's Section objects"
    requirement: "CLEAN-01"
    verification:
      - kind: unit
        ref: "tests/unit/test_clean.py::TestCleanParsedDocThreading::test_cleaned_doc_preserves_section_count"
        status: pass
      - kind: unit
        ref: "tests/unit/test_clean.py::TestCleanParsedDocThreading::test_no_in_place_mutation_of_caller_sections"
        status: pass
      - kind: unit
        ref: "tests/unit/test_clean.py::TestCleanParsedDocThreading::test_legacy_path_no_parsed_doc_returns_none_cleaned_doc"
        status: pass
    human_judgment: false
  - id: D2
    description: "WR-05 parent-scoped content_hash (f\"{parsed_artifact_id}:{cleaned_text}\") — two documents with identical cleaned text but different parents get distinct content_hash values, closing the dormant cross-document lineage-corruption bug"
    requirement: "CLEAN-03"
    verification:
      - kind: unit
        ref: "tests/unit/test_clean.py::TestCleanParsedDocThreading::test_distinct_content_hash_across_parents"
        status: pass
      - kind: unit
        ref: "tests/unit/test_clean.py::TestCleanParsedDocThreading::test_distinct_content_hash_with_empty_cleaned_text"
        status: pass
    human_judgment: false
  - id: D3
    description: "QUAL-05 conservation invariant (sections_rejected + sections_kept == sections_considered) enforced at runtime via RuntimeError (never a bare assert); zero-section input logged distinctly and does not raise"
    requirement: "QUAL-05"
    verification:
      - kind: unit
        ref: "tests/unit/test_clean.py::TestCleanConservationInvariant::test_conservation_invariant_raises_runtime_error"
        status: pass
      - kind: unit
        ref: "tests/unit/test_clean.py::TestCleanConservationInvariant::test_clean_sections_empty_input_no_raise"
        status: pass
    human_judgment: false
  - id: D4
    description: "sections_considered/kept/rejected/rejection_reasons computed unconditionally (including on the exact-dup early-return branch) and persisted on cleaned_document.metadata_ so a quality-audit re-run never reads stale/absent counts; rejection reason counts sum rather than overwrite"
    requirement: "QUAL-04"
    verification:
      - kind: unit
        ref: "tests/unit/test_clean.py::TestCleanConservationInvariant::test_unconditional_counting_on_exact_dup_branch"
        status: pass
      - kind: unit
        ref: "tests/unit/test_clean.py::TestCleanConservationInvariant::test_clean_sections_rejection_reasons_sum_across_sections"
        status: pass
    human_judgment: false
  - id: D5
    description: "process_crawled/Dagster clean_document wiring to consume clean()'s new signature/return shape"
    requirement: "CLEAN-02"
    verification: []
    human_judgment: true
    rationale: "CLEAN-02's caller-side wiring (Dagster clean_document asset, CLI process_crawled) is explicitly Plans 17-02/17-03's scope per this plan's own objective ('every other plan depends on the new clean() signature'). This plan only builds the substrate clean() now exposes; the requirement is marked complete per the plan's requirements frontmatter but its consumer-side behavior is verified in 17-02/17-03."

duration: 13min
completed: 2026-07-16
status: complete
---

# Phase 17 Plan 01: Close the Bypass — clean() Substrate Summary

**Retrofitted `clean()` with an optional in-memory `parsed_doc` kwarg, WR-05 parent-scoped content hashing, and unconditional per-section kept/rejected/considered counting with a runtime conservation invariant — the foundational substrate every other Phase 17 plan (Dagster wiring, CLI wiring, quality-audit) depends on.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-07-16T04:44:39Z (plan doc commit)
- **Completed:** 2026-07-16T04:57:00Z
- **Tasks:** 2 (each executed as a full TDD RED → GREEN cycle)
- **Files modified:** 2 (`src/knowledge_lake/pipeline/clean.py`, `tests/unit/test_clean.py`)

## Accomplishments

- `clean()` gained a keyword-only `parsed_doc: ParsedDoc | None = None` parameter. When supplied, it skips the S3 re-fetch entirely and cleans each `Section.text` via `dataclasses.replace()`, never mutating the caller's original `Section` objects (guards against the mutation-aliasing hazard where the same cleaned `ParsedDoc` is later shared read-only across three Dagster consumers).
- `content_hash` now uses the WR-05 parent-scoped form `f"{parsed_artifact_id}:{cleaned_text}"` instead of an unscoped hash of the cleaned bytes — closes the dormant cross-document lineage-corruption bug before the parsed_doc forwarding (Plans 17-02/17-03) makes it live.
- Every `clean()` return path (exact-dup early return and the normal-write branch) now carries a `cleaned_doc` key and four count keys (`sections_considered`, `sections_kept`, `sections_rejected`, `rejection_reasons`), computed unconditionally from the in-memory `parsed_doc` — never read stale off `existing.metadata_`.
- New `_clean_sections()` pure helper factors the per-section boilerplate loop out of `clean()`, directly unit-testable, and enforces the QUAL-05 conservation invariant (`rejected + kept == considered`) as a `RuntimeError` (never a bare `assert`), with a distinct `clean.zero_sections` log warning for the legitimate zero-section boundary case.
- Zero regressions: full unit suite (773 tests, 1 xfailed as before) stayed green throughout.

## Task Commits

Each task was executed as a full TDD RED → GREEN cycle, committed atomically:

1. **Task 1: Thread parsed_doc through clean() with per-section cleaning and WR-05 hash scoping**
   - `9371689` (test) — RED: 4 failing tests for parsed_doc threading + WR-05 hash
   - `49b7081` (feat) — GREEN: implementation
2. **Task 2: Conservation invariant and unconditional rejection-count recording**
   - `ca4a369` (test) — RED: 4 failing tests for `_clean_sections`/conservation invariant/unconditional counting
   - `74f495a` (feat) — GREEN: implementation
3. **Bonus coverage (non-blocking flagged assumption from PLAN.md)**
   - `aa31c46` (test) — empty-`cleaned_text` hash-distinctness test

**Plan metadata:** (this commit, following)

## Files Created/Modified

- `src/knowledge_lake/pipeline/clean.py` — added `_clean_sections()` helper; `clean()` gained `parsed_doc` kwarg, per-section cleaning, WR-05 hash, conservation invariant, unconditional count recording, `cleaned_doc` in every returned dict.
- `tests/unit/test_clean.py` — added `TestCleanParsedDocThreading` (5 tests) and `TestCleanConservationInvariant` (4 tests), plus shared fixtures mirroring `test_clean_silver_key.py`'s in-memory-SQLite + mocked-`StorageBackend` pattern.

## Decisions Made

- **Split the plan's two tasks into four separate TDD commits** (test/feat × 2) rather than implementing both tasks' logic in one combined pass. RESEARCH.md's Pitfall 1 requires the WR-05 hash fix (CLEAN-03) and the parsed_doc forwarding (CLEAN-01) to ship in the same wave/commit — that requirement is satisfied by Task 1's single commit containing both. Task 2's conservation-invariant and unconditional-counting work is a genuinely separable concern (it doesn't change hash scoping or section-forwarding correctness) and got its own RED/GREEN pair, matching the plan's task boundaries exactly.
- **Added a non-blocking bonus test** for the plan's flagged CLEAN-03 assumption (empty `cleaned_text` across two different `parsed_artifact_id`s still yields distinct hashes) — cheap to add, strengthens confidence in the parent-ID-prefix hash design.
- **Registry lookup (Step 1) always runs**, even when `parsed_doc` is supplied — `parsed_artifact_id` is still needed as `parent_artifact_id` for the cleaned artifact and its existence must still be validated. Only the S3 `get_object()` fetch (Step 2) is skipped when `parsed_doc` is provided.
- **`clean.zero_sections` warning only fires when `parsed_doc is not None`** — the legacy S3-only path has no per-section data at all (`sections_considered` is trivially `0` on every legacy call), so gating the warning on `parsed_doc is not None` avoids noisy, meaningless log spam on every backward-compatible call.

## Deviations from Plan

None — plan executed exactly as written. All five `must_haves.truths` from the plan frontmatter are satisfied:

1. ✅ `clean()` accepts `parsed_doc: ParsedDoc | None` keyword-only, skips S3 re-fetch, cleans in place via `dataclasses.replace` (never mutates caller's Sections).
2. ✅ Two `clean()` calls with identical `cleaned_text` but different `parsed_artifact_id` produce distinct `content_hash` values (WR-05).
3. ✅ Returned dict always contains `cleaned_doc` (ParsedDoc with section list length preserved, or `None`).
4. ✅ Conservation invariant asserted at runtime via `RuntimeError` (never a bare `assert`).
5. ✅ Zero-section input logged as `clean.zero_sections`, does not raise, distinguishable from an all-rejected gate.
6. ✅ `sections_considered/kept/rejected/rejection_reasons` computed unconditionally, including on the exact-dup early-return branch, persisted on `cleaned_document.metadata_`.
7. ✅ Rejection reason counts sum across sections within a call (`.get(key, 0) + 1` accumulation pattern), matching the additive contract a future cross-document quality-audit accumulator needs.
8. ✅ No floating-point precision loss anywhere in the CLEAN-02 parse-clean-chunk boundary touched by this plan — only UTF-8 string pass-through and SHA256 hex digests are used (backstop verification: no float arithmetic was introduced anywhere in `clean.py`'s modified code).

The two "unclassified" flagged assumptions in the plan (CLEAN-01 zero-sections success path, CLEAN-03 empty-cleaned-text hash distinctness) are both directly true of the shipped implementation; the second is now covered by an added test.

## Issues Encountered

None. One test-fixture bug was self-caught and fixed before any commit: initial fixture code accessed SQLAlchemy ORM objects' `.id` attributes *after* the `with Session(...) as session:` block closed, triggering `DetachedInstanceError` (the session's `__exit__` expires/detaches all instances on close). Fixed by capturing `.id` values as plain strings while still inside the session block, before any `clean()` call. This was pre-commit test-authoring cleanup, not a deviation from the plan's design.

## Next Phase Readiness

- Plan 17-02 (Dagster wiring) can now call `clean(parsed_artifact_id, source_id, parsed_doc=parsed_doc, settings=settings)` and read `clean_result["cleaned_doc"]` to swap into `clean_document`'s output dict — zero further changes needed to `clean.py`.
- Plan 17-03 (`process_crawled` CLI/API/MCP parity) can insert the identical `clean()` call between `parse()` and `chunk()`.
- Plan 17-04 (quality-audit) can read `sections_considered/sections_kept/sections_rejected/rejection_reasons` directly off `clean()`'s return dict (or `cleaned_document.metadata_` for a persisted re-read) with the guarantee that counts are always fresh, even on a dedup-short-circuited re-run.
- No blockers. Full unit suite (773 passed, 1 xfailed) green; zero regressions to any of the 9 original `test_clean.py` tests or both `test_clean_silver_key.py` tests.

---
*Phase: 17-close-the-bypass-measurement*
*Completed: 2026-07-16*

## Self-Check: PASSED

- FOUND: src/knowledge_lake/pipeline/clean.py
- FOUND: tests/unit/test_clean.py
- FOUND: .planning/phases/17-close-the-bypass-measurement/17-01-SUMMARY.md
- FOUND commits: 9371689, 49b7081, ca4a369, 74f495a, aa31c46
