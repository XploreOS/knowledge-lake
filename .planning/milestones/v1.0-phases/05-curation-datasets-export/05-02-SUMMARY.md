---
phase: 05-curation-datasets-export
plan: "02"
subsystem: datasets
tags: [datasets, qa-generation, instruction-tuning, litellm, eval-model, strong-model, dataset-examples, lineage, dagster, fastapi, typer]
dependency_graph:
  requires:
    - "05-01-SUMMARY.md (curated_document artifacts, curation pipeline)"
    - "04-02-SUMMARY.md (enriched_document artifacts with summary/keywords/document_type)"
    - "03-02-SUMMARY.md (chunk artifacts with metadata_.text)"
  provides:
    - "DatasetExample rows with non-null source_artifact_id FK (DATA-03 lineage)"
    - "generate_qa_example() — per-chunk Q&A pair via eval_model (DATA-01)"
    - "generate_instruction_example() — per-document instruction pair via strong_model (DATA-02)"
    - "POST /datasets/examples API endpoint"
    - "klake generate-dataset CLI command"
    - "generate_dataset Dagster asset (GenerateDatasetConfig)"
  affects:
    - "registry/models.py (Dataset real columns + DatasetExample new table)"
    - "registry/repo.py (5 new dataset functions)"
    - "config/settings.py (DatasetSettings + Settings.dataset field)"
    - "ids.py (dataset='dst', dataset_example='dex')"
tech_stack:
  added: []
  patterns:
    - "Structural copy of enrich.py's cached, budget-capped LLM-call shape (D-07)"
    - "QAPairResult has NO citation_chunk_id field — caller assigns programmatically (T-05-05)"
    - "Separate 'dataset_generation' LlmSpend scope — never shares enrich's 'global' (AI-SPEC Pitfall 2)"
    - "Synthetic cache key = sha256(content_hash:prompt_version) stored in payload['_cache_key'] (D-04 precedent)"
    - "get_or_create_dataset() get-or-creates by name so repeated calls accumulate into ONE Dataset row"
key_files:
  created:
    - "src/knowledge_lake/pipeline/datasets.py"
    - "src/knowledge_lake/registry/alembic/versions/0008_dataset_examples.py"
    - "tests/unit/test_datasets.py"
  modified:
    - "src/knowledge_lake/registry/models.py (Dataset real columns + DatasetExample class)"
    - "src/knowledge_lake/registry/repo.py (5 new dataset repo functions)"
    - "src/knowledge_lake/config/settings.py (DatasetSettings, Settings.dataset)"
    - "src/knowledge_lake/ids.py (dataset, dataset_example prefixes)"
    - "src/knowledge_lake/cli/app.py (klake generate-dataset command)"
    - "src/knowledge_lake/api/app.py (POST /datasets/examples)"
    - "src/knowledge_lake/api/schemas.py (GenerateDatasetRequest, GenerateDatasetResponse)"
    - "src/knowledge_lake/dagster_defs/assets.py (generate_dataset, GenerateDatasetConfig)"
    - "src/knowledge_lake/dagster_defs/definitions.py (register generate_dataset)"
decisions:
  - "QAPairResult deliberately excludes citation_chunk_id field — programmatic assignment only (T-05-05, AI-SPEC Common Pitfall 1)"
  - "dataset_generation LlmSpend scope is separate from enrich's 'global' scope — regression guard for AI-SPEC Common Pitfall 2"
  - "dataset_examples uses payload['_cache_key'] for idempotency (no UNIQUE(content_hash, artifact_type) since examples are not Artifact nodes, D-08)"
  - "list_dataset_examples_by_cache_key uses JSON path cast comparison (works on PostgreSQL + SQLite in-memory tests)"
  - "Task 3 checkpoint auto-approved: AUTO_MODE=true, gate='blocking' (not 'blocking-human'); comprehensive mocked unit tests verify correctness"
metrics:
  duration: "~8 minutes"
  completed_date: "2026-07-06"
  tasks_completed: 3
  files_created: 3
  files_modified: 9
status: complete
---

# Phase 05 Plan 02: Dataset Generation Summary

Per-chunk Q&A/RAG-eval generation via eval_model, per-document instruction-tuning generation via strong_model, and dataset_examples lineage join table — all following enrich.py's cached, budget-capped LLM-call shape.

## What Was Built

### pipeline/datasets.py (new)

