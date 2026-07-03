---
status: testing
phase: 01-foundation-end-to-end-spike
source: [01-VERIFICATION.md]
started: 2026-07-03T00:00:00Z
updated: 2026-07-03T00:00:00Z
---

## Current Test

number: 1
name: Docker Compose Stack Health (FOUND-01)
expected: |
  All 7 services (postgres, minio, qdrant, litellm, dagster-webserver, dagster-daemon, api) reach healthy state.
  curl localhost:8000/health returns {"status":"ok"}.
  LiteLLM is healthy without AWS/Bedrock credentials.
awaiting: user response

## Tests

### 1. Docker Compose Stack Health (SC-1 / FOUND-01)
expected: All 7 services healthy; `curl localhost:8000/health` returns 200; LiteLLM healthy with no AWS creds
result: [pending]

### 2. End-to-End Pipeline + Search (SC-2)
expected: `uv run pytest tests/integration/test_demo_spike.py -v` green, or `uv run klake demo` returns at least one hit with score + citation fields
result: [pending]

### 3. Lineage Query (SC-3 / FOUND-07)
expected: `uv run klake lineage <chunk_id>` and `curl localhost:8000/lineage/<chunk_id>` return full ancestry tree (chunk → parsed → raw) with all 6 FOUND-06 fields per node
result: [pending]

### 4. Raw Zone Immutability (SC-4 / FOUND-04)
expected: `uv run pytest tests/integration/test_raw_immutable.py -v` passes all 12 tests; re-ingest no-op confirmed; overwrite guard triggers
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
