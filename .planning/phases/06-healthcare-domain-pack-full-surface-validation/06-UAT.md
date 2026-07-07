---
status: testing
phase: 06-healthcare-domain-pack-full-surface-validation
source: [06-VERIFICATION.md]
started: 2026-07-07T06:00:00Z
updated: 2026-07-07T06:00:00Z
---

## Current Test

number: 1
name: 5-Source E2E Healthcare Pipeline (DOMAIN-04)
expected: |
  pytest tests/e2e/test_e2e_healthcare.py -v -m integration reports 4 passed (all assertions green: materialize success, lineage ≥3 nodes, search returns result, Parquet exists in MinIO)
awaiting: user response

## Tests

### 1. 5-Source E2E Healthcare Pipeline (DOMAIN-04)

expected: |
  Start docker-compose stack: `docker compose up -d`
  Then run: `uv run pytest tests/e2e/test_e2e_healthcare.py -v -m integration`
  Expected: 4 passed (materialize success, lineage ≥3 nodes per source, klake search returns ≥1 result, Parquet file exists in MinIO gold zone)
result: [pending]

### 2. Dagster UI shows healthcare_e2e_job (IFACE-03)

expected: |
  With docker-compose running, open http://localhost:3000
  Navigate to Jobs tab
  Verify "healthcare_e2e_job" appears in the job list
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
