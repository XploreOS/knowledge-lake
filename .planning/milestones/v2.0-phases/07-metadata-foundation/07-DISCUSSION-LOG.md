# Phase 7: Metadata Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-08
**Phase:** 7-metadata-foundation
**Areas discussed:** Field provenance, Source-metadata persistence, Payload index strategy, Filter semantics + CLI/API surface, Backward-compat contract
**Mode:** `--auto` (all areas auto-selected, recommended defaults chosen)

---

## Field Provenance

| Option | Description | Selected |
|--------|-------------|----------|
| Extend single-session join | Fetch Source row in existing `get_session()` block (D-01 pattern) | ✓ |
| Per-chunk lazy fetch | Separate query per chunk for source metadata | |
| Pre-compute at ingest time | Store payload fields in the registry at ingest | |

**Auto-selected:** Extend single-session join (recommended — mirrors existing domain/enrichment join; O(1) queries per `index()` call)
**Notes:** `source_type` IS the format field; `organization` degrades to None (no data source today).

---

## Source-Metadata Persistence (tags gap)

| Option | Description | Selected |
|--------|-------------|----------|
| Persist tags into Source.config at registration | Extend `register_source` to include tags/organization from sources.yaml | ✓ |
| Add Source columns for tags | New Alembic migration adding JSON/array columns | |
| Read tags from sources.yaml at index time | Bypass registry, read YAML directly during indexing | |

**Auto-selected:** Persist into Source.config (recommended — follows existing `domain` pattern in Pitfall 4; no migration needed; additive)
**Notes:** `register_source` (ingest.py:277) currently drops tags. Fix is to merge them into the `config` dict alongside `domain`.

---

## Payload Index Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Idempotent ensure_payload_indexes() on bootstrap + reindex | Create keyword indexes on all filterable fields; call from ensure_aliased_collection and reindex | ✓ |
| One-time migration script | CLI command to create indexes on existing collections | |
| Lazy index on first filter use | Check/create index when a filter kwarg is first passed | |

**Auto-selected:** Idempotent ensure_payload_indexes() (recommended — covers both fresh and reindexed collections; safe to call repeatedly; O(1) idempotent)
**Notes:** No payload indexes exist today — the existing `domain`/`document_type`/`quality_score` filters all hit unindexed scan. This phase fixes that for all fields.

---

## Filter Semantics + CLI/API Surface

| Option | Description | Selected |
|--------|-------------|----------|
| Array-contains with MatchAny for multi-tag | Single tag = MatchValue; multiple = MatchAny (OR) | ✓ |
| Array-contains-all (AND) | Chunk must have ALL given tags | |

**Auto-selected:** MatchAny/OR (recommended — more useful for exploratory search; AND is restrictive with curated source tags)
**Notes:** CLI flags mirror existing `--domain`/`--document-type` pattern. `--tag` is repeatable.

---

## Backward-Compat Contract

| Option | Description | Selected |
|--------|-------------|----------|
| Forward-only (new indexed chunks only) | Document that filters don't match pre-Phase-7 points; no forced backfill | ✓ |
| Forced backfill via enrichment re-run | Re-index all existing chunks with new payload | |

**Auto-selected:** Forward-only (recommended — consistent with research "filters only fully effective on points indexed after this phase"; no downtime risk; users can optionally reindex)

---

## Claude's Discretion

- Exact CLI flag naming (`--tag` vs `--tags`)
- API param handling (repeated `tags=` vs CSV)
- Internal organization of `ensure_payload_indexes()` (new method vs folded into existing)
- Precise ordering of `must` conditions in the filter builder

## Deferred Ideas

- Quality-score-aware ranking — QUALITY-01 (v2.1)
- Object tags / domain-scoped keys — Phase 9 (STORE-01/02/03)
- Sparse/hybrid filtering interplay — Phase 10 (RETR-01/03)
- Adding `organization:` to healthcare sources.yaml — optional data enhancement
