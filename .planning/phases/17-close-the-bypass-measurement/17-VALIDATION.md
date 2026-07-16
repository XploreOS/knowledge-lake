---
phase: 17
slug: close-the-bypass-measurement
status: planned
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-16
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (project-wide; `xfail_strict = true` in `pyproject.toml:125`) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/unit/test_clean.py tests/unit/test_clean_silver_key.py tests/unit/test_pipeline_extractions.py -x` |
| **Full suite command** | `uv run pytest tests/unit tests/integration -x` (excludes `tests/e2e`, which requires `docker compose up` per its module docstring) |
| **Estimated runtime** | ~30 seconds (unit+integration; excludes e2e) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit/test_clean.py tests/unit/test_clean_silver_key.py tests/unit/test_pipeline_extractions.py -x`
- **After every plan wave:** Run `uv run pytest tests/unit tests/integration -x`
- **Before `/gsd-verify-work`:** Full suite must be green, plus `tests/e2e/test_e2e_healthcare.py` if a docker-compose environment is available (not required for the unit/integration gate, but directly exercises `clean_document → chunk_document` materialization end-to-end — the natural place to assert CLEAN-01's literal acceptance criterion)
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 17-01-T1 | 17-01 | 1 | CLEAN-01, CLEAN-02, CLEAN-03 | T-17-01-01 | `clean()` threads parsed_doc, cleans sections without dropping any, WR-05 parent-scoped hash | unit | `uv run pytest tests/unit/test_clean.py tests/unit/test_clean_silver_key.py -x` | extend `tests/unit/test_clean.py` | ⬜ pending |
| 17-01-T2 | 17-01 | 1 | QUAL-04, QUAL-05 | T-17-01-01 | Conservation invariant (`rejected+kept==considered`), unconditional rejection-count recording | unit | `uv run pytest tests/unit/test_clean.py -x` | extend `tests/unit/test_clean.py` | ⬜ pending |
| 17-02-T1 | 17-02 | 2 | CLEAN-01 | T-17-02-01 | `clean_document` forwards `clean_result["cleaned_doc"]` under the `"parsed_doc"` key | integration | `uv run pytest tests/integration/test_dagster_assets.py::TestDefinitionsLoad -x` | `src/knowledge_lake/dagster_defs/assets.py` (modified) | ⬜ pending |
| 17-02-T2 | 17-02 | 2 | CLEAN-01 | T-17-02-01 | `chunk_document` receives sections with boilerplate removed; uncleaned `parsed_doc` no longer forwarded; curate_document_asset regression-free (D-03) | integration | `uv run pytest tests/integration/test_dagster_assets.py -k materialize -x` | extend `test_dagster_materialize_produces_artifacts` (`test_dagster_assets.py:291`) | ⬜ pending |
| 17-03-T1 | 17-03 | 2 | CLEAN-02 | T-17-03-01 | `process_crawled` calls `clean()` between `parse()`/`chunk()`; `chunk()` receives `cleaned_doc` | unit | `uv run pytest tests/unit/test_process_crawled_clean.py -x` | new `tests/unit/test_process_crawled_clean.py` | ⬜ pending |
| 17-03-T2 | 17-03 | 2 | CLEAN-02 | T-17-03-01 | `klake process` produces chunks from cleaned text — identical output to Dagster path; error-handling/empty-chunks parity | unit | `uv run pytest tests/unit/test_process_crawled_clean.py -x` | extend `tests/unit/test_process_crawled_clean.py` | ⬜ pending |
| 17-04-T1 | 17-04 | 2 | MEAS-01, QUAL-04 | T-17-04-01, T-17-04-02 | `run_quality_audit()` per-source table: total sections, kept, rejected, reasons, garbage rate; no embed/index calls | unit | `uv run pytest tests/unit/test_quality_audit.py -x` | new `tests/unit/test_quality_audit.py` | ⬜ pending |
| 17-04-T2 | 17-04 | 2 | MEAS-01 | T-17-04-01 | `klake quality-audit` CLI produces N-row reproducible table (row count = live `Source.domain` query, not hardcoded) or `--json` | unit | `uv run pytest tests/unit/test_cli_quality_audit.py -x` | new `tests/unit/test_cli_quality_audit.py` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs assigned by the planner (17-close-the-bypass-measurement, 2026-07-16): 4 plans, 2 waves, 8 tasks total. Wave 1 (17-01) is a hard prerequisite for Wave 2 (17-02/17-03/17-04, which run in parallel — no file overlap).*

---

## Wave 0 Requirements

All four gaps are covered by the plan's own tasks (each task creates or extends its test file as
part of implementation — no separate Wave 0 scaffold task was needed since every task pairs its
code change with tests in the same task, tdd="true"):

- [x] `tests/unit/test_clean.py` — extended with WR-05 hash-scoping assertions (CLEAN-03) and conservation-invariant assertions (QUAL-05) — Plan 17-01, Tasks 1-2
- [x] `tests/unit/test_process_crawled_clean.py` (new) — covers CLEAN-02's clean-stage insertion and parity with the Dagster path — Plan 17-03, Tasks 1-2
- [x] `tests/integration/test_dagster_assets.py` — extended with a boilerplate-removal content assertion and a curate regression check — Plan 17-02, Task 2
- [x] New test files for the `quality-audit` module and CLI command (MEAS-01, QUAL-04) — `tests/unit/test_quality_audit.py` (Plan 17-04, Task 1) and `tests/unit/test_cli_quality_audit.py` (Plan 17-04, Task 2), following the project's established `typer.testing.CliRunner` pattern
- [x] Framework install: none — pytest and all fixtures already present.

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies — all 8 tasks across 4 plans carry `<verify><automated>` commands
- [x] Sampling continuity: no 3 consecutive tasks without automated verify — every task has one
- [x] Wave 0 covers all MISSING references — all four gaps closed within the plans' own tasks (tdd="true")
- [x] No watch-mode flags
- [x] Feedback latency < 30s — unit-level task commands complete well under 30s; the two integration-level commands (17-02) are plan/wave-level checks against the already-running docker-compose stack, not per-task quick checks
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planned — plans committed 2026-07-16, ready for `/gsd-execute-phase 17`
