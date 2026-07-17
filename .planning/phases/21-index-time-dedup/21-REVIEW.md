---
status: issues_found
files_reviewed: 20
findings:
  critical: 0
  warning: 1
  info: 1
  total: 2
fix_report: .planning/phases/21-index-time-dedup/21-REVIEW-FIX.md
fix_status: all_fixed
---

# Code Review: Phase 21 (index-time-dedup)

## Summary

Phase 21 adds a Postgres-backed corpus-wide exact-dedup ledger
(`chunk_dedup_ledger`, migration 0011), pure hash/point-ID primitives
(`pipeline/dedup.py`), a `VectorStorePlugin.set_payload()` protocol extension
implemented in `QdrantVectorStore`, the `dedup_chunks()` router, `index()`'s
duplicate-routing + self-heal branch, and CLI (`process_crawled`) / Dagster
(`dedup_chunks` asset) call-site wiring. The core mechanics are sound: the
atomic `INSERT ... ON CONFLICT (collection, text_sha256) DO NOTHING ...
RETURNING` claim in `claim_dedup_ledger_entry` is race-safe under Postgres's
documented unique-constraint-insert blocking semantics; the ORDERING
INVARIANT (ledger commit before Qdrant write) is respected consistently in
both the new-primary and duplicate/self-heal paths; the conservation
invariant in `dedup_chunks()` is asserted unconditionally; the CLI/Dagster
parity and reindex-survival integration tests genuinely exercise the live
stack rather than mocking around it; and `set_payload()`'s 404-as-`False`
handling is correctly the sole existence check driving self-heal, per the
documented D-24/D-26 design.

One real gap survived: reprocessing a document that has already been fully
indexed (a legitimate, undocumented-against scenario — manual
re-materialization, an operator re-running `process_crawled`/a Dagster job
for an already-parsed document, etc.) causes the ledger to record that
document's own chunk as a *second, distinct* contributor of itself, because
`append_dedup_contributor` has no guard against re-appending an entry whose
`chunk_id` already exists in `contributors[]`. `chunk()` is itself
content-hash idempotent (same `parsed_artifact_id` + text → the same
`chunk_id` is reused across runs), which is exactly what makes this
reachable: the second run's `dedup_chunks()` call correctly loses the ledger
claim race (same `text_sha256` already claimed) and routes the chunk to
`duplicates`, and `index()` then unconditionally calls
`append_dedup_contributor` for it — including when `dup_chunk["chunk_id"] ==
ledger_row.primary_chunk_id`, i.e. the "contributor" being appended *is* the
existing primary. No test in this phase's suite (unit or integration)
exercises this path — every test that seeds a duplicate uses a
`chunk_id` distinct from the pre-seeded primary's.

