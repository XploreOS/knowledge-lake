---
phase: 02-ingestion
plan: 06
subsystem: discovery
tags: [discovery, searxng, ssrf, dedup, protocol]
dependency_graph:
  requires: [02-01]
  provides: [discovery-pipeline, searxng-compose, discovery-protocol]
  affects: [plugins/protocols, plugins/resolver, config/settings, cli/app, api/app, docker-compose]
tech_stack:
  added: [searxng/searxng (Docker)]
  patterns: [DiscoveryPlugin protocol, get_discovery resolver injection, SSRF-validate-before-register]
key_files:
  created:
    - src/knowledge_lake/plugins/builtin/searxng_discovery.py
    - src/knowledge_lake/pipeline/discover.py
    - infra/searxng/settings.yml
    - tests/unit/test_discovery.py
    - tests/integration/test_discovery_register.py
  modified:
    - src/knowledge_lake/plugins/protocols.py
    - src/knowledge_lake/plugins/resolver.py
    - src/knowledge_lake/config/settings.py
    - src/knowledge_lake/pipeline/ingest.py
    - src/knowledge_lake/registry/repo.py
    - src/knowledge_lake/cli/app.py
    - src/knowledge_lake/api/app.py
    - src/knowledge_lake/api/schemas.py
    - docker-compose.yml
    - pyproject.toml
decisions:
  - "SearXNG plugin uses httpx.Client (sync) with params dict — not string-formatted into URL (T-02-23)"
  - "register_source gets source_type_override param rather than a separate registration function (DRY)"
  - "SearXNG Docker service listens on internal port 8080, mapped to host 8888 (avoids conflict with API on 8000)"
metrics:
  duration: "~8 minutes"
  completed: "2026-07-04T03:20:00Z"
  tasks_completed: 3
  tasks_total: 3
  tests_added: 21
  files_created: 5
  files_modified: 10
status: complete
---

# Phase 02 Plan 06: Source Discovery (SearXNG) Summary

Swappable DiscoveryPlugin protocol with SearXNG as the first implementation — JSON API search, SSRF-validated and URL-deduped auto-registration of discovered sources, plus the SearXNG Docker service wired into the compose stack with JSON output format enabled.

## One-liner

SearXNG-backed source discovery with DiscoveryPlugin protocol, SSRF-validated auto-registration, and URL-first dedup preventing duplicate source rows.

## Artifacts Produced

| Artifact | Purpose |
|----------|---------|
| `DiscoveryPlugin` protocol + `DiscoveryResult` dataclass | Swappable discovery contract (D-10) |
| `SearXNGDiscovery` plugin | First implementation using SearXNG JSON API |
| `get_discovery(settings)` resolver | Injects searxng_url from settings (CR-03) |
| `discover_sources(query, limit, settings)` | Orchestrates search + validate + register pipeline |
| `list_sources_by_type(session, source_type)` | ORM query for listing discovered sources |
| `klake discover <query> --limit N` | CLI entry point |
| `POST /discover` | API entry point with DiscoverOut schema |
| `infra/searxng/settings.yml` | SearXNG config with formats: [html, json] |
| `searxng` Docker compose service | Self-hosted meta-search on port 8888 |
| `knowledge_lake.discovery` entry-point group | Plugin registration in pyproject.toml |

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | DiscoveryPlugin protocol + resolver + settings + SearXNG plugin | 13b4e73 | protocols.py, resolver.py, settings.py, searxng_discovery.py |
| 2 | Discovery pipeline + SearXNG compose service | d3aa322 | pipeline/discover.py, repo.py, docker-compose.yml, settings.yml |
| 3 | CLI + API + integration tests | 7c8ec9e | cli/app.py, api/app.py, schemas.py, test_discovery_register.py |

## Security Mitigations

| Threat ID | Mitigation | Status |
|-----------|------------|--------|
| T-02-22 | validate_public_url() called on every result URL before auto-register | Implemented |
| T-02-22b | Discovered URLs inherit redirect-hop validation from _fetch_with_retry on subsequent crawl | By design (crawl phase) |
| T-02-23 | Query passed as httpx params value, never string-formatted into URL | Implemented + tested |
| T-02-24 | formats: [html, json] in settings.yml + 403 raises RuntimeError | Implemented + tested |
| T-02-25 | limit bounded [1, 100] via pydantic Field; URL-first dedup prevents duplicates | Implemented |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added source_type_override to register_source**
- **Found during:** Task 2
- **Issue:** register_source hardcoded source_type="web" — discovery needs "discovered"
- **Fix:** Added optional source_type_override parameter (DRY, backward-compatible)
- **Files modified:** src/knowledge_lake/pipeline/ingest.py
- **Commit:** d3aa322

## Verification Results

- `uv run pytest tests/unit/test_discovery.py tests/integration/test_discovery_register.py -q` — 21 tests pass
- `uv run pytest tests/unit/test_settings.py -q` — 17 tests pass (no regression)
- `uv run klake discover --help` exits 0 with --limit option shown
- `GET /openapi.json` contains /discover (POST)
- `infra/searxng/settings.yml` has search.formats containing html and json

## Known Stubs

None — all data paths are wired and functional.

## Self-Check: PASSED
