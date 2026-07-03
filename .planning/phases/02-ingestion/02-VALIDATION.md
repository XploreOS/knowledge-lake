---
phase: 2
slug: ingestion
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-03
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Derived from 02-RESEARCH.md ## Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio (auto mode) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`asyncio_mode = "auto"`, `testpaths=["tests"]`) |
| **Quick run command** | `uv run pytest tests/unit -x -q` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~30–60 seconds (unit fast/no-network; integration uses local HTML fixtures + mocked httpx) |
| **Property testing** | `hypothesis` — NOT installed; add to dev group for URL-normalization laws (Wave 0) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit -x -q` (URL normalize, robots/rate-limit, crawler select, discovery — all fast, no network)
- **After every plan wave:** Run `uv run pytest -q` (adds integration; crawler adapters use local HTML fixtures / mocked httpx, not live network)
- **Before `/gsd-verify-work`:** Full suite green + a manual live smoke (`klake discover`, `klake crawl <small public site>`)
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

> Task IDs are TBD until plans exist; rows are keyed by requirement/decision and will be refined against PLAN.md task IDs by the executor / nyquist-auditor.

| Task ID | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| TBD | INGEST-01 | — | Register source via CLI+API; provenance recorded | integration | `uv run pytest tests/integration/test_source_register.py -x` | ❌ W0 | ⬜ pending |
| TBD | INGEST-02 | T-SSRF | Single-URL download records SHA256/MIME/URL/ts/license; private-IP rejected | integration | `uv run pytest tests/integration/test_ingest_url_dedup.py -x` | ❌ W0 | ⬜ pending |
| TBD | INGEST-03 | — | File upload records same provenance | unit+integration | `uv run pytest tests/integration/test_upload.py -x` | ❌ W0 | ⬜ pending |
| TBD | INGEST-04 | — | Crawl4AI yields raw+bronze artifacts with lineage | integration | `uv run pytest tests/integration/test_crawl4ai_adapter.py -x` | ❌ W0 | ⬜ pending |
| TBD | INGEST-05 | — | Scrapy subprocess crawl produces results, no ReactorNotRestartable on 2nd run | integration | `uv run pytest tests/integration/test_scrapy_subprocess.py -x` | ❌ W0 | ⬜ pending |
| TBD | INGEST-06 | — | Playwright renders SPA fixture → markdown | integration | `uv run pytest tests/integration/test_playwright_adapter.py -x` | ❌ W0 | ⬜ pending |
| TBD | INGEST-07 | T-SSRF | SearXNG discovery parses JSON → auto-registered sources; discovered URLs re-validated | unit+integration | `uv run pytest tests/unit/test_discovery.py -x` | ❌ W0 | ⬜ pending |
| TBD | INGEST-08 | — | Re-ingest identical URL/content → same IDs, no dup rows | unit+integration | `uv run pytest tests/integration/test_dedup_noop.py -x` | ❌ W0 | ⬜ pending |
| TBD | INGEST-09 | — | robots Disallow → robots_blocked; 3-tier delay resolves; retries fire | unit | `uv run pytest tests/unit/test_robots_ratelimit.py -x` | ❌ W0 | ⬜ pending |
| TBD | D-04 | — | Auto-selection picks correct adapter for HTML signals | unit (property/table) | `uv run pytest tests/unit/test_crawler_select.py -x` | ❌ W0 | ⬜ pending |
| TBD | D-06 | — | URL normalization idempotent + preserves query order | property (hypothesis) | `uv run pytest tests/unit/test_url_normalize.py -x` | ❌ W0 | ⬜ pending |
| TBD | D-03 | — | Interrupted crawl resumes without re-fetching completed pages | integration | `uv run pytest tests/integration/test_crawl_resume.py -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Observable Truths (what "true" looks like)
- **Dedup no-op:** two `ingest_url(same_url)` calls → identical `source_id` + `artifact_id`; `SELECT count(*) FROM sources WHERE normalized_url=?` == 1.
- **Resume:** kill a crawl after N pages → `crawl_states` has N `complete` + M `pending`; re-run fetches only the M pending (assert completed URLs not re-requested — spy on the fetch layer).
- **robots_blocked:** crawl a fixture whose robots.txt disallows `/private/` → that URL's `crawl_states.status == 'robots_blocked'`; no raw/bronze artifact written for it.
- **Rate-limit precedence:** table test across all tier permutations → resolver returns the expected delay.
- **Lineage (D-01):** bronze artifact's `parent_artifact_id` == its raw artifact's id; lineage walk goes bronze → raw → source.
- **SSRF:** discovery/crawl of a private-IP URL is rejected before any fetch (assert `ValueError` / skipped state).

---

## Wave 0 Requirements

- [ ] `tests/unit/test_url_normalize.py` — property tests (D-06). Requires `hypothesis` in dev deps.
- [ ] `tests/unit/test_robots_ratelimit.py` — 3-tier resolver + Protego robots parse (INGEST-09).
- [ ] `tests/unit/test_crawler_select.py` — auto-selection table tests (D-04).
- [ ] `tests/unit/test_discovery.py` — SearXNG JSON parsing with mocked httpx (INGEST-07).
- [ ] `tests/fixtures/` — add: static HTML page, SPA-shell HTML page, `robots.txt` with Disallow + Crawl-delay, sample SearXNG JSON response, small sitemap.xml.
- [ ] `tests/integration/conftest.py` — fixtures to spawn/mock Scrapy subprocess + Playwright (or mark `@pytest.mark.browser` and skip when chromium absent).
- [ ] Dev-dep install: `uv add --dev hypothesis` (if property tests adopted).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live discovery smoke | INGEST-07 | Requires running SearXNG Docker service + live meta-search | `klake discover "<query>"` → candidate sources appear in registry |
| Live crawl smoke | INGEST-04/05/06 | Requires live network + browser binaries | `klake crawl <small public site>` → raw+bronze artifacts + crawl_states populated |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
