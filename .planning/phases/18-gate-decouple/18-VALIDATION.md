---
phase: 18
slug: gate-decouple
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-16
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
| 18-TBD | TBD | TBD | GATE-01 | — | Gate signature byte-stable across clean.py changes; adding pattern to BOILERPLATE_PATTERNS does not change gate sig | unit | `uv run pytest tests/unit/test_gate_signature_pin.py -x` | ❌ W0 — new file | ⬜ pending |
| 18-TBD | TBD | TBD | GATE-01 | — | Existing recrawl gate tests still pass (no regression from decoupling) | unit | `uv run pytest tests/unit/test_recrawl_gate.py -x` | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_gate_signature_pin.py` (new) — covers GATE-01: gate-signature byte-stability pinning test and decoupled-from-clean-patterns assertion
- [ ] Existing `tests/unit/test_recrawl_gate.py` already covers the gate's functional regression — no gap

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
