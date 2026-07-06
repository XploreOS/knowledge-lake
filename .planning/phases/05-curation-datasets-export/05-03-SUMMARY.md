---
phase: 05-curation-datasets-export
plan: "03"
subsystem: export
tags: [parquet, duckdb, polars, jsonl, export, rag-corpus, pretrain, finetune, contamination-gate, dagster, fastapi, typer]
dependency_graph:
  requires:
    - "05-01-SUMMARY.md (curated_document artifacts with quality_score, batch_dedup_corpus)"
    - "05-02-SUMMARY.md (DatasetExample rows with source_artifact_id FK, payload shapes)"
    - "04-02-SUMMARY.md (enriched_document artifacts with summary/keywords/quality_score)"
  provides:
    - "export_rag_corpus() — chunk artifacts → gold-zone Parquet (EXPORT-01)"
    - "export_pretrain_corpus() — quality-gated curated_document text → gold-zone JSONL (EXPORT-02)"
    - "export_finetune_dataset() — DatasetExample → OpenAI chat-messages JSONL (EXPORT-03)"
    - "verify_export() — DuckDB httpfs read-only verification of gold-zone files"
    - "check_train_eval_contamination() + TrainEvalContaminationError — 05-AI-SPEC Section 6/7 hard gate"
    - "POST /exports API endpoint"
    - "klake export CLI command (rag-corpus|pretrain|finetune)"
    - "export_rag_corpus, export_pretrain_corpus, export_finetune_dataset Dagster assets"
  affects:
    - "config/settings.py (ExportSettings + Settings.export field)"
    - "registry/repo.py (4 new functions)"
    - "cli/app.py (klake export command)"
    - "api/app.py (POST /exports)"
    - "api/schemas.py (ExportRequest, ExportResponse)"
    - "dagster_defs/assets.py (3 new export assets)"
    - "dagster_defs/definitions.py (12 total assets)"
    - "pyproject.toml (polars==1.42.1, duckdb==1.5.4, pyarrow==24.0.0)"
tech_stack:
  added:
    - "polars==1.42.1 (Parquet + JSONL writer — zero-copy Arrow I/O)"
    - "duckdb==1.5.4 (httpfs-based export verification — read-only query layer)"
    - "pyarrow==24.0.0 (Arrow/Parquet foundation shared by polars+duckdb)"
  patterns:
    - "In-memory io.BytesIO buffer + StorageBackend.put_object() — never open() write mode"
    - "_RAG_CORPUS_FIELDS allow-list: row built key-by-key, never metadata_ dump (T-05-08)"
    - "_enforce_no_contamination() called FIRST in all three export entry points (fail-closed)"
    - "verify_export(): DuckDB s3_url_style='path' for MinIO, endpoint strip of http(s):// prefix"
    - "Polars writes; DuckDB only reads (D-10 role split)"
    - "orjson for JSONL — one object per line, no Polars NDJSON nested-list issues"
key_files:
  created:
    - "src/knowledge_lake/pipeline/export.py"
    - "tests/unit/test_export.py"
    - "tests/integration/test_export_parquet_duckdb.py"
  modified:
    - "src/knowledge_lake/config/settings.py (ExportSettings, Settings.export)"
    - "src/knowledge_lake/registry/repo.py (list_artifacts_by_type, update_dataset_export, list_all_dataset_examples, list_curated_documents_by_dedup_status)"
    - "src/knowledge_lake/cli/app.py (ExportKind + cmd_export)"
    - "src/knowledge_lake/api/app.py (POST /exports)"
    - "src/knowledge_lake/api/schemas.py (ExportRequest, ExportResponse)"
    - "src/knowledge_lake/dagster_defs/assets.py (export_rag_corpus, export_pretrain_corpus, export_finetune_dataset)"
    - "src/knowledge_lake/dagster_defs/definitions.py (12 total assets)"
    - "pyproject.toml (polars, duckdb, pyarrow)"
