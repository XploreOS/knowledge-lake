---
phase: 19-section-classifier-patterns
fixed_at: 2026-07-16T18:03:30Z
review_path: .planning/phases/19-section-classifier-patterns/19-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 19: Code Review Fix Report

**Fixed at:** 2026-07-16T18:03:30Z
**Source review:** .planning/phases/19-section-classifier-patterns/19-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (2 Critical, 4 Warning — `fix_scope: critical_warning`; the 2 Info findings were out of scope and not attempted)
- Fixed: 6
- Skipped: 0

## Fixed Issues

### CR-01: Overbroad marketing-CTA pattern silently strips legitimate clinical content

**Files modified:** `src/knowledge_lake/pipeline/clean.py`, `tests/unit/test_clean.py`
**Commit:** 105a5fd
**Applied fix:** Narrowed the `register for .*` open-wildcard alternative in the
Phase-19 marketing/enrollment-CTA `BOILERPLATE_PATTERNS` entry to a closed set of
fixed marketing phrases (`register for (?:updates|our newsletter|a free
(?:trial|demo|account))`), matching the anchoring style of the sibling
alternatives in the same pattern and the adjacent government-disclaimer
pattern's stated narrowness principle. Added a comment explaining the intent.
Added two regression tests: `test_boilerplate_preserves_clinical_register_for_sentence`
(a "Register for the diabetes prevention program..." sentence now survives
`remove_boilerplate()` intact) and `test_boilerplate_removal_register_for_marketing_phrase`
(confirms the narrowed pattern still strips genuine marketing CTAs like
"Register for our newsletter"). The Phase 18 gate's frozen `_GATE_BOILERPLATE_PATTERNS`
copy in `crawl.py` was deliberately left untouched, per Phase 18's decoupling
(verified `tests/unit/test_gate_signature_pin.py` still passes unchanged).

### CR-02: Domain pack models silently ignore unknown/misspelled YAML keys

**Files modified:** `src/knowledge_lake/domains/models.py`, `tests/unit/test_domain_loader.py`
**Commit:** a7b571c
**Applied fix:** Added `model_config = ConfigDict(extra="forbid")` to all four
domain-pack schema models (`SourceEntry`, `DomainManifest`, `DomainFilters`,
`TaxonomyManifest`) so an unrecognized key in `filters.yaml`/`domain.yaml`/
`sources.yaml` now raises `pydantic.ValidationError` at `DomainLoader`
construction time instead of being silently dropped. Verified directly that
`DomainFilters.model_validate({"normative_alowlists": [...]})` (typo) now
raises, and that the existing healthcare pack (with its populated
`filters.yaml`) and aviation pack (no `filters.yaml`) both still load without
error — no existing YAML file in either pack contains an unrecognized key.
Added `test_domain_filters_rejects_unknown_key` and
`test_domain_loader_healthcare_and_aviation_still_load_with_forbid_extra` as
regression guards.

### WR-01: Malformed domain-pack regex crashes the entire clean stage

**Files modified:** `src/knowledge_lake/pipeline/clean.py`,
`src/knowledge_lake/pipeline/quality/predicates.py`, `tests/unit/test_clean.py`,
`tests/unit/test_quality_predicates.py`
**Commit:** 01ba6fc
**Applied fix:** In `classify_sections()`, moved compilation of
`domain_filters.boilerplate_patterns` out of the per-section loop (it was
previously being needlessly recompiled once per section) and wrapped each
`re.compile()` call in `try/except re.error`, logging
(`domain_boilerplate_pattern_invalid`) and skipping any pattern that fails to
compile rather than propagating the exception. In `check_domain_allowlist()`,
wrapped the `re.search(pattern, text)` call in `try/except re.error`,
`continue`-ing past a malformed pattern so remaining patterns are still
evaluated and the predicate falls through to `no_allowlist_match` instead of
raising. Added regression tests
`test_classify_sections_malformed_domain_pattern_does_not_crash`,
`test_check_domain_allowlist_malformed_pattern_does_not_raise`, and
`test_check_domain_allowlist_only_malformed_pattern_falls_through`.

