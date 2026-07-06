---
phase: 05-curation-datasets-export
verified: 2026-07-06T00:00:00Z
status: human_needed
score: 11/12
behavior_unverified: 0
overrides_applied: 0
human_verification:
  - test: "Run live Bedrock smoke test for eval_model and strong_model aliases"
    expected: "klake generate-dataset qa <chunk_id> --dataset-name smoke-test prints status: generated; re-run prints status: cached; klake generate-dataset instruction <enriched_document_artifact_id> --dataset-name smoke-test prints status: generated"
    why_human: "Plan 05-02 Task 3 is a gate='blocking' checkpoint requiring a real AWS Bedrock-backed LiteLLM proxy call. Unit tests use mocked litellm.completion. Phase 4's checkpoint only verified cheap_model live; strong_model and eval_model have never been exercised live against real Bedrock in this project. Cannot verify without a running docker-compose stack and AWS credentials."
---

# Phase 05: Curation, Datasets & Export — Verification Report

**Phase Goal:** The enriched corpus becomes AI-ready deliverables — curated pretraining corpus, generated fine-tuning and RAG-eval datasets with full lineage, and standard export formats consumable by downstream tools
**Verified:** 2026-07-06
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Running `klake curate <cleaned_artifact_id> <source_id>` produces a curated_document artifact recording EVERY configured DataTrove filter's pass/fail independently (not just the first failure), plus a composite_quality_score combining Phase 3's parse-quality heuristic, Phase 4's enrichment quality_score, and this phase's filter-pass ratio (CURATE-01, CURATE-03) | ✓ VERIFIED | `score_document()` in `pipeline/curate.py` calls each filter's `.filter(doc)` in a loop and records every result regardless of order. `test_filter_results_records_all_heuristics` PASSED — asserts all 3 filter entries exist in `metadata_["filter_results"]` including ones after the first failure. `compute_composite_quality_score()` in `quality/scorer.py` implements the weighted 0.3/0.4/0.3 formula. `test_composite_quality_score` PASSED. |
| 2 | Running `klake dedupe` builds exactly ONE MinHash LSH index over the whole cleaned_document corpus in a single pass and flags near-duplicate curated_document artifacts, replacing Phase 3's per-call transient scan as the authoritative dedup signal for this corpus (CURATE-02) | ✓ VERIFIED | `batch_dedup_corpus()` in `pipeline/curate.py` builds one `MinHashLSH` instance before iterating all artifacts. `test_batch_dedup_single_pass` PASSED — verifies exactly one LSH index built for 3 seeded documents with 2 near-duplicates correctly classified as "near_dup" and 1 as "unique". |
| 3 | Composite quality scores are queryable via both `klake curate` output and a GET /curated-documents API endpoint filterable by min_quality_score (CURATE-03 'queryable via CLI/API') | ✓ VERIFIED | `cmd_curate` in `cli/app.py` echoes `quality_score`. `GET /curated-documents` endpoint exists in `api/app.py` (line 838), filterable by `min_quality_score` with Pydantic `ge=0.0, le=1.0` bounds. FastAPI route inspection confirmed: `['/curate', '/datasets/examples', '/curated-documents', '/exports']`. |
| 4 | Re-running curate on an unchanged cleaned_document + unchanged CurateSettings.filter_config_version is a registry-level no-op (cached), mirroring enrich_document()'s idempotency pattern | ✓ VERIFIED | `_curation_cache_key()` computes `sha256(cleaned_content_hash:filter_config_version)`, stored as the artifact's `content_hash`. Cache check via `get_artifact_by_hash(session, synthetic_hash, "curated_document")` returns early if found. `test_curate_is_idempotent_cache_hit` PASSED. |
| 5 | Running `klake generate-dataset qa <chunk_id> --dataset-name <name>` produces exactly one validated QAPairResult (question/answer) per chunk via the eval_model task alias, with citation_chunk_id assigned programmatically from the already-known chunk_id — never LLM-produced (DATA-01) | ✓ VERIFIED | `generate_qa_example()` in `pipeline/datasets.py` routes to `openai/eval_model`. `QAPairResult` model has no `citation_chunk_id` field (verified by grep and `test_citation_chunk_id_never_llm_producible` PASSED). `citation_chunk_id` assigned at line 364 after LLM call returns. `test_qa_generation_produces_valid_result` PASSED. |
| 6 | Running `klake generate-dataset instruction <enriched_document_artifact_id> --dataset-name <name>` produces exactly one validated instruction/input/output triple per document via the strong_model task alias (DATA-02) | ✓ VERIFIED | `generate_instruction_example()` routes to `openai/strong_model`. `InstructionPairResult` schema has `instruction`, `input`, `output` with `max_length` bounds. `test_instruction_generation_produces_valid_result` PASSED with mock confirming `model == "openai/strong_model"`. |
| 7 | Every generated example is persisted as a dataset_examples row with a non-null source_artifact_id FK resolving back to its source chunk/document — DATA-03's lineage requirement, queryable as 'which datasets does artifact X appear in' | ✓ VERIFIED | `DatasetExample.source_artifact_id` is a nullable FK (`ondelete=SET NULL`) to `artifacts.id`. `create_dataset_example()` always receives the caller-supplied `chunk_id` or `enriched_document_id` as `source_artifact_id`. `test_dataset_examples_lineage` PASSED — asserts both rows share one Dataset and each `source_artifact_id` resolves via `get_artifact()`. Migration 0008 applies cleanly. |
| 8 | Re-running generation for the same source artifact + unchanged DatasetSettings.prompt_version is a no-op (cached), and cumulative dataset-generation spend is tracked under its own 'dataset_generation' LlmSpend scope, never merged with enrichment's 'global' scope | ✓ VERIFIED | Cache key `sha256(content_hash:prompt_version)` stored in `payload["_cache_key"]`; `list_dataset_examples_by_cache_key()` short-circuits on repeat. `record_llm_spend(scope="dataset_generation")` at lines 352 and 518 in `datasets.py`. `test_dataset_generation_uses_distinct_budget_scope` PASSED — seeds exhausted `"global"` scope, asserts generation still proceeds on its own scope. |
| 9 | Running `klake export rag-corpus` writes an allow-listed-columns-only Parquet file to the gold zone containing every chunk's citation + enrichment payload, and the file round-trips through DuckDB read_parquet() with the expected row count (EXPORT-01) | ✓ VERIFIED | `export_rag_corpus()` builds rows strictly from `_RAG_CORPUS_FIELDS` list (9 columns, line 58). Uses `polars.DataFrame.write_parquet()` into `io.BytesIO`, then `StorageBackend.put_object()`. `verify_export()` uses DuckDB `httpfs`. `test_rag_corpus_export_uses_allow_list_only` PASSED. Integration test `test_export_parquet_duckdb.py` exists for live round-trip. |
| 10 | Running `klake export pretrain` writes a JSONL file to the gold zone containing one line per curated_document whose composite_quality_score meets ExportSettings.min_quality_score_for_pretrain, in a schema DuckDB/Polars can read back (EXPORT-02) | ✓ VERIFIED | `export_pretrain_corpus()` filters by `quality_score >= min_quality_score_for_pretrain` (default 0.4) then writes `orjson.dumps(row)` per line. `test_pretrain_jsonl_schema` PASSED — asserts 1 of 2 seeded documents survives the quality threshold and the line parses as JSON with `"text"` key. |
| 11 | Running `klake export finetune --dataset-name <name>` writes a JSONL file in OpenAI chat-messages format (one {"messages": [...]} per line) from that Dataset's dataset_examples rows, skipping any example whose source_artifact_id no longer resolves to a live artifact (EXPORT-03, DATA-03 lineage integrity) | ✓ VERIFIED | `export_finetune_dataset()` branches on payload shape (QA → user/assistant pair, instruction → instruction+input/output). Dangling lineage check at line 479 increments `skipped_dangling` counter. `test_finetune_jsonl_chat_format` PASSED (correct messages format). `test_finetune_export_skips_dangling_lineage` PASSED (non-zero `skipped_dangling_lineage` count). |
| 12 | Running any `klake export` subcommand (rag-corpus, pretrain, finetune) first calls check_train_eval_contamination() and fails closed — raises TrainEvalContaminationError, writes NO file — on any non-zero undocumented overlap, per 05-AI-SPEC.md Section 6/7's hard-block guardrail. Any live Bedrock smoke test for strong_model/eval_model aliases (Plan 05-02 Task 3 gate="blocking" checkpoint) | ⚠️ PARTIAL | Train/eval contamination gate VERIFIED: `_enforce_no_contamination()` called first in all 3 export functions (verified by `inspect.getsource` assertion). 4 contamination tests all PASSED. BUT: Plan 05-02 Task 3 is a `gate="blocking"` `checkpoint:human-verify` requiring a live Bedrock smoke test for `strong_model` and `eval_model` — auto-approved via `AUTO_MODE=true` in the SUMMARY but was NOT run against real Bedrock (gate is "blocking", not "blocking-human", but it explicitly requires live LLM proxy call that can't be verified programmatically). |

