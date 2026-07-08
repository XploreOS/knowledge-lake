---
phase: 01-foundation-end-to-end-spike
plan: "03"
subsystem: storage
tags: [storage, s3, minio, boto3, content-addressed, immutable, worm, tdd, found-03, found-04]
status: complete

dependency_graph:
  requires:
    - plan 01 (pydantic-settings config, pytest infra, compose stack)
    - plan 02 (registry models + repo, get_artifact_by_hash no-op seam)
  provides:
    - knowledge_lake.storage.s3 (StorageBackend — single boto3 client)
    - knowledge_lake.storage.bootstrap (ensure_buckets — WORM bucket setup)
    - Four-layer immutable raw zone enforcement (FOUND-04)
  affects:
    - Plan 04 (pipeline): put_raw is the ingest storage call
    - Plan 05 (lineage): every artifact's storage_uri points at a raw/ key
    - All plans: storage.StorageBackend is the only object-store interface

tech_stack:
  added:
    - boto3 1.43.39 (already in deps; now exercised in production code)
    - botocore BotoConfig(signature_version='s3v4') for MinIO compatibility
  patterns:
    - Single boto3 S3 client per StorageBackend; endpoint_url toggle: MinIO dev / AWS prod
    - Content-addressed raw keys raw/{source_id}/{sha256}.{ext}
    - Four-layer WORM: registry no-op + content-addressed key + head_object guard + bucket-level (versioning + object lock + delete-deny policy)
    - ensure_buckets is idempotent; called at startup or provisioning time
    - SQLite in-memory for registry integration in unit-level immutability tests

key_files:
  created:
    - src/knowledge_lake/storage/__init__.py (storage package)
    - src/knowledge_lake/storage/s3.py (StorageBackend — put_object, get_object, exists, object_uri, put_raw)
    - src/knowledge_lake/storage/bootstrap.py (ensure_buckets — WORM bucket bootstrap)
    - tests/integration/test_storage.py (17 tests: round-trip, exists, AWS-mode, bootstrap)
    - tests/integration/test_raw_immutable.py (12 tests: first-store, no-op, overwrite guard, no wildcard)

decisions:
  - Single boto3 client per StorageBackend instance — no second client, no raw HTTP (FOUND-03)
  - MinIO object lock requires versioning at creation — ensure_buckets creates bucket with ObjectLockEnabledForBucket=True
  - S3 If-None-Match:'*' NOT used — MinIO does not support this wildcard; enforcement is app+bucket-policy layer only (FOUND-04, RESEARCH Pitfall A)
  - Registry no-op is the first enforcement layer — SHA256 lookup before any S3 write
  - head_object guard is defense-in-depth only (content-addressing makes structural overwrite impossible)
  - Delete-deny bucket policy uses Principal:'*' (applies to all clients including the app role)
  - SQLite in-memory used for registry fixtures in test_raw_immutable.py to avoid PostgreSQL dependency in fast integration tests

metrics:
  duration: "~12 minutes"
  completed: "2026-07-03"
  tasks_completed: 2
  files_created: 5
  tests_passing: 29
---

# Phase 01 Plan 03: S3 Storage Abstraction + Immutable Raw Zone Summary

One-liner: Single boto3-based StorageBackend for MinIO (dev) and AWS S3 (prod) via endpoint_url toggle, with SHA256 content-addressed raw keys, a four-layer WORM enforcement (registry no-op + content-addressed key + head_object guard + versioning/object-lock/delete-deny bucket policy), and 29 integration tests proving round-trip, no-op, and overwrite refusal.

## What Was Built

### Task 1 — StorageBackend + Raw Bucket WORM Bootstrap (FOUND-03, TDD)

**RED phase:** Wrote 17 failing tests across test_storage.py covering single-client assertion, put/get round-trips, exists() semantics, object_uri format, AWS-mode client construction (endpoint_url=None → amazonaws.com endpoint), and raw bucket bootstrap verification (versioning, object lock, delete-deny policy).

**GREEN phase:**
- `storage/s3.py`: `StorageBackend` wraps a single boto3 S3 client constructed from `StorageSettings`. `endpoint_url` toggle: set for MinIO, `None` for AWS S3. Methods: `put_object`, `get_object`, `exists` (via `head_object`), `object_uri` (returns `s3://bucket/key`). No second client, no raw HTTP, no local filesystem.
- `storage/bootstrap.py`: `ensure_buckets(settings)` creates the bucket with `ObjectLockEnabledForBucket=True`, ensures versioning is enabled, and attaches a delete-deny bucket policy (Deny `s3:DeleteObject` + `s3:DeleteObjectVersion` for Principal:`*`). Idempotent — safe to call multiple times.
- All 17 tests green.

### Task 2 — Content-Addressed put_raw with Registry No-Op + Overwrite Guard (FOUND-04, TDD)

**Implementation** (in `s3.py`, `put_raw` method — Four-layer Pattern 1 enforcement):

