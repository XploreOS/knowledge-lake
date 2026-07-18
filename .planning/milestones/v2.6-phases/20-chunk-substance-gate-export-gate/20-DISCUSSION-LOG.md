# Phase 20: Chunk Substance Gate + Export Gate - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-16
**Phase:** 20-Chunk Substance Gate + Export Gate
**Mode:** --auto (fully autonomous)
**Areas discussed:** Substance gate wiring, FineWebQualityFilter chunk settings, Export gate mechanism, Report/enforce mode toggle, Must-not-reject fixture design, Filter config versioning

---

## Substance Gate Wiring

| Option | Description | Selected |
|--------|-------------|----------|
| Inside `chunk()` post-generation filter | Gate runs in the chunk function itself, automatic parity across Dagster and CLI | [auto] ✓ |
| Separate Dagster asset between chunk and embed | New asset in the DAG, requires CLI-side wiring separately | |
| In `chunk_document` Dagster wrapper | Gate in the Dagster asset, requires separate CLI wiring in `process_crawled` | |

**Selected:** Inside `chunk()` function, post-generation filter (recommended default)
**Notes:** Mirrors Phase 19's section classifier pattern. Both paths call `chunk()`, so parity is automatic.

---

## FineWebQualityFilter Chunk Settings

| Option | Description | Selected |
|--------|-------------|----------|
| Separate `ChunkQualitySettings` | New Pydantic model in settings hierarchy with chunk-appropriate thresholds | [auto] ✓ |
| Reuse `CurateSettings` with overrides | Pass override params to FineWebQualityFilter at call site | |
| Hardcode chunk thresholds | Fixed values in the predicate wrapper, no settings exposure | |

**Selected:** Separate `ChunkQualitySettings` in settings (recommended default)
**Notes:** Parallels existing `CurateSettings` pattern. Different text distribution in chunks vs documents requires distinct thresholds.

---

## Export Gate Mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Filter on chunk `metadata_.substance_passed` | Chunks carry quality flag; export reads it directly | [auto] ✓ |
| Join against rejection records table | Export queries Postgres for rejection status per chunk | |
| Separate export-time re-evaluation | Re-run predicates during export | |

**Selected:** Filter on chunk metadata `substance_passed` flag (recommended default)
**Notes:** Simpler than Postgres join, follows metadata-carry pattern used throughout the pipeline. Pre-v2.6 chunks default to `True` (backward compatible).

---

## Report vs Enforce Mode Toggle

| Option | Description | Selected |
|--------|-------------|----------|
| Settings field `gate_mode` | Pydantic field with env var override, follows project pattern | [auto] ✓ |
| Per-invocation CLI flag | `--report-only` flag on `klake process` | |
| Environment variable only | Raw env var without settings model | |

**Selected:** Settings field `settings.chunk_quality.gate_mode` (recommended default)
**Notes:** Consistent with project's nested settings pattern and `KLAKE_*` env var convention.

---

## Must-Not-Reject Fixture Design

| Option | Description | Selected |
|--------|-------------|----------|
| YAML file with labeled chunks | Human-readable, editable by domain experts | [auto] ✓ |
| Inline pytest fixtures | Fixtures embedded in test code | |
| JSON file | Machine-readable but less human-friendly | |

**Selected:** YAML file in `tests/fixtures/must_not_reject.yaml` (recommended default)
**Notes:** YAML keeps fixtures readable and editable by non-developers (domain experts). Parametrized pytest test loads and validates.

---

## Filter Config Versioning

| Option | Description | Selected |
|--------|-------------|----------|
| Reuse `_curation_cache_key` pattern | `filter_config_version` field in settings, sha256 cache key | [auto] ✓ |
| Git-hash-based versioning | Derive version from code changes automatically | |
| Manual version bumping only | No cache invalidation, manual re-processing | |

**Selected:** Reuse same pattern with `chunk_quality.filter_config_version` (recommended default)
**Notes:** Proven pattern from `curate.py:80`. Config change → cache miss → re-processing on next run.

---

## Claude's Discretion

- Exact threshold values in `ChunkQualitySettings`
- FineWebQualityFilter parameter tuning for chunk scope
- YAML fixture content (specific clinical text samples)
- Field naming conventions in `ChunkQualitySettings`
- Cache check implementation details in the Dagster asset
- Eval dataset version format
- FineWebQualityFilter wrapper predicate internals

## Deferred Ideas

None — all discussion stayed within phase scope.
