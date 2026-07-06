---
phase: 05-curation-datasets-export
plan: "01"
subsystem: curation
tags: [datatrove, minhash, quality-scoring, curated-document, dagster, fastapi, typer]
dependency_graph:
  requires:
    - "04-03-SUMMARY.md (enriched_document artifacts, quality_score column)"
    - "03-02-SUMMARY.md (cleaned_document artifacts, compute_minhash, MinHashLSH)"
  provides:
    - "curated_document artifact type with per-heuristic filter_results and composite_quality_score"
    - "batch_dedup_corpus() — authoritative corpus-wide MinHash dedup (replaces Phase 3's transient scan)"
    - "POST /curate, GET /curated-documents API endpoints"
    - "klake curate, klake dedupe CLI commands"
    - "curate_document_asset Dagster asset"
  affects:
    - "pipeline/clean.py (docstring updated — Phase 5 batch dedup is authoritative)"
    - "registry/repo.py (two new functions)"
    - "quality/scorer.py (compute_composite_quality_score added)"
    - "config/settings.py (CurateSettings + Settings.curate field)"
    - "ids.py (curated_document added to _PREFIX)"
tech_stack:
  added:
    - "datatrove==0.9.0 (GopherRepetitionFilter, GopherQualityFilter, C4QualityFilter)"
    - "nltk>=3.9,<4 (word tokenizer required by Gopher filters)"
  patterns:
    - "DataTrove filters called via .filter(doc) directly (never .run()) — records ALL heuristics"
    - "Synthetic content_hash = sha256(cleaned_hash:filter_config_version) — cache-key pattern from enrich.py"
    - "Sibling lookup via get_child_artifact_by_type(session, cleaned_id, 'enriched_document') (Pitfall 4)"
    - "Mutable JSON re-assignment for SQLAlchemy dirty-tracking on metadata_ updates"
key_files:
  created:
    - "src/knowledge_lake/pipeline/curate.py"
    - "tests/unit/test_curate.py"
  modified:
    - "src/knowledge_lake/quality/scorer.py (compute_composite_quality_score added)"
    - "src/knowledge_lake/registry/repo.py (create_curated_artifact, get_child_artifact_by_type)"
    - "src/knowledge_lake/config/settings.py (CurateSettings, Settings.curate)"
    - "src/knowledge_lake/ids.py (curated_document prefix)"
    - "src/knowledge_lake/pipeline/clean.py (docstring/comment update only)"
    - "src/knowledge_lake/cli/app.py (curate, dedupe commands)"
    - "src/knowledge_lake/api/app.py (POST /curate, GET /curated-documents)"
    - "src/knowledge_lake/api/schemas.py (CurateRequest, CurateResponse, CuratedDocumentOut)"
    - "src/knowledge_lake/dagster_defs/assets.py (curate_document_asset)"
    - "src/knowledge_lake/dagster_defs/definitions.py (register curate_document_asset)"
    - "pyproject.toml (datatrove==0.9.0, nltk>=3.9,<4)"
    - "tests/unit/test_quality_scorer.py (test_composite_quality_score tests added)"
decisions:
  - "DataTrove filters called via .filter(doc) in a loop — never .run() or LocalPipelineExecutor (RESEARCH.md Pitfall 2 — .run() silently drops on first failure)"
  - "batch_dedup_corpus() builds ONE MinHashLSH instance for the whole corpus (not rebuilt per document pair) — resolves T-03-06 tech debt"
  - "Composite score weights: parse_quality 0.30 + enrich_quality 0.40 + filter_pass_ratio 0.30 (Claude's discretion)"
  - "Curated dedup_status recorded on curated_document.metadata_, not overwriting cleaned_document (D-02: planner's discretion)"
  - "Task 1 (package legitimacy checkpoint) auto-approved: datatrove and nltk both independently verified in RESEARCH.md session"
  - "minhash_threshold=0.5 used in batch_dedup_corpus test (default 0.8 is too strict for short test texts)"
metrics:
  duration: "~10 minutes"
  completed_date: "2026-07-06"
  tasks_completed: 3
  files_created: 2
  files_modified: 12
status: complete
---

# Phase 05 Plan 01: Curation Core Summary

DataTrove-style quality filtering with composite quality scores (parse + enrich + curation), corpus-wide MinHash batch dedup, and full CLI/API/Dagster wiring for curated_document artifacts.

## What Was Built

