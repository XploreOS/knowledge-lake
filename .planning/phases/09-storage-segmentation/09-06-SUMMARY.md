---
phase: "09-storage-segmentation"
plan: "06"
subsystem: "pipeline/export"
tags: [storage, gold-zone, domain-segmentation, s3-tags, export, STORE-02, STORE-03]
dependency_graph:
  requires: [09-03]
  provides: [gold-zone domain-scoped keys, export domain kwarg on all three functions, gold put_object tags]
  affects: [pipeline/export.py]
tech_stack:
  added: []
  patterns:
    - domain_seg = domain or '_unclassified' guard on gold key construction
    - 3-key tags dict (domain, format, artifact_type) on gold put_object — source_name omitted per D-11
    - row_domain local variable to prevent kwarg shadowing by inner loop variable
key_files:
  created: []
  modified:
    - src/knowledge_lake/pipeline/export.py
    - tests/unit/test_export.py
decisions:
  - "domain kwarg added to all three export functions as Optional[str]=None (additive, backward-compatible) — Pitfall 2 from RESEARCH.md resolved"
  - "Inner for-loop variable renamed to row_domain in export_rag_corpus to prevent shadowing of the function-level domain kwarg"
  - "Tags on gold exports use 3-key dict (domain, format, artifact_type) — source_name omitted per D-11 (multi-source exports)"
  - "All existing mock_put_object helpers updated to accept **kwargs — forward-compatible with put_object(tags=) signature added in Plan 03"
metrics:
  duration_minutes: 22
  completed_date: "2026-07-09"
  tasks_completed: 2
  files_changed: 2
status: complete
requirements: [STORE-02, STORE-03]
---

# Phase 09 Plan 06: Gold Zone Domain Segmentation Summary

**One-liner:** Added `domain: Optional[str] = None` kwarg to all three export functions with `domain or "_unclassified"` guard and 3-key S3 object tags, making gold-zone keys `gold/{domain}/rag_corpus/`, `gold/{domain}/pretrain/`, and `gold/{domain}/finetune/` (STORE-02 + STORE-03).

## What Was Built

Wave 2 — gold-zone domain segmentation. This plan closes out Phase 9 by extending `export.py` so all three gold export functions produce domain-scoped S3 keys and include S3 object tags on their writes.

### Changes Made

**`src/knowledge_lake/pipeline/export.py`** — three targeted changes per export function:

| Function | Signature change | Key before | Key after |
|---|---|---|---|
| `export_rag_corpus` | Added `domain: Optional[str] = None` | `gold/{prefix}/rag_corpus/{id}.parquet` | `gold/{prefix}/{domain_seg}/rag_corpus/{id}.parquet` |
| `export_pretrain_corpus` | Added `domain: Optional[str] = None` | `gold/{prefix}/pretrain/{id}.jsonl` | `gold/{prefix}/{domain_seg}/pretrain/{id}.jsonl` |
| `export_finetune_dataset` | Added `domain: Optional[str] = None` | `gold/{prefix}/finetune/{dataset.id}.jsonl` | `gold/{prefix}/{domain_seg}/finetune/{dataset.id}.jsonl` |

All three functions use `domain_seg = domain or "_unclassified"` guard (D-13) and pass `tags={"domain": domain_seg, "format": "...", "artifact_type": "..."}` to `storage.put_object()` (D-11).

**`tests/unit/test_export.py`** — xfail decorators removed from all four `TestGoldZone*` classes; six mock helper functions updated to accept `**kwargs`.

## Verification Results

```
pytest tests/unit/test_export.py -v → 13 passed
  TestGoldZoneDomainKey::test_rag_corpus_key_contains_domain_segment PASSED
  TestGoldZoneUnclassified::test_rag_corpus_none_domain_uses_unclassified PASSED
  TestGoldZonePretrain::test_pretrain_key_contains_domain_segment PASSED
  TestGoldZoneFinetune::test_finetune_key_contains_domain_segment PASSED

pytest tests/unit/ → 383 passed, 1 xfailed, 20 xpassed

grep -c "domain_seg = domain or" export.py → 3
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] export_rag_corpus: inner loop variable `domain` shadowed the new function kwarg**

- **Found during:** Task 1 — TestGoldZoneUnclassified failed because `export_rag_corpus(domain=None)` was calling `get_domain_for_source()` per-chunk in the for-loop and assigning the result to a local `domain` variable, overwriting the function parameter.
- **Issue:** After adding the `domain` kwarg, the first chunk's per-row domain lookup (`domain = registry_repo.get_domain_for_source(session, chunk.source_id)`) clobbered the caller-supplied `domain=None`, causing `domain_seg` to resolve to "healthcare" instead of "_unclassified".
- **Fix:** Renamed the inner loop variable from `domain` to `row_domain` everywhere inside the for-loop in `export_rag_corpus`. The `row` dict now uses `"domain": row_domain` for per-row data enrichment. The `domain_seg` guard uses the function-level `domain` kwarg correctly.
- **Files modified:** `src/knowledge_lake/pipeline/export.py`
- **Commit:** dab53f5

**2. [Rule 1 - Bug] Existing mock_put_object helpers raised TypeError with new tags= kwarg**

- **Found during:** Task 1 full unit suite run — `TestRagCorpus::test_rag_corpus_export_uses_allow_list_only` and others failed because `mock_put_object(key, data)` and `lambda key, data: None` side_effects did not accept `**kwargs`.
- **Issue:** Plan 03 added `tags=` kwarg to `StorageBackend.put_object()`; Plan 06 calls it on all three gold export functions. Six existing test mocks were not updated to accept the new kwarg.
- **Fix:** Updated all six mock definitions in `test_export.py` to accept `**kwargs` / `**kw`.
- **Files modified:** `tests/unit/test_export.py`
- **Commits:** dab53f5, 0ec0c5b

## Self-Check: PASSED

- [x] `src/knowledge_lake/pipeline/export.py` exists and contains `domain_seg = domain or` 3 times
- [x] `tests/unit/test_export.py` exists with xfail decorators removed from all 4 TestGoldZone* classes
- [x] Commit `dab53f5` exists (Task 1)
- [x] Commit `0ec0c5b` exists (Task 2)
- [x] All 4 TestGoldZone* tests PASSED
- [x] Full unit suite: 383 passed, 0 failures
