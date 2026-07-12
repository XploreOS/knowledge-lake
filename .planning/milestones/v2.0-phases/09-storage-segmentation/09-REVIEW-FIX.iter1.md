---
phase: 09-storage-segmentation
fixed_at: 2026-07-10T00:00:00Z
review_path: .planning/phases/09-storage-segmentation/09-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 3
skipped: 1
status: partial
---

# Phase 9: Storage Segmentation — Code Review Fix Report

**Fixed at:** 2026-07-10
**Source review:** `.planning/phases/09-storage-segmentation/09-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope (Critical + Warning): 4
- Fixed: 3
- Skipped: 1

## Fixed Issues

### CR-01: Dagster export assets bypass STORE-03 domain segmentation

**Files modified:** `src/knowledge_lake/dagster_defs/assets.py`
**Commit:** `30dc8c0`
**Applied fix:** Added `ExportRagConfig` (with `domain: str = ""`) before `export_rag_corpus`, `ExportPretrainConfig` (with `domain: str = ""`) before `export_pretrain_corpus`, and added `domain: str = ""` to the existing `ExportFinetuneConfig`. All three export asset functions now accept the config parameter and pass `domain=config.domain or None` to the underlying pipeline functions. Empty string falls back to `_unclassified`, preserving existing operator behaviour. Dagster-triggered exports now honour STORE-03 domain segmentation identically to the CLI/API path.

---

### WR-03: `"_unclassified"` literal appears 5x with no shared constant

**Files modified:** `src/knowledge_lake/storage/s3.py`, `src/knowledge_lake/pipeline/export.py`
**Commit:** `9718a77`
**Applied fix:** Defined `_UNCLASSIFIED_DOMAIN = "_unclassified"` as a module-level constant in `s3.py` with a docstring explaining its role. Replaced both occurrences in `s3.py` (`put_raw` and `put_bronze`) and all three occurrences in `export.py` (`export_rag_corpus`, `export_pretrain_corpus`, `export_finetune_dataset`) with the constant. `export.py` imports the constant from `storage.s3`. A rename now requires a single edit; the storage namespace can no longer silently split between zones.

---

### WR-04: Redundant `get_domain_for_source` call when Source ORM already in scope

**Files modified:** `src/knowledge_lake/pipeline/ingest.py`
**Commit:** `9e4b928`
**Applied fix:** Replaced both `registry_repo.get_domain_for_source(session, source.id) or "_unclassified"` calls (in `ingest_url` at line 430 and `ingest_file` at line 539) with `(source.config or {}).get("domain") or _UNCLASSIFIED_DOMAIN`. The `Source` ORM object is already in scope at both sites, so `session.get(Source, source_id)` was being re-issued unnecessarily. The `or {}` None-guard handles sources created without a config dict (no `AttributeError` on `None.get()`). Also added `_UNCLASSIFIED_DOMAIN` to the import from `storage.s3`.

---

## Skipped Issues

### WR-02: Linked-doc ingest has no lineage to parent source (D-22)

**File:** `src/knowledge_lake/pipeline/crawl.py:499`
**Reason:** Code already satisfies the fix requirement. The review stated the fix was "either add a comment explicitly acknowledging the known limitation OR extend `ingest_url()`." A D-22 tech debt comment spanning lines 493-497 already exists in the codebase, explicitly documenting that `ingest_url()` does not accept `source_id` or `job_id`, that linked artifacts receive their own source rows, and that extending `ingest_url()` is the tracked remedy. The fix requirement is already met; no code change is needed. The deeper extension (actually adding `source_id`/`job_id` kwargs to `ingest_url()`) is a separate scope of work tracked as tech debt D-22 and is not part of this review-fix iteration.

---

_Fixed: 2026-07-10_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