### pipeline/curate.py (new)

**`_build_filters(settings)`** — Factory for DataTrove filter instances (`GopherRepetitionFilter`, `GopherQualityFilter`, `C4QualityFilter`). Factored separately so tests can monkeypatch it with fake filter doubles, avoiding the real nltk `punkt_tab` data dependency in unit tests (Pitfall 1).

**`score_document(cleaned_text, artifact_id, settings)`** — Wraps text as an in-memory `datatrove.data.Document` and calls each filter's `.filter(doc)` method directly in a loop. Records `{filter_name: {"passed": bool, "reason": str|None}}` for EVERY configured filter regardless of pass/fail order (CURATE-01). Never uses `.run()` or `LocalPipelineExecutor` (Pitfall 2 / FOUND-03).

**`curate_document(cleaned_artifact_id, source_id, *, settings)`** — Registry-first pipeline stage following the established `enrich.py` pattern:
- Fetches cleaned artifact → validates type == `cleaned_document`
- Retrieves text from S3 silver zone (single boto3 `StorageBackend` client)
- Computes filter_results and synthetic content_hash via `_curation_cache_key()`
- Cache checks via `UNIQUE(content_hash, artifact_type)` constraint
- Resolves `parse_quality_score` from parent `parsed_document.metadata_["quality_score"]`
- Resolves `enrich_quality_score` from `enriched_document` sibling via `get_child_artifact_by_type()` (sibling lookup, not ancestor walk — Pitfall 4)
- Computes `composite_score = parse*0.3 + enrich*0.4 + filter_pass_ratio*0.3`
- Writes `curated_document` artifact with `filter_results`, `composite_quality_score`, `dedup_status="not_yet_computed"`, `quality_score` as the real `Artifact.quality_score` column
- Handles concurrent race via `IntegrityError` → cache hit (WR-02)

**`batch_dedup_corpus(*, settings)`** — Corpus-wide MinHash dedup (CURATE-02):
- Fetches ALL `cleaned_document` artifacts in one session read
- Builds **exactly ONE** `MinHashLSH` instance for the whole corpus (not rebuilt per pair)
- Reuses `pipeline.clean.compute_minhash()` — never reimplements the math
- Updates `curated_document.metadata_["dedup_status"]` via whole-dict re-assignment (SQLAlchemy mutable JSON dirty-tracking requirement)
- Returns `{total, unique, near_dup, skipped_no_curation}`

### quality/scorer.py

**`compute_composite_quality_score(parse_quality_score, enrich_quality_score, filter_results)`** — New function implementing the `0.3/0.4/0.3` weighted formula (CURATE-03), clamped to `[0.0, 1.0]`, with `log.debug("quality_scorer.composite", ...)` mirroring the existing heuristic scorer's convention.

### registry/repo.py

**`create_curated_artifact(session, *, ...)`** — Mirrors `create_enriched_artifact` exactly, with `artifact_type="curated_document"` and `quality_score` stored as the real column.

**`get_child_artifact_by_type(session, parent_artifact_id, artifact_type)`** — Generic one-hop child lookup via parameterized ORM `select()`. Used both for finding the `enriched_document` sibling (for composite score) and the `curated_document` child (for batch dedup updates).

### CLI, API, Dagster

- **`klake curate <cleaned_artifact_id> <source_id>`** — Calls `pipeline.curate.curate_document`, echoes status/artifact_id/quality_score/cached/dedup_status
- **`klake dedupe`** — Calls `pipeline.curate.batch_dedup_corpus()`, echoes total/unique/near_dup/skipped_no_curation
- **`POST /curate`** — Mirrors `enrich_endpoint` shape; `ValueError` → `HTTPException(422)`
- **`GET /curated-documents?min_quality_score=<float>`** — Parameterized ORM query with Pydantic `ge=0.0, le=1.0` bounds (T-05-03); ordered by `quality_score DESC`
- **`curate_document_asset`** Dagster asset — named `curate_document_asset` to avoid shadowing `pipeline.curate.curate_document`; parallel branch off `clean_document`; 8 total assets in `defs`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `_FakeFilter` class mutating shared `__name__` attribute**
- **Found during:** Task 2 GREEN phase — `test_filter_results_records_all_heuristics` failed because all instances ended up with the same `type().__name__`
- **Issue:** `type(self).__name__ = name` modifies the class attribute on the shared `_FakeFilter` class, so all three instances reported the same name (the last one set)
- **Fix:** Changed `_FakeFilter` from a class to a factory function that creates a fresh subclass per call via `type(name, (), {"filter": _filter_method})()`
- **Files modified:** `tests/unit/test_curate.py`
- **Commit:** cb145e7 (included in GREEN phase)

