---
phase: 10-hybrid-retrieval
plan: "03"
subsystem: sparse-embedding-dependency
status: partial
tags: [fastembed, bm25, sparse-vectors, dependency, checkpoint]
dependency_graph:
  requires: []
  provides: [fastembed-cpu-installed]
  affects: [10-05-sparse-embedder, 10-07-reembedding]
tech_stack:
  added: [fastembed==0.8.0, onnxruntime==1.27.0, py-rust-stemmers==0.1.8, mmh3==5.2.1]
  patterns: [cpu-only-onnx-embedding]
key_files:
  modified: [pyproject.toml, uv.lock]
decisions:
  - "fastembed>=0.8,<0.9 pinned adjacent to qdrant-client==1.18.0 per D-01"
  - "fastembed==0.8.0 resolves to onnxruntime-only (CPU); torch/nvidia packages are pre-existing from sentence-transformers, not introduced by fastembed"
metrics:
  duration: "~1m"
  completed_date: "2026-07-10"
  tasks_completed: 1
  tasks_total: 2
  files_modified: 2
requirements_satisfied: []
---

# Phase 10 Plan 03: fastembed CPU Dependency Install Summary

## One-liner

Added `fastembed>=0.8,<0.9` (qdrant-client's CPU BM25 ONNX extra) to pyproject.toml; gated behind human-verify checkpoint confirming Qdrant/bm25 model loads CPU-only.

## What Was Built

- `fastembed>=0.8,<0.9` added to `[project].dependencies` in `pyproject.toml` adjacent to `qdrant-client==1.18.0` (per D-01)
- `uv` resolved `fastembed==0.8.0` with its minimal deps: `onnxruntime`, `py-rust-stemmers`, `mmh3`, `flatbuffers`
- No GPU/CUDA wheels were introduced by fastembed — it uses CPU onnxruntime only
- `uv run python -c "import fastembed"` exits 0; version `0.8.0` confirmed

## Tasks

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | Add fastembed>=0.8,<0.9 to pyproject and install CPU-only | DONE | 35982b3 |
| 2 | Checkpoint: fastembed CPU install + Qdrant/bm25 model download | AWAITING HUMAN | — |

## Deviations from Plan

None — plan executed exactly as written.

## Key Note: torch/nvidia Packages

`uv pip list` shows torch==2.12.1 and nvidia-* packages — these are **pre-existing** from `sentence-transformers==5.6.0` (which declares `torch>=1.11.0` as a direct dep). `fastembed` itself only requires `onnxruntime` (CPU). The checkpoint verification command below accounts for this by checking `fastembed`'s specific behavior, not the presence/absence of torch in the environment.

## Checkpoint State

**Status:** AWAITING human verification of Qdrant/bm25 model first-use download.

**Verification commands to run:**

```bash
# 1. Load SparseTextEmbedding and embed a test string
uv run python -c "
from fastembed import SparseTextEmbedding
m = SparseTextEmbedding(model_name='Qdrant/bm25')
e = next(iter(m.embed(['administrative safeguards for protected health information'])))
print('indices', len(e.indices), 'values', len(e.values))
"

# 2. Confirm fastembed itself does NOT import torch (onnxruntime only)
uv run python -c "
import importlib.util
print('torch via fastembed:', importlib.util.find_spec('torch'))
from fastembed.sparse.bm25 import Bm25
import sys
torch_loaded = 'torch' in sys.modules
print('torch in sys.modules after fastembed import:', torch_loaded)
"

# 3. Confirm model cached after first run
ls ~/.cache/fastembed/ 2>/dev/null || ls ~/.cache/huggingface/ 2>/dev/null
```

**Resume signal:** Type "approved" if Qdrant/bm25 loads with non-zero indices/values and fastembed itself does not load torch. On failure, describe issue to trigger rank_bm25 fallback discussion.

## Self-Check: PASSED

- [x] `pyproject.toml` contains `fastembed>=0.8,<0.9` at line 20
- [x] `uv run python -c "import fastembed; print(fastembed.__version__)"` → `0.8.0`
- [x] `uv.lock` updated by uv
- [x] Commit `35982b3` exists: `chore(10-03): add fastembed>=0.8,<0.9 CPU dependency (RETR-01, D-01)`
- [x] No fastembed-gpu or GPU-specific fastembed wheel in resolved environment
