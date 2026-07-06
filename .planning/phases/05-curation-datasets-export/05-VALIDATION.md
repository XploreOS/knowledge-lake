---
phase: 05
slug: curation-datasets-export
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-06
---

# Phase 05 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (installed and configured; `pyproject.toml` `[tool.pytest.ini_options]`, `asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `pytest tests/unit/test_curate.py tests/unit/test_datasets.py tests/unit/test_export.py -x -v` |
| **Full suite command** | `pytest tests/unit tests/integration -v` (integration tests marked `@pytest.mark.integration`) |
| **Estimated runtime** | ~30 seconds (unit) / ~90 seconds (full, including live MinIO/DuckDB httpfs integration) |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/unit/test_curate.py tests/unit/test_datasets.py tests/unit/test_export.py -x`
- **After every plan wave:** Run `pytest tests/unit tests/integration -v`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-XX-01 | TBD | TBD | CURATE-01 | — | Each configured DataTrove filter's `.filter()` result recorded independently in `metadata_["filter_results"]`, even for docs failing multiple heuristics | unit (mocked/real `Document`, no LLM) | `pytest tests/unit/test_curate.py::test_filter_results_records_all_heuristics -x` | ❌ W0 | ⬜ pending |
| 05-XX-02 | TBD | TBD | CURATE-02 | — | Batch dedup flags near-duplicates across the whole corpus in one pass, not per-call | unit (multiple `cleaned_document` fixtures, one LSH build) | `pytest tests/unit/test_curate.py::test_batch_dedup_single_pass -x` | ❌ W0 | ⬜ pending |
| 05-XX-03 | TBD | TBD | CURATE-03 | — | Composite score correctly joins parse + enrich + curate signals, including the sibling-lookup case (Pitfall 4) | unit | `pytest tests/unit/test_quality_scorer.py::test_composite_quality_score -x` | ❌ W0 | ⬜ pending |
| 05-XX-04 | TBD | TBD | DATA-01 | Prompt injection (Tampering) | Q&A generation produces a validated `QAPairResult` with a real `citation_chunk_id` | unit (mocked `litellm.completion`, pattern from `test_enrich.py`) | `pytest tests/unit/test_datasets.py::test_qa_generation_produces_valid_result -x` | ❌ W0 | ⬜ pending |
| 05-XX-05 | TBD | TBD | DATA-02 | Prompt injection (Tampering) | Instruction-tuning generation produces a validated instruction/response pair from an `enriched_document` | unit (mocked LLM) | `pytest tests/unit/test_datasets.py::test_instruction_generation_produces_valid_result -x` | ❌ W0 | ⬜ pending |
| 05-XX-06 | TBD | TBD | DATA-03 | — | Every generated example has a `dataset_examples` row with a non-null `source_artifact_id` | unit (registry-backed) | `pytest tests/unit/test_datasets.py::test_dataset_examples_lineage -x` | ❌ W0 | ⬜ pending |
| 05-XX-07 | TBD | TBD | EXPORT-01 | Info Disclosure (allow-list fields) | Parquet export round-trips through DuckDB `read_parquet` with the expected row count and only allow-listed columns | integration (real MinIO, matches `test_storage.py`'s existing live-MinIO pattern) | `pytest tests/integration/test_export_parquet_duckdb.py -x -m integration` | ❌ W0 | ⬜ pending |
| 05-XX-08 | TBD | TBD | EXPORT-02 | — | Pretraining JSONL export contains one line per curated document with the expected schema | unit | `pytest tests/unit/test_export.py::test_pretrain_jsonl_schema -x` | ❌ W0 | ⬜ pending |
| 05-XX-09 | TBD | TBD | EXPORT-03 | — | Fine-tuning JSONL matches the OpenAI chat-messages schema per line | unit | `pytest tests/unit/test_export.py::test_finetune_jsonl_chat_format -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*Task IDs are placeholders — the planner assigns real plan/task IDs; this map's Req ID / Test Type / Command columns are locked from research.*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_curate.py` — stubs for CURATE-01, CURATE-02
- [ ] `tests/unit/test_datasets.py` — stubs for DATA-01, DATA-02, DATA-03
- [ ] `tests/unit/test_export.py` — stubs for EXPORT-02, EXPORT-03
- [ ] `tests/integration/test_export_parquet_duckdb.py` — covers EXPORT-01 (live MinIO + DuckDB httpfs round-trip)
- [ ] `tests/unit/test_quality_scorer.py::test_composite_quality_score` — extends the existing Phase 3 test file rather than creating a new one
- [ ] Framework install: `datatrove`, `nltk` (+ one-time `nltk.download("punkt_tab")`), `polars`, `duckdb`, `pyarrow` added to `pyproject.toml` — none are installed yet (RESEARCH.md Environment Availability)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real Bedrock LLM call succeeds through the `strong_model`/`eval_model` task aliases | DATA-01, DATA-02 | Phase 4's live checkpoint verified only the `cheap_model` alias against real Bedrock; `strong_model`/`eval_model` were reserved in Phase 4's CONTEXT.md but never actually exercised live — no AWS credentials available in the research/dev environment to verify now | Run `klake generate-dataset <doc-or-chunk>` (or equivalent) against a real enriched document with Bedrock credentials configured; confirm a non-error structured response for both `strong_model` and `eval_model`; flag as a `checkpoint:human-verify` task at Wave 0 |
| `nltk` `punkt_tab` data download succeeds in the target deployment environment (DigitalOcean droplet) | CURATE-01 | Requires one-time network access to NLTK's data server at first run; cannot be verified from the research/dev sandbox whether the production droplet allows this egress | Run `python -c "import nltk; nltk.download('punkt_tab')"` once during deployment setup; confirm `GopherRepetitionFilter`/`GopherQualityFilter` instantiate without a `LookupError` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
