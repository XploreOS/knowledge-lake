---
phase: 11-crawl-scheduling
verified: 2026-07-11T04:49:00Z
reverified: 2026-07-11T06:20:00Z
status: verified
score: 9/9 must-haves verified
behavior_unverified: 0
overrides_applied: 0
gap_closure_plan: 11-06-PLAN.md
resolved_human_verification:
  - item: "Nonce/timestamp thrash suppression (SCHED-02 acceptance clause, truth #7)."
    resolution: "Closed by 11-06. Added gate-local volatile-token suppression (_suppress_volatile) in pipeline/crawl.py, layered on remove_boilerplate (clean.py untouched): ISO-8601 datetimes, HH:MM:SS clock times, UUIDs, and >=16-char hex nonces are neutralized before the signature is hashed. The ISO pattern requires a time component so human-meaningful bare dates survive; over-suppression is bounded by max_staleness_days. The self-fulfilling test_nonce_noise_unchanged was rewritten to import the gate's real _signature and assert unconditionally sig_a==sig_b AND crawl_source NOT called."
    evidence: "commit c2bdd19; tests/unit/test_recrawl_gate.py 5 passed; independent check: inline-timestamp & UUID nonces suppress (skip), bare effective-date '2026-01-01' vs '2027-01-01' preserved (recrawl), genuine content change recrawls; git diff confirms pipeline/clean.py byte-for-byte unchanged."
  - item: "Live per-source concurrency serialization under QueuedRunCoordinator."
    resolution: "Demonstrated by exercising Dagster's genuine dequeue decision (QueuedRunCoordinatorDaemon._get_runs_to_dequeue) against an ephemeral instance seeded with real QUEUED runs, using the exact tag_concurrency_limits parsed from the shipped infra/dagster/dagster.yaml. Committed as a durable regression + config-drift guard. The running dagster-webserver/daemon still hold pre-phase-11 definitions (recrawl_source_job not yet loaded), so a real two-crawl launch was deliberately NOT forced on the user's running dev stack; the coordinator gating itself is proven against the identical live config."
    evidence: "commit db16687; tests/integration/test_recrawl_concurrency.py 2 passed — 3 queued src_A + 2 src_B dequeue as {A:1, B:1} (same-source serialized, cross-source concurrent); 1 in-flight src_A holds both queued src_A while src_B dequeues (in-flight hold)."
---

# Phase 11: Crawl Scheduling Verification Report

**Phase Goal:** The lake re-crawls sources on schedule and only re-ingests genuinely changed content, so it stays fresh without thrashing the immutable raw zone.
**Verified:** 2026-07-11T04:49:00Z
**Re-verified:** 2026-07-11T06:20:00Z (after gap-closure plan 11-06)
**Status:** verified (was human_needed; both human-verification items closed — see Gap Closure below)
**Re-verification:** Yes — gap closure of the 2 human-verification items

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Lake re-crawls scheduled sources: sensor emits due-based RunRequests | ✓ VERIFIED | Live `build_sensor_context` eval: due source (`0 3 * * *`, base created_at) emitted exactly 1 RunRequest; not-due source returned `SkipReason`. |
| 2 | Deterministic run_key avoids duplicate runs / tick storms | ✓ VERIFIED | Live: run_key = `src_DUE:2026-07-11T03:00:00+00:00` (cron fire timestamp, not `now`); second eval in same window produced identical run_key. QueuedRunCoordinator config verified (see truth 9). |
| 3 | Change gate skips unchanged content before any raw write (WORM-safe) | ✓ VERIFIED | `test_unchanged_skips_no_raw` + `test_nonce_noise_unchanged` pass; crawl.py:143-151 skip branch calls only `touch_source_crawl(last_crawled_at=now)`, `crawl_source` not invoked. |
| 4 | Changed / NULL-hash / stale forces full re-ingest + hash update | ✓ VERIFIED | `test_changed_recrawls`, `test_null_hash_forces_crawl`, `test_staleness_forces_refresh` pass; crawl.py:154-155 calls `crawl_source` then writes new `last_content_hash`. |
| 5 | SSRF `validate_public_url` runs before any outbound HTTP | ✓ VERIFIED | crawl.py:133 `validate_public_url(url)` precedes crawl.py:139 `adapter.fetch_page(url)`; asserted by gate tests (`mock_validate.assert_called_once`). |
| 6 | Gate hashes normalized silver-stage text, not raw bytes | ✓ VERIFIED | `_signature` reuses `remove_boilerplate` from pipeline.clean; live: identical text → same sig, genuine content change → different sig. No second normalizer; no raw-bytes hashing. |
| 7 | Dynamic timestamps/nonces don't thrash the raw zone | ✓ VERIFIED (closed by 11-06) | Gate-local `_suppress_volatile` neutralizes ISO-8601 timestamps, clock times, UUIDs, and long hex nonces on top of `remove_boilerplate` (clean.py untouched). Independent check: inline-body timestamp & UUID nonce → same signature (skip); bare effective-date preserved (recrawl); genuine change recrawls. `test_nonce_noise_unchanged` now asserts suppression + skip unconditionally. commit c2bdd19. |
| 8 | Additive forward-only 0009 migration: 3 nullable columns | ✓ VERIFIED | Live klake_test: `crawl_schedule VARCHAR(255)`, `last_crawled_at TIMESTAMP`, `last_content_hash VARCHAR(64)` all nullable; alembic head = 0009, down_revision 0008; no server_default; downgrade round-trip green (13 passed). |
| 9 | Schedule set via sources.yaml + CLI, cron-validated, stored as a COLUMN; per-source concurrency=1 config | ✓ VERIFIED | Live CLI: valid cron persists to `crawl_schedule` column (config stays NULL), malformed cron rejected pre-write (exit 1), `--clear` → None, unknown source → exit 1. dagster.yaml = QueuedRunCoordinator, tag_concurrency_limits klake/source applyLimitPerUniqueValue=true limit=1. Serialization now exercised end-to-end against the real dequeue decision (commit db16687). |

