# Phase 21: Index-Time Dedup - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-16
**Phase:** 21-Index-Time Dedup
**Areas discussed:** Dedup key normalization, Point ID determinism, Ledger schema & source of truth, Dedup stage placement & wiring, Contributors & primary determination, Vector store protocol extension
**Mode:** `--auto` — all gray areas auto-selected; the recommended option was chosen for every question without prompting. No user input was collected.

---

## Dedup Key Normalization

| Option | Description | Selected |
|--------|-------------|----------|
| NFKC + whitespace collapse, no casefold (recommended) | Neutralize whitespace/Unicode-form noise only. Preserves case and punctuation — DEDUP-01 is *exact* dedup, and healthcare text has case-bearing meaning (`WBC` vs `wbc`). | ✓ |
| Reuse `_normalize_whitespace()` from `clean.py:66` | No new code, but couples the dedup key to a cosmetic cleaning function — a readability tweak would silently repartition the dedup space. | |
| Aggressive: casefold + punctuation strip + whitespace collapse | Catches more boilerplate variants, but merges semantically distinct clinical text into one point. That job belongs to MinHash in `curate.py`. | |
| Exact bytes, no normalization | Simplest, but misses duplicates differing only by trailing whitespace or Unicode form. | |

**Selected:** NFKC + whitespace collapse, no casefold → D-01, D-02, D-03, D-04
**Notes:** The audit's 653 exact duplicates are already byte-identical, so conservative normalization is sufficient to hit the target. Flagged in CONTEXT.md `<specifics>` as a judgment call worth a human glance — this is the knob to turn if case-variant boilerplate was also intended.

---

## Point ID Determinism

| Option | Description | Selected |
|--------|-------------|----------|
| `uuid5(hardcoded NAMESPACE, sha256_hexdigest)` (recommended) | Matches DEDUP-02 literally. Namespace is a frozen module constant — never from settings/env/collection, since a changing namespace orphans every prior point. | ✓ |
| Namespace derived from collection name | Would scope IDs per collection, but makes the ID scheme non-portable across a reindex and breaks DEDUP-02's idempotency-by-construction claim. | |
| uuid5 over raw normalized text (skip the sha256) | Fewer steps, but diverges from DEDUP-02's stated formulation and loses the reusable `text_sha256` ledger key. | |

**Selected:** uuid5 over the hex digest string with a hardcoded namespace → D-05, D-06, D-07, D-09
**Notes:** Replaces `_strip_prefix(chunk_id)` on the write path. `_strip_prefix` is retained for resolving pre-v2.6 points.

---

## Forward-Only vs Re-key on Reindex

| Option | Description | Selected |
|--------|-------------|----------|
| Forward-only; reindex copies verbatim (recommended) | Consistent with milestone D-2. Accepts a transitional collection holding both ID schemes, where the same text may exist under two points. | ✓ |
| Re-key existing points to uuid5 during reindex | Collapses the dual-scheme state immediately, but rewrites point identity for the existing 4,499-chunk corpus — contradicts D-2 and expands blast radius well beyond this phase. | |

**Selected:** Forward-only → D-08
**Notes:** Consequence recorded explicitly: success criterion 1 is only observable on newly processed sources. Re-key deferred to a future `reindex --rekey` mode.

---

## Ledger Schema & Source of Truth

| Option | Description | Selected |
|--------|-------------|----------|
| New `chunk_dedup_ledger` table, alias-scoped, Postgres as truth (recommended) | Follows the `VectorCollection` precedent (Postgres tracks Qdrant state independently). Unique on `(collection, text_sha256)`. | ✓ |
| Unique on `text_sha256` alone (global) | Simpler key, but a wiped/recreated collection would be starved of points by stale ledger rows claiming the text is already indexed. | |
| Reuse the `artifacts` table with a new artifact type | No migration, but conflates a dedup index with lineage nodes and muddies WR-05's per-document artifact guarantee. | |
| Qdrant itself as the dedup index (scroll/filter by text hash) | No new table, but O(n) lookup, no transactional guarantee, and makes contributors unreconstructable if a collection is lost. | |

**Selected:** New alias-scoped ledger table, Postgres as source of truth → D-10, D-11, D-12, D-13, D-14
**Notes:** Atomic `ON CONFLICT DO NOTHING` upsert chosen over check-then-insert so concurrent Dagster runs can't both claim "first". Ledger row commits before the Qdrant upsert, mirroring the existing ORDERING INVARIANT in `index.py`.

