---
phase: 19-section-classifier-patterns
plan: 03
subsystem: pipeline
tags: [boilerplate, regex, clean, clean-05, gate-decouple]

# Dependency graph
requires: []
provides:
  - "BOILERPLATE_PATTERNS extended from 4 to 9 compiled re.Pattern entries in src/knowledge_lake/pipeline/clean.py, covering CLEAN-05's five audit categories (nav menus, terms-of-service, marketing CTAs, cookie consent, government disclaimer)"
affects: [19-04-section-classifier]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Additive-only list extension via a single .extend([...]) call appended after the original literal, preserving byte-identical indices 0-3 so the Phase 18 frozen gate signature (crawl.py's _GATE_BOILERPLATE_PATTERNS) stays decoupled"
    - "Government-disclaimer pattern anchored to specific multi-word phrases (not a generic disclaimer/warning keyword) to avoid false-positive stripping of genuine clinical safety text"

key-files:
  created: []
  modified:
    - src/knowledge_lake/pipeline/clean.py
    - tests/unit/test_clean.py

key-decisions:
  - "Used one .extend([...]) call with a 5-entry list literal rather than five separate .append() calls, per the plan's explicit instruction — functionally equivalent, cleaner diff"
  - "Government-disclaimer pattern list (this website is not a substitute for professional medical advice | for official use only | privacy policy | accessibility statement | no fear act | foia) intentionally excludes any bare 'disclaimer' or 'warning' keyword — verified via a dedicated regression test that a realistic clinical-safety sentence beginning with 'Manufacturer disclaimer:' survives unchanged"

patterns-established:
  - "New BOILERPLATE_PATTERNS entries are appended via .extend() immediately after the base list literal, never inserted, reordered, or converted to a dict — future extensions should follow the same additive convention to keep the Phase 18 gate signature stable"

requirements-completed: [CLEAN-05]

coverage:
  - id: D1
    description: "BOILERPLATE_PATTERNS has exactly 9 compiled regex entries after the extension, with indices 0-3 byte-identical to their pre-Phase-19 .pattern strings"
    requirement: "CLEAN-05"
    verification:
      - kind: unit
        ref: "tests/unit/test_clean.py (all 18 pre-existing tests, unchanged) + tests/unit/test_gate_signature_pin.py::test_gate_signature_byte_stable, test_gate_decoupled_from_clean_patterns"
        status: pass
    human_judgment: false
  - id: D2
    description: "Each of the 5 new categories (nav menu, terms-of-service, marketing CTA, cookie consent, gov disclaimer) strips its target text via remove_boilerplate() while preserving surrounding body text"
    requirement: "CLEAN-05"
    verification:
      - kind: unit
        ref: "tests/unit/test_clean.py::test_boilerplate_removal_nav_menu_extended, test_boilerplate_removal_terms_of_service, test_boilerplate_removal_marketing_cta, test_boilerplate_removal_cookie_consent_extended, test_boilerplate_removal_gov_disclaimer"
        status: pass
    human_judgment: false
  - id: D3
    description: "A genuine clinical safety-warning sentence containing the word 'disclaimer' mid-line is NOT stripped by the new patterns (prohibition regression guard); remove_boilerplate('') returns '' without raising"
    requirement: "CLEAN-05"
    verification:
      - kind: unit
        ref: "tests/unit/test_clean.py::test_boilerplate_preserves_clinical_disclaimer_sentence, test_boilerplate_removal_empty_string_no_raise"
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-07-16
status: complete
---

# Phase 19 Plan 3: Extend BOILERPLATE_PATTERNS Summary

**`BOILERPLATE_PATTERNS` in `clean.py` grows from 4 to 9 compiled regex entries via a single additive `.extend()` call, covering CLEAN-05's five garbage categories (navigation, terms-of-service, marketing CTAs, cookie consent, government disclaimer) — the raw-text pattern list Plan 19-04's `classify_sections()` will read directly to help decide `is_boilerplate`.**

## Performance

- **Duration:** 6 min
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Extended `BOILERPLATE_PATTERNS` from 4 to 9 entries via `BOILERPLATE_PATTERNS.extend([...])` immediately after the original 4-entry list literal — indices 0-3 remain byte-identical, verified by both the 18 pre-existing `test_clean.py` tests and the two Phase 18 gate-signature pinning tests (`test_gate_signature_byte_stable`, `test_gate_decoupled_from_clean_patterns`) passing unchanged
- Added 5 new compiled patterns exactly as specified in the plan: extended navigation phrases (main menu, breadcrumbs, skip to footer, etc.), terms-of-service line-strip, marketing/enrollment CTAs (enroll now, sign up today, etc.), extended cookie-consent phrasing (we use cookies, cookie settings), and government disclaimer text anchored to specific multi-word phrases (not a bare "disclaimer" keyword)
- Updated the module header comment to document all 9 entries and the additive-extension convention that keeps the gate signature decoupled
- Added 7 new regression tests to `tests/unit/test_clean.py`: one per new category, plus `test_boilerplate_preserves_clinical_disclaimer_sentence` (the prohibition regression guard) and `test_boilerplate_removal_empty_string_no_raise` (empty-input edge probe)

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend BOILERPLATE_PATTERNS with 5 new categories** - `3eb2ab3` (feat)
2. **Task 2: Add regression tests for the 5 new categories and edge cases** - `dbdd6f2` (test)

**Plan metadata:** (this commit)

## Files Created/Modified
- `src/knowledge_lake/pipeline/clean.py` - `BOILERPLATE_PATTERNS` extended from 4 to 9 entries via `.extend()`; header comment updated
- `tests/unit/test_clean.py` - 7 new regression test functions (25 total in file)

## Decisions Made
- Single `.extend([...])` call with a 5-entry list literal, per plan instruction, instead of five `.append()` calls — functionally equivalent, cleaner diff
- Government-disclaimer pattern list deliberately excludes any bare "disclaimer"/"warning" keyword, keeping it narrow enough to leave genuine clinical safety text untouched — directly regression-tested

## Deviations from Plan
None. Implementation used the exact regex sources, category order, and test names specified in 19-03-PLAN.md.

## Issues Encountered
None.

## Verification
- `uv run pytest tests/unit/test_clean.py tests/unit/test_gate_signature_pin.py -x -q` → 27 passed (18 pre-existing + 7 new + 2 gate-pin tests)
- `uv run python -c "..."` sanity check: `len(BOILERPLATE_PATTERNS) == 9`; `remove_boilerplate("Main Menu") == ""`; the clinical disclaimer sentence survives unchanged
- Full unit suite: `uv run pytest tests/unit -q` → 831 passed, 1 xfailed (pre-existing), 0 failed — up from 824 passed after Plan 19-02, exactly +7 new tests, no regressions

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `BOILERPLATE_PATTERNS` (9 entries) is ready for Plan 19-04's `classify_sections()` to import and match against raw section text when deciding `is_boilerplate`, per this plan's `key_links` entry
- The Phase 18 gate signature remains fully decoupled — `_GATE_BOILERPLATE_PATTERNS` in `crawl.py` is an independent frozen copy unaffected by this or future `clean.py` pattern extensions
- Known, accepted out-of-scope gap carried forward unchanged: the 5 new patterns are English-only; non-English boilerplate (es/fr/de/pt) is not stripped by them (per 19-CONTEXT.md D-05 and this plan's dismissed prohibition entry)

---
*Phase: 19-section-classifier-patterns*
*Completed: 2026-07-16*
