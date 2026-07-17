---
phase: 20
fixed_at: 2026-07-17T07:30:00Z
review_path: .planning/phases/20-chunk-substance-gate-export-gate/20-REVIEW.md
iteration: 1
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 20: Code Review Fix Report

**Fixed at:** 2026-07-17T07:30:00Z
**Source review:** .planning/phases/20-chunk-substance-gate-export-gate/20-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 2
- Fixed: 2
- Skipped: 0

## Fixed Issues

### CR-01: `clean()` never receives `domain_filters` in production — clinical-code sections can be dropped before `chunk()`'s gate ever runs

**Files modified:** `src/knowledge_lake/pipeline/process.py`, `src/knowledge_lake/dagster_defs/assets.py`, `tests/unit/test_process_crawled_clean.py`, `tests/unit/test_must_not_reject.py`
**Commit:** `95d2eef`
**Applied fix:** Threaded the already-resolved `domain_filters` into the `clean()` call in `process_crawled()` (`process.py`). In `assets.py`'s `clean_document` Dagster asset, added the same `DomainLoader.from_name(settings.domain.domain_name).filters` resolution guard already used by `chunk_document`/`enrich_document`, and threaded the result into `clean()`. Extended `test_process_crawled_clean.py::TestProcessCrawledDomainFilters::test_domain_filters_resolved_and_threaded_when_domain_configured` to assert `clean()` (not just `chunk()`) receives the resolved filters — verified to fail without the `process.py` fix (`KeyError: 'domain_filters'`). Added `test_must_not_reject.py::test_bare_icd10_code_survives_real_clean_then_chunk_sequence` proving the real `clean() → chunk()` sequence preserves a bare `"ICD-10 E11.9"` section end-to-end.

### CR-02: New cardinality-constraint allowlist pattern unconditionally exempts ordinary pagination/boilerplate text

**Files modified:** `domains/healthcare/filters.yaml`, `tests/unit/test_must_not_reject.py`
**Commit:** `95d2eef`
**Applied fix:** Narrowed `\d+\s*(?:of|/)\s*\d+` to `\d+\s*(?:of|/)\s*\d+\s+(?:SIRS|Duke|Ranson|SOFA|criteria|metabolic syndrome)`, requiring adjacency to clinical-scoring vocabulary. Verified empirically the narrowed pattern still matches all 5 `cardinality_constraint` fixtures in `must_not_reject.yaml` (SIRS, Duke, Ranson's, SOFA, metabolic syndrome phrasings) while no longer matching `"Page 1 of 5"`, `"Showing 1 of 20 results"`, or nav-junk with an incidental page-footer fragment. Added 3 parametrized negative-fixture tests (`test_pagination_boilerplate_still_rejected_with_domain_filters_active`) — verified to fail without the `filters.yaml` fix (all 3 asserted the pagination text was wrongly exempted).

## Skipped Issues

None — all findings were fixed.

---

_Fixed: 2026-07-17T07:30:00Z_
_Fixer: Claude (orchestrator, direct fix — gsd-code-fixer agent type unavailable, applied fixes inline following the same intelligent-fix-with-verification protocol)_
_Iteration: 1_
