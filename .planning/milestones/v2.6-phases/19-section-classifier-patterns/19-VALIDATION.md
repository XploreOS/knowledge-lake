---
phase: 19
slug: section-classifier-patterns
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-16
validated: 2026-07-18
---

# Phase 19 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-cov 5.x (both pinned in pyproject.toml) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `xfail_strict = true`, `testpaths = ["tests"]` |
| **Quick run command** | `uv run pytest tests/unit/test_clean.py tests/unit/test_quality_predicates.py tests/unit/test_domain_loader.py -x -q` |
| **Full suite command** | `uv run pytest --cov=knowledge_lake --cov-branch` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit/test_clean.py tests/unit/test_quality_predicates.py -x -q`
- **After every plan wave:** Run `uv run pytest tests/unit/ -x -q` (all unit tests — this phase touches shared `clean.py` consumed by `process.py`, `quality_audit.py`, and the Dagster `clean_document` asset)
- **Before `/gsd-verify-work`:** `uv run pytest --cov=knowledge_lake --cov-branch` full suite green, plus the explicit 100%-branch-coverage gate on `pipeline/quality/`
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 19-01-T1 | 19-01 | 1 | QUAL-01 | — | `pipeline/quality/` package: 7 pure `check_*` predicates, `PredicateResult`, `run_predicates()`, `compute_substance_signals()` — zero I/O | unit | `uv run pytest tests/unit/test_quality_predicates.py -x` | `tests/unit/test_quality_predicates.py` (29 tests) | ✅ green |
| 19-01-T2 | 19-01 | 1 | QUAL-01 | — | Zero-I/O contract: importing `pipeline.quality` never transitively loads sqlalchemy/boto3/dagster; 100% branch coverage | unit + coverage gate | `uv run pytest tests/unit/test_quality_predicates.py --cov=knowledge_lake.pipeline.quality --cov-branch --cov-fail-under=100` | `tests/unit/test_quality_predicates.py::test_import_does_not_pull_in_sqlalchemy_boto3_dagster` | ✅ green (100% branch cov confirmed) |
| 19-02-T1 | 19-02 | 1 | CLEAN-06 | — | `DomainFilters` model validates `filters.yaml` (boilerplate_patterns/normative_allowlists/thresholds) | unit | `uv run pytest tests/unit/test_domain_loader.py -k filters -x` | `tests/unit/test_domain_loader.py::test_domain_filters_model_defaults` | ✅ green |
| 19-02-T2 | 19-02 | 1 | CLEAN-06 | — | `DomainLoader.filters` is `None` (no exception) for packs without `filters.yaml`; populated for healthcare; healthcare allowlist covers ICD-10/LOINC/RxNorm | unit | `uv run pytest tests/unit/test_domain_loader.py -x` | `tests/unit/test_domain_loader.py::test_domain_loader_aviation_has_no_filters`, `::test_domain_loader_healthcare_has_filters` | ✅ green |
| 19-03-T1 | 19-03 | 1 | CLEAN-05 | — | `BOILERPLATE_PATTERNS` extended 4→9 entries covering 5 garbage categories; indices 0-3 byte-identical (Phase-18 gate stays decoupled) | unit | `uv run pytest tests/unit/test_clean.py tests/unit/test_gate_signature_pin.py -x` | `tests/unit/test_clean.py::test_boilerplate_removal_nav_menu_extended` (+4 sibling category tests) | ✅ green |
| 19-03-T2 | 19-03 | 1 | CLEAN-05 | — | Genuine clinical safety sentence containing "disclaimer" is NOT stripped (prohibition regression guard); empty-string edge case | unit | `uv run pytest tests/unit/test_clean.py -x` | `tests/unit/test_clean.py::test_boilerplate_preserves_clinical_disclaimer_sentence`, `::test_boilerplate_removal_empty_string_no_raise` | ✅ green |
| 19-04-T1 | 19-04 | 1 | CLEAN-04 | — | `classify_sections()` computes substance signals + `is_boilerplate`/`allowlisted`/`reason` without mutating/dropping (TDD RED→GREEN) | unit | `uv run pytest tests/unit/test_clean.py -k classify -x` | `tests/unit/test_clean.py::test_classify_sections_distinguishes_boilerplate_from_clinical`, `::test_classify_sections_allowlist_override` | ✅ green |
| 19-04-T2 | 19-04 | 1 | CLEAN-04 | — | `_clean_sections()`/`clean()` actually drop boilerplate sections; domain-allowlist unconditionally overrides for short clinical codes/dosage patterns; `section_annotations` persisted for every section | unit | `uv run pytest tests/unit/test_clean.py -k TestClassifySectionsCleanIntegration -x` | `tests/unit/test_clean.py::TestClassifySectionsCleanIntegration` (4 tests) | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs assigned by the planner (19-section-classifier-patterns, 2026-07-16): 4 plans, 1 wave (sequential — 19-04 depends on 19-01/02/03), 8 tasks total, all `tdd="true"` where noted.*

---

## Wave 0 Requirements

All gaps closed within the plans' own tasks (each pairs code change with tests in the same task):

- [x] `tests/unit/test_quality_predicates.py` — new file, covers QUAL-01, 100% branch coverage confirmed (`--cov-fail-under=100` passes) — Plan 19-01, Tasks 1-2
- [x] `domains/healthcare/filters.yaml` — new fixture file with clinical-code allowlist (ICD-10, LOINC, RxNorm, dosage patterns) — Plan 19-02, Task 2
- [x] Must-not-reject coverage for CLEAN-06: `test_classify_sections_allowlist_overrides_short_clinical_code`/`_dosage_pattern` prove ICD-10/dosage strings survive — Plan 19-04, Task 2 (full ~20-item MEAS-02 fixture set remains Phase 20's job, as scoped)
- [x] Coverage gate: run inline via `pytest --cov=knowledge_lake.pipeline.quality --cov-branch --cov-fail-under=100` (not wired into a Makefile target — acceptable, ran directly in this audit and confirmed 100%)

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies — all 8 tasks across 4 plans carry `<verify><automated>` commands
- [x] Sampling continuity: no 3 consecutive tasks without automated verify — every task has one
- [x] Wave 0 covers all MISSING references — all gaps closed within the plans' own tasks
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated — all 4 plans (8 tasks) executed and verified green; full unit suite reached 837 passed, 1 xfailed, 0 failed at phase completion; retroactive audit 2026-07-18 re-confirmed 100% branch coverage gate and all named test functions/classes present

---

## Validation Audit 2026-07-18

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

Reconstructed per-task map from all 4 plans' SUMMARY.md files (task IDs and plan/wave assignments were TBD placeholders at planning time). Cross-checked every named test function/class against source via grep — all present. Re-ran the QUAL-01 100%-branch-coverage gate directly: `uv run pytest tests/unit/test_quality_predicates.py --cov=knowledge_lake.pipeline.quality --cov-branch --cov-fail-under=100` → 33 passed, 100% coverage confirmed (test count grew from 29 to 33 across the phase's later plans touching the same file). No gaps.