### WR-02: `cleaned_doc.metadata` aliases `parsed_doc.metadata` instead of copying

**Files modified:** `src/knowledge_lake/pipeline/clean.py`, `tests/unit/test_clean.py`
**Commit:** 226edcd
**Applied fix:** Changed `metadata=parsed_doc.metadata` to
`metadata=dict(parsed_doc.metadata)` when constructing `cleaned_doc`, mirroring
the mutation-aliasing guard already applied to `sections` via
`dataclasses.replace`. Added `test_cleaned_doc_metadata_is_not_aliased_to_parsed_doc`,
which asserts `cleaned_doc.metadata is not doc.metadata` and that mutating
`cleaned_doc.metadata` after `clean()` returns does not affect the original
`parsed_doc.metadata`.

### WR-03: `run_predicates()`'s exemption detection is fragile (identity-based)

**Files modified:** `src/knowledge_lake/pipeline/quality/predicates.py`,
`tests/unit/test_quality_predicates.py`
**Commit:** 3d6b252
**Applied fix:** Added an optional `exemption_predicates: set | None = None`
keyword-only parameter to `run_predicates()`, defaulting to the existing
module-level `_EXEMPTION_PREDICATES` set for full backward compatibility
(the only existing caller, `classify_sections()`, calls
`run_predicates()` without this parameter and is unaffected). A future caller
that must wrap `check_domain_allowlist` via
`functools.partial(check_domain_allowlist, allowlist_patterns=patterns)` (to
satisfy its required keyword-only argument, since `run_predicates()` invokes
every predicate as `predicate(text, metadata)`) can now pass the exact wrapped
callable in `exemption_predicates` explicitly, so identity matching works
correctly regardless of wrapping. Documented the caveat in the docstring.
Added `test_run_predicates_functools_partial_exemption_requires_explicit_param`
(demonstrates both the bug — a non-matching wrapped allowlist check
incorrectly short-circuits the whole call as an outright rejection when
`exemption_predicates` is omitted — and the fix, where explicitly naming the
wrapped callable restores correct no-op-fallthrough semantics) and
`test_run_predicates_default_exemption_predicates_unchanged` (confirms
omitting the new parameter preserves the exact pre-existing default
behavior).

### WR-04: `zip(sections, classifications)` without `strict=True`

**Files modified:** `src/knowledge_lake/pipeline/clean.py`
**Commit:** 56ecdce
**Applied fix:** Changed `zip(sections, classifications)` to
`zip(sections, classifications, strict=True)` in `_clean_sections()`
(ruff B905). `classify_sections()` always returns exactly one result per
input section today (verified: no early-continue paths skip appending a
result), so this is a no-behavior-change safety net that will raise
immediately rather than silently truncate if a future refactor ever violates
that invariant. No new test needed — existing `_clean_sections()` tests
(section-count assertions) already exercise this line on every call and
continue to pass.

## Skipped Issues

None — all 6 in-scope findings were fixed.

**Out of scope (not attempted per `fix_scope: critical_warning`):**
- IN-01 (unanchored `.*` wrapping in terms-of-service/cookie-consent patterns) — Info-tier
- IN-02 (unsorted import blocks, ruff I001) — Info-tier, cosmetic only

## Verification

Ran the full unit suite after all 6 fixes: `uv run pytest tests/unit -q` →
**847 passed, 1 xfailed** (the xfail is pre-existing and unrelated to this
phase). `tests/unit/test_clean.py` (35 tests) and
`tests/unit/test_gate_signature_pin.py` (2 tests, confirming the Phase 18
gate's frozen boilerplate-pattern copy in `crawl.py` remains byte-identical
and decoupled) both pass.

---

_Fixed: 2026-07-16T18:03:30Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
