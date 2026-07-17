---
phase: 22
slug: address-tech-debt-measure-garbage-junk-rates-end-to-end-reco
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-17
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
| 22-01-T1 | 22-01 | 1 | MEAS-01 (extended) | — | New chunk-level measurement function returns correct kept/rejected/reason tallies against a seeded in-memory-SQLite fixture (mirrors `test_quality_audit.py`'s existing fixture pattern) | unit | `pytest tests/unit/test_quality_audit.py -k chunk_audit -x` | ❌ Wave 0 — extend existing file | ⬜ pending |
| 22-01-T2 | 22-01 | 1 | EXPORT-01 (measurement-side verification) | — | D-04 scoping: export-junk count only reflects this run's own chunk IDs, not the domain's full 4,521-chunk population (regression test: seed old ungated chunks + new gated chunks in the same fixture DB, assert old chunks are excluded from the reported rate) | unit | `pytest tests/unit/test_quality_audit.py -k dilution -x` | ❌ Wave 0 — new test, critical regression coverage for D-04 | ⬜ pending |
| 22-01-T3 | 22-01 | 1 | — | — | `domain_filters` gap fix (research Pitfall 1): a clinical-code fixture text survives the extended audit's `clean()` call | unit | `pytest tests/unit/test_quality_audit.py -k domain_filters -x` | ❌ Wave 0 — new test | ⬜ pending |
| 22-02-T1 | 22-02 | 2 | MEAS-01 (extended) | — | New CLI command/flag prints the extended table / `--json` output correctly | unit | `pytest tests/unit/test_cli_quality_audit.py -k chunk -x` | ❌ Wave 0 — extend existing file | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs are provisional — assigned by the planner once PLAN.md files exist.*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_quality_audit.py` — extend with chunk-level tally tests + the D-04 dilution-regression test (seed both a pre-v2.6 chunk with no `substance_passed` key and a fresh gated chunk in the same fixture DB; assert the scoped measurement reports only the fresh one)
- [ ] `tests/unit/test_cli_quality_audit.py` — extend with the new CLI surface's output-format test
- [x] No new fixtures/conftest needed — `test_quality_audit.py`'s existing in-memory-SQLite engine/session fixtures (StaticPool, monkeypatched `get_engine`) are directly reusable

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real end-to-end measurement against the 34 healthcare sources on the live dev stack | Milestone Success Criteria #1/#2 | Requires the live Postgres/MinIO stack and real reprocessed data — not something a pytest fixture can substitute for; this is the actual deliverable of the phase, not incidental verification | Run the new chunk-level measurement command/function against `domain="healthcare"` on the live dev stack; capture kept/rejected counts and compare against the 28%/33% baselines from `MILESTONE-CONTEXT.md` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** planned — pending `/gsd-plan-phase 22` plan creation
