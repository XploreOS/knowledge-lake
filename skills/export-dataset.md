---
name: export-dataset
description: >-
  Turn the curated knowledge lake into AI-ready datasets and confirm what was
  produced. Run `export` for a RAG corpus, a pretraining corpus, or a fine-tuning
  dataset, then call `stats` to verify lake contents. Use this when a user wants to
  "export the corpus", "generate a training set", or "produce a RAG dataset".
---

# Export an AI-ready dataset

This skill drives corpus export using the Knowledge Lake MCP tools. Reference only
registry tool names.

## Journey

1. **Export** — `export`
   - `kind` (required), one of:
     - `"rag-corpus"` — a retrieval corpus (Parquet) for RAG pipelines.
     - `"pretrain"` — a plain-text pretraining corpus (JSONL).
     - `"finetune"` — an instruction/fine-tuning dataset (JSONL) built from a
       named dataset.
   - `dataset_name` (optional, **required when `kind="finetune"`**): the logical
     dataset name to export.
   - Exports are written to the gold zone. `finetune` exports enforce a
     train/eval contamination guard — a contamination error means the requested
     split overlaps and must be corrected before export.

2. **Verify** — `stats`
   - Call `stats` (optionally scoped by `domain`) to confirm lake contents:
     source count, document count, artifact counts by type, and the Qdrant vector
     point count. Use this to sanity-check that the export drew from the expected
     population.

## Success

`export` produces the requested gold-zone dataset for the chosen `kind`, and
`stats` confirms the underlying lake contents that fed it.
