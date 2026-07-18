# Phase 21: Index-Time Dedup - Context

**Gathered:** 2026-07-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Duplicate chunk text is embedded and indexed exactly once, corpus-wide, while per-document chunk artifacts and their lineage stay intact (WR-05 preserved). After this phase, a dedup stage sits between chunk and embed: it resolves each chunk's text to a deterministic point ID via `uuid5(NAMESPACE, sha256(normalized_text))`, consults a Postgres dedup ledger, and routes first-seen text to embed+upsert while routing already-seen text to a payload-only contributor append. The single surviving Qdrant point carries the primary source's metadata plus an additive `contributors[]` list, and all existing PAYLOAD-01/02 filters keep working.

**Requirements:** DEDUP-01, DEDUP-02, DEDUP-03

**Explicitly NOT in this phase:** chunk-artifact deduplication (chunk artifacts stay per-document — that IS the WR-05 guarantee), retroactive dedup of the existing 4,499-chunk corpus (forward-only per milestone D-2), near-duplicate/MinHash/semantic dedup (corpus-wide MinHash already exists in the pretrain `curate` path — this phase is exact dedup only, per DEDUP-01), and tree-index dedup.

</domain>

<decisions>
## Implementation Decisions

*Auto-mode: every decision below is the recommended default, selected without prompting. Review before planning.*

### Dedup Key Normalization (DEDUP-01)
- **D-01:** A new pure function `normalize_for_dedup(text: str) -> str` lives in the new `pipeline/dedup.py` module. It applies, in order: Unicode NFKC normalization, collapse of every whitespace run (including newlines/tabs) to a single space, then strip. Nothing else.
- **D-02:** **No casefolding, no punctuation stripping, no stopword removal.** DEDUP-01 is *exact* dedup — the normalizer exists only to neutralize whitespace/Unicode-form noise, not to merge semantically similar text. This is deliberate: healthcare text where case carries meaning (`WBC` vs `wbc`, drug trade names) must never be collapsed into one point. Aggressive normalization belongs to the MinHash path in `curate.py`, not here.
- **D-03:** `_normalize_whitespace()` in `clean.py:66` is NOT reused. It is line-oriented (preserves single newlines, collapses 3+ blank lines to 2) and serves a different contract — cleaned-text readability. Coupling the dedup key to it would make a cosmetic cleaning tweak silently repartition the dedup space. The two functions stay independent by design; note this rationale in the code so a future reader doesn't "DRY" them together.
- **D-04:** The dedup key is `sha256(normalize_for_dedup(text).encode("utf-8")).hexdigest()`, referred to as `text_sha256` throughout. It is computed from the chunk's `text` field only — never from section_path, page, or any per-document field (including those would defeat cross-document dedup).

### Point ID Determinism (DEDUP-02)
- **D-05:** `KLAKE_DEDUP_NAMESPACE` is a module-level frozen `uuid.UUID` constant in `pipeline/dedup.py`, generated once at implementation time and hardcoded. It is never derived from settings, env, or collection name — a changing namespace would silently orphan every prior point.
- **D-06:** Point ID = `uuid5(KLAKE_DEDUP_NAMESPACE, text_sha256_hexdigest)` — the uuid5 name input is the 64-char hex digest **string**, matching DEDUP-02's literal formulation. Function: `point_id_for_text(text) -> str` returning `str(uuid5(...))`, the bare-UUID form Qdrant requires.
- **D-07:** This **replaces** `_strip_prefix(chunk_id)` as the point-ID source for newly indexed chunks (`index.py:_strip_prefix`, currently the only ID scheme). `_strip_prefix` stays in the module — it is still needed to read/resolve pre-v2.6 points — but is no longer called on the write path for dense chunk points.
- **D-08:** Forward-only (milestone D-2). Pre-v2.6 points keep their chunk-ID-derived IDs; no backfill, no migration of existing Qdrant points. A re-index (`reindex_collection`) copies points verbatim and does not re-key them. Consequence, accepted: for a transitional period a collection holds both ID schemes, and an old-scheme point plus a new-scheme point may carry the same text. Planner should note this in the reindex docstring rather than attempt a re-key.
- **D-09:** The payload `qdrant_id` field carries the new uuid5 point ID (it already exists as the "bare UUID for Qdrant cross-ref" field, `index.py`), keeping the payload self-describing.

