---
phase: 11
slug: crawl-scheduling
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-10
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: 11-RESEARCH.md § Validation Architecture (all commands verified against installed `.venv`).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (+ pytest-asyncio, `asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]`, `testpaths = ["tests"]` |
| **Quick run command** | `./.venv/bin/pytest tests/unit/test_recrawl_gate.py tests/unit/test_recrawl_sensor.py -x -q` |
| **Full suite command** | `./.venv/bin/pytest -q` |
| **Estimated runtime** | ~30 seconds (quick unit); full suite ~several minutes |

---

## Sampling Rate

- **After every task commit:** Run `./.venv/bin/pytest tests/unit/test_recrawl_gate.py tests/unit/test_recrawl_sensor.py -x -q`
- **After every plan wave:** Run `./.venv/bin/pytest tests/unit -q`
- **Before `/gsd-verify-work`:** Full suite (`./.venv/bin/pytest -q`) must be green
- **Max feedback latency:** ~30 seconds (quick unit path)

---

## Per-Task Verification Map

> Task IDs are provisional until PLAN.md files exist — rows are keyed by requirement + behavior from RESEARCH.md and will bind to concrete task IDs during planning/execution.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 11-01-xx | 01 | 0 | SCHED-02 | T-11-SSRF | Seed probe calls `validate_public_url()` before HTTP; `put_raw` NOT called on unchanged skip | unit | `pytest tests/unit/test_recrawl_gate.py::test_unchanged_skips_no_raw -x` | ❌ W0 | ⬜ pending |
| 11-01-xx | 01 | 0 | SCHED-02 | — | Changed signature ⇒ full `crawl_source` path + `last_content_hash` updated | unit | `pytest tests/unit/test_recrawl_gate.py::test_changed_recrawls -x` | ❌ W0 | ⬜ pending |
| 11-01-xx | 01 | 0 | SCHED-02 | T-11-THRASH | Reuses `remove_boilerplate` — dynamic nonce/timestamp does NOT flip the hash | unit | `pytest tests/unit/test_recrawl_gate.py::test_nonce_noise_unchanged -x` | ❌ W0 | ⬜ pending |
| 11-01-xx | 01 | 0 | SCHED-02 | — | `last_content_hash IS NULL` ⇒ always crawls | unit | `pytest tests/unit/test_recrawl_gate.py::test_null_hash_forces_crawl -x` | ❌ W0 | ⬜ pending |
| 11-01-xx | 01 | 0 | SCHED-02 | — | Staleness exceeded ⇒ re-ingest even when hash matches | unit | `pytest tests/unit/test_recrawl_gate.py::test_staleness_forces_refresh -x` | ❌ W0 | ⬜ pending |
| 11-02-xx | 02 | 0 | SCHED-01 | T-11-TICKSTORM | Sensor emits exactly one `RunRequest` per due source with deterministic `run_key` | unit | `pytest tests/unit/test_recrawl_sensor.py::test_emits_deterministic_run_key -x` | ❌ W0 | ⬜ pending |
| 11-02-xx | 02 | 0 | SCHED-01 | — | Not-due source emits `SkipReason`, no RunRequest | unit | `pytest tests/unit/test_recrawl_sensor.py::test_skips_not_due -x` | ❌ W0 | ⬜ pending |
| 11-02-xx | 02 | 0 | SCHED-01 | T-11-TICKSTORM | Same fire window ⇒ identical run_key (idempotent across re-eval) | unit | `pytest tests/unit/test_recrawl_sensor.py::test_run_key_stable_within_window -x` | ❌ W0 | ⬜ pending |
| 11-02-xx | 02 | 0 | SCHED-01 | T-11-CRON | `is_valid_cron_string` rejects malformed schedule at set time | unit | `pytest tests/unit/test_set_schedule_cli.py::test_rejects_bad_cron -x` | ❌ W0 | ⬜ pending |
| 11-03-xx | 03 | — | Criterion 1 | — | `0009` upgrade adds 3 nullable columns; downgrade drops them; head chains 0008→0009 | integration | `pytest tests/integration/test_migrations.py -x` (extend existing) | ⚠️ extend | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_recrawl_gate.py` — SCHED-02 gate stubs (skip/crawl/null/staleness/nonce). Use a fake adapter returning controlled markdown; patch `StorageBackend`/`put_raw` to assert it is NOT called on skip.
- [ ] `tests/unit/test_recrawl_sensor.py` — SCHED-01 stubs via `dagster.build_sensor_context(cursor=...)`; assert `run_key`, run tags, cursor advance, and `SkipReason`.
- [ ] `tests/unit/test_set_schedule_cli.py` — CLI set/clear schedule + `is_valid_cron_string` rejection.
- [ ] Extend `tests/integration/test_migrations.py` (and/or `tests/integration/test_crawl_schema.py`) for the `0009` columns + 0008→0009 head chain.
- [ ] Fixtures: reuse `tests/conftest.py` in-memory SQLite pattern; add a `DummySource` namedtuple for the materialized-row helper.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Sensor actually fires on schedule under the running Dagster daemon | SCHED-01 | Requires the docker-compose `dagster-daemon` process up; in-process `build_sensor_context` covers logic but not daemon tick delivery | Bring up compose, set a source `crawl_schedule` to a near-future cron, confirm a `recrawl_source_job` run launches with the expected `run_key` |
| Per-source concurrency=1 under `QueuedRunCoordinator` | SCHED-01 (D-16) | `applyLimitPerUniqueValue` on `klake/source` is inert under `DefaultRunCoordinator`; only observable against a live queued daemon | With `QueuedRunCoordinator` configured, enqueue two runs for the same `source_id`; confirm the second queues until the first completes |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