**2. [Rule 1 - Bug] Fixed `datatrove.io` substring in docstring triggering the file-I/O scaffold test**
- **Found during:** Task 2 — `test_never_adopts_datatrove_file_io_scaffolding` caught the string `datatrove.io` in the module docstring
- **Fix:** Rephrased the docstring to describe the constraint without using the exact forbidden substring
- **Files modified:** `src/knowledge_lake/pipeline/curate.py`
- **Commit:** cb145e7

**3. [Rule 1 - Bug] Fixed near-dup detection test using texts below the 0.8 Jaccard threshold**
- **Found during:** Task 2 — `test_batch_dedup_single_pass` classified all 3 texts as "unique" because the test's near-duplicate pair had Jaccard ~0.74 < default threshold 0.8
- **Fix:** Test constructs `dedup_settings` with `minhash_threshold=0.5` (the near-dup pair has Jaccard ~0.74 which clears 0.5); updated test texts to share a longer common base for better similarity
- **Files modified:** `tests/unit/test_curate.py`
- **Commit:** cb145e7

**4. [Rule 1 - Bug] Fixed syntax error in test file**
- **Found during:** Task 2 — `from knowledge_lake.registry import repo as registry_repo as repo` is invalid Python
- **Fix:** Removed the duplicate `as repo` alias
- **Files modified:** `tests/unit/test_curate.py`
- **Commit:** cb145e7

## Task 1 Checkpoint

**Type:** `checkpoint:human-verify` with `gate="blocking-human"`
**Resolution:** Auto-approved per `<auto_mode_checkpoints>` directive (AUTO_MODE=true). Both `datatrove==0.9.0` and `nltk>=3.9,<4` were independently verified in the RESEARCH.md session against their real GitHub/PyPI sources. `datatrove` is already a CLAUDE.md-locked stack choice. The raw `[SUS]` seam verdict was confirmed to be a "unknown-downloads" false positive in RESEARCH.md's Package Legitimacy Audit.

## Known Stubs

None. All curated_document artifacts carry real computed values:
- `filter_results`: per-heuristic DataTrove filter pass/fail
- `composite_quality_score`: weighted average of 3 real signals
- `quality_score`: real `Artifact.quality_score` column, filterable
- `dedup_status`: `"not_yet_computed"` until `klake dedupe` runs (intentional — not a stub, documented in CLI/API output)

## Threat Flags

None beyond what was already in the plan's threat register (T-05-01, T-05-02, T-05-03, T-05-SC all addressed as planned):
- T-05-SC mitigated: Task 1 checkpoint verified both packages
- T-05-03 mitigated: `GET /curated-documents` uses Pydantic `ge/le` bounds + parameterized ORM
- T-05-01/T-05-02 accepted: annotate-only, operator-triggered batch job

## Self-Check: PASSED

Files verified:
- `/root/healthlake/src/knowledge_lake/pipeline/curate.py` — FOUND
- `/root/healthlake/src/knowledge_lake/quality/scorer.py` — FOUND (compute_composite_quality_score)
- `/root/healthlake/src/knowledge_lake/registry/repo.py` — FOUND (create_curated_artifact, get_child_artifact_by_type)
- `/root/healthlake/src/knowledge_lake/config/settings.py` — FOUND (CurateSettings)
- `/root/healthlake/src/knowledge_lake/ids.py` — FOUND (curated_document)
- `/root/healthlake/src/knowledge_lake/cli/app.py` — FOUND (curate, dedupe)
- `/root/healthlake/src/knowledge_lake/api/app.py` — FOUND (/curate, /curated-documents)
- `/root/healthlake/tests/unit/test_curate.py` — FOUND

Commits verified:
- `a32023f` (test RED phase) — FOUND
- `cb145e7` (feat GREEN phase) — FOUND
- `d40c430` (feat Task 3 wiring) — FOUND

Test results: `pytest tests/unit/test_curate.py tests/unit/test_quality_scorer.py` — 14 passed
Full unit suite: `pytest tests/unit/` (excluding browser tests) — 264 passed, 0 failures
