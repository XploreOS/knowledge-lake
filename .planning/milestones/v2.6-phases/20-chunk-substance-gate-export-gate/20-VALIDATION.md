---
phase: 20
slug: chunk-substance-gate-export-gate
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-17
validated: 2026-07-18
---

# Phase 20 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (already configured, `testpaths = ["tests"]`, `xfail_strict = true` in `pyproject.toml`) |
| **Config file** | `pyproject.toml:121` `[tool.pytest.ini_options]` |
| **Quick run command** | `pytest tests/unit/test_chunk_substance_gate.py tests/unit/test_quality_predicates.py -x` |
| **Full suite command** | `pytest tests/` |
| **Estimated runtime** | ~90 seconds (quick), full suite matches existing 994+ test baseline |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/unit/test_chunk_substance_gate.py tests/unit/test_chunk_storage.py tests/unit/test_export.py tests/unit/test_datasets.py tests/unit/test_must_not_reject.py -x`
- **After every plan wave:** Run `pytest tests/`
- **Before `/gsd-verify-work`:** Full suite must be green (994+ existing tests still pass, `xfail_strict=true` holds)
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 20-01-T1 | 20-01 | 1 | QUAL-02 | V5 | `ChunkQualitySettings` model (gate_mode, thresholds, FineWebQualityFilter params, filter_config_version) registered as `settings.chunk_quality` | unit | `uv run pytest tests/unit/test_chunk_substance_gate.py -x` | `tests/unit/test_chunk_substance_gate.py` (20 tests) | ✅ green |
| 20-01-T2 | 20-01 | 1 | QUAL-03 | Tampering/Repudiation | Composite gate (FineWebQualityFilter + Phase-19 predicates + allowlist) rejects/flags per enforce/report mode; `is_table=True` always exempt | unit | `uv run pytest tests/unit/test_chunk_substance_gate.py -k gate -x` | `tests/unit/test_chunk_substance_gate.py::test_apply_substance_gate_enforce_mode_excludes_nav_junk`, `::test_apply_substance_gate_is_table_exempt_regardless_of_text` | ✅ green |
| 20-01-T3 | 20-01 | 1 | PIPE-01, QUAL-05 | Tampering | `filter_config_version` folded into WR-05 per-chunk content hash (version bump → new hash); conservation invariant raises `RuntimeError` on violation | unit | `uv run pytest tests/unit/test_chunk_storage.py -k cache_version -x` | `tests/unit/test_chunk_storage.py::test_chunk_different_filter_config_version_produces_different_content_hash`, `::test_chunk_same_filter_config_version_hits_existing_cache` | ✅ green |
| 20-02-T1 | 20-02 | 1 | QUAL-03 | — | `chunk_document` (Dagster) resolves `DomainLoader.from_name(...).filters` and threads into `chunk()`, mirroring `enrich_document`'s guard | unit | AST-based verify (plan Task 1) + `pytest tests/unit/test_asset_ordering.py tests/unit/test_dagster_retry_policies.py tests/unit/test_tree_index_asset.py -x` | `src/knowledge_lake/dagster_defs/assets.py` (modified, verified via existing asset tests) | ✅ green |
| 20-02-T2 | 20-02 | 1 | QUAL-03 | — | `process_crawled()` resolves `domain_filters` once (outside loop) and threads into every `chunk()` call; `None` when no domain configured | unit | `uv run pytest tests/unit/test_process_crawled_clean.py -x` | `tests/unit/test_process_crawled_clean.py::TestProcessCrawledDomainFilters` (2 tests) | ✅ green |
| 20-02-T3 | 20-02 | 1 | MEAS-02 | V5 | `filters.yaml` gains cardinality-constraint pattern (`\d+\s*(?:of\|/)\s*\d+`), closing the 5th of 5 MEAS-02 fixture categories | unit | plan-specified verify script + `pytest tests/unit/test_domain_loader.py tests/unit/test_clean.py -x` | `domains/healthcare/filters.yaml` (7 entries) | ✅ green |
| 20-03-T1 | 20-03 | 1 | EXPORT-01 | Information Disclosure | `export_rag_corpus()` gates on chunk-level `substance_passed` (True/missing-key included, False/None excluded); no new export column added | unit | `uv run pytest tests/unit/test_export.py -k RagCorpus -x` | `tests/unit/test_export.py::TestRagCorpus` | ✅ green |
| 20-03-T2 | 20-03 | 1 | EXPORT-02 | — | `generate_qa_example()`/`generate_instruction_example()` tag `DatasetExample.payload` with `version` from `filter_config_version` | unit | `uv run pytest tests/unit/test_datasets.py -k version -x` | `tests/unit/test_datasets.py::test_qa_example_payload_carries_version_field`, `::test_instruction_example_payload_carries_version_field`, `::test_qa_example_different_filter_config_version_yields_different_version_tag` | ✅ green |
| 20-04-T1 | 20-04 | 1 | MEAS-02 | — | `tests/fixtures/must_not_reject.yaml` — 25 hand-labeled clinical fixtures (5 per category: icd_code, dosage, loinc, hipaa_ref, cardinality_constraint) | fixture validation | plan-specified verify script (yaml.safe_load + category/label assertions) | `tests/fixtures/must_not_reject.yaml` (25 entries confirmed) | ✅ green |
| 20-04-T2 | 20-04 | 1 | MEAS-02 | V5 | Parametrized CI test proves every fixture survives the REAL `chunk()` gate with `domain_filters` resolved via the REAL `DomainLoader.from_name("healthcare")` | unit (parametrized) | `uv run pytest tests/unit/test_must_not_reject.py -x` | `tests/unit/test_must_not_reject.py::test_fixture_survives_real_chunk_substance_gate` (25/25 parametrized cases) | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs assigned by the planner (20-chunk-substance-gate-export-gate, 2026-07-17): 4 plans, 1 wave (sequential — 20-02/03/04 build on 20-01), 10 tasks total.*

---

## Wave 0 Requirements

All gaps closed within the plans' own tasks:

- [x] `tests/fixtures/must_not_reject.yaml` — 25 hand-labeled entries (D-15), exceeding the ~20 minimum: label, text, category (icd_code, dosage, loinc, hipaa_ref, cardinality_constraint) — Plan 20-04, Task 1
- [x] `tests/unit/test_must_not_reject.py` — parametrized CI gate test (D-16), covers MEAS-02, proven non-vacuous via deliberate local fixture corruption — Plan 20-04, Task 2
- [x] `tests/unit/test_chunk_substance_gate.py` — new file (20 tests), covers QUAL-02/QUAL-03 gate logic, enforce/report modes, conservation invariant — Plan 20-01
- [x] Extend `tests/unit/test_chunk_storage.py` — cache-key versioning assertions (PIPE-01) — Plan 20-01, Task 3
- [x] Extend `tests/unit/test_export.py` — `substance_passed` filtering assertions (EXPORT-01) — Plan 20-03, Task 1
- [x] Extend `tests/unit/test_datasets.py` — version-tag assertions (EXPORT-02) — Plan 20-03, Task 2
- [x] Framework install: none — pytest/datatrove already present

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies — all 10 tasks across 4 plans carry `<verify><automated>` commands
- [x] Sampling continuity: no 3 consecutive tasks without automated verify — every task has one
- [x] Wave 0 covers all MISSING references — all gaps closed within the plans' own tasks
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated — all 4 plans (10 tasks) executed and verified green; full suite reached 1114 passed, 3 skipped, 6 xfailed, 0 failed at phase completion; retroactive audit 2026-07-18 re-confirmed all named test functions/classes and the 25-entry fixture file present

---

## Validation Audit 2026-07-18

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

Reconstructed per-task map from all 4 plans' SUMMARY.md files (task IDs/plan/wave were TBD placeholders at planning time). Cross-checked every named test function/class against source via grep, and confirmed `tests/fixtures/must_not_reject.yaml` contains exactly 25 entries via `yaml.safe_load`. No gaps.
