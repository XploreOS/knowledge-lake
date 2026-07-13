---
gsd_summary_version: 1.0
quick_id: 260713-3le
slug: fix-export-rag-corpus-empty-chunk-text-r
date: 2026-07-13
branch: quick/260713-1yf-fix-pipeline-findings
status: complete
---

# Summary: fix export_rag_corpus empty chunk text

## Outcome

`export_rag_corpus` now reads each row's `text` from object storage via
`chunk.storage_uri` — the gold RAG-corpus Parquet no longer emits empty text.
Pre-fix chunks with `storage_uri=None` degrade to `""` without raising.

## Changes

- **`fix(export)` (410824c)** — `src/knowledge_lake/pipeline/export.py`:
  added `from knowledge_lake.pipeline.utils import uri_to_key as _uri_to_key`;
  replaced `"text": meta.get("text", "")` with a storage read-back block that
  mirrors `datasets.generate_qa_example` (same helper, same `try/except BLE001`
  fallback pattern). Uses the already-constructed `_make_storage(s)` instance —
  no second StorageBackend. T-05-08 key-by-key row construction preserved.
- **`tests/unit/test_export.py`** — two new regression tests in `TestRagCorpus`:
  1. `test_rag_corpus_reads_chunk_text_from_storage_uri`: seeds a chunk WITH
     `storage_uri`, patches `get_object` to return known bytes, asserts the
     written Parquet row `text` == decoded known text (non-empty).
  2. `test_rag_corpus_storage_uri_none_degrades_to_empty`: pre-fix chunk with
     `storage_uri=None`, asserts `text == ""` and `get_object` not called.

## Design decisions

- Reused `uri_to_key` from `pipeline/utils.py` — same helper the QA path uses,
  no new util invented.
- `try/except` with explicit fallback reassignment (SIM105 noqa) rather than
  `contextlib.suppress` because the fallback assignment requires the except branch.
- No new dependency, no schema change — `chunk.storage_uri` was already
  populated by the Finding-1 fix in this same quick task (260713-1yf).

## Verification

- `uv run ruff check src/` → clean.
- `uv run pytest tests/unit/test_export.py -m "not browser" -q` → 15 passed.
- `uv run pytest tests/unit -m "not browser" -q` → **549 passed, 1 xfailed, 39 xpassed**.
- No other export functions (finetune, pretrain, contamination gate) changed.
