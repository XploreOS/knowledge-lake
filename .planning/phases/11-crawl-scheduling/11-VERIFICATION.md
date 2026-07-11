---
phase: 11-crawl-scheduling
verified: 2026-07-11T04:49:00Z
status: human_needed
score: 8/9 must-haves verified
behavior_unverified: 1
overrides_applied: 0
behavior_unverified_items:
  - truth: "Dynamic timestamps/nonces don't thrash the raw zone (SCHED-02 acceptance clause)."
    test: "Fetch a page whose only change between crawls is an inline body timestamp/nonce line (e.g. 'Page generated at <ISO>'), set last_content_hash to the prior signature, and run recrawl_source; observe whether crawl_source/put_raw is skipped."
    expected: "Unchanged-except-nonce pages should skip re-ingest. In practice remove_boilerplate strips nonces only when they live in boilerplate/footer/nav regions; an inline body timestamp is NOT stripped, so such a page re-crawls every tick."
    why_human: "remove_boilerplate does not normalize away inline body timestamps (independently confirmed live), and the nonce-noise unit test is self-fulfilling (asserts skip only IF sig_a==sig_b, else asserts crawl — it passes either way). A human must decide whether normalizer-dependent nonce suppression is acceptable for v2.0 or needs a stronger normalizer/test."
human_verification:
  - test: "Nonce/timestamp suppression (see behavior_unverified_items[0])."
    expected: "Boilerplate-region nonces skip; inline-body timestamps currently do not."
    why_human: "Requires judgment on acceptable normalizer scope vs a stronger test; touches SCHED-02's explicit anti-thrash acceptance language."
  - test: "Live per-source concurrency serialization under QueuedRunCoordinator. Stand up dagster-daemon, enqueue two recrawl_source_job runs for the same source_id, and confirm the second queues until the first completes while a different source runs concurrently."
    expected: "Same-source runs serialize (tag_concurrency_limit klake/source=1); different sources run in parallel."
    why_human: "Config (dagster.yaml) and the driving klake/source run tag are verified, but live daemon serialization was not exercised (needs a running dagster-daemon + two overlapping real crawls). This is Dagster's guaranteed behavior given the verified config, but not observed end-to-end here."
---

# Phase 11: Crawl Scheduling Verification Report

**Phase Goal:** The lake re-crawls sources on schedule and only re-ingests genuinely changed content, so it stays fresh without thrashing the immutable raw zone.
**Verified:** 2026-07-11T04:49:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

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
| 7 | Dynamic timestamps/nonces don't thrash the raw zone | ⚠️ PRESENT_BEHAVIOR_UNVERIFIED | Normalized gate handles boilerplate-region noise, but live check shows `remove_boilerplate` does NOT strip an inline body timestamp; the nonce unit test is self-fulfilling (skip asserted only if sigs already equal). See Human Verification. |
| 8 | Additive forward-only 0009 migration: 3 nullable columns | ✓ VERIFIED | Live klake_test: `crawl_schedule VARCHAR(255)`, `last_crawled_at TIMESTAMP`, `last_content_hash VARCHAR(64)` all nullable; alembic head = 0009, down_revision 0008; no server_default; downgrade round-trip green (13 passed). |
| 9 | Schedule set via sources.yaml + CLI, cron-validated, stored as a COLUMN; per-source concurrency=1 config | ✓ VERIFIED | Live CLI: valid cron persists to `crawl_schedule` column (config stays NULL), malformed cron rejected pre-write (exit 1), `--clear` → None, unknown source → exit 1. dagster.yaml = QueuedRunCoordinator, tag_concurrency_limits klake/source applyLimitPerUniqueValue=true limit=1. |

**Score:** 8/9 truths verified (1 present, behavior-unverified)

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
| RunRequest tags | QueuedRunCoordinator | `{"klake/source": src.id}` → tag_concurrency_limits | ✓ WIRED (tag present live; live daemon serialization not exercised — see Human Verification) |

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
| tests/unit/test_recrawl_gate.py | 173-229 | Self-fulfilling conditional assertion in `test_nonce_noise_unchanged` | ⚠️ Warning | Test passes whether or not the nonce is normalized away → provides false confidence for SCHED-02's anti-thrash clause. |
| tests/unit/test_set_schedule_cli.py | 63-101 | "Unit" tests patch `set_source_schedule` but not `get_session` | ℹ️ Info | Tests implicitly require a live Postgres (pass here because docker is up; would fail DB-less per prior review CR-01). Functional behavior independently live-verified. |
| infra/dagster/dagster.yaml | 29,36 | Legacy `dagster.core.*` module paths (run_launcher/run_coordinator) | ℹ️ Info | Works on Dagster 1.13.x; deprecation risk on future upgrade (prior review WR-01). |
| dagster_defs/sensors.py | 27 | Imports from private `dagster._utils.schedules` | ℹ️ Info | Importable and working in-env; no stability guarantee across Dagster minors (prior review CR-02). Not a goal blocker. |

No debt markers (TBD/FIXME/XXX) found in phase files.

### Human Verification Required

1. **Nonce/timestamp thrash suppression (SCHED-02 acceptance nuance)**
   - Test: Crawl a page twice where only an inline body timestamp/nonce line changes; set `last_content_hash` to the prior signature; run `recrawl_source`.
   - Expected: Should skip re-ingest. Live check confirms `remove_boilerplate` strips nonces only in boilerplate/footer/nav regions, NOT inline body timestamps — such a page re-crawls every tick.
   - Why human: The unit test is self-fulfilling; a human must decide if normalizer-dependent suppression is acceptable for v2.0 or warrants a stronger normalizer/test. The requirement's PRIMARY mandate (normalized-text, not raw-bytes) is met.

2. **Live per-source concurrency serialization**
   - Test: Stand up dagster-daemon; enqueue two `recrawl_source_job` runs for the same `source_id`; confirm the second queues until the first completes; confirm a different source runs concurrently.
   - Expected: Same-source serialized (klake/source limit 1); cross-source parallel.
   - Why human: Config + driving run tag verified; live daemon serialization not exercised here (Dagster's guaranteed behavior given the verified config).

### Gaps Summary

No blocking gaps. All enabling schema, repo plumbing, the change gate, the sensor, the run coordinator, and both operator schedule-setting paths exist, are wired, and were exercised live (DB columns, alembic head, sensor eval, CLI persistence, test suites). SCHED-01 is fully verified end-to-end. SCHED-02's core (normalized-signature change gate, WORM-safe skip, SSRF-first, staleness override) is verified; its explicit "dynamic timestamps/nonces don't thrash" clause is only as strong as `remove_boilerplate`'s stripping — which does not cover inline body timestamps — and its unit test is self-fulfilling. This is surfaced for human judgment rather than treated as a blocker, since the requirement's primary mandate (normalized text, not raw bytes) is satisfied and real-world nonces typically reside in boilerplate regions the normalizer does strip.

---

_Verified: 2026-07-11T04:49:00Z_
_Verifier: Claude (gsd-verifier)_