1. **SHA256 hash:** `hashlib.sha256(data).hexdigest()` — stdlib, never hand-rolled, never xxhash
2. **Registry no-op:** `repo.get_artifact_by_hash(session, hash, "raw_document")` — if artifact exists, return immediately; no S3 write, no new node (FOUND-04 verbatim)
3. **Content-addressed key:** `raw/{source_id}/{sha256}.{ext}` — identity == content
4. **head_object guard:** `if self.exists(key): raise RuntimeError(...)` — refuse overwrite
5. **S3 write + registry node:** `put_object` then `create_raw_artifact`

**No `If-None-Match:'*'`** used anywhere in the codebase.

**RED phase:** Wrote 12 failing tests across test_raw_immutable.py covering first-store (creates object + node), registry no-op (second put returns same artifact, no new node, no new S3 version), overwrite guard (forced key collision raises RuntimeError), and no-wildcard check (source code inspection + call capture).

**GREEN phase:** Tests pass against the already-implemented `put_raw` in `s3.py`. All 12 tests green.

## Acceptance Criteria Verification

| Criterion | Status |
|-----------|--------|
| FOUND-03: single boto3 client; endpoint_url selects MinIO vs AWS | PASS — single client in `__init__`, AWS test verifies amazonaws.com endpoint |
| FOUND-03: put/get round-trips identical bytes on MinIO | PASS — 3 round-trip tests (bytes, binary, UTF-8 JSON) |
| FOUND-03: no second client, no raw HTTP, no local FS store | PASS — grep confirms single boto3.client call in s3.py |
| FOUND-04: raw key is raw/{source_id}/{sha256}.{ext} | PASS — test_put_raw_key_is_content_addressed |
| FOUND-04: re-ingesting identical content → no new object, no new node | PASS — 3 no-op tests (same ID, same count, no put_object call) |
| FOUND-04: head_object guard refuses overwrite of existing raw key | PASS — test_forced_key_collision_raises_runtime_error |
| FOUND-04: no S3 If-None-Match:'*' anywhere | PASS — source inspection + call capture tests |
| Raw bucket: versioning enabled | PASS — test_raw_bucket_has_versioning_enabled |
| Raw bucket: object lock configured (Enabled) | PASS — test_raw_bucket_has_object_lock_configured |
| Raw bucket: delete-deny bucket policy applied | PASS — test_raw_bucket_has_delete_deny_policy |
| ensure_buckets is idempotent | PASS — test_ensure_buckets_is_idempotent |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test assertion: boto3 meta.endpoint_url is not None for AWS mode**
- **Found during:** Task 1 TDD GREEN (test_aws_mode_client_has_no_endpoint_url failed)
- **Issue:** The RED test asserted `endpoint is None` for AWS mode, but boto3 resolves the regional endpoint URL (`https://s3.us-west-2.amazonaws.com`) at client creation time, so `meta.endpoint_url` is non-None.
- **Fix:** Changed assertion to verify the endpoint contains `amazonaws.com` and does NOT contain `localhost`/`127.0.0.1`. This accurately distinguishes AWS mode from MinIO mode.
- **Files modified:** `tests/integration/test_storage.py`
- **Commit:** 29f368c

**2. [Rule 1 - Bug] Test isolation: exists() test failed due to key persisting from prior run**
- **Found during:** Task 1 TDD GREEN (test_exists_via_head_object assertion failed)
- **Issue:** The test used a fixed key `test/exists/head_check.bin` which already existed from a prior test run against MinIO (keys persist between runs).
- **Fix:** Changed to `uuid.uuid4().hex`-suffixed keys for existence tests to ensure uniqueness. Applied the same fix to `test_exists_returns_false_for_absent_key`.
- **Files modified:** `tests/integration/test_storage.py`
- **Commit:** 29f368c

**3. [Rule 1 - Bug] Test regex case mismatch for overwrite guard message**
- **Found during:** Task 2 (test_forced_key_collision_raises_runtime_error)
- **Issue:** The test pattern `"raw key already exists"` (lowercase 'r') did not match the implementation's `"Raw key already exists"` (uppercase 'R').
- **Fix:** Changed match pattern to `"[Rr]aw key already exists"` (case-insensitive).
- **Files modified:** `tests/integration/test_raw_immutable.py`
- **Commit:** 2c165cb

## Known Stubs

None. `StorageBackend` and `ensure_buckets` are fully functional against both MinIO and AWS S3. `put_raw` fully implements all four enforcement layers. No hardcoded empty values or placeholder data.

## Threat Flags

No new security-relevant surface beyond what was planned:
- T-01-08 (raw-zone overwrite/delete) mitigated: four-layer enforcement complete
- T-01-09 (dev/prod immutability divergence) mitigated: no If-None-Match:'*' anywhere; enforcement is backend-portable
- T-01-10 (content hashing) mitigated: hashlib.sha256 (stdlib), never xxhash for raw identity

## Self-Check

PASSED
