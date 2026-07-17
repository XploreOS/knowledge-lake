---
phase: 20-chunk-substance-gate-export-gate
verified: 2026-07-17T08:15:00Z
status: passed
score: 5/5 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 20: Chunk Substance Gate + Export Gate Verification Report

**Phase Goal:** Garbage chunks are rejected before embedding and the gold RAG export contains only quality content
**Verified:** 2026-07-17T08:15:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP §Phase 20 Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `FineWebQualityFilter` rejects "too short"/"no real sentences" chunks while passing clinical prose, using chunk-scoped settings (not `CurateSettings`) | VERIFIED | `ChunkQualitySettings` (settings.py:313-350+) is a distinct Pydantic model from `CurateSettings`, holding `fineweb_line_punct_thr`/`fineweb_short_line_thr`/`fineweb_short_line_length`/`min_token_count`/etc. `_build_fineweb_filter()` (chunk.py:280-295) instantiates `FineWebQualityFilter` from these chunk-scoped fields, never `CurateSettings`. `tests/unit/test_chunk_substance_gate.py::test_apply_substance_gate_clinical_prose_passes`, `test_fineweb_predicate_nav_junk_fails_line_punct_ratio`, `test_fineweb_predicate_exact_line_punct_boundary_passes`, `test_fineweb_predicate_empty_lines_fails_with_empty_reason` — all pass (independently re-run). |
| 2 | Chunks failing the composite substance predicate are rejected (enforce) or flagged with recorded reason (report); `is_table=True` always exempt | VERIFIED | `_apply_substance_gate()` (chunk.py:340-425) runs `[check_table_exemption, allowlist_pred, fineweb_pred, token_pred, alpha_pred, link_pred, stopword_pred, check_terminal_punct_ratio]` via `run_predicates()`, sets `substance_passed`/`rejection_reason` on every raw chunk, filters in enforce mode / annotates-only in report mode (D-13). `check_table_exemption` is first in the exemption set — always exempt regardless of text. Confirmed by `test_apply_substance_gate_enforce_mode_excludes_nav_junk`, `test_apply_substance_gate_report_mode_annotates_but_keeps_nav_junk`, `test_apply_substance_gate_is_table_exempt_regardless_of_text`, `test_chunk_is_table_exempt_at_pipeline_level` (all pass, independently re-run). |
| 3 | CI fails if any fixture in the ~20 hand-labeled must-not-reject set is dropped | VERIFIED | `tests/fixtures/must_not_reject.yaml` has 25 entries (5 per category: icd_code, dosage, loinc, hipaa_ref, cardinality_constraint — confirmed by direct YAML load). `tests/unit/test_must_not_reject.py` parametrizes over all 25, calling the real `chunk()` with `domain_filters` resolved via the real `DomainLoader.from_name("healthcare")` (not mocked) — 29 tests total in this file (25 fixture cases + 1 clean→chunk sequence proof + 3 negative pagination-boilerplate guards), all pass. Non-vacuousness independently re-verified below (Behavioral Spot-Checks). |
| 4 | A mixed-quality document (clinical tables + cookie banners) exports only clinical chunks to gold | VERIFIED | `export_rag_corpus()` (export.py:302-311) pre-filters on `meta.get("substance_passed", True)` with a `continue`-skip before row construction — identical idiom to the existing domain-mismatch filter, never adds `substance_passed`/`rejection_reason` as an exported column (`_RAG_CORPUS_FIELDS` unchanged, confirmed unchanged in diff). `test_export.py::TestRagCorpus` covers True/False/None/missing-key cases and the exact-column-set assertion — all pass (independently re-run). Critically, this truth also depends on clinical content surviving the upstream `clean()` stage; CR-01 (see below) closed the gap where `clean()` could drop clinical-code sections before `chunk()`'s gate ever ran — fixed and independently re-verified as a genuine regression guard (see Anti-Patterns / Behavioral Spot-Checks). |
| 5 | Changing a filter threshold invalidates the cache and triggers re-processing (`_curation_cache_key` pattern) | VERIFIED | `chunk.py`'s per-chunk hash formula changed from `f"{parsed_artifact_id}:{text}"` to `f"{parsed_artifact_id}:{s.chunk_quality.filter_config_version}:{text}"` (PIPE-01). `test_chunk_storage.py::test_chunk_different_filter_config_version_produces_different_content_hash` and `test_chunk_same_filter_config_version_hits_existing_cache` both pass (independently re-run), proving version-bump invalidation and same-version cache-hit behavior. |

