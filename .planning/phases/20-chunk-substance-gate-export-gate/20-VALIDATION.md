---
phase: 20
slug: chunk-substance-gate-export-gate
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-17
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
| 20-01-01 | 01 | TBD | QUAL-02 | V5 | FineWebQualityFilter rejects too-short/no-sentences, passes clinical control set, uses chunk-scoped settings not CurateSettings | unit | `pytest tests/unit/test_chunk_substance_gate.py -k fineweb -x` | ❌ W0 | ⬜ pending |
| 20-01-02 | 01 | TBD | QUAL-03 | Tampering/Repudiation | Composite predicate rejects/flags per enforce/report mode; `is_table=True` always exempt; conservation invariant asserted | unit | `pytest tests/unit/test_chunk_substance_gate.py -k gate -x` | ❌ W0 | ⬜ pending |
| 20-02-01 | 02 | TBD | MEAS-02 | V5 | ~20 must-not-reject fixtures (ICD/LOINC/RxNorm/HIPAA/dosage/cardinality) never dropped by the gate | unit (parametrized) | `pytest tests/unit/test_must_not_reject.py -x` | ❌ W0 | ⬜ pending |
| 20-03-01 | 03 | TBD | EXPORT-01 | Information Disclosure | Mixed-quality doc exports only `substance_passed=True` chunks to gold; no new export column added | unit | `pytest tests/unit/test_export.py -k substance -x` | ❌ W0 (extends existing) | ⬜ pending |
| 20-03-02 | 03 | TBD | EXPORT-02 | — | Eval dataset examples carry `version` field derived from `filter_config_version` | unit | `pytest tests/unit/test_datasets.py -k version -x` | ❌ W0 (extends existing) | ⬜ pending |
| 20-04-01 | 04 | TBD | PIPE-01 | Tampering | Config version bump invalidates chunk cache key, triggers re-processing on next run | unit | `pytest tests/unit/test_chunk_storage.py -k cache_version -x` | ❌ W0 (extends existing) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Plan/Wave columns are TBD — the planner assigns final plan IDs and wave numbers; this table's Req ID → Test mapping is the binding contract.*

---

## Wave 0 Requirements

- [ ] `tests/fixtures/must_not_reject.yaml` — ~20 hand-labeled entries (D-15): label, text, category (icd_code, dosage, loinc, hipaa_ref, cardinality_constraint)
- [ ] `tests/unit/test_must_not_reject.py` — parametrized CI gate test (D-16), covers MEAS-02
- [ ] `tests/unit/test_chunk_substance_gate.py` — new file, covers QUAL-02/QUAL-03 gate logic, enforce/report modes, conservation invariant
- [ ] Extend `tests/unit/test_chunk_storage.py` — cache-key versioning assertions (PIPE-01)
- [ ] Extend `tests/unit/test_export.py` — `substance_passed` filtering assertions (EXPORT-01)
- [ ] Extend `tests/unit/test_datasets.py` — version-tag assertions (EXPORT-02)
- [ ] Framework install: none — pytest/datatrove already present

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