**Score:** 11/12 truths verified (1 requires live human verification)

### Deferred Items

No items deferred to later phases. All 9 requirement IDs are implemented in this phase.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/knowledge_lake/pipeline/curate.py` | `_build_filters()`, `score_document()`, `curate_document()`, `batch_dedup_corpus()` | ✓ VERIFIED | All 4 functions present and substantive (431 lines). No stubs. |
| `src/knowledge_lake/quality/scorer.py` | `compute_composite_quality_score()` | ✓ VERIFIED | Function at line 111, implements 0.3/0.4/0.3 weighted formula with clamping and log.debug. |
| `src/knowledge_lake/registry/repo.py` | `create_curated_artifact`, `get_child_artifact_by_type` | ✓ VERIFIED | Both present at lines 671 and 724. |
| `src/knowledge_lake/config/settings.py` | `CurateSettings`, `DatasetSettings`, `ExportSettings` | ✓ VERIFIED | All 3 classes at lines 185, 205, 231. Registered on `Settings` at lines 366, 369, 375. |
| `src/knowledge_lake/ids.py` | `curated_document`, `dataset`, `dataset_example` prefixes | ✓ VERIFIED | Lines 43-45: `"curated_document": "doc"`, `"dataset": "dst"`, `"dataset_example": "dex"`. |
| `src/knowledge_lake/pipeline/datasets.py` | `QAPairResult`, `InstructionPairResult`, `generate_qa_example()`, `generate_instruction_example()` | ✓ VERIFIED | All present, substantive (548 lines). QAPairResult has NO `citation_chunk_id` field. |
| `src/knowledge_lake/registry/alembic/versions/0008_dataset_examples.py` | Migration adding `dataset_examples` table + Dataset columns | ✓ VERIFIED | Present, `down_revision = "0007"`, complete upgrade/downgrade. |
| `src/knowledge_lake/registry/models.py` | `Dataset` real columns + `DatasetExample` class | ✓ VERIFIED | `DatasetExample` at line 502, `source_artifact_id` nullable FK with `ondelete="SET NULL"`. Dataset extended with `dataset_type`, `format`, `example_count`, `storage_uri` at lines 480-486. |
| `src/knowledge_lake/pipeline/export.py` | `export_rag_corpus()`, `export_pretrain_corpus()`, `export_finetune_dataset()`, `verify_export()`, `check_train_eval_contamination()`, `TrainEvalContaminationError` | ✓ VERIFIED | All 6 entities present, substantive (617 lines). No stubs. No `open()` calls. `_enforce_no_contamination()` wired first in all 3 export entry points. |
| `src/knowledge_lake/cli/app.py` | `klake curate`, `klake dedupe`, `klake generate-dataset`, `klake export` commands | ✓ VERIFIED | All 4 commands confirmed in CLI command list. |
| `src/knowledge_lake/api/app.py` | `POST /curate`, `GET /curated-documents`, `POST /datasets/examples`, `POST /exports` | ✓ VERIFIED | All 4 routes confirmed via FastAPI route inspection. |
| `src/knowledge_lake/dagster_defs/assets.py` | `curate_document_asset`, `generate_dataset`, `export_rag_corpus`, `export_pretrain_corpus`, `export_finetune_dataset` | ✓ VERIFIED | All 5 assets present. `defs.assets` count = 12. |
| `tests/unit/test_curate.py` | Unit tests for curation | ✓ VERIFIED | 5 test functions, all PASSED. |
| `tests/unit/test_datasets.py` | Unit tests for dataset generation | ✓ VERIFIED | 7 test functions, all PASSED. |
| `tests/unit/test_export.py` | Unit tests for export + contamination gate | ✓ VERIFIED | 9 test functions, all PASSED. |
| `tests/integration/test_export_parquet_duckdb.py` | Live MinIO + DuckDB integration test | ✓ VERIFIED (file exists, live run not attempted) | File present and substantive. Live run requires docker-compose MinIO — not run in this verification. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `curate_document()` synthetic cache | `UNIQUE(content_hash, artifact_type)` constraint | `_curation_cache_key(cleaned_content_hash, filter_config_version)` | ✓ WIRED | Hash computed at line 209, cache check at line 213, IntegrityError race handled at line 275. |
| `curated_document.parent_artifact_id` | `cleaned_document` (not parsed_document) | `parent_artifact_id=cleaned_artifact_id` at line 257 | ✓ WIRED | Always parents off cleaned_document artifact (D-01). |
| Enriched sibling lookup | `get_child_artifact_by_type(session, cleaned_artifact_id, "enriched_document")` | Sibling lookup off shared cleaned_document parent (Pitfall 4) | ✓ WIRED | Line 228 in curate.py — one-hop child lookup, never ancestor walk. |
| `DatasetExample.source_artifact_id` | `artifacts.id` (chunk or enriched_document) | Nullable FK `ondelete="SET NULL"` | ✓ WIRED | Line 525 in models.py. Caller assigns at `create_dataset_example(source_artifact_id=chunk_id)`. |
| `generate_qa_example()` LLM alias | `openai/eval_model` | `model="openai/eval_model"` in litellm.completion call | ✓ WIRED | Line 190 in datasets.py. |
| `generate_instruction_example()` LLM alias | `openai/strong_model` | `model="openai/strong_model"` in litellm.completion call | ✓ WIRED | Line 227 in datasets.py. |
| Every export write | `StorageBackend.put_object()` via `io.BytesIO` | In-memory buffer, never `open()` | ✓ WIRED | Lines 324, 410, 524 in export.py. 0 `open()` calls confirmed by `ast.parse()` check. |
| `_enforce_no_contamination()` in all 3 export entry points | Contamination check runs FIRST | Called at lines 263, 361, 454 in export.py | ✓ WIRED | Confirmed by `inspect.getsource` assertion returning count == 3. |
| `export_rag_corpus()` enrichment join | `get_enriched_artifact_for_parsed()` | Same join helper as `pipeline/index.py` | ✓ WIRED | Line 278 in export.py — reused verbatim from index.py. |
| DataTrove filter calls | `.filter(doc)` method directly | Never `.run()` or `LocalPipelineExecutor` | ✓ WIRED | `grep -c 'LocalPipelineExecutor|datatrove.io|BaseDiskReader' curate.py` = 0. `test_never_adopts_datatrove_file_io_scaffolding` PASSED. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `pipeline/curate.py::curate_document()` | `filter_results` | `score_document()` → DataTrove `.filter(doc)` on real text from S3 | Yes — text fetched from S3 via `StorageBackend.get_object()` at line 203 | ✓ FLOWING |
| `pipeline/curate.py::batch_dedup_corpus()` | `dedup_status` | `list_cleaned_artifacts()` → S3 text → `compute_minhash()` → `MinHashLSH` | Yes — real S3 text fetched per artifact, real MinHash computation | ✓ FLOWING |
| `pipeline/datasets.py::generate_qa_example()` | `payload` (question/answer) | `litellm.completion(model="openai/eval_model")` → `QAPairResult.model_validate_json()` | Yes — LLM call with budget check, cached in `dataset_examples` | ✓ FLOWING |
| `pipeline/export.py::export_rag_corpus()` | Parquet rows | `list_artifacts_by_type("chunk")` → `get_enriched_artifact_for_parsed()` → `polars.DataFrame.write_parquet()` | Yes — DB query produces real artifact rows | ✓ FLOWING |
| `pipeline/export.py::export_pretrain_corpus()` | JSONL text | `list_artifacts_by_type("curated_document")` filtered by `quality_score >= 0.4` → S3 text retrieval | Yes — quality-gated, S3 text fetched per qualifying artifact | ✓ FLOWING |
| `pipeline/export.py::export_finetune_dataset()` | Chat-messages JSONL | `list_dataset_examples(dataset.id)` → payload branch → `orjson.dumps()` | Yes — real `DatasetExample.payload` from DB | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All DataTrove filter results recorded per document | `pytest test_curate.py::test_filter_results_records_all_heuristics` | PASSED | ✓ PASS |
| Exactly one MinHashLSH built for full corpus batch | `pytest test_curate.py::test_batch_dedup_single_pass` | PASSED | ✓ PASS |
| Curation idempotency (cache hit) | `pytest test_curate.py::test_curate_is_idempotent_cache_hit` | PASSED | ✓ PASS |
| Composite quality score formula (0.3/0.4/0.3) | `pytest test_quality_scorer.py::test_composite_quality_score` | PASSED | ✓ PASS |
| citation_chunk_id not in QAPairResult model_fields | `pytest test_datasets.py::test_citation_chunk_id_never_llm_producible` | PASSED | ✓ PASS |
| Dataset-generation uses distinct LlmSpend scope | `pytest test_datasets.py::test_dataset_generation_uses_distinct_budget_scope` | PASSED | ✓ PASS |
| Contamination gate blocks direct overlap | `pytest test_export.py::TestTrainEvalContamination::test_contamination_blocks_direct_overlap` | PASSED | ✓ PASS |
| Contamination gate blocks near-dup overlap | `pytest test_export.py::TestTrainEvalContamination::test_contamination_blocks_near_dup_overlap` | PASSED | ✓ PASS |
| Clean corpus passes contamination gate | `pytest test_export.py::TestTrainEvalContamination::test_contamination_allows_clean_export` | PASSED | ✓ PASS |
| Contamination override allowlist | `pytest test_export.py::TestTrainEvalContamination::test_contamination_override_allowlist` | PASSED | ✓ PASS |
| No open() write calls in export.py | `ast.parse() check` | 0 occurrences | ✓ PASS |
| _enforce_no_contamination called in all 3 export entry points | `inspect.getsource` count check | count == 3 | ✓ PASS |
| Dagster assets count = 12 | `from defs import defs; len(list(defs.assets))` | 12 | ✓ PASS |
| Phase 5 CLI commands present | `cli_app.registered_commands` | curate, dedupe, generate-dataset, export | ✓ PASS |
| Phase 5 API routes present | FastAPI route inspection | /curate, /curated-documents, /datasets/examples, /exports | ✓ PASS |
| Live strong_model + eval_model against real Bedrock | `klake generate-dataset qa/instruction` (live) | NOT RUN | ? SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| CURATE-01 | 05-01-PLAN | DataTrove-style quality filters (length, repetition, boilerplate heuristics) | ✓ SATISFIED | `score_document()` calls GopherRepetitionFilter, GopherQualityFilter, C4QualityFilter via `.filter(doc)` in a loop recording all results. `test_filter_results_records_all_heuristics` PASSED. |
| CURATE-02 | 05-01-PLAN | Corpus-wide deduplication producing cleaned training corpus | ✓ SATISFIED | `batch_dedup_corpus()` builds ONE MinHashLSH for the whole corpus. `test_batch_dedup_single_pass` PASSED. |
| CURATE-03 | 05-01-PLAN | Composite quality scores queryable via CLI/API | ✓ SATISFIED | `compute_composite_quality_score()` implemented. `GET /curated-documents?min_quality_score=` endpoint confirmed. |
| DATA-01 | 05-02-PLAN | Citation-grounded Q&A / RAG-eval datasets from enriched chunks via LiteLLM | ✓ SATISFIED | `generate_qa_example()` via `openai/eval_model`. `citation_chunk_id` programmatic. `test_qa_generation_produces_valid_result` PASSED. |
| DATA-02 | 05-02-PLAN | Instruction-tuning datasets from enriched documents | ✓ SATISFIED | `generate_instruction_example()` via `openai/strong_model`. `test_instruction_generation_produces_valid_result` PASSED. |
| DATA-03 | 05-02-PLAN | Generated dataset examples record lineage to source chunks/documents | ✓ SATISFIED | `DatasetExample.source_artifact_id` nullable FK. `test_dataset_examples_lineage` PASSED. |
| EXPORT-01 | 05-03-PLAN | RAG corpus (chunks + metadata) to Parquet queryable via DuckDB | ✓ SATISFIED | `export_rag_corpus()` writes Parquet with `_RAG_CORPUS_FIELDS` allow-list. `verify_export()` uses DuckDB httpfs. Integration test present. |
| EXPORT-02 | 05-03-PLAN | Pretraining-style text corpus to JSONL | ✓ SATISFIED | `export_pretrain_corpus()` quality-gates by `min_quality_score_for_pretrain`. `test_pretrain_jsonl_schema` PASSED. |
| EXPORT-03 | 05-03-PLAN | Fine-tuning datasets to JSONL in standard chat/instruction formats | ✓ SATISFIED | `export_finetune_dataset()` writes OpenAI chat-messages format. Dangling lineage skip. `test_finetune_jsonl_chat_format` + `test_finetune_export_skips_dangling_lineage` PASSED. |

All 9 requirement IDs accounted for. No orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None found | — | — | — | No TBD/FIXME/XXX markers in Phase 5 files. No placeholder returns. No hardcoded empty data stubs. |

Zero debt markers, zero placeholders, zero stubs in all Phase 5 source files examined (`pipeline/curate.py`, `pipeline/datasets.py`, `pipeline/export.py`, `quality/scorer.py`).

### Human Verification Required

#### 1. Live Bedrock Smoke Test for eval_model and strong_model Aliases

**Test:** Ensure AWS_BEDROCK_API_KEY is set and `docker compose up -d litellm postgres qdrant minio` is healthy. Obtain a real `chunk_id` (via `klake demo` or the ingest/parse/clean/chunk chain). Run:
1. `klake generate-dataset qa <chunk_id> --dataset-name smoke-test` — confirm `status: generated` with a non-null `example_id`.
2. `klake generate-dataset instruction <enriched_document_artifact_id> --dataset-name smoke-test` — confirm `status: generated`.
3. Re-run step 1 with identical arguments — confirm `status: cached`.

**Expected:** Both model aliases (`eval_model`, `strong_model`) resolve against the real Bedrock-backed LiteLLM proxy and return valid JSON conforming to `QAPairResult` / `InstructionPairResult`. Cache hit on re-run confirms idempotency.

**Why human:** Plan 05-02 Task 3 is a `gate="blocking"` `checkpoint:human-verify`. Unit tests use `mocked litellm.completion`. The live strong_model and eval_model aliases were never exercised live against Bedrock in this project (Phase 4 only verified `cheap_model`). Cannot verify LiteLLM proxy config (`config.yaml` model ID mappings) programmatically.

---

## Gaps Summary

No blocking gaps. All 9 CURATE/DATA/EXPORT requirements are implemented with passing unit tests and correct wiring. The one outstanding item is a live Bedrock smoke test for the two dataset-generation model aliases (eval_model, strong_model) — required by Plan 05-02's Task 3 `gate="blocking"` checkpoint, which was auto-approved during execution because `AUTO_MODE=true` but was not run against real infrastructure.

This is the only item preventing `status: passed`. All automated evidence points to a complete, correct implementation.

---

_Verified: 2026-07-06_
_Verifier: Claude (gsd-verifier)_