### Ledger Schema and Source of Truth (DEDUP-01)
- **D-10:** New SQLAlchemy model `ChunkDedupLedger` (`__tablename__ = "chunk_dedup_ledger"`) in `registry/models.py`, following the `VectorCollection` model's shape (prefixed-UUID `id` PK, `created_at` with `server_default=func.now()`). New Alembic migration `0011_chunk_dedup_ledger.py` — next in sequence after `0010_sources_domain_column.py`.
- **D-11:** Columns: `id` (String(64) PK, prefixed UUIDv7), `collection` (String(128), the **alias** name), `text_sha256` (String(64)), `point_id` (String(64), the uuid5), `primary_chunk_id` (String(64)), `primary_parsed_artifact_id` (String(64)), `primary_source_id` (String(64), nullable), `primary_created_at` (DateTime tz), `contributors` (JSONB, default `[]`), `contributor_count` (Integer, default 1), `created_at`, `updated_at`.
- **D-12:** Unique constraint on **`(collection, text_sha256)`** — not on `text_sha256` alone. Ledger rows are scoped per alias so that wiping/recreating a collection, or running a second collection, cannot leave the new collection starved of points because a stale ledger row claims the text is "already indexed". Index on `(collection, text_sha256)` gives the O(1) lookup DEDUP-01 requires.
- **D-13:** **The Postgres ledger is the source of truth for dedup and contributors. The Qdrant payload is a mirror**, rebuildable from the ledger. This follows the project's existing precedent (`VectorCollection` tracks alias→physical mapping in Postgres "independent of Qdrant's own alias listing").
- **D-14:** Ledger insert uses an atomic upsert (`INSERT ... ON CONFLICT (collection, text_sha256) DO NOTHING` then re-select) rather than check-then-insert, so two concurrent Dagster runs indexing the same boilerplate cannot both believe they are first. The row is committed **before** the Qdrant upsert, mirroring the ORDERING INVARIANT already documented in `index.py` for `register_vector_collection` — a durable ledger row with a missing point is self-healing (D-24); a point with no ledger row is not.

