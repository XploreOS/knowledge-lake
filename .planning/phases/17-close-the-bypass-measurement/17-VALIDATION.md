---
phase: 17
slug: close-the-bypass-measurement
status: draft
nyquist_compliant: false
wave_0_complete: false
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
| 17-TBD | TBD | TBD | CLEAN-01 | — | `chunk_document` receives sections with boilerplate removed; uncleaned `parsed_doc` no longer forwarded | integration | `uv run pytest tests/integration/test_dagster_assets.py -k materialize -x` | ⚠️ Partial — extend `test_dagster_materialize_produces_artifacts` (`test_dagster_assets.py:291`) with a boilerplate-content assertion | ⬜ pending |
| 17-TBD | TBD | TBD | CLEAN-02 | — | `klake process` produces chunks from cleaned text; identical output to Dagster path | unit/integration | new `tests/unit/test_process_crawled_clean.py` | ❌ W0 | ⬜ pending |
| 17-TBD | TBD | TBD | CLEAN-03 | — | Two documents with identical cleaned text produce distinct `content_hash` (WR-05 parent-scoped hash — closes a dormant lineage-corruption bug, see Security Domain) | unit | extend `tests/unit/test_clean.py` | ❌ W0 | ⬜ pending |
| 17-TBD | TBD | TBD | QUAL-04 | — | Per-source table: total sections, kept, rejected, reasons, garbage rate | integration | new test file for `quality-audit` command | ❌ W0 | ⬜ pending |
| 17-TBD | TBD | TBD | QUAL-05 | — | `rejected + kept == sections_considered`; zero-section case distinct from all-rejected case | unit | extend `tests/unit/test_clean.py` | ❌ W0 | ⬜ pending |
| 17-TBD | TBD | TBD | MEAS-01 | — | `klake quality-audit` produces N-row reproducible table (row count = live `Source.domain` query, not hardcoded) | integration | new CLI-level test (Typer `CliRunner`) | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Task IDs are placeholders — the planner assigns final plan/wave/task numbers; this map records the requirement→test coverage contract, not the final task graph.*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_clean.py` — extend with WR-05 hash-scoping assertions (CLEAN-03) and conservation-invariant assertions (QUAL-05)
- [ ] `tests/unit/test_process_crawled_clean.py` (new) — covers CLEAN-02's clean-stage insertion and parity with the Dagster path
- [ ] `tests/integration/test_dagster_assets.py` — extend `test_dagster_materialize_produces_artifacts` (or add a sibling test) with a boilerplate-removal content assertion on the chunk artifacts produced (CLEAN-01)
- [ ] New test file for the `quality-audit` CLI command (MEAS-01, QUAL-04) — no existing fixture/harness to reuse; needs its own `CliRunner`-based test following the project's established CLI test pattern (grep `typer.testing.CliRunner` usage in `tests/` before writing)
- [ ] Framework install: none — pytest and all fixtures already present.

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
