---
phase: 18
slug: gate-decouple
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-16
validated: 2026-07-18
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (project-wide; `xfail_strict = true` in `pyproject.toml`) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `uv run pytest tests/unit/test_gate_signature_pin.py tests/unit/test_recrawl_gate.py -x` |
| **Full suite command** | `uv run pytest tests/unit tests/integration -x` |
| **Estimated runtime** | ~20 seconds (unit only) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit/test_gate_signature_pin.py tests/unit/test_recrawl_gate.py -x`
- **After every plan wave:** Run `uv run pytest tests/unit tests/integration -x`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 20 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 18-01-T1 | 18-01 | 1 | GATE-01 | — | `_GATE_BOILERPLATE_PATTERNS` frozen copy + `_gate_normalize()` sever `_signature()` from `clean.py`'s `remove_boilerplate()` | unit | `uv run pytest tests/unit/test_gate_signature_pin.py tests/unit/test_recrawl_gate.py -x` | `tests/unit/test_gate_signature_pin.py::test_gate_signature_byte_stable` | ✅ green |
| 18-01-T2 | 18-01 | 1 | GATE-01 | — | Gate signature byte-stable across `clean.py` changes; appending a pattern to `BOILERPLATE_PATTERNS` does not change gate sig | unit | `uv run pytest tests/unit/test_gate_signature_pin.py -x` | `tests/unit/test_gate_signature_pin.py::test_gate_decoupled_from_clean_patterns` | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/unit/test_gate_signature_pin.py` (new) — covers GATE-01: gate-signature byte-stability pinning test and decoupled-from-clean-patterns assertion — Plan 18-01, Tasks 1-2
- [x] Existing `tests/unit/test_recrawl_gate.py` already covers the gate's functional regression — no gap

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 20s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** validated — plan 18-01 executed and verified green (7 passed for gate-specific tests; full suite 1000 passed, 3 skipped, 6 xfailed at plan completion); retroactive audit 2026-07-18 confirmed both test functions exist and match the requirement map

---

## Validation Audit 2026-07-18

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

Reconstructed per-task map from 18-01-SUMMARY.md (task IDs were placeholders at planning time; plan had not yet been created). Both tasks' test functions (`test_gate_signature_byte_stable`, `test_gate_decoupled_from_clean_patterns`) confirmed present in `tests/unit/test_gate_signature_pin.py` via source grep. No gaps.
