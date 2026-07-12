---
phase: 11
slug: crawl-scheduling
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on (high) severity
threats_open: 0
asvs_level: 1
created: 2026-07-12
---

# Phase 11 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Crawl scheduling — cron-driven Dagster sensor, change-detection recrawl gate, SSRF-guarded seed probe, tick-storm dedup.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Operator/YAML/CLI → registry | cron strings (user input) persisted to `sources.crawl_schedule` | user-supplied cron |
| Dagster daemon → external source host | seed-probe GET + crawl fetches cross to the untrusted internet (SSRF surface) | untrusted outbound HTTP |
| Sensor → Dagster run storage | uncontrolled RunRequest emission could flood the run queue (tick storm) | run requests |
| Sensor → registry (read-only) | sensor reads scheduled sources; it must not write | read-only query |
| Run coordinator → executor | per-source serialization prevents a slow crawl overlapping its own next tick | run tags |
| Crawl op → registry (touch_source_crawl) | watermark writes cross the process boundary from the op (never the sensor) | watermark write |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-11-SSRF | Information Disclosure | recrawl_source seed probe | high | mitigate | `validate_public_url(url)` runs before `adapter.fetch_page`; crawl_source re-validates every URL (defense in depth) — `pipeline/crawl.py:176` | closed |
| T-11-THRASH | Denial of Service (cost) | change-detection gate | high | mitigate | normalized-text SHA256 signature skips unchanged pages before `put_raw`; `max_staleness_days` caps forced refresh — `pipeline/crawl.py:183` | closed |
| T-11-TICKSTORM | Denial of Service | recrawl_sensor + run coordinator | high | mitigate | deterministic `run_key = f"{sid}:{fire.isoformat()}"` (Dagster dedups) + `minimum_interval_seconds=60` + `klake/source` tag for per-source QueuedRunCoordinator limit=1 — `dagster_defs/sensors.py:116,94,120` | closed |
| T-11-CRON | Denial of Service (V5 input) | set-schedule + domain-init | medium | mitigate | `is_valid_cron_string` rejects malformed cron at write time (vendored engine, no ReDoS regex) — `pipeline/domains.py:86`, `cli/app.py:1073` | closed |
| T-11-WRITE | Tampering / Integrity | recrawl_sensor | medium | mitigate | sensor side-effect-free apart from `context.update_cursor`; all DB writes (touch_source_crawl) happen in the op — `dagster_defs/sensors.py:100,125` | closed |
| T-11-SC | Tampering (supply chain) | dependency set | high | mitigate | no new package added; cron helpers from `dagster._utils.schedules` (vendored), never the standalone `croniter` — `dagster_defs/sensors.py:20` | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above high count toward threats_open*

*Note: this phase-level register is authored across plans 11-01…11-05; each threat is consolidated to its highest-severity representative. (Plan 11-06 is a docs/wiring plan with no threat model.)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|

No accepted risks — every threat in this phase carries a verified `mitigate` disposition.

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-12 | 6 | 6 | 0 | gsd-secure-phase |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-12