**`QAPairResult(BaseModel)`** — Validated LLM response schema for DATA-01 Q&A pairs. Deliberately does NOT include a `citation_chunk_id` field (AI-SPEC Common Pitfall 1 / T-05-05) — the caller assigns it programmatically from the already-known `chunk_id` after validation.

**`InstructionPairResult(BaseModel)`** — Validated LLM response schema for DATA-02 instruction pairs with `instruction`, `input` (default=""), and `output` fields, all with `max_length` bounds (T-05-04).

**`_dataset_gen_cache_key()`** — Mirrors `_enrichment_cache_key()` exactly: `sha256(content_hash:prompt_version)`.

**`_strip_json_fences()`** — Copied verbatim from enrich.py (defensive against live Bedrock's markdown fence wrapping).

**`_call_llm_for_qa_generation()`** — Tenacity-retried LLM call via `openai/eval_model` alias, `max_tokens=768`, `temperature=0.2`. Same `stop_after_attempt(3)`, `wait_exponential`, retry-on-`(RuntimeError, ValidationError)` policy as enrich.py. Cost appended to `attempt_costs` before validation (WR-03 precedent).

**`_call_llm_for_instruction_generation()`** — Sibling to above via `openai/strong_model`, `max_tokens=1024`, `temperature=0.3`.

**`generate_qa_example(chunk_id, dataset_name, *, settings)`** — Public entry point for DATA-01:
- Validates chunk artifact type
- Computes synthetic cache key from `chunk.content_hash + prompt_version`
- Cache check via `list_dataset_examples_by_cache_key()` on `payload._cache_key`
- Budget check against separate `"dataset_generation"` LlmSpend scope
- Calls `_call_llm_for_qa_generation` with chunk text excerpt (capped to `qa_excerpt_chars`)
- On success: `get_or_create_dataset()`, `record_llm_spend()`, `create_dataset_example()` with `citation_chunk_id` assigned programmatically
- Never raises (D-05) — returns status dict with `"skipped_generation_failed"` on exception

**`generate_instruction_example(enriched_document_id, dataset_name, *, settings)`** — Public entry point for DATA-02:
- Validates enriched_document artifact type
- Fetches parent cleaned_document text from S3 (via `StorageBackend`)
- Builds prompt with deterministic hints (summary/keywords/document_type from `enriched_metadata`) + document excerpt (capped to `instruction_excerpt_chars=6000`)
- Same cache/budget/LLM-call/write flow as `generate_qa_example` but via `strong_model`

### Migration 0008

- `datasets` table: added `dataset_type`, `format`, `example_count`, `storage_uri` columns + `uq_datasets_name` unique constraint
- `dataset_examples` table: new join table with `id`, `dataset_id` (FK CASCADE), `source_artifact_id` (FK SET NULL, nullable), `example_index`, `payload` (JSON), `created_at`, plus indexes on `dataset_id` and `source_artifact_id`
- Migration applied cleanly against the dev Postgres DB on top of migration 0007

### registry/models.py

**`Dataset`** extended with real columns (`dataset_type`, `format`, `example_count`, `storage_uri`) and `__table_args__ = (UniqueConstraint("name", ...),)`.

**`DatasetExample(Base)`** — New ORM model (not an Artifact/lineage-tree node per D-08) with nullable `source_artifact_id` FK.

### registry/repo.py (5 new functions)

- **`create_dataset()`** — Plain insert with `new_id("dataset")` → `dst_<uuidv7>` prefix
- **`get_dataset_by_name()`** — O(1) lookup via `uq_datasets_name` index
- **`get_or_create_dataset()`** — Get-or-create discipline mirroring `record_llm_spend()`
- **`create_dataset_example()`** — Plain insert with `new_id("dataset_example")` → `dex_<uuidv7>` prefix
- **`list_dataset_examples()`** — Ordered by `example_index`
- **`list_dataset_examples_by_cache_key()`** — JSON path comparison on `payload["_cache_key"]` for idempotency cache lookup

### config/settings.py

**`DatasetSettings`** nested model with `budget_usd=5.0`, `prompt_version="v1"`, `cache_enabled=True`, `qa_excerpt_chars=512`, `instruction_excerpt_chars=6000`. Registered on `Settings.dataset`.

### ids.py

`"dataset": "dst"` and `"dataset_example": "dex"` added to `_PREFIX`.

### CLI, API, Dagster

- **`klake generate-dataset <kind> <source_artifact_id> --dataset-name <name>`** — Dispatches to `generate_qa_example` or `generate_instruction_example`, echoes status/example_id/dataset_id/cost_usd. Invalid `kind` values → `Exit(code=1)`.
- **`POST /datasets/examples`** — `GenerateDatasetRequest` with `pattern="^(qa|instruction)$"` kind validation (T-05-07), dispatches to same functions, `ValueError` → `HTTPException(422)`.
- **`generate_dataset` Dagster asset** with `GenerateDatasetConfig` (kind, source_artifact_id, dataset_name), reconstructs `Settings` from postgres/minio/litellm resources, dispatches to same functions (D-02: no logic duplicated).
- **9 total Dagster assets** in `defs` (original 7 + curate_document_asset + generate_dataset).

## Deviations from Plan

None — plan executed exactly as written. The `list_dataset_examples_by_cache_key()` helper was added to `repo.py` (not explicitly listed in the plan's repo additions) because the cache lookup needed a clean repo function rather than inline JSON querying in `datasets.py`, consistent with repo.py's established pattern of parameterized ORM queries.

## Task 3 Checkpoint

**Type:** `checkpoint:human-verify` with `gate="blocking"`
**Resolution:** ⚡ Auto-approved per `<auto_mode_checkpoints>` directive (AUTO_MODE=true, gate is not `"blocking-human"`, checkpoint concerns live Bedrock connectivity not package legitimacy). All automated tests pass comprehensively with mocked litellm.completion verifying model alias routing, citation assignment, budget scope isolation, and never-raise discipline.

## Known Stubs

None. All generated examples carry:
- `payload["citation_chunk_id"]`: programmatically-assigned chunk ID (DATA-01)
- `source_artifact_id`: non-null FK to originating artifact (DATA-03)
- `dataset_id`: FK to the logical Dataset row (get-or-create by name)
- `payload["_cache_key"]`: synthetic cache key for idempotency
- `"dataset_generation"` LlmSpend scope: separate from enrich's `"global"` scope

## Threat Flags

No new threat surface beyond what was in the plan's threat register (T-05-04, T-05-05, T-05-06, T-05-07 all addressed as planned):
- T-05-04 mitigated: `_QA_SYSTEM_PROMPT`/`_INSTRUCTION_SYSTEM_PROMPT` carry the verbatim prompt-injection clause; all LLM responses validated against Pydantic schemas with `max_length` bounds
- T-05-05 mitigated: `QAPairResult` structurally excludes `citation_chunk_id`; verified by `test_citation_chunk_id_never_llm_producible`
- T-05-06 mitigated: `dataset_generation` budget check runs before every LLM call; verified by `test_dataset_generation_uses_distinct_budget_scope`
- T-05-07 mitigated: `GenerateDatasetRequest.kind` uses `Field(pattern="^(qa|instruction)$")`

## Self-Check: PASSED

Files verified:
- `/root/healthlake/src/knowledge_lake/pipeline/datasets.py` — FOUND
- `/root/healthlake/src/knowledge_lake/registry/alembic/versions/0008_dataset_examples.py` — FOUND
- `/root/healthlake/tests/unit/test_datasets.py` — FOUND
- `/root/healthlake/src/knowledge_lake/registry/models.py` — FOUND (Dataset + DatasetExample)
- `/root/healthlake/src/knowledge_lake/registry/repo.py` — FOUND (6 new dataset functions)
- `/root/healthlake/src/knowledge_lake/config/settings.py` — FOUND (DatasetSettings)
- `/root/healthlake/src/knowledge_lake/ids.py` — FOUND (dataset, dataset_example)
- `/root/healthlake/src/knowledge_lake/cli/app.py` — FOUND (klake generate-dataset)
- `/root/healthlake/src/knowledge_lake/api/app.py` — FOUND (POST /datasets/examples)
- `/root/healthlake/src/knowledge_lake/dagster_defs/assets.py` — FOUND (generate_dataset)

Commits verified:
- `791a9d7` (test RED phase) — FOUND
- `1368871` (feat GREEN phase) — FOUND
- `adee4d9` (feat Task 2 wiring) — FOUND

Test results: `pytest tests/unit/test_datasets.py` — 6 passed
Full unit suite: `pytest tests/unit/` (excluding browser tests) — 299 passed, 0 failures
Alembic: `uv run alembic upgrade head` — migration 0008 applied cleanly
API route: `POST /datasets/examples` verified in FastAPI route table
Dagster: `defs.assets` — 9 assets (original 7 + curate_document_asset + generate_dataset)
Guardrail: `python -c "from knowledge_lake.pipeline.datasets import QAPairResult; assert 'citation_chunk_id' not in QAPairResult.model_fields"` — exits 0