**Score:** 5/5 truths verified (0 present-but-behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/knowledge_lake/config/settings.py` | `ChunkQualitySettings` class + `Settings.chunk_quality` field | VERIFIED | Class exists at line 313 with 9 fields (`gate_mode`, `min_token_count`, `min_alpha_ratio`, `max_link_density`, `min_stopword_ratio`, 3 FineWeb overrides, `filter_config_version`), registered as `Settings.chunk_quality`. |
| `src/knowledge_lake/pipeline/chunk.py` | `domain_filters` param, gate wiring, PIPE-01 hash | VERIFIED | `chunk()` accepts `domain_filters: DomainFilters | None = None`; `_apply_substance_gate()`, `_build_fineweb_filter()`, `_fineweb_predicate()`, `_assert_chunk_conservation_invariant()` all present and wired in the pipeline function body. |
| `tests/unit/test_chunk_substance_gate.py` | New test file | VERIFIED | 19 tests, all pass. |
| `src/knowledge_lake/dagster_defs/assets.py` | `domain_filters` resolution in `chunk_document` (and, post-fix, `clean_document`) | VERIFIED | `chunk_document` (line 367) and `clean_document` (line 279) both resolve `domain_filters` via `DomainLoader.from_name(...).filters` and thread it into `chunk()`/`clean()` respectively. |
| `src/knowledge_lake/pipeline/process.py` | `domain_filters` resolution in `process_crawled` (both `clean()` and `chunk()` calls) | VERIFIED | Resolved once (line 104-107) before the loop; threaded into both `clean(...)` (line 123) and `chunk(...)` (line 126). |
| `domains/healthcare/filters.yaml` | New cardinality-constraint pattern | VERIFIED | 7th `normative_allowlists` entry present: `\d+\s*(?:of|/)\s*\d+\s+(?:SIRS|Duke|Ranson|SOFA|criteria|metabolic syndrome)` — the narrowed (post-CR-02-fix) version. |
| `src/knowledge_lake/pipeline/export.py` | `substance_passed` pre-filter + counter | VERIFIED | `substance_filtered_out` counter and pre-row-build `continue`-skip present (lines 289-311, 352); `_RAG_CORPUS_FIELDS` unchanged. |
| `src/knowledge_lake/pipeline/datasets.py` | `version` field on generated examples | VERIFIED | `"version": s.chunk_quality.filter_config_version` present in both `generate_qa_example()` (line 382) and `generate_instruction_example()` (line 547). |
| `tests/fixtures/must_not_reject.yaml` | ~20+ fixtures across 5 categories | VERIFIED | 25 entries, 5 per category (icd_code, dosage, loinc, hipaa_ref, cardinality_constraint), leading scope-boundary comment present. |
| `tests/unit/test_must_not_reject.py` | Parametrized CI test | VERIFIED | 29 tests (25 fixture + 1 clean→chunk sequence + 3 negative pagination guards), all pass. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `chunk()` gate output | chunk artifact `metadata_` | `substance_passed`/`rejection_reason` written in both existing-hit and new-artifact persistence branches | WIRED | Confirmed in chunk.py lines 520-521, 555-556, 570-571 — sourced fresh from `raw` each call. |
| chunk `metadata_.substance_passed` | `export_rag_corpus()` | pre-row-build `continue`-skip | WIRED | Confirmed export.py:309-311. |
| `settings.domain.domain_name` | `chunk()`/`clean()` `domain_filters` param | `DomainLoader.from_name(...).filters`, both Dagster (`chunk_document`, `clean_document`) and CLI (`process_crawled`) entry points | WIRED | Confirmed in assets.py (322-325, 400-403) and process.py (104-107, 123, 126). Note: this link was initially broken for `clean()` (CR-01) — fixed in commit `95d2eef`, independently re-verified below by reverting the fix and confirming the regression test fails without it. |
| `ChunkQualitySettings.filter_config_version` | `datasets.py` `version` payload field | copied verbatim in `generate_qa_example`/`generate_instruction_example` | WIRED | Confirmed datasets.py:382, 547. |
| `tests/fixtures/must_not_reject.yaml` | `tests/unit/test_must_not_reject.py` | module-level YAML load + `pytest.mark.parametrize`, real `chunk()` call with real `DomainLoader` | WIRED | Confirmed — 25/25 parametrized cases pass; independently re-verified as non-vacuous. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full phase-relevant unit suite | `pytest tests/unit/test_chunk_substance_gate.py tests/unit/test_chunk_storage.py tests/unit/test_process_crawled_clean.py tests/unit/test_export.py tests/unit/test_datasets.py tests/unit/test_must_not_reject.py -q` | 92 passed | PASS |
| Full workspace suite (run once, per constraint) | `pytest tests/ -q` | 1118 passed, 3 skipped, 6 xfailed, 0 failed | PASS — matches SUMMARY claim exactly, independently reproduced |
| CR-01 regression test genuinely fails without the fix | Reverted `process.py`'s `clean()` call to drop `domain_filters=domain_filters`, re-ran `test_domain_filters_resolved_and_threaded_when_domain_configured` | `KeyError: 'domain_filters'` — test fails as expected | PASS (proves the CR-01 fix and its regression test are real, not vacuous) — file restored after test, `git status` clean |
| CR-02 regression test genuinely fails without the fix | Reverted `filters.yaml`'s cardinality pattern to the unnarrowed `\d+\s*(?:of|/)\s*\d+`, re-ran the 3 pagination-boilerplate negative-fixture tests | All 3 fail with `AssertionError: ... WRONGLY exempted` | PASS (proves the CR-02 fix and its regression tests are real, not vacuous) — file restored after test, `git status` clean |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| QUAL-02 | 20-01 | FineWebQualityFilter at chunk scope | SATISFIED | `ChunkQualitySettings`, `_build_fineweb_filter()` |
| QUAL-03 | 20-01, 20-02 | Composite substance gate, enforce/report modes, is_table exempt | SATISFIED | `_apply_substance_gate()`, production wiring in 20-02 |
| MEAS-02 | 20-02, 20-04 | Must-not-reject CI fixtures | SATISFIED | `must_not_reject.yaml` (25 entries) + parametrized test, both CR fixes closing the real end-to-end gap |
| EXPORT-01 | 20-03 | Gold RAG export chunk-level gate | SATISFIED | `export_rag_corpus()` pre-filter |
| EXPORT-02 | 20-03 | Eval dataset versioning | SATISFIED | `version` field tagging; regeneration documented as explicit operator action (not auto-migration, correctly scoped as forward-only) |
| PIPE-01 | 20-01 | Filter config cache versioning | SATISFIED | WR-05 hash formula includes `filter_config_version` |

No orphaned requirements — all 6 IDs declared across the 4 plans' frontmatter match `.planning/REQUIREMENTS.md`'s Phase 20 mapping exactly.

### Anti-Patterns Found

None. Scanned all 9 modified/created production and fixture files (`settings.py`, `chunk.py`, `assets.py`, `process.py`, `filters.yaml`, `export.py`, `datasets.py`, `must_not_reject.yaml`, `test_must_not_reject.py`) for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER`/"not yet implemented" — zero matches.

### Code Review Findings (20-REVIEW.md / 20-REVIEW-FIX.md)

A post-execution code review found 2 CRITICAL issues, both independently re-verified as genuinely fixed (not just claimed):

- **CR-01** (`clean()` never received `domain_filters` in production, allowing clinical-code sections to be dropped before `chunk()`'s gate ever ran): Fixed in `process.py` and `assets.py`'s `clean_document` asset. Independently confirmed by reverting `process.py`'s fix and re-running `test_domain_filters_resolved_and_threaded_when_domain_configured` — fails with `KeyError: 'domain_filters'` without the fix, passes with it.
- **CR-02** (overbroad cardinality allowlist regex `\d+\s*(?:of|/)\s*\d+` exempted ordinary pagination text like "Page 1 of 5"): Fixed by narrowing the pattern to require adjacency to clinical-scoring vocabulary. Independently confirmed by reverting `filters.yaml`'s pattern and re-running the 3 pagination-boilerplate negative-fixture tests — all 3 fail (wrongly exempted) without the fix, pass with it.

Both fixes are backed by genuine, non-vacuous regression tests (proven above, not merely trusted from SUMMARY/REVIEW-FIX narrative).

### Human Verification Required

None. All must-haves are verifiable programmatically via code inspection and test execution; no visual, real-time, or external-service-dependent behavior in this phase's scope.

### Gaps Summary

No gaps. All 5 ROADMAP success criteria verified true in the codebase; all 6 requirement IDs (QUAL-02, QUAL-03, MEAS-02, EXPORT-01, EXPORT-02, PIPE-01) satisfied with test evidence; both CRITICAL code-review findings independently re-confirmed as fixed via revert-and-retest (not merely trusted from the review-fix narrative); full test suite green (1118 passed, 0 failed, 3 skipped, 6 xfailed), matching the SUMMARY's claimed count exactly on independent re-run.

---

_Verified: 2026-07-17T08:15:00Z_
_Verifier: Claude (gsd-verifier)_
