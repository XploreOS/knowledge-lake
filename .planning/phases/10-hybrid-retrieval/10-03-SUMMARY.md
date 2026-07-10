---
phase: 10-hybrid-retrieval
plan: "03"
subsystem: sparse-embedding-dependency
status: complete
tags: [fastembed, bm25, sparse-vectors, dependency, checkpoint]
dependency_graph:
  requires: []
  provides: [fastembed-cpu-installed, qdrant-bm25-model-verified]
  affects: [10-05-sparse-embedder, 10-07-reembedding]
tech_stack:
  added: [fastembed==0.8.0, onnxruntime==1.27.0, py-rust-stemmers==0.1.8, mmh3==5.2.1]
  patterns: [cpu-only-onnx-embedding]
key_files:
  modified: [pyproject.toml, uv.lock]
decisions:
  - "fastembed>=0.8,<0.9 pinned adjacent to qdrant-client==1.18.0 per D-01"
  - "fastembed==0.8.0 resolves to onnxruntime-only (CPU); torch/nvidia packages are pre-existing from sentence-transformers, not introduced by fastembed"
  - "Qdrant/bm25 model verified: non-zero sparse embeddings produced, fastembed does not load torch at import time"
  - "Model cache location varies by platform/version; embed success in step 1 confirms download occurred"
metrics:
  duration: "~3m"
  completed_date: "2026-07-10"
  tasks_completed: 2
  tasks_total: 2
  files_modified: 2
requirements_satisfied: [RETR-01]
---

# Phase 10 Plan 03: fastembed CPU Dependency Install Summary

## One-liner

Added `fastembed>=0.8,<0.9` (qdrant-client's CPU BM25 ONNX extra) to pyproject.toml and human-verified that Qdrant/bm25 loads, embeds CPU-only, and does not pull torch into the process.

## What Was Built

- `fastembed>=0.8,<0.9` added to `[project].dependencies` in `pyproject.toml` adjacent to `qdrant-client==1.18.0` (per D-01)
- `uv` resolved `fastembed==0.8.0` with its minimal deps: `onnxruntime`, `py-rust-stemmers`, `mmh3`, `flatbuffers`
- No GPU/CUDA wheels were introduced by fastembed — it uses CPU onnxruntime only
- `uv run python -c "import fastembed"` exits 0; version `0.8.0` confirmed
- Human verified: `SparseTextEmbedding('Qdrant/bm25')` produces non-zero sparse embeddings and does not load torch at import time (RESEARCH Open Question 2 resolved: proceed with fastembed, no rank_bm25 fallback needed)

## Tasks

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | Add fastembed>=0.8,<0.9 to pyproject and install CPU-only | DONE | 35982b3 |
| 2 | Checkpoint: fastembed CPU install + Qdrant/bm25 model download | APPROVED | — |

## Deviations from Plan

None — plan executed exactly as written.

## Key Note: torch/nvidia Packages

`uv pip list` shows torch==2.12.1 and nvidia-* packages — these are **pre-existing** from `sentence-transformers==5.6.0` (which declares `torch>=1.11.0` as a direct dep). `fastembed` itself only requires `onnxruntime` (CPU). Human verification confirmed fastembed does not load torch at import time (`'torch' in sys.modules` is `False` after `from fastembed import SparseTextEmbedding`).

## Checkpoint Outcome

**Status:** APPROVED by human on 2026-07-10.

**Verification results:**
- Step 1: `SparseTextEmbedding('Qdrant/bm25').embed(...)` produced non-zero indices and values — PASSED
- Step 2: fastembed does not load torch at import time — PASSED
- Step 3: Cache directory not found at expected path (~/.cache/fastembed or ~/.cache/huggingface/hub) — non-issue; embed call in step 1 succeeded, confirming model was downloaded and cached at a platform-specific path

**RESEARCH Open Question 2 resolved:** Proceed with `fastembed` `Qdrant/bm25` — no fallback to `rank_bm25` needed. Plans 10-05 (sparse_embedder) and 10-07 (re-embedding migration) are unblocked.

## Self-Check: PASSED

- [x] `pyproject.toml` contains `fastembed>=0.8,<0.9` at line 20
- [x] `uv run python -c "import fastembed; print(fastembed.__version__)"` → `0.8.0`
- [x] `uv.lock` updated by uv
- [x] Commit `35982b3` exists: `chore(10-03): add fastembed>=0.8,<0.9 CPU dependency (RETR-01, D-01)`
- [x] No fastembed-gpu or GPU-specific fastembed wheel in resolved environment
- [x] Human checkpoint approved: Qdrant/bm25 embeds CPU-only, no torch loaded by fastembed