### Dedup Stage Placement and Wiring (DEDUP-01)
- **D-15:** New module `src/knowledge_lake/pipeline/dedup.py` exposing `dedup_chunks(chunks, *, collection, settings=None) -> dict` returning `{"new": [...], "duplicates": [...], "stats": {...}}`. Each chunk dict is annotated with `text_sha256` and `point_id` before being routed. Chunk artifacts are untouched — the registry still gets both per-document chunk rows (WR-05).
- **D-16:** Dedup does **not** go inside `chunk()` (unlike Phase 20's substance gate, D-01) and does **not** go inside `embed()`. `embed()` is contractually stateless with "no registry writes in this stage" — a ledger write there would break that contract. `chunk()` is the wrong place because the roadmap specifies a stage *between* chunk and embed, and because dedup must run **after** the Phase 20 substance gate (roadmap: "L3 must precede L4 — dedup before filtering promotes garbage via IDF inversion"). Since Phase 20's gate runs inside `chunk()`, placing dedup after `chunk()` returns satisfies that ordering by construction.
- **D-17:** Two call sites, wired explicitly (accepted cost of a separate stage — parity is enforced by test, not by shared function):
  - `pipeline/process.py:111` — insert `dedup_chunks()` between `chunk()` and `embed(chunks_list)`; embed only `result["new"]`.
  - `dagster_defs/assets.py` — new asset `dedup_chunks` between `chunk_document` (line ~349) and `embed_chunks` (line 536), passing through the established dict-shape convention (`parsed_artifact_id`, `source_id`, `collection`, plus `new`/`duplicates`).
- **D-18:** A parity test asserts the CLI and Dagster paths produce identical point IDs and identical ledger state for the same input — this is the guardrail that replaces Phase 20's shared-function parity.
- **D-19:** `index()` gains an optional `duplicate_chunks: list[dict] | None = None` kwarg. New points take the existing embed→upsert path; duplicates take a payload-only contributor append. Keeping both in `index()` means one place owns "what lands in Qdrant" and both callers pass the same shape. `embed()` signature is unchanged — it simply receives a shorter list.
- **D-20:** Conservation invariant (consistent with QUAL-05, Phase 17): assert `len(new) + len(duplicates) == len(chunks_in)` at the end of `dedup_chunks()`. Structured log `dedup.complete` with `total`, `unique`, `duplicates`, `collection`, and `embed_calls_saved`.

### Contributors and Primary Determination (DEDUP-03)
- **D-21:** Primary = **earliest `primary_created_at`**, which is by construction the first writer of the ledger row (D-14's atomic upsert makes "first writer" deterministic under concurrency). Tie-break on identical timestamps: lexicographically smallest `chunk_id`. The primary is **never reassigned** once set — a later document contributing the same text does not steal primary status even if its `created_at` is somehow earlier (clock skew, backfill). This keeps the payload stable and re-index idempotent.
- **D-22:** The point's primary-derived payload fields (`document`, `chunk_id`, `source_id`, `source_name`, `source_url`, `format`, `domain`, `tags`, `title`, `organization`, `document_type`, `keywords`, `quality_score`) are exactly what `_resolve_document_payload_fields()` already produces for the **primary's** `parsed_artifact_id` — unchanged code path, so PAYLOAD-01/02 filters (DEDUP-03's acceptance: filterable by source_id, domain, format) keep working with zero modification.
- **D-23:** New payload field `contributors: list[dict]`, each entry `{chunk_id, document, source_id, created_at}` (ISO-8601 string for `created_at` — Qdrant payloads are JSON). Plus `contributor_count: int`. The ledger holds **all** contributors unbounded; the Qdrant payload mirrors at most the **first 50** (deterministic: ordered by `created_at`, then `chunk_id`), while `contributor_count` always reports the exact total. Rationale: boilerplate appearing in all 34 sources — and far more at scale — would otherwise grow an unbounded payload on the hottest points. The primary is always contributors[0].
- **D-24:** On a duplicate hit, `index()` calls the vector store's `set_payload` with **only** `{contributors, contributor_count}` — never a full payload overwrite, which would clobber the primary's metadata. **Self-healing drift check:** if `set_payload` reports the point does not exist (ledger row present, Qdrant point gone — e.g. collection wiped, or the D-14 commit survived a failed upsert), the chunk is demoted to the `new` path (embed + full upsert) and the ledger row is repaired to point at the re-created point. This makes the ledger's authority safe rather than a footgun.

### Vector Store Protocol Extension
- **D-25:** `VectorStorePlugin` protocol (`plugins/protocols.py:212`) gains one method: `set_payload(collection: str, point_id: str, payload: dict) -> bool` — merges the given keys into an existing point's payload, returning `False` if the point does not exist. Implemented in `plugins/builtin/qdrant_store.py`. Returning existence (rather than a bare no-op) is what powers D-24; Qdrant's native `set_payload` silently no-ops on a missing ID, so the implementation must check existence (`retrieve`) before or alongside the write.
- **D-26:** This is the minimum viable protocol extension — no `retrieve`/`delete`/`scroll` added speculatively. The framework's tool-agnostic constraint means every added protocol method is a tax on future vector-store plugins; one method is defensible, four is not.

### Claude's Discretion

Claude has flexibility on: the concrete `KLAKE_DEDUP_NAMESPACE` UUID value; the exact contributors payload cap (50 is a starting point, not a researched threshold — surface it as a `DedupSettings` field if that proves cleaner); whether `DedupSettings` warrants its own Pydantic settings model or the handful of knobs live inline; the `dedup_chunks()` return-dict key names; ledger column sizing/nullability details; the Dagster asset's exact dict passthrough shape; structured-log event field names; and whether the `set_payload` existence check uses `retrieve` or Qdrant's conditional update primitives.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Scope
- `.planning/REQUIREMENTS.md` §DEDUP-01 (lines 113–117), §DEDUP-02 (lines 121–125), §DEDUP-03 (lines 129–133) — Full requirement definitions and acceptance criteria
- `.planning/ROADMAP.md` §Phase 21 (lines 142–150) — Success criteria; dependency on Phase 20 with the "L3 before L4 / IDF inversion" rationale
- `.planning/MILESTONE-CONTEXT.md` §L4 (lines 72–76), §D-2 Forward-only (lines 103–109), §D-3 Dedup at index time (lines 111–114), §Constraints (lines 124–135) — Why WR-05 produced the 653 exact duplicates by design, and why the resolution is index-time rather than chunk-time

### Prior Phase Context
- `.planning/phases/20-chunk-substance-gate-export-gate/20-CONTEXT.md` — **Hard dependency.** Substance gate runs inside `chunk()` (D-01), chunk `metadata_` annotations `substance_passed`/`rejection_reason` (D-02) that flow through dedup to index, table exemption (D-03), conservation invariant (D-04), `filter_config_version` cache keying (D-17/18)
- `.planning/phases/17-close-the-bypass-measurement/17-CONTEXT.md` — Conservation invariant infrastructure (QUAL-05), parent-scoped hash convention (CLEAN-03)
- `.planning/phases/19-section-classifier-patterns/19-CONTEXT.md` — `pipeline/quality/` pure-predicate module conventions (zero I/O, deterministic) — the model `pipeline/dedup.py`'s pure helpers should follow

### Pipeline Code (the write path this phase modifies)
- `src/knowledge_lake/pipeline/index.py` — `index()` (the function to extend with `duplicate_chunks`), `_strip_prefix()` (the ID scheme being replaced on the write path), `_resolve_document_payload_fields()` (reused unchanged for the primary), `reindex_collection()`, and the module docstring's full payload-field contract + ORDERING INVARIANT comment
- `src/knowledge_lake/pipeline/embed.py` — `embed()` (50 lines; stateless-by-contract — read the docstring before considering a ledger write here)
- `src/knowledge_lake/pipeline/chunk.py` — `chunk()` (line 263); the WR-05 hash comment at lines 314–318 is the exact constraint this phase must not violate
- `src/knowledge_lake/pipeline/process.py` — `process_crawled()`, `embed`/`index` call at lines 111–112 (CLI wiring point)
- `src/knowledge_lake/dagster_defs/assets.py` — `chunk_document` (line ~349), `embed_chunks` (line 536), `index_chunks` (line 578) — the new `dedup_chunks` asset sits between 536 and the chunk asset
- `src/knowledge_lake/pipeline/clean.py` — `_normalize_whitespace()` (line 66) — read to understand why D-03 deliberately does NOT reuse it

### Registry & Storage
- `src/knowledge_lake/registry/models.py` — `VectorCollection` (line 453) is the shape template for `ChunkDedupLedger`; `Artifact` (line 138)
- `src/knowledge_lake/registry/alembic/versions/0010_sources_domain_column.py` — latest migration; `0011_chunk_dedup_ledger.py` follows it
- `src/knowledge_lake/registry/repo.py` — `get_artifact_by_hash()` (content-addressed lookup pattern), `register_vector_collection()`, `get_domain_for_source()`

### Plugin Protocol
- `src/knowledge_lake/plugins/protocols.py` — `VectorStorePlugin` (line 212), `VectorPoint` (line 83), `Hit` (line 115)
- `src/knowledge_lake/plugins/builtin/qdrant_store.py` — `upsert()` (line 520), `refresh_all_points_payload()` (line 306) — closest existing analog to the new `set_payload`

### Downstream Consumers (must keep working)
- `src/knowledge_lake/pipeline/search.py` — reads `payload['chunk_id']`, `Hit.id`; PAYLOAD-01/02 filters (source_id, domain, format, tags, quality_score) are DEDUP-03's acceptance surface
- `src/knowledge_lake/pipeline/export.py` — `export_rag_corpus()`; Phase 20 adds the `substance_passed` chunk-level gate here

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `_resolve_document_payload_fields()` (`index.py`) — Already resolves all 11 primary-derived payload fields per parsed_artifact_id with an internal per-document cache. Reused **verbatim** for the primary's payload; this is why DEDUP-03's "existing PAYLOAD-01/02 filters remain functional" is nearly free.
- `VectorCollection` model + `register_vector_collection()` — Direct shape template for `ChunkDedupLedger`: prefixed-UUID PK, alias-scoped, `server_default=func.now()`, Postgres-as-truth-independent-of-Qdrant.
- `refresh_all_points_payload()` (`qdrant_store.py:306`) — Existing payload-mutation-without-re-embedding machinery; the closest analog for `set_payload` and a possible future rebuild-payload-from-ledger repair path.
- The ORDERING INVARIANT comment in `index()` — An explicit, load-bearing precedent for "commit the Postgres row before the Qdrant write." D-14 follows it deliberately; the existing comment even warns future refactors not to reorder.
- `get_artifact_by_hash()` (`repo.py`) — Established content-addressed lookup pattern; the ledger lookup mirrors its ergonomics.

### Established Patterns
- **Point IDs must be bare UUIDs or unsigned ints** — Qdrant's constraint is the reason `_strip_prefix` exists; uuid5 satisfies it natively and needs no stripping.
- **Registry ID prefixes** — `chk_<uuidv7>`, `art_<uuidv7>`; the ledger's `id` follows (`VectorCollection` uses `art_`).
- **Dagster assets pass dicts** with `parsed_artifact_id`, `source_id`, `chunks`, `collection` keys and destructure them; the new asset must preserve this convention.
- **`metadata_` dict carries per-chunk annotations** (`text`, `section_path`, `page`, `is_table`, `oversized`, and Phase 20's `substance_passed`) — dedup annotates `text_sha256`/`point_id` alongside.
- **Settings hierarchy** — nested Pydantic models with `KLAKE_*__*` env vars; `_env_file=None` override in Dagster assets.
- **Structured logging** via `structlog` with dotted stage-scoped event names (`index.upsert`, `embed.complete`) — `dedup.*` follows.
- **`collection` is always the alias**, never the physical collection — every call site passes the alias and the resolution layer handles it. The ledger's `collection` column stores the alias (D-12).

### Integration Points
- `chunk()` output → **new** `dedup_chunks()` → `embed()` (new only) → `index()` (new + duplicates). Two wirings: `process.py:111` and a new Dagster asset.
- `index()` → gains `duplicate_chunks` kwarg and the `set_payload` contributor-append branch.
- `VectorStorePlugin` protocol → +1 method (`set_payload`); `QdrantStore` implements it.
- `registry/models.py` + Alembic → `ChunkDedupLedger` and migration `0011`.
- `search.py` → unchanged code, but its filter surface is DEDUP-03's acceptance test; `contributors[]` becomes newly available to callers.
- `reindex_collection()` → copies points verbatim; must not re-key IDs (D-08). Its docstring needs the dual-ID-scheme note.

### Landmines
- **WR-05 is a designed constraint, not a bug** (`chunk.py:314–318`). The chunk-artifact hash MUST keep including `parsed_artifact_id`. Phase 21 dedups the *vector*, never the *artifact*. Success criterion 1 explicitly requires both chunk artifacts to survive.
- **`embed()` declares itself stateless** ("No registry writes in this stage") — respect it (D-16).
- **Qdrant `set_payload` silently no-ops on a missing point ID** — a naive implementation would drop a vector with no error. D-25's existence-returning signature exists precisely to make D-24's self-healing possible.
- **Ordering vs Phase 20** — dedup must run after the substance gate, or garbage gets promoted via IDF inversion. Phase 20's gate lives inside `chunk()`, so "after `chunk()` returns" satisfies this — but a future move of the gate would silently break the ordering. Worth an assertion or comment.

</code_context>

<specifics>
## Specific Ideas

No user-supplied specifics — this context was generated in `--auto` mode with recommended defaults throughout. Three decisions are judgment calls worth a human glance before planning:

- **D-02 (no casefolding)** — deliberately conservative. If the intent was to also catch case-variant boilerplate, this is the knob to turn. The trade-off is healthcare text where case is meaningful.
- **D-23 (50-contributor payload cap)** — an unresearched round number chosen to bound payload growth on hot boilerplate points. The ledger keeps all contributors regardless, so raising or removing the cap later is non-destructive.
- **D-08 (no re-key on reindex)** — accepts a transitional period where a collection holds both ID schemes and the same text can exist under two points. Consistent with milestone D-2 (forward-only), but it does mean success criterion 1 is only observable on newly processed sources.

</specifics>

<deferred>
## Deferred Ideas

- **Retroactive dedup of the existing 4,499-chunk corpus** — Forward-only (milestone D-2). A deliberate reprocess from the immutable raw zone remains possible later.
- **Re-keying pre-v2.6 points to the uuid5 scheme** — Would collapse the dual-ID-scheme transitional state (D-08). A `reindex --rekey` mode is the natural home; belongs to a future phase, not this one.
- **Near-duplicate / semantic dedup at index time** — DEDUP-01 is exact dedup. MinHash near-dup already exists corpus-wide in the pretrain `curate` path; extending it to the RAG index path is a separate capability.
- **Tree-index dedup** — `tree_index.py` builds a parallel structure with its own duplication characteristics. Out of scope; DEDUP-01..03 name the chunk/embed/index path only.
- **Rebuild-payload-from-ledger repair command** — The ledger being source of truth (D-13) makes a full `contributors[]` payload rebuild possible (analogous to `reindex --refresh-payload` for KL-06). Not needed to satisfy DEDUP-01..03; note as a v2.7 operability candidate.

</deferred>

---

*Phase: 21-Index-Time Dedup*
*Context gathered: 2026-07-16*