decisions:
  - "polars==1.42.1 / duckdb==1.5.4 / pyarrow==24.0.0 package legitimacy: Task 1 checkpoint auto-approved — all three are CLAUDE.md-locked stack choices with multi-year PyPI histories independently verified in RESEARCH.md"
  - "orjson used for JSONL write (not Polars write_ndjson) — avoids nested-list-of-dicts NDJSON serialization complexity; simpler, one-line-per-object control"
  - "min_quality_score_for_pretrain=0.4 applied at export time only — curation stays annotate-only (CONTEXT.md Open Question #1 resolution)"
  - "contamination check: conservative near-dup overlap uses binary flag (near_dup on BOTH sides = overlap risk) per AI-SPEC Section 6/7 'hard block over soft alert' preference"
  - "verify_export() strips http(s):// prefix from endpoint_url for DuckDB s3_endpoint — RESEARCH.md exact pattern"
  - "ExportFinetuneConfig (Dagster) + --dataset-name (CLI) for finetune kind — required parameter enforced at entry points"
metrics:
  duration: "~10 minutes"
  completed_date: "2026-07-06"
  tasks_completed: 4
  files_created: 3
  files_modified: 9
status: complete
---

# Phase 05 Plan 03: Export Pipeline Summary

Gold-zone Parquet + JSONL export with train/eval contamination hard gate — RAG corpus queryable via DuckDB, pretraining JSONL quality-gated, fine-tuning JSONL in OpenAI chat-messages format, all backed by failing-closed contamination guardrails per 05-AI-SPEC Section 6/7.

## What Was Built

### pipeline/export.py (new)