A second, minor finding: `registry/models.py`'s `ChunkDedupLedger
.primary_created_at` docstring states the field is "Never reassigned once
set (D-21)," but `index()`'s self-heal branch does reassign it (along with
`primary_chunk_id`/`primary_parsed_artifact_id`/`primary_source_id`) per the
separately-documented D-24 exception. This is an intentional, CONTEXT.md
-documented design tension, not a functional bug, but the model docstring
doesn't mention the D-24 carve-out and reads as an absolute guarantee that
isn't quite true.

## Findings

### WR-01: Reprocessing an already-indexed document double-counts its own chunk as a new ledger contributor
**File:** src/knowledge_lake/pipeline/index.py:290-297 (also src/knowledge_lake/registry/repo.py:1246-1274)
**Severity:** Warning

`index()`'s duplicate-routing loop calls
`registry_repo.append_dedup_contributor(session, ledger_row, chunk_id=dup_chunk["chunk_id"], ...)`
unconditionally for every chunk in `duplicate_chunks`, and
`append_dedup_contributor` (repo.py:1246) appends to `contributors[]` and
increments `contributor_count` with no check for whether an entry with the
same `chunk_id` (or even the same `document`) is already present.

**Failure scenario:** A document `doc_1` is ingested and indexed once via
`process_crawled()` or the Dagster chain: `chunk()` creates chunk artifact
`chk_1` (content-hash-derived ID, `pipeline/chunk.py:502-523`), `dedup_chunks()`
claims it as the ledger primary (`contributor_count == 1`,
`contributors == [{"chunk_id": "chk_1", "document": "doc_1", ...}]`), and
`index()` upserts it as a fresh Qdrant point. Later, the SAME document is
reprocessed — e.g. an operator manually re-materializes the Dagster asset
chain for `doc_1`, or re-invokes `process_crawled()` in a way that bypasses
its own "no parsed child yet" filter (e.g. a direct per-document
reprocess/backfill entry point). `chunk()` is content-hash idempotent, so it
returns the SAME `chk_1` artifact id (`get_artifact_by_hash` no-op branch).
`dedup_chunks()`'s ledger claim for the same `text_sha256` now loses the
`ON CONFLICT DO NOTHING` race (row already exists) and correctly routes
`chk_1` to `duplicates`. `index()` then calls `append_dedup_contributor` with
`chunk_id="chk_1"`, `document="doc_1"` — identical to the entry already at
`contributors[0]`. The ledger row now has `contributor_count == 2` and
`contributors == [{"chunk_id": "chk_1", "document": "doc_1", ...}, {"chunk_id": "chk_1", "document": "doc_1", ...}]`
— the SAME document/chunk counted twice, purely from a re-run, with no new
contributing document involved. `_build_capped_contributors_mirror`
(index.py:392-419) then also surfaces this duplicate entry in the Qdrant
payload mirror (as a "remaining" contributor distinct from
`contributors[0]`), so the corruption is visible to search-time consumers
of `contributors`/`contributor_count` too. This violates the module's own
stated goal of "preserving full per-document contributor lineage (WR-05)"
(`pipeline/dedup.py` module docstring) — the lineage now claims 2 documents
contributed this text when only 1 did.

No existing test (unit or integration) exercises this: every duplicate
fixture in `tests/unit/test_index_dedup.py::TestIndexDuplicateRouting`
uses a `dup_chunk["chunk_id"]` distinct from the pre-seeded primary's
(e.g. `"chk_dup"` vs `"chk_primary"`), and
`test_reprocessing_identical_document_is_idempotent` in
`tests/unit/test_index_dedup.py` only asserts `dedup_chunks()`'s own
routing output on a rerun — it never carries the result into `index()` to
check what happens to the ledger's `contributors[]`/`contributor_count`
afterward.

**Suggested fix:** In `append_dedup_contributor` (or its caller in
`index()`), skip the append (and treat it as a no-op, not an error) when an
entry with the same `chunk_id` already exists in `ledger_row.contributors`
— mirroring the idempotency guarantee `chunk()` already provides one layer
up. Alternatively, guard in `index()`'s duplicate loop: if
`dup_chunk["chunk_id"] == ledger_row.primary_chunk_id`, skip both the
contributor append and the `set_payload` call entirely (the point already
carries correct payload from the original run).

### IN-01: `primary_created_at` docstring's "never reassigned" claim doesn't mention the D-24 self-heal exception
**File:** src/knowledge_lake/registry/models.py:533-537
**Severity:** Info

`ChunkDedupLedger.primary_created_at`'s docstring reads: "Never reassigned
once set (D-21) — the first successful claimant is permanent." However,
`index()`'s self-heal branch (`pipeline/index.py:346-349`) does reassign it
(along with `primary_chunk_id`, `primary_parsed_artifact_id`,
`primary_source_id`) when a duplicate's Qdrant point has vanished
out-of-band. This is an intentional, CONTEXT.md-documented exception (D-24:
"the ledger row is repaired to point at the re-created point") scoped to
the self-heal path only — normal duplicate contribution never reassigns
these fields — so this is not a functional bug. It's worth tightening the
model docstring to note the D-24 carve-out so a future reader of
`registry/models.py` alone (without cross-referencing `index.py`'s inline
D-24 comments) doesn't take the "never reassigned" claim as an absolute
invariant enforceable elsewhere (e.g. in an audit/lineage report that
assumes `primary_created_at` is immutable).

**Suggested fix:** Append one clause to the docstring, e.g.: "...permanent,
except during D-24 self-heal repair, which reassigns all `primary_*` fields
when the point was lost and re-created under the same `point_id`."
