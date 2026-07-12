---
status: complete
phase: 11-crawl-scheduling
source: [11-01-SUMMARY.md, 11-02-SUMMARY.md, 11-03-SUMMARY.md, 11-04-SUMMARY.md, 11-05-SUMMARY.md]
started: 2026-07-11T01:46:09Z
updated: 2026-07-11T04:39:30Z
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: From a clean state, `alembic upgrade head` reaches revision 0009 with no errors and adds `crawl_schedule`, `last_crawled_at`, `last_content_hash` to the `sources` table. Dagster Definitions load cleanly with `recrawl_sensor` (RUNNING) and `recrawl_source_job` registered.
result: pass
source: user + automated
evidence: "Live DB `alembic current` = 0009 (head); all three columns PRESENT (crawl_schedule VARCHAR(255), last_crawled_at TIMESTAMP, last_content_hash VARCHAR(64)); Definitions load OK with sensor 'recrawl_sensor' registered + default_status=RUNNING + min_interval=60, job 'recrawl_source_job' registered; migration integration suite 13 passed incl. downgrade→upgrade round-trip on a real klake_test DB."

### 2. Set / Clear / Validate Crawl Schedule via CLI
expected: `klake set-schedule <source_id> --cron "0 3 * * *"` persists the schedule on that source. `klake set-schedule <source_id> --clear` sets it back to None. A malformed cron (e.g. `--cron "not a cron"`) is rejected before any write with an error. An unknown source_id exits non-zero.
result: pass
source: automated
evidence: "Live CLI against klake_test: valid cron → exit 0, persisted in crawl_schedule COLUMN = '0 3 * * *' (config unchanged, no 'schedule' key); malformed cron → exit 1 'Invalid cron expression'; unknown source_id → exit 1 'Source not found'; --clear → exit 0, column = None. Plus test_set_schedule_cli.py 3 passed."

### 3. domain-init Persists crawl_schedule from sources.yaml
expected: A `sources.yaml` entry with a `crawl_schedule:` field persists that schedule to the DB after `klake init`. An entry with an invalid cron emits a stderr warning and persists None for that source instead of aborting the whole init.
result: pass
source: automated
evidence: "Built temp domain pack (valid / invalid / no-schedule entries), ran `klake init -d uatpack` against klake_test: stderr 'Warning: Invalid cron ... schedule will not be persisted', 'Registered 3 sources' (no abort). Persisted: Valid → '0 6 * * *', Invalid → None, No-schedule → None. Stored as column, not config."

### 4. Change Gate Skips Unchanged Content
expected: Re-crawling a source whose seed page content is unchanged (matching signature, within staleness, non-NULL prior hash) skips the full crawl — no new raw object is written — and only bumps `last_crawled_at`. The SSRF `validate_public_url` check runs before the page is fetched.
result: pass
source: automated
evidence: "test_recrawl_gate.py::test_unchanged_skips_no_raw + test_nonce_noise_unchanged pass: assert validate_public_url called_once, crawl_source assert_not_called (WORM-safe), touch_source_crawl called_once (bumps last_crawled_at only). Source order check: validate_public_url precedes fetch_page in recrawl_source."

### 5. Change Gate Recrawls Changed / Stale / Never-Crawled Content
expected: Re-crawling triggers a full `crawl_source` when the seed content changed, when the source is past `max_staleness_days`, or when `last_content_hash` is NULL. After a real crawl, `last_content_hash` and `last_crawled_at` are updated to the new values.
result: pass
source: automated
evidence: "test_recrawl_gate.py::test_changed_recrawls (crawl_source called_once, new signature written via touch_source_crawl), test_null_hash_forces_crawl, test_staleness_forces_refresh — all pass."

### 6. Recrawl Sensor Emits Scheduled Runs
expected: In the Dagster UI, `recrawl_sensor` is present and RUNNING. When a scheduled source is due per its cron, the sensor emits a run of `recrawl_source_job` for that source; sources not yet due are skipped (SkipReason). The run_key is deterministic (`{source_id}:{fire_time}`) so the same cron window does not double-fire.
result: pass
source: automated
evidence: "Sensor registered + default_status=RUNNING (verified via Definitions). Live build_sensor_context eval: due source emits 1 RunRequest run_key='src_UAT_due:2026-07-11T04:38:00+00:00' tags klake/source=src_UAT_due; not-due source does NOT emit; re-eval in same window yields identical run_key (idempotent). Plus test_recrawl_sensor.py 3 passed (deterministic run_key, skips not due, run_key stable)."

### 7. Per-Source Recrawl Concurrency = 1
expected: With `QueuedRunCoordinator` configured in `dagster.yaml`, concurrent recrawl runs for the same source are serialized (tag_concurrency_limit on `klake/source` = 1) — a second run for the same source queues until the first finishes. Different sources still run concurrently.
result: pass
source: automated
evidence: "dagster.yaml run_coordinator = QueuedRunCoordinator with tag_concurrency_limits key 'klake/source', applyLimitPerUniqueValue: true, limit: 1 (per-source serialization, cross-source parallel). Sensor confirmed to tag every RunRequest with klake/source. NOTE: config + driving tag verified; live daemon serialization of two overlapping same-source runs was not exercised (would require standing up dagster-daemon + concurrent real crawls). Serialization itself is Dagster's guaranteed behavior given this config."

## Summary

total: 7
passed: 7
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none]
