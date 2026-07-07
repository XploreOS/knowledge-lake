---
status: resolved
phase: 05-curation-datasets-export
source: [05-VERIFICATION.md]
started: 2026-07-06T00:00:00Z
updated: 2026-07-07T04:30:00Z
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
result: passed — `klake generate-dataset qa` returned `status: generated` via eval_model; `klake generate-dataset instruction` returned `status: generated` via strong_model. Both used real Bedrock through LiteLLM proxy. Cost-calc warning is cosmetic (task alias not in LiteLLM's price table; cost tracked correctly by proxy).

## Summary

total: 1
passed: 1
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