---

## Dedup Stage Placement & Wiring

| Option | Description | Selected |
|--------|-------------|----------|
| New `pipeline/dedup.py` stage between chunk and embed (recommended) | Matches the roadmap's "dedup stage between chunk and embed". Runs after Phase 20's in-`chunk()` substance gate by construction, satisfying L3-before-L4. | ✓ |
| Inside `chunk()`, like Phase 20's substance gate | Would give free CLI/Dagster parity, but contradicts the roadmap's stage placement and entangles vector-level dedup with artifact generation. | |
| Inside `embed()` | Convenient interception point, but `embed()` is contractually stateless ("No registry writes in this stage") — a ledger write breaks that contract. | |

**Selected:** Separate stage module → D-15, D-16, D-17, D-19, D-20
**Notes:** Accepted cost — two call sites (`process.py:111` and a new Dagster asset) instead of Phase 20's single shared function. Mitigated by an explicit parity test (D-18) asserting identical point IDs and ledger state across both paths.

---

## Contributors & Primary Determination

| Option | Description | Selected |
|--------|-------------|----------|
| First ledger writer is primary, never reassigned; payload cap 50 + exact count (recommended) | Deterministic under concurrency via the atomic upsert. Stable payload keeps reindex idempotent. Ledger holds all contributors unbounded. | ✓ |
| Recompute primary on every contribution (true earliest `created_at`) | Strictly honors "earliest wins", but clock skew or backfill could reassign primary and churn the payload of an already-stable point. | |
| Mirror all contributors to the payload, uncapped | Simpler, but boilerplate present in every source grows an unbounded payload on exactly the hottest points. | |

**Selected:** First-writer primary, immutable; capped payload mirror → D-21, D-22, D-23, D-24
**Notes:** Primary-derived payload reuses `_resolve_document_payload_fields()` unchanged, which is why DEDUP-03's "PAYLOAD-01/02 filters remain functional" comes nearly free. Duplicate hits use `set_payload` with only `{contributors, contributor_count}` — never a full overwrite. Self-healing path added: a ledger row whose Qdrant point is gone demotes the chunk back to the embed+upsert path. The 50-cap is flagged in CONTEXT.md as an unresearched round number.

---

## Vector Store Protocol Extension

| Option | Description | Selected |
|--------|-------------|----------|
| Add one method: `set_payload(...) -> bool` (recommended) | Minimum viable extension. Returning existence powers the self-healing drift check, since Qdrant's native `set_payload` silently no-ops on a missing ID. | ✓ |
| Add `set_payload` + `retrieve` + `delete` + `scroll` | More flexible, but every protocol method is a tax on future vector-store plugins — the framework's tool-agnostic constraint argues for the minimum. | |
| Avoid the protocol change: re-upsert the full point | No protocol change, but upsert requires a vector — forcing a re-embed and defeating the entire cost saving DEDUP-01 exists to capture. | |

**Selected:** Single `set_payload` method returning existence → D-25, D-26

---

## Claude's Discretion

Auto-mode: every decision was Claude's. The following were additionally left open for planning/execution rather than fixed in CONTEXT.md:

- The concrete `KLAKE_DEDUP_NAMESPACE` UUID value
- The exact contributors payload cap (50 is a starting point; may become a `DedupSettings` field)
- Whether `DedupSettings` warrants its own Pydantic model or the knobs live inline
- `dedup_chunks()` return-dict key names
- Ledger column sizing/nullability details
- The Dagster asset's exact dict passthrough shape
- Structured-log event field names
- Whether `set_payload`'s existence check uses `retrieve` or Qdrant's conditional update primitives

## Deferred Ideas

- **Retroactive dedup of the existing 4,499-chunk corpus** — forward-only per milestone D-2; reprocess from the immutable raw zone remains possible later
- **Re-keying pre-v2.6 points to uuid5** — natural home is a future `reindex --rekey` mode
- **Near-duplicate / semantic dedup at index time** — DEDUP-01 is exact dedup; MinHash near-dup already exists in the pretrain `curate` path
- **Tree-index dedup** — `tree_index.py` has its own duplication characteristics; DEDUP-01..03 name the chunk/embed/index path only
- **Rebuild-payload-from-ledger repair command** — enabled by the ledger being source of truth; v2.7 operability candidate
