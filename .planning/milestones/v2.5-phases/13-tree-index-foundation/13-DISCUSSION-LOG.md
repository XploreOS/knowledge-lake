# Phase 13: Tree Index Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-13
**Phase:** 13-tree-index-foundation
**Mode:** `--auto` (all gray areas auto-resolved to the recommended option)
**Areas discussed:** Tree schema contract, PageIndex integration & deterministic construction, Dedup / content-hash key, Storage layout & artifact type, Config surface & mode gating

---

## Tree schema contract

| Option | Description | Selected |
|--------|-------------|----------|
| Dataclasses in `plugins/protocols.py` | `TreeNode`/`TreeIndex` alongside Section/ParsedDoc/Hit; shared seam contract defined first | ✓ |
| New module `plugins/tree_schema.py` | Separate schema file | |
| Inline dicts | No formal schema, pass dicts | |

**Auto-selected:** Dataclasses in `plugins/protocols.py`
**Notes:** Pitfall 4 (schema coupling) — define the shared indexer↔retriever contract before either implementation. Mirrors the existing seam convention.

---

## PageIndex integration & deterministic construction

| Option | Description | Selected |
|--------|-------------|----------|
| Deterministic from `ParsedDoc.sections`; PageIndex only in LLM mode behind IndexerPlugin | Zero-dep, zero-cost deterministic tree; pre-release dep isolated behind plugin seam | ✓ |
| PageIndex for both modes | Use PageIndex even for deterministic | |
| Vendor PageIndex now | Copy 6 files into repo immediately | |

**Auto-selected:** Deterministic from `ParsedDoc.sections`; PageIndex confined to LLM-mode builtin
**Notes:** Honors deterministic-first constraint; de-risks the `0.3.0.dev3` pre-release pin. Vendoring stays a documented fallback validated during execution.

---

## Dedup / content-hash key (TREE-02 no-op)

| Option | Description | Selected |
|--------|-------------|----------|
| `hash(parsed content_hash + mode + schema_version)` | Mode-aware no-op via `get_artifact_by_hash(..., 'tree_index')` | ✓ |
| Hash source bytes only | Ignores mode/schema | |
| Hash rendered tree JSON | Hash the output, not the inputs | |

**Auto-selected:** `hash(parsed content_hash + mode + schema_version)`
**Notes:** Mirrors `chunk.py` no-op. Including `mode` prevents a false cache hit when switching deterministic→LLM.

---

## Storage layout & artifact type

| Option | Description | Selected |
|--------|-------------|----------|
| `tree_index/{domain}/{source_id}/{hash}.json`, silver zone, type `tree_index`, parent `parsed_document` | Mirrors `_CHUNK_PREFIX` convention | ✓ |
| Under `chunks/` prefix | Reuse chunk namespace | |
| Gold zone | Store as final artifact | |

**Auto-selected:** Dedicated `tree_index/` silver-zone key, artifact type `tree_index`
**Notes:** Silver = derived artifact; lineage parent = parsed_document (same as chunk). Raw zone untouched.

---

## Config surface & mode gating

| Option | Description | Selected |
|--------|-------------|----------|
| New `TreeSettings` submodel | `mode: deterministic|llm = deterministic`, `budget_usd=5.0`, `cheap_model` alias; reuse enrich budget-check | ✓ |
| Reuse `EnrichSettings` | Share enrich's config | |
| CLI-flag only | No settings submodel | |

**Auto-selected:** New `TreeSettings` submodel mirroring `EnrichSettings`
**Notes:** Deterministic default satisfies deterministic-first; LLM mode gated by the same `LlmSpend` budget flow as `enrich.py` (never raises on budget-exceeded).

---

## Claude's Discretion

- `node_id` scheme, JSON serialization helper, and `schema_version` string format left to planner/executor, provided the D-01/D-02 schema contract stays stable.

## Deferred Ideas

- Tree schema versioning + migration (TREE-06) — v2.6+.
- PageIndex File System / corpus meta-tree (TREE-07) — v2.6+.
- Tree retrieval / traversal — Phase 14.
- RAPTOR-style bottom-up construction — v2.6+.

## Process note

- Invocation directive "use sonnet model for sub agent executors" honored:
  `model_overrides.gsd-executor: "sonnet"` set in `.planning/config.json`.
