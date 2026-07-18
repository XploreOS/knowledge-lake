---
phase: 22
slug: address-tech-debt-measure-garbage-junk-rates-end-to-end-reco
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-17
validated: 2026-07-18
---

# Phase 22 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.1.1 (project-pinned, confirmed via `pyproject.toml`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (line 121) — `testpaths=["tests"]`, `xfail_strict=true`, markers `browser`/`integration` |
| **Quick run command** | `pytest tests/unit/test_quality_audit.py tests/unit/test_cli_quality_audit.py -x` |
| **Full suite command** | `pytest` |
| **Estimated runtime** | ~90 seconds (unit); full suite is the existing 1176+ baseline |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/unit/test_quality_audit.py tests/unit/test_cli_quality_audit.py -x`
- **After every plan wave:** Run `pytest` (full suite)
- **Before `/gsd-verify-work`:** Full suite must be green; additionally, since this phase's actual purpose is producing a real number against real (reprocessed) data, a manual/scripted "run the real thing against the live dev stack" step is required distinct from pytest fixture-based unit tests — the fixture tests prove the *code* is correct; only a real run against the 34 healthcare sources proves the *milestone criteria* are met.
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 22-01-T1 | 22-01 | 1 | QUAL-03 | — | Fixed `domain_filters` gap (Pitfall 1): `run_quality_audit()`'s existing `clean()` call now threads `domain_filters`, closing a real clinical-code-stripping risk | unit | `uv run pytest tests/unit/test_quality_audit.py -k domain_filters -x` | `tests/unit/test_quality_audit.py::TestRunQualityAuditDomainFiltersGap` | ✅ green |
| 22-01-T2 | 22-01 | 1 | MEAS-01 (extended) | — | `run_full_pipeline_audit()` chunk-level tally: correct kept/rejected/reason counts from the real in-memory gate annotation (`_build_token_chunks`+`_apply_substance_gate`), zero-chunks yields `None` rate | unit | `uv run pytest tests/unit/test_quality_audit.py -k chunk_audit -x` | `tests/unit/test_quality_audit.py::TestRunFullPipelineAuditChunkTally` | ✅ green |
| 22-01-T3 | 22-01 | 1 | EXPORT-01 (measurement-side verification) | — | D-04 scoping: export-junk count only reflects this run's own chunk IDs (regression test: seed one pre-v2.6 ungated chunk + one fresh gated chunk in the same fixture DB, assert the scoped measurement excludes the old one while the real unmodified `export_rag_corpus()` independently proves it scanned both) | unit | `uv run pytest tests/unit/test_quality_audit.py -k dilution -x` | `tests/unit/test_quality_audit.py::TestRunFullPipelineAuditExportScoping::test_dilution_regression_excludes_pre_v26_chunks` | ✅ green |
| 22-02-T1 | 22-02 | 2 | MEAS-01 (extended) | — | `klake quality-audit --full` prints extended table (chunks_kept/rejected/garbage_rate + baseline summary); `--full --json` round-trips `{rows, summary}`; empty-rows message unchanged; non-`--full` path byte-identical | unit | `uv run pytest tests/unit/test_cli_quality_audit.py -k FullFlag -x` | `tests/unit/test_cli_quality_audit.py::TestCliQualityAuditFullFlag` (3 tests) + `::test_help_lists_full_flag` | ✅ green |
| 22-03-T1 | 22-03 | 3 | MEAS-01, EXPORT-01 | — | Real, reproducible `klake quality-audit --domain healthcare --full --json` run against the live 34-source healthcare corpus; Pitfall-2/A1 convergence check (`export_junk_rate <= chunk_garbage_rate`) explicitly verified | manual (live-stack) | `uv run klake quality-audit --domain healthcare --full --json` (executed 2026-07-17; see Manual-Only Verifications) | `.planning/phases/22-.../22-03-SUMMARY.md` (captured results) | ✅ green — executed, results captured |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs assigned by the planner (22-address-tech-debt-measure-garbage-junk-rates-end-to-end-reco, 2026-07-17): 3 plans, 3 waves (sequential — 22-02 builds on 22-01's return shape, 22-03 exercises both against the live stack), 5 tasks total.*

---

## Wave 0 Requirements

All gaps closed within the plans' own tasks:

- [x] `tests/unit/test_quality_audit.py` — extended with chunk-level tally tests (`TestRunFullPipelineAuditChunkTally`) + the D-04 dilution-regression test (`TestRunFullPipelineAuditExportScoping`) — Plan 22-01
- [x] `tests/unit/test_cli_quality_audit.py` — extended with `TestCliQualityAuditFullFlag` (3 tests) + help-flag test — Plan 22-02
- [x] No new fixtures/conftest needed — `test_quality_audit.py`'s existing in-memory-SQLite engine/session fixtures (StaticPool, monkeypatched `get_engine`) directly reused

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions | Result (2026-07-17) |
|----------|-------------|------------|-------------------|-----|
| Real end-to-end measurement against the 34 healthcare sources on the live dev stack | Milestone Success Criteria #1/#2 | Requires the live Postgres/MinIO stack and real reprocessed data — not something a pytest fixture can substitute for; this is the actual deliverable of the phase, not incidental verification | Run `klake quality-audit --domain healthcare --full --json` on the live dev stack; capture kept/rejected counts and compare against the 28%/33% baselines | Executed (Plan 22-03, commit `acb8c84`). `chunk_garbage_rate=45.64%` (vs 28% baseline — NOT MET by literal wording, but expected: this measures live gate-rejection of candidates, not post-hoc corpus classification — see 22-03-SUMMARY.md's Interpretive Note). `export_junk_rate=0.0%` (vs 33% baseline — MET, target <2%). Pitfall-2/A1 convergence (`export_junk_rate <= chunk_garbage_rate`) confirmed holding: 0.0% <= 45.64%. |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies — all 5 tasks across 3 plans carry `<verify>` (4 automated, 1 manual-live-stack by design)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify — every task has one
- [x] Wave 0 covers all MISSING references — all gaps closed within the plans' own tasks
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated — all 3 plans (5 tasks) executed; Plan 22-03's live measurement run completed and results captured 2026-07-17; full suite reached 1185 passed, 3 skipped, 6 xfailed, 0 failed; retroactive audit 2026-07-18 re-confirmed all named test classes present

---

## Validation Audit 2026-07-18

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

Reconstructed per-task map from all 3 plans' SUMMARY.md files (task IDs were placeholders at planning time). Cross-checked every named test class against source via grep — all present. Confirmed Plan 22-03's manual-only live-stack measurement was actually executed (not just planned) with results captured in 22-03-SUMMARY.md, including the D-08/D-09 Nyquist-reconciliation operator follow-up that directly requested `/gsd-validate-phase 17` through `21` — this session's audits of phases 17-22 fulfill that follow-up. No gaps.

**Operator note carried forward:** 22-03-SUMMARY.md flags an unresolved product question — whether REQUIREMENTS.md's criterion #1 wording ("<5% garbage chunks") should be revised to reference `export_junk_rate` (the metric representative of "garbage reaching the corpus," measured at 0.0%) rather than `chunk_garbage_rate` (structurally expected to be nonzero, even high, under a correctly-working gate — measured at 45.64%). This is a requirements-clarity decision, not a test-coverage gap, and is out of scope for this validation audit.