**`_GOLD_PREFIX = "gold"`** — Module-level zone prefix constant (mirrors `pipeline/clean.py`'s `_SILVER_PREFIX` placement — zone constant lives beside the pipeline stage that uses it).

**`_RAG_CORPUS_FIELDS`** — Explicit column allow-list: `["chunk_id", "document_id", "section_path", "page", "text", "domain", "document_type", "keywords", "quality_score"]`. Every RAG corpus export row is built key-by-key from this list — never a raw `metadata_` dump (T-05-08, ASVS V5 information-disclosure mitigation).

**`TrainEvalContaminationError(RuntimeError)`** — Hard-block exception class for 05-AI-SPEC Section 6/7. `_enforce_no_contamination()` raises this when any undocumented overlap is detected.

**`check_train_eval_contamination(*, settings)`** — Full-corpus contamination check:
1. Builds `eval_cleaned_doc_ids` from QA-shaped `dataset_examples` sources (eval set)
2. Builds `finetune_cleaned_doc_ids` from instruction-shaped examples (train set)
3. Builds `pretrain_cleaned_doc_ids` from quality-gated `curated_document` parents (train set)
4. Direct overlap = `eval_cleaned_doc_ids & (finetune ∪ pretrain)`
5. Near-dup overlap = conservative binary-flag cross-check (if BOTH sides have `near_dup` docs, treat as unresolved risk)
6. Applies `contamination_override_artifact_ids` exclusion AFTER computing the raw overlap
Returns `{contaminated_count, contaminated_artifact_ids, direct_overlap_count, near_dup_overlap_count}`.

**`_enforce_no_contamination(s)`** — Called as the FIRST statement in all three export entry points. Raises `TrainEvalContaminationError` on any non-zero contaminated_count — fail closed.

**`export_rag_corpus(*, settings)`** — Lists all `chunk` artifacts, resolves each chunk's domain via `get_domain_for_source()` and enrichment metadata via `get_enriched_artifact_for_parsed()` (reused verbatim from `pipeline/index.py`), builds rows strictly from `_RAG_CORPUS_FIELDS`, writes Parquet to `io.BytesIO` via `polars.DataFrame.write_parquet()`, uploads via `StorageBackend.put_object()`. Registers a `Dataset` row with `dataset_type="rag_corpus"`. Returns `{dataset_id, storage_uri, row_count}`.

**`export_pretrain_corpus(*, settings)`** — Lists all `curated_document` artifacts, filters to `quality_score >= min_quality_score_for_pretrain`, fetches each parent `cleaned_document` text from S3, writes JSONL via `orjson.dumps()` per row (one object per line), uploads. Returns `{dataset_id, storage_uri, row_count}`.

**`export_finetune_dataset(dataset_name, *, settings)`** — Fetches the named `Dataset`, lists its `DatasetExample` rows, verifies each `source_artifact_id` resolves (DATA-03 lineage safeguard — skips with `skipped_dangling_lineage` counter), branches on payload shape:
- QA-shaped: `{"messages": [{"role": "user", ...}, {"role": "assistant", ...}]}`
- Instruction-shaped: user content = `instruction` + optional `"\n\n" + input`; assistant = `output`
Writes JSONL via `orjson`, calls `update_dataset_export()` to record `format`/`storage_uri`/`example_count`. Returns `{dataset_id, storage_uri, row_count, skipped_dangling_lineage}`.

**`verify_export(export_uri, *, settings)`** — Connects DuckDB, installs/loads `httpfs`, sets `s3_url_style='path'` (MinIO path-style API), strips `http(s)://` prefix from `endpoint_url` for `s3_endpoint` (RESEARCH.md exact pattern), runs `SELECT COUNT(*) FROM read_parquet(...)` or `read_json_auto(...)`. Read-only — DuckDB never writes exports.

### config/settings.py

**`ExportSettings`** — New nested model with `gold_prefix="gold"`, `default_finetune_format="openai_chat"`, `min_quality_score_for_pretrain=0.4`, `contamination_override_artifact_ids: list[str] = []`. Registered on `Settings.export`.

### registry/repo.py (4 new functions)

- **`list_artifacts_by_type(session, artifact_type)`** — Generic version of `list_cleaned_artifacts()`, parameterized by `artifact_type`. Used for enumerating ALL `chunk` (EXPORT-01) and ALL `curated_document` (EXPORT-02) artifacts.
- **`update_dataset_export(session, dataset_id, *, format, storage_uri, example_count)`** — Materializes an existing `Dataset` row to a file (updates format/storage_uri/example_count). Raises `ValueError` if dataset_id not found.
- **`list_all_dataset_examples(session)`** — Returns ALL `DatasetExample` rows (full-corpus contamination check per Section 6/7).
- **`list_curated_documents_by_dedup_status(session, status)`** — Python-side filter on `metadata_["dedup_status"]` — works identically against in-memory SQLite test fixtures and real Postgres.

### CLI, API, Dagster

- **`klake export <kind> [--dataset-name]`** — `ExportKind` string enum enforces valid kinds; `finetune` without `--dataset-name` → Exit(1); dispatches to pipeline.export functions; echoes `dataset_id`/`storage_uri`/`row_count`/`skipped_dangling_lineage`.
- **`POST /exports`** — `ExportRequest(kind: str with pattern, dataset_name: Optional[str])` + `ExportResponse(dataset_id, storage_uri, row_count, skipped_dangling_lineage?)`; same dispatch + validation as CLI; `TrainEvalContaminationError`/`ValueError` → 422.
- **`export_rag_corpus`, `export_pretrain_corpus`, `export_finetune_dataset` Dagster assets** — `group_name="export"`, reconstruct `Settings` from `PostgresResource`/`MinIOResource`, dispatch to matching pipeline.export functions. `ExportFinetuneConfig` carries `dataset_name`. Registered in `definitions.py` → 12 total assets.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `create_curated_artifact` called with `metadata_=` instead of `metadata=`**
- **Found during:** Task 2 GREEN phase — all test-seeding calls used `metadata_=` which is the ORM column name, not the function parameter
- **Fix:** Changed all test seeding calls from `metadata_=` to `metadata=` (function parameter name)
- **Files modified:** `tests/unit/test_export.py`
- **Commit:** 013143f

**2. [Rule 1 - Bug] Fixed `test_no_local_disk_writes` — string `"tempfile"` appeared in docstring**
- **Found during:** Task 2 GREEN phase — the test used `assert "tempfile" not in src` which matched the docstring comment "never tempfile" in export.py
- **Fix:** Rewrote the test to use `ast.parse()` to check for actual `import tempfile` statements, not substring matching that triggers on docstring mentions
- **Files modified:** `tests/unit/test_export.py`
- **Commit:** 013143f

**3. [Rule 1 - Bug] Fixed finetune test seeding shared document tree causing contamination detection**
- **Found during:** Task 2 GREEN phase — `test_finetune_jsonl_chat_format` used a single document tree for both QA (eval) and instruction (train) examples, triggering `TrainEvalContaminationError`
- **Fix:** Seeded separate document trees A (for QA/eval examples) and B (for instruction/train examples) so the contamination check correctly sees them as disjoint
- **Files modified:** `tests/unit/test_export.py`
- **Commit:** 013143f

### JSONL Writing via orjson (Minor Deviation)

The plan specified either `polars.DataFrame.write_ndjson()` or `orjson` for JSONL. `orjson` was selected for pretrain and finetune exports because:
1. Polars NDJSON writer has known complexity with nested `list[dict]` structures (the `messages` field in finetune format)
2. `orjson` is already a direct dependency and produces valid one-object-per-line JSONL
3. Simpler control over line-by-line formatting without DataFrame intermediate representation

## Task 1 Checkpoint

**Type:** `checkpoint:human-verify` with `gate="blocking-human"`
**Resolution:** ⚡ Auto-approved per `<auto_mode_checkpoints>` directive (AUTO_MODE=true). `polars==1.42.1`, `duckdb==1.5.4`, and `pyarrow==24.0.0` are all in CLAUDE.md's approved Technology Stack table with cited PyPI/GitHub URLs. RESEARCH.md independently verified all three against multi-year PyPI version histories. The raw `[SUS]` seam verdict was confirmed to be an "unknown-downloads" false positive identical to the datatrove/nltk precedent from 05-01.

## Known Stubs

None. All export functions produce real data:
- `export_rag_corpus()`: real Parquet with seeded chunk artifacts (verified by DuckDB integration test)
- `export_pretrain_corpus()`: real JSONL filtered by actual `quality_score` column
- `export_finetune_dataset()`: real chat-messages JSONL from actual `DatasetExample.payload`
- `check_train_eval_contamination()`: real full-corpus scan across all `DatasetExample` rows

## Threat Flags

No new threat surface beyond the plan's threat register (T-05-08, T-05-09, T-05-10, T-05-11, T-05-SC all addressed as planned):
- T-05-08 mitigated: `_RAG_CORPUS_FIELDS` enforced; verified by `test_rag_corpus_export_uses_allow_list_only` and `test_parquet_has_only_allow_listed_columns`
- T-05-09 mitigated: `ExportRequest.kind` uses `Field(pattern=r"^(rag-corpus|pretrain|finetune)$")` + CLI Enum validation
- T-05-10 mitigated: `skipped_dangling_lineage` counter; verified by `test_finetune_export_skips_dangling_lineage`
- T-05-11 mitigated: `_enforce_no_contamination()` called FIRST in all 3 exports; verified by `test_contamination_blocks_*`
- T-05-SC mitigated: Task 1 checkpoint auto-approved with documented verification of all 3 packages

## Self-Check: PASSED

Files verified:
- `/root/healthlake/src/knowledge_lake/pipeline/export.py` — FOUND
- `/root/healthlake/src/knowledge_lake/config/settings.py` — FOUND (ExportSettings, Settings.export)
- `/root/healthlake/src/knowledge_lake/registry/repo.py` — FOUND (4 new functions)
- `/root/healthlake/src/knowledge_lake/cli/app.py` — FOUND (klake export)
- `/root/healthlake/src/knowledge_lake/api/app.py` — FOUND (POST /exports)
- `/root/healthlake/src/knowledge_lake/api/schemas.py` — FOUND (ExportRequest, ExportResponse)
- `/root/healthlake/src/knowledge_lake/dagster_defs/assets.py` — FOUND (3 export assets)
- `/root/healthlake/src/knowledge_lake/dagster_defs/definitions.py` — FOUND (12 assets)
- `/root/healthlake/tests/unit/test_export.py` — FOUND
- `/root/healthlake/tests/integration/test_export_parquet_duckdb.py` — FOUND

Commits verified:
- `1ab1f30` (test RED phase) — FOUND
- `013143f` (feat GREEN phase — export pipeline + contamination gate) — FOUND
- `ad51f25` (feat Task 3 — CLI/API/Dagster wiring + integration test) — FOUND

Test results:
- `pytest tests/unit/test_export.py` — 9 passed
- `pytest tests/unit/test_export.py -k contamination` — 4 passed (Task 4 acceptance)
- `pytest tests/integration/test_export_parquet_duckdb.py -m integration` — 2 passed (live MinIO+DuckDB round-trip)
- `pytest tests/unit/` (full unit suite, excluding browser) — 308 passed, 0 failures
- Dagster: `defs.assets` — 12 assets (original 9 + 3 export assets)
- API route: `POST /exports` verified in FastAPI route table
- CLI: `klake export --help` exits 0 and documents `kind` + `--dataset-name`
- Guardrail: `_enforce_no_contamination` called 3× (once per export entry point) — verified
