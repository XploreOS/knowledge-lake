---
phase: 02-ingestion
plan: 01
subsystem: pipeline/ingest, registry, cli, api
tags: [ingestion, dedup, ssrf, url-normalization, cli, api]
dependency_graph:
  requires: [01-foundation]
  provides: [validate_public_url, normalize_url, register_source, normalized_url_column]
  affects: [02-02, 02-03, 02-04, 02-05, 02-06]
tech_stack:
  added: [hypothesis]
  patterns: [url-first-dedup, hash-second-dedup, redirect-hop-ssrf-validation]
key_files:
  created:
    - src/knowledge_lake/registry/alembic/versions/0002_source_normalized_url.py
    - tests/unit/test_url_normalize.py
    - tests/unit/test_fetch_redirect_ssrf.py
    - tests/integration/test_dedup_noop.py
    - tests/integration/test_source_register.py
    - tests/integration/test_ingest_url_dedup.py
    - tests/integration/test_upload.py
  modified:
    - src/knowledge_lake/pipeline/ingest.py
    - src/knowledge_lake/registry/models.py
    - src/knowledge_lake/registry/repo.py
    - src/knowledge_lake/cli/app.py
    - src/knowledge_lake/api/app.py
    - src/knowledge_lake/api/schemas.py
    - pyproject.toml
decisions:
  - "D-06 normalization uses stdlib urlsplit only (no w3lib/courlan that reorder params)"
  - "validate_public_url is the single shared SSRF guard for all future crawlers"
  - "_fetch_with_retry uses manual redirect following with per-hop SSRF revalidation"
  - "POST /uploads accepts file_path query param (hermetic testing) rather than multipart"
metrics:
  duration: "12m 3s"
  completed: "2026-07-03"
  tasks: 3
  tests_added: 28
  files_created: 7
  files_modified: 7
status: complete
---

# Phase 2 Plan 01: Source Registration, URL Ingest, and Upload with Dedup Summary

Shared ingestion foundation delivering URL normalization, SSRF hardening with per-redirect-hop validation, URL-first and hash-second dedup, source registration, and file upload -- all exposed via CLI and API with full provenance tracking.

## Artifacts Produced

### New Public Symbols (importable by downstream plans)

| Symbol | Location | Purpose |
|--------|----------|---------|
| `normalize_url(url: str) -> str` | `pipeline/ingest.py` | Conservative D-06 URL normalizer (stdlib only) |
| `validate_public_url(url: str) -> None` | `pipeline/ingest.py` | Shared SSRF guard -- every crawler plan imports this |
| `register_source(url, name, ...)` | `pipeline/ingest.py` | Dedup-aware source registration |
| `Source.normalized_url` | `registry/models.py` | Text column, nullable, indexed |
| `repo.get_source_by_normalized_url(session, norm_url)` | `registry/repo.py` | URL-first dedup lookup |
| `repo.get_raw_artifact_for_source(session, source_id)` | `registry/repo.py` | Artifact lookup by source |
| `SourceCreate`, `SourceOut`, `UploadOut` | `api/schemas.py` | API request/response schemas |

### CLI Commands

| Command | Description |
|---------|-------------|
| `klake add-source URL [--name] [--domain] [--license]` | Register a source with URL-first dedup |
| `klake upload FILE_PATH [--source] [--license]` | Upload a local file with hash-second dedup |

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `POST /sources` (body: SourceCreate) | Register source, returns SourceOut |
| `POST /uploads?file_path=...` | Upload file, returns UploadOut |

### Migration

| Revision | Description |
|----------|-------------|
| `0002_source_normalized_url` | Adds `sources.normalized_url` (Text, nullable) + `ix_sources_normalized_url` index |

## Task Completion

| Task | Name | Commit | Tests |
|------|------|--------|-------|
| 1 | URL normalizer + SSRF guard + redirect-hop validation | a3f1891 (RED), 67b0ef3 (GREEN) | 20 tests (16 normalize + 4 fetch/redirect) |
| 2 | normalized_url schema + dedup-aware ingest/register | 9d921ed (RED), 0ac51c2 (GREEN) | 2 integration tests |
| 3 | CLI add-source/upload + API /sources /uploads | 2becd46 | 6 integration tests |

## Key Implementation Details

### URL Normalization (D-06)

Uses only stdlib `urlsplit`/`urlunsplit`. Transformations: lowercase scheme+host, strip fragment, strip trailing slash (keep root "/"), preserve port, preserve query verbatim. Does NOT reorder or remove query params.

### SSRF Hardening (T-02-01, T-02-01b)

- `validate_public_url` renamed from `_validate_url_scheme` to be module-public
- `_fetch_with_retry` now uses `follow_redirects=False` and drives redirects manually
- Each 3xx Location is resolved via `urljoin`, then `validate_public_url` validates the target
- Redirect chain capped at 10 hops
- A public URL that 302-redirects to 169.254.169.254 or RFC-1918 is rejected before the private host is contacted

### Dedup Strategy (D-05, D-07)

- **URL-first (ingest_url):** normalize URL, check `get_source_by_normalized_url`. If found, return existing IDs without fetching. Skip is total -- no network I/O on repeat.
- **Hash-second (ingest_file):** compute SHA256, check `get_artifact_by_hash`. If found, return existing artifact. No duplicate source row created.
- Both return the same dict shape regardless of fresh vs dedup path (D-07 silent success).

## Deviations from Plan

None -- plan executed exactly as written.

## Decisions Made

1. **stdlib-only URL normalization:** No external library -- D-06 is achievable in 6 lines of `urllib.parse`. Libraries like w3lib sort query params which violates D-06.
2. **Manual redirect following:** httpx `follow_redirects=False` + loop with `validate_public_url` on each hop. This is the only way to close the redirect-hop SSRF gap.
3. **POST /uploads as query-param path (not multipart):** For hermetic testing, the endpoint accepts a server-side file path. Multipart upload is deferred to a future plan when a web UI exists.
4. **Backward compat alias:** `_validate_url_scheme = validate_public_url` preserves any internal callers.

## Self-Check: PASSED
