---
status: testing
phase: 06-healthcare-domain-pack-full-surface-validation
source: [06-VERIFICATION.md]
started: 2026-07-07T06:00:00Z
updated: 2026-07-07T06:00:00Z
---

## Current Test

[testing complete]

## Tests

### 1. 5-Source E2E Healthcare Pipeline (DOMAIN-04)

expected: |
  Start docker-compose stack: `docker compose up -d`
  Then run: `uv run pytest tests/e2e/test_e2e_healthcare.py -v -m integration`
  Expected: 4 passed (materialize success, lineage ≥3 nodes per source, klake search returns ≥1 result, Parquet file exists in MinIO gold zone)
result: issue
reported: "3 passed, 1 failed — test_e2e_parquet_exported FAILED with TrainEvalContaminationError: train/eval contamination: 1 undocumented overlap(s) — ['doc_019f3ad6-f7a9-7700-977e-365adec2f291']. export_rag_corpus() raises because the E2E test data triggers the Phase 5 contamination hard-gate."
severity: major

### 2. Dagster UI shows healthcare_e2e_job (IFACE-03)

expected: |
  With docker-compose running, open http://localhost:3000
  Navigate to Jobs tab
  Verify "healthcare_e2e_job" appears in the job list
result: issue
reported: "Dagster UI shows code location knowledge_lake.dagster_defs.definitions but with zero assets and zero jobs — healthcare_e2e_job is not visible, and no assets appear either."
severity: major

## Summary

total: 2
passed: 0
issues: 2
pending: 0
skipped: 0
blocked: 0

## Gaps

- truth: "5-source E2E Parquet export completes without error (test_e2e_parquet_exported passes)"
  status: failed
  reason: "User reported: TrainEvalContaminationError raised by _enforce_no_contamination() in export_rag_corpus() — artifact doc_019f3ad6-f7a9-7700-977e-365adec2f291 is flagged as an undocumented train/eval overlap. The E2E test calls export_rag_corpus() directly with a fresh Settings object but the contamination check finds overlap with the Phase 5 dataset. The test needs to either mock/bypass the contamination check for E2E purposes, pass the artifact ID in contamination_override_artifact_ids, or the test fixture must avoid creating documents that appear in both train and eval splits."
  severity: major
  test: 1
  artifacts: [src/knowledge_lake/pipeline/export.py, tests/e2e/test_e2e_healthcare.py]
  missing: []

- truth: "Dagster UI at http://localhost:3000 shows healthcare_e2e_job under Jobs and all pipeline assets under Assets"
  status: failed
  reason: "User reported: Dagster UI shows code location knowledge_lake.dagster_defs.definitions but zero assets and zero jobs. The definitions module loaded by the running dagster-webserver does not reflect the updated definitions.py that includes healthcare_e2e_job and all assets — likely a stale deployment or import error in the running container that prevents definitions from loading."
  severity: major
  test: 2
  artifacts: [src/knowledge_lake/dagster_defs/definitions.py]
  missing: []