**Score:** 9/9 truths verified (truth #7 closed by gap-closure plan 11-06)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `registry/alembic/versions/0009_crawl_scheduling.py` | Additive migration, revision 0009 → 0008 | ✓ VERIFIED | 3 nullable `op.add_column`, reverse-order downgrade, no server_default. Live head=0009. |
| `registry/models.py` | 3 nullable Mapped columns on Source | ✓ VERIFIED | `crawl_schedule`/`last_crawled_at`/`last_content_hash` present, all nullable. |
| `registry/repo.py` | touch_source_crawl, list_scheduled_sources, set_source_schedule, create_source kwarg | ✓ VERIFIED | All import cleanly; `_ScheduledSource` namedtuple materialized; `create_source(crawl_schedule=...)` persists column (live). |
| `config/settings.py` | max_staleness_days default 30 + env override | ✓ VERIFIED | Default 30; `KLAKE_CRAWL__MAX_STALENESS_DAYS=7` → 7 (live). |
| `pipeline/crawl.py` | recrawl_source + _signature gate | ✓ VERIFIED | Probe→normalize→sha256→skip/crawl; WORM-safe; SSRF-first; reuses remove_boilerplate. |
| `domains/models.py` | SourceEntry.crawl_schedule optional | ✓ VERIFIED | Defaults None; accepts cron string. |
| `cli/app.py` | set-schedule verb + domain-init persistence, cron-validated | ✓ VERIFIED | `is_valid_cron_string` guards both paths; live CLI exercise passes. |
| `dagster_defs/sensors.py` | RecrawlConfig, recrawl_op, recrawl_source_job, recrawl_sensor | ✓ VERIFIED | All importable; sensor side-effect-free apart from update_cursor; no croniter import. |
| `dagster_defs/definitions.py` | sensor + job registered | ✓ VERIFIED | Live: sensors={recrawl_sensor}, jobs include recrawl_source_job; default_status=RUNNING, min_interval=60. |
| `infra/dagster/dagster.yaml` | QueuedRunCoordinator + klake/source limit 1 | ✓ VERIFIED | Config parsed and confirmed. |

### Key Link Verification

| From | To | Via | Status |
|------|----|----|--------|
| recrawl_sensor | recrawl_source_job | `@dg.sensor(job=recrawl_source_job)` + RunRequest | ✓ WIRED (live eval emits RunRequest targeting the job) |
| recrawl_op | pipeline.crawl.recrawl_source | `asyncio.run(recrawl_source(config.source_id))` | ✓ WIRED |
| recrawl_source | crawl_source (change path) | reused wholesale, no logic duplicated | ✓ WIRED |
| recrawl_source | repo.touch_source_crawl | skip: bumps last_crawled_at only; crawl: writes hash | ✓ WIRED |
| sensor | repo.list_scheduled_sources | patchable module wrapper, own session | ✓ WIRED |
| set-schedule / domain-init | repo.set_source_schedule / create_source | is_valid_cron_string before persist, column not config | ✓ WIRED (live) |
| RunRequest tags | QueuedRunCoordinator | `{"klake/source": src.id}` → tag_concurrency_limits | ✓ WIRED (tag present live; serialization exercised against the real dequeue decision with the shipped config — tests/integration/test_recrawl_concurrency.py, commit db16687) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Phase 11 unit suites | `pytest test_recrawl_gate/sensor/set_schedule_cli` | 11 passed | ✓ PASS |
| Migration integration | `pytest tests/integration/test_migrations.py` (klake_test) | 13 passed, 2 skipped | ✓ PASS |
| Live sensor due/skip/idempotent | `build_sensor_context` eval | due→1 RunRequest, notdue→SkipReason, run_key stable | ✓ PASS |
| Live set-schedule CLI | `klake set-schedule` (klake_test) | valid persists as column; malformed exit 1; clear→None; unknown exit 1 | ✓ PASS |
| remove_boilerplate strips inline timestamp | live `_signature` on nonce pair | NOT stripped → sigs differ | ✗ FAIL (informs truth 7) |
| alembic head | `alembic current` / `heads` | 0009 (head) | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| SCHED-01 | 11-01/02/04/05 | Dagster sensor triggers periodic re-crawl by `crawl_schedule`, deterministic run_key + cursor watermark to avoid duplicate runs/tick storms | ✓ SATISFIED | Truths 1,2,8,9; live sensor eval + CLI + Definitions registration + QueuedRunCoordinator config. |
| SCHED-02 | 11-01/02/03 | Change comparison over normalized silver-stage text (not raw bytes) gates re-ingest; max-staleness forces refresh | ✓ SATISFIED (core) | Truths 3,4,5,6,8; WORM-safe skip, SSRF-first, staleness override, normalized signature. Caveat: nonce/timestamp suppression clause is normalizer-dependent and weakly tested (truth 7 → human review). |

Both requirement IDs accounted for. REQUIREMENTS.md lines 38-39 mark both `[x]` and lines 101-102 mark both "Complete". No orphaned SCHED requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| tests/unit/test_recrawl_gate.py | 173-229 | ~~Self-fulfilling conditional assertion in `test_nonce_noise_unchanged`~~ | ✓ RESOLVED (11-06) | Rewritten to assert `sig_a==sig_b` AND `crawl_source` not-called unconditionally, using the gate's real `_signature`. commit c2bdd19. |
| tests/unit/test_set_schedule_cli.py | 63-101 | "Unit" tests patch `set_source_schedule` but not `get_session` | ℹ️ Info | Tests implicitly require a live Postgres (pass here because docker is up; would fail DB-less per prior review CR-01). Functional behavior independently live-verified. |
| infra/dagster/dagster.yaml | 29,36 | Legacy `dagster.core.*` module paths (run_launcher/run_coordinator) | ℹ️ Info | Works on Dagster 1.13.x; deprecation risk on future upgrade (prior review WR-01). |
| dagster_defs/sensors.py | 27 | Imports from private `dagster._utils.schedules` | ℹ️ Info | Importable and working in-env; no stability guarantee across Dagster minors (prior review CR-02). Not a goal blocker. |

No debt markers (TBD/FIXME/XXX) found in phase files.

### Human Verification (RESOLVED via gap-closure plan 11-06)

1. **Nonce/timestamp thrash suppression (SCHED-02 acceptance clause)** — ✓ RESOLVED
   - Fix: Added gate-local `_suppress_volatile()` in `pipeline/crawl.py`, applied inside `_signature` AFTER `remove_boilerplate` (which is left byte-for-byte unchanged, so the clean stage and D-06 agreement are preserved). It neutralizes ISO-8601 datetimes, `HH:MM:SS` clock times, UUIDs, and ≥16-char hex nonces. The ISO pattern requires a time component, so human-meaningful bare dates (publication/effective dates) are preserved; over-suppression is bounded by `max_staleness_days`, which forces a full refresh each window.
   - Test: `test_nonce_noise_unchanged` now imports the gate's real `_signature` and asserts unconditionally that the two nonce-differing pages share a signature AND that `crawl_source` is not called (the self-fulfilling `if/else` is gone).
   - Evidence: commit c2bdd19; `tests/unit/test_recrawl_gate.py` 5 passed; independent check confirmed inline-timestamp & UUID suppression, bare-date preservation, and genuine-change recrawl; `pipeline/clean.py` unchanged.

2. **Live per-source concurrency serialization** — ✓ RESOLVED (demonstrated against the real dequeue decision)
   - Method: Rather than perturb the user's running dev stack (whose webserver/daemon still hold pre-phase-11 definitions — `recrawl_source_job` is not yet loaded there), the serialization is proven by driving Dagster's genuine `QueuedRunCoordinatorDaemon._get_runs_to_dequeue` against an ephemeral instance seeded with real QUEUED runs, using the exact `tag_concurrency_limits` parsed from the shipped `infra/dagster/dagster.yaml`.
   - Result: 3 queued `src_A` + 2 queued `src_B` → dequeue `{A:1, B:1}` (same-source serialized, cross-source concurrent); with 1 `src_A` in flight, both queued `src_A` are held while `src_B` dequeues.
   - Evidence: commit db16687; `tests/integration/test_recrawl_concurrency.py` 2 passed. The test also fails if `dagster.yaml`'s `klake/source` limit is ever weakened (config-drift guard).
   - Residual note (non-blocking): a two-real-crawl launch on a live daemon was intentionally not forced; it requires reloading the running code location (which would activate the RUNNING recrawl sensor). 0 sources currently carry a schedule, so that reload would be side-effect-free if the operator chooses to do it.

### Gaps Summary

No open gaps. SCHED-01 is fully verified end-to-end. SCHED-02 is now fully verified including its explicit "dynamic timestamps/nonces don't thrash" clause: the change gate suppresses inline body timestamps and nonces (not just boilerplate-region noise) by construction, meaningful dates survive, and the guard test proves it rather than assuming it. Both former human-verification items were closed by gap-closure plan 11-06 (commits c2bdd19, db16687).

---

_Verified: 2026-07-11T04:49:00Z (initial, gsd-verifier) → Re-verified: 2026-07-11T06:20:00Z (gap closure 11-06)_
_Verifier: Claude (gsd-verifier); gap closure: Claude (gsd-execute-phase --gaps-only)_
