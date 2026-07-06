---
status: testing
phase: 05-curation-datasets-export
source: [05-VERIFICATION.md]
started: 2026-07-06T00:00:00Z
updated: 2026-07-06T00:00:00Z
---

## Current Test

number: 1
name: Live Bedrock smoke test for eval_model and strong_model aliases
expected: |
  `klake generate-dataset qa <chunk_id> --dataset-name smoke-test` prints `status: generated`;
  re-run prints `status: cached`.
  `klake generate-dataset instruction <enriched_document_artifact_id> --dataset-name smoke-test`
  prints `status: generated`.
awaiting: user response

## Tests

### 1. Live Bedrock smoke test for eval_model and strong_model aliases
expected: |
  Run with a real AWS Bedrock credential and a running docker-compose stack
  (`docker compose up -d litellm postgres qdrant minio`):

  1. `klake generate-dataset qa <chunk_id> --dataset-name smoke-test`
     → output contains `status: generated`
  2. Re-run same command → output contains `status: cached`
  3. `klake generate-dataset instruction <enriched_document_artifact_id> --dataset-name smoke-test`
     → output contains `status: generated`
result: [pending]

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
