# Phase 21: Index-Time Dedup - Research

**Researched:** 2026-07-17
**Domain:** Postgres atomic upsert + Qdrant payload mutation + Dagster asset insertion, in an already-heavily-decided phase
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Dedup Key Normalization (DEDUP-01)**
- D-01: A new pure function `normalize_for_dedup(text: str) -> str` lives in the new `pipeline/dedup.py` module. It applies, in order: Unicode NFKC normalization, collapse of every whitespace run (including newlines/tabs) to a single space, then strip. Nothing else.
- D-02: No casefolding, no punctuation stripping, no stopword removal. DEDUP-01 is exact dedup — the normalizer exists only to neutralize whitespace/Unicode-form noise, not to merge semantically similar text. This is deliberate: healthcare text where case carries meaning (`WBC` vs `wbc`, drug trade names) must never be collapsed into one point. Aggressive normalization belongs to the MinHash path in `curate.py`, not here.
- D-03: `_normalize_whitespace()` in `clean.py` is NOT reused. It is line-oriented (preserves single newlines, collapses 3+ blank lines to 2) and serves a different contract — cleaned-text readability. Coupling the dedup key to it would make a cosmetic cleaning tweak silently repartition the dedup space. The two functions stay independent by design; note this rationale in the code so a future reader doesn't "DRY" them together.
- D-04: The dedup key is `sha256(normalize_for_dedup(text).encode("utf-8")).hexdigest()`, referred to as `text_sha256` throughout. It is computed from the chunk's `text` field only — never from section_path, page, or any per-document field (including those would defeat cross-document dedup).

**Point ID Determinism (DEDUP-02)**
- D-05: `KLAKE_DEDUP_NAMESPACE` is a module-level frozen `uuid.UUID` constant in `pipeline/dedup.py`, generated once at implementation time and hardcoded. It is never derived from settings, env, or collection name — a changing namespace would silently orphan every prior point.
- D-06: Point ID = `uuid5(KLAKE_DEDUP_NAMESPACE, text_sha256_hexdigest)` — the uuid5 name input is the 64-char hex digest string, matching DEDUP-02's literal formulation. Function: `point_id_for_text(text) -> str` returning `str(uuid5(...))`, the bare-UUID form Qdrant requires.
- D-07: This replaces `_strip_prefix(chunk_id)` as the point-ID source for newly indexed chunks (`index.py:_strip_prefix`, currently the only ID scheme). `_strip_prefix` stays in the module — it is still needed to read/resolve pre-v2.6 points — but is no longer called on the write path for dense chunk points.
- D-08: Forward-only (milestone D-2). Pre-v2.6 points keep their chunk-ID-derived IDs; no backfill, no migration of existing Qdrant points. A re-index (`reindex_collection`) copies points verbatim and does not re-key them. Consequence, accepted: for a transitional period a collection holds both ID schemes, and an old-scheme point plus a new-scheme point may carry the same text. Planner should note this in the reindex docstring rather than attempt a re-key.
- D-09: The payload `qdrant_id` field carries the new uuid5 point ID (it already exists as the "bare UUID for Qdrant cross-ref" field, `index.py`), keeping the payload self-describing.

**Ledger Schema and Source of Truth (DEDUP-01)**
- D-10: New SQLAlchemy model `ChunkDedupLedger` (`__tablename__ = "chunk_dedup_ledger"`) in `registry/models.py`, following the `VectorCollection` model's shape (prefixed-UUID `id` PK, `created_at` with `server_default=func.now()`). New Alembic migration `0011_chunk_dedup_ledger.py` — next in sequence after `0010_sources_domain_column.py`.
- D-11: Columns: `id` (String(64) PK, prefixed UUIDv7), `collection` (String(128), the alias name), `text_sha256` (String(64)), `point_id` (String(64), the uuid5), `primary_chunk_id` (String(64)), `primary_parsed_artifact_id` (String(64)), `primary_source_id` (String(64), nullable), `primary_created_at` (DateTime tz), `contributors` (JSONB, default `[]`), `contributor_count` (Integer, default 1), `created_at`, `updated_at`.
- D-12: Unique constraint on `(collection, text_sha256)` — not on `text_sha256` alone. Ledger rows are scoped per alias so that wiping/recreating a collection, or running a second collection, cannot leave the new collection starved of points because a stale ledger row claims the text is "already indexed". Index on `(collection, text_sha256)` gives the O(1) lookup DEDUP-01 requires.
- D-13: The Postgres ledger is the source of truth for dedup and contributors. The Qdrant payload is a mirror, rebuildable from the ledger. This follows the project's existing precedent (`VectorCollection` tracks alias→physical mapping in Postgres "independent of Qdrant's own alias listing").
- D-14: Ledger insert uses an atomic upsert (`INSERT ... ON CONFLICT (collection, text_sha256) DO NOTHING` then re-select) rather than check-then-insert, so two concurrent Dagster runs indexing the same boilerplate cannot both believe they are first. The row is committed before the Qdrant upsert, mirroring the ORDERING INVARIANT already documented in `index.py` for `register_vector_collection` — a durable ledger row with a missing point is self-healing (D-24); a point with no ledger row is not.

**Dedup Stage Placement and Wiring (DEDUP-01)**
- D-15: New module `src/knowledge_lake/pipeline/dedup.py` exposing `dedup_chunks(chunks, *, collection, settings=None) -> dict` returning `{"new": [...], "duplicates": [...], "stats": {...}}`. Each chunk dict is annotated with `text_sha256` and `point_id` before being routed. Chunk artifacts are untouched — the registry still gets both per-document chunk rows (WR-05).
- D-16: Dedup does not go inside `chunk()` (unlike Phase 20's substance gate, D-01) and does not go inside `embed()`. `embed()` is contractually stateless with "no registry writes in this stage" — a ledger write there would break that contract. `chunk()` is the wrong place because the roadmap specifies a stage between chunk and embed, and because dedup must run after the Phase 20 substance gate (roadmap: "L3 must precede L4 — dedup before filtering promotes garbage via IDF inversion"). Since Phase 20's gate runs inside `chunk()`, placing dedup after `chunk()` returns satisfies that ordering by construction.
- D-17: Two call sites, wired explicitly (accepted cost of a separate stage — parity is enforced by test, not by shared function): `pipeline/process.py` — insert `dedup_chunks()` between `chunk()` and `embed(chunks_list)`; embed only `result["new"]`. `dagster_defs/assets.py` — new asset `dedup_chunks` between `chunk_document` and `embed_chunks`, passing through the established dict-shape convention (`parsed_artifact_id`, `source_id`, `collection`, plus `new`/`duplicates`).
- D-18: A parity test asserts the CLI and Dagster paths produce identical point IDs and identical ledger state for the same input — this is the guardrail that replaces Phase 20's shared-function parity.
- D-19: `index()` gains an optional `duplicate_chunks: list[dict] | None = None` kwarg. New points take the existing embed→upsert path; duplicates take a payload-only contributor append. Keeping both in `index()` means one place owns "what lands in Qdrant" and both callers pass the same shape. `embed()` signature is unchanged — it simply receives a shorter list.
- D-20: Conservation invariant (consistent with QUAL-05, Phase 17): assert `len(new) + len(duplicates) == len(chunks_in)` at the end of `dedup_chunks()`. Structured log `dedup.complete` with `total`, `unique`, `duplicates`, `collection`, and `embed_calls_saved`.

**Contributors and Primary Determination (DEDUP-03)**
- D-21: Primary = earliest `primary_created_at`, which is by construction the first writer of the ledger row (D-14's atomic upsert makes "first writer" deterministic under concurrency). Tie-break on identical timestamps: lexicographically smallest `chunk_id`. The primary is never reassigned once set — a later document contributing the same text does not steal primary status even if its `created_at` is somehow earlier (clock skew, backfill). This keeps the payload stable and re-index idempotent.
- D-22: The point's primary-derived payload fields (`document`, `chunk_id`, `source_id`, `source_name`, `source_url`, `format`, `domain`, `tags`, `title`, `organization`, `document_type`, `keywords`, `quality_score`) are exactly what `_resolve_document_payload_fields()` already produces for the primary's `parsed_artifact_id` — unchanged code path, so PAYLOAD-01/02 filters (DEDUP-03's acceptance: filterable by source_id, domain, format) keep working with zero modification.
- D-23: New payload field `contributors: list[dict]`, each entry `{chunk_id, document, source_id, created_at}` (ISO-8601 string for `created_at` — Qdrant payloads are JSON). Plus `contributor_count: int`. The ledger holds all contributors unbounded; the Qdrant payload mirrors at most the first 50 (deterministic: ordered by `created_at`, then `chunk_id`), while `contributor_count` always reports the exact total. Rationale: boilerplate appearing in all 34 sources — and far more at scale — would otherwise grow an unbounded payload on the hottest points. The primary is always contributors[0].
- D-24: On a duplicate hit, `index()` calls the vector store's `set_payload` with only `{contributors, contributor_count}` — never a full payload overwrite, which would clobber the primary's metadata. Self-healing drift check: if `set_payload` reports the point does not exist (ledger row present, Qdrant point gone — e.g. collection wiped, or the D-14 commit survived a failed upsert), the chunk is demoted to the `new` path (embed + full upsert) and the ledger row is repaired to point at the re-created point. This makes the ledger's authority safe rather than a footgun.

**Vector Store Protocol Extension**
- D-25: `VectorStorePlugin` protocol (`plugins/protocols.py`) gains one method: `set_payload(collection: str, point_id: str, payload: dict) -> bool` — merges the given keys into an existing point's payload, returning `False` if the point does not exist. Implemented in `plugins/builtin/qdrant_store.py`. Returning existence (rather than a bare no-op) is what powers D-24; Qdrant's native `set_payload` — **research correction: does NOT silently no-op; it raises `UnexpectedResponse` (404) — see `## Architecture Patterns` Pattern 2** — so the implementation must catch that exception to produce the boolean-existence contract.
- D-26: This is the minimum viable protocol extension — no `retrieve`/`delete`/`scroll` added speculatively. The framework's tool-agnostic constraint means every added protocol method is a tax on future vector-store plugins; one method is defensible, four is not.

### Claude's Discretion

Claude has flexibility on: the concrete `KLAKE_DEDUP_NAMESPACE` UUID value; the exact contributors payload cap (50 is a starting point, not a researched threshold — surface it as a `DedupSettings` field if that proves cleaner); whether `DedupSettings` warrants its own Pydantic settings model or the handful of knobs live inline; the `dedup_chunks()` return-dict key names; ledger column sizing/nullability details (this research recommends `JSON().with_variant(JSONB, "postgresql")` over bare `postgresql.JSONB` for the `contributors` column — see Pattern 3 — to preserve SQLite unit-test-harness compatibility); the Dagster asset's exact dict passthrough shape; structured-log event field names; and whether the `set_payload` existence check uses `retrieve` or Qdrant's conditional update primitives (this research recommends catching `UnexpectedResponse`/404 directly on `set_payload` itself, avoiding a second protocol method — see Pattern 2).

### Deferred Ideas (OUT OF SCOPE)

- Retroactive dedup of the existing 4,499-chunk corpus — Forward-only (milestone D-2). A deliberate reprocess from the immutable raw zone remains possible later.
- Re-keying pre-v2.6 points to the uuid5 scheme — Would collapse the dual-ID-scheme transitional state (D-08). A `reindex --rekey` mode is the natural home; belongs to a future phase, not this one.
- Near-duplicate / semantic dedup at index time — DEDUP-01 is exact dedup. MinHash near-dup already exists corpus-wide in the pretrain `curate` path; extending it to the RAG index path is a separate capability.
- Tree-index dedup — `tree_index.py` builds a parallel structure with its own duplication characteristics. Out of scope; DEDUP-01..03 name the chunk/embed/index path only.
- Rebuild-payload-from-ledger repair command — The ledger being source of truth (D-13) makes a full `contributors[]` payload rebuild possible (analogous to `reindex --refresh-payload` for KL-06). Not needed to satisfy DEDUP-01..03; note as a v2.7 operability candidate.
</user_constraints>

## Summary

CONTEXT.md's D-01 through D-26 already fully specify this phase's design — normalization,
point-ID scheme, ledger schema, stage placement, contributor semantics, and the protocol
extension are locked. This research does not revisit any of those decisions. Its job is the
one the orchestrator asked for: verify that the concrete file/line references CONTEXT.md
cites still match the code after Phase 20 landed (commit `95d2eef`, after CONTEXT.md was
written), and de-risk the two genuinely new technical primitives this phase introduces to
the codebase — a Postgres `INSERT ... ON CONFLICT DO NOTHING` atomic upsert, and a Qdrant
`set_payload` existence-check.

**Both de-risking exercises surfaced a real correction to a CONTEXT.md assumption, verified
empirically against the live dev-stack Postgres 16 and Qdrant 1.18.2 instances in this
environment (not just documentation):**　qdrant-client 1.18.0's `set_payload` does **not**
silently no-op on a missing point ID — it raises `UnexpectedResponse` (HTTP 404). D-24's
"self-healing" logic must catch this exception, not check a falsy return value. Additionally,
`INSERT ... ON CONFLICT DO NOTHING`'s SQLAlchemy `CursorResult.rowcount` is unreliable
(`-1`) under psycopg3 for this statement shape — the atomic upsert must use `.returning()`
to detect first-writer status, not rowcount.

Every canonical file reference in CONTEXT.md's `<canonical_refs>`/`<code_context>` sections
has drifted by 15-25 lines (chunk.py, index.py, process.py, assets.py) because Phase 20's
fix commit `95d2eef` landed after CONTEXT.md was written — the *shapes and contracts* CONTEXT.md
describes are all still accurate, only the line numbers are stale. This document gives the
corrected line numbers below.

**Primary recommendation:** Implement exactly per CONTEXT.md's D-01..D-26, using the
corrected line numbers in `## Canonical References (Corrected)` below, the exception-based
`set_payload` existence check, the `.returning()`-based atomic-upsert pattern, and
`JSON().with_variant(JSONB, "postgresql")` (not bare `postgresql.JSONB`) for the ledger's
`contributors` column so the existing SQLite-backed unit-test harness (`test_index_payload.py`
pattern) keeps working. Also: register the new `dedup_chunks` asset in
`core_pipeline_e2e_job`'s selection tuple — omitting it silently breaks ordering exactly the
way KL-06 did (test_asset_ordering.py already pins this against regression).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Text normalization + hashing (`normalize_for_dedup`, `text_sha256`) | API/Backend (pure function, `pipeline/dedup.py`) | — | Zero I/O, deterministic — same tier as `pipeline/quality/` (Phase 19 convention) |
| Point-ID derivation (`uuid5`) | API/Backend (pure function) | — | Deterministic, no DB/network access needed |
| Dedup ledger (existence check + insert) | Database (Postgres, `chunk_dedup_ledger` table) | API/Backend (`repo.py` functions) | Source of truth per D-13; Postgres already owns `VectorCollection`'s analogous alias-mapping role |
| Duplicate routing (`dedup_chunks()`) | API/Backend (`pipeline/dedup.py`) | Database (ledger reads/writes) | Orchestrates the ledger lookup + chunk partitioning; called from both CLI (`process.py`) and Dagster (`assets.py`) |
| Contributor payload append | API/Backend (`index()` in `pipeline/index.py`) | Database / Vector Store (Qdrant payload mutation) | `index()` already owns "what lands in Qdrant" (D-19); extending it keeps one place responsible |
| Point existence check + payload merge (`set_payload`) | Vector Store (Qdrant, via `VectorStorePlugin`) | — | New protocol method on `QdrantStore`, mirrors `refresh_all_points_payload`'s existing analog |
| Dagster asset wiring (`dedup_chunks` asset) | Orchestration (Dagster) | API/Backend (calls same pipeline function as CLI) | Thin wrapper only — no logic duplicated, matches every other asset in `assets.py` |

## Standard Stack

### Core
No new third-party packages. This phase is pure additive code against the already-pinned
stack (CLAUDE.md): SQLAlchemy 2.0.51, psycopg 3.3.4, qdrant-client 1.18.0, structlog 26.1.0 —
all confirmed installed in this environment (`uv pip show`) and matching CLAUDE.md's pinned
versions `[VERIFIED: uv pip show, this environment]`.

| Component | Source | Purpose |
|-----------|--------|---------|
| `uuid.uuid5` | stdlib | Deterministic point-ID generation (DEDUP-02) |
| `hashlib.sha256` | stdlib | `text_sha256` dedup key |
| `unicodedata.normalize("NFKC", ...)` | stdlib | D-01's Unicode normalization step |
| `sqlalchemy.dialects.postgresql.insert` | already a transitive dependency of SQLAlchemy | Atomic `ON CONFLICT DO NOTHING` upsert (D-14) |
| `qdrant_client.http.exceptions.UnexpectedResponse` | qdrant-client 1.18.0 | Catch to detect a missing point ID in `set_payload` |

### Package Legitimacy Audit

Not applicable — no new packages are installed by this phase. All primitives used
(`uuid`, `hashlib`, `unicodedata`, SQLAlchemy's `dialects.postgresql.insert`, and
`qdrant_client`'s existing exception classes) come from packages already in `pyproject.toml`.

## Canonical References (Corrected)

CONTEXT.md's `<canonical_refs>`/`<code_context>` sections were written before Phase 20's fix
commit `95d2eef` landed. Every shape/contract they describe is still accurate — only line
numbers drifted. Verified by direct file read in this session `[VERIFIED: direct file read, this session]`:

| CONTEXT.md said | Actual (verified 2026-07-17) | Drift cause |
|---|---|---|
| `chunk.py` `chunk()` at line 263 | `chunk()` at **line 431** | Phase 20 inserted `_build_fineweb_filter`, `_fineweb_predicate`, `_assert_chunk_conservation_invariant`, `_apply_substance_gate` (lines 280-425) before it |
| WR-05 hash comment at chunk.py lines 314-318 | **lines 495-503**: `hash_input = f"{parsed_artifact_id}:{s.chunk_quality.filter_config_version}:{text}"` | Same — Phase 20's substance-gate block precedes it. Formula content is unchanged (still folds in `parsed_artifact_id` + `filter_config_version`, per PIPE-01) |
| `clean.py` `_normalize_whitespace()` at line 66 | **lines 115-127** | Unrelated additions earlier in the file |
| `process.py:111` (insert `dedup_chunks()` between `chunk()` and `embed(chunks_list)`) | `chunk()` call at **line 126**; `embed(chunks_list)` at **line 131**; `index(...)` at **line 132**. Insert `dedup_chunks()` between 126 and 131 | Phase 20 added `domain_filters` resolution block (lines 104-107) and the `if not chunks_list: continue` early-return (lines 127-129) before this call |
| `assets.py` `chunk_document` at line ~349 | **line 367** (decorator starts 353) | |
| `assets.py` `embed_chunks` at line 536 | **line 559** | |
| `assets.py` `index_chunks` at line 578 | **line 601** | |
| `VectorCollection` model at models.py line 453 | **line 453** — unchanged, confirmed | |
| `VectorStorePlugin` protocol at protocols.py line 212 | **line 212** — unchanged, confirmed | |
| `qdrant_store.py` `upsert()` at line 520 | **line 520** — unchanged, confirmed | |
| `qdrant_store.py` `refresh_all_points_payload()` at line 306 | **line 306** — unchanged, confirmed | |
| `0010_sources_domain_column.py` is latest migration | **Confirmed** — `0011_chunk_dedup_ledger.py` is the correct next filename | |

**No shape/contract drift found** — `chunk()`'s return dict keys
(`chunk_id, artifact_id, text, section_path, page, content_hash, is_table, oversized,
substance_passed, rejection_reason`) are exactly what D-15/D-16 assume `dedup_chunks()`
receives. `embed()`'s docstring still says "No registry writes in this stage" verbatim
(line 6), confirming D-16's "stateless by contract" reasoning still holds. The Dagster
asset dict shapes are exactly as CONTEXT.md's Integration Points section describes:
- `chunk_document` returns `{chunks, parsed_artifact_id, source_id, collection}`
- `embed_chunks` (input `chunk_document: dict`) returns `{vectors, dim, chunks, parsed_artifact_id, source_id, collection}`
- `index_chunks` (input `embed_chunks: dict`) reads `vectors, dim, chunks, parsed_artifact_id, collection`

## Architecture Patterns

### System Architecture Diagram

```
                 chunk() [Phase 20 substance gate already applied]
                          |
                          v
      +----------------------------------------+
      |         dedup_chunks() (NEW)            |
      |  for each chunk:                        |
      |    text_sha256 = sha256(normalize(text)) |
      |    point_id = uuid5(NS, text_sha256)     |
      |    atomic INSERT..ON CONFLICT DO NOTHING |
      |    into chunk_dedup_ledger               |
      |    (collection, text_sha256) UNIQUE      |
      |         |                    |           |
      |    [won insert]        [lost insert]     |
      |    -> route "new"      -> re-SELECT ledger|
      |                           row; append     |
      |                           contributor;    |
      |                           route "dup"     |
      +----------------------------------------+
             |  new                    |  duplicates
             v                         v
      embed(new only)          (no embedding)
             |                         |
             v                         v
      +----------------------------------------+
      |              index() (extended)         |
      |  new: embed+upsert VectorPoint (uuid5 id)|
      |  dup: vstore.set_payload(point_id,       |
      |       {contributors, contributor_count}) |
      |       -- self-heal if point missing:     |
      |       demote to new-path embed+upsert    |
      +----------------------------------------+
                          |
                          v
                   Qdrant point (1 per unique text)
                   filterable via existing PAYLOAD-01/02
```

Two wiring call sites reproduce this graph identically (D-17/D-18):
`pipeline/process.py` (CLI/API/MCP shared path) and a new Dagster asset
`dedup_chunks` inserted between `chunk_document` and `embed_chunks`.

### Pattern 1: Atomic "first writer wins" upsert via `.returning()`, NOT `.rowcount`

**What:** `INSERT ... ON CONFLICT (collection, text_sha256) DO NOTHING` determines
first-writer status.

**Verified pitfall `[VERIFIED: live Postgres 16 test, this session]`:** Under SQLAlchemy
2.0.51 + psycopg 3.3.4 (this project's exact pinned combination), `CursorResult.rowcount`
returns `-1` for this statement shape regardless of whether the row was actually inserted or
the conflict fired. **Do not branch on `.rowcount`.** Instead, chain `.returning(Model.id)`
(or any column) — an empty result set means you lost the race (row already existed); a
non-empty result set means you won and the row is yours.

```python
# Source: verified empirically in this session against live Postgres 16
# (docker container healthlake-postgres-1) via psycopg 3.3.4 / SQLAlchemy 2.0.51.
from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = (
    pg_insert(ChunkDedupLedger)
    .values(
        id=new_id("artifact"),  # or a dedicated prefix
        collection=collection,
        text_sha256=text_sha256,
        point_id=point_id,
        primary_chunk_id=chunk_id,
        primary_parsed_artifact_id=parsed_artifact_id,
        primary_source_id=source_id,
        primary_created_at=now,
        contributors=[],
        contributor_count=1,
    )
    .on_conflict_do_nothing(index_elements=["collection", "text_sha256"])
    .returning(ChunkDedupLedger.id)
)
won = session.execute(stmt).fetchall()  # non-empty == first writer
session.commit()  # commit BEFORE the Qdrant write (ORDERING INVARIANT, D-14)

if not won:
    # Lost the race — re-select the existing (winning) row for its primary fields.
    existing = session.execute(
        select(ChunkDedupLedger)
        .where(ChunkDedupLedger.collection == collection)
        .where(ChunkDedupLedger.text_sha256 == text_sha256)
    ).scalar_one()
```

Confirmed with a live two-transaction test in this session: transaction 1's
`.returning()` yielded `[('row1',)]`; transaction 2 (same conflict key, committed after
transaction 1) yielded `[]`. `.rowcount` on both statements printed `-1` — proving rowcount
cannot distinguish the two outcomes on this stack.

### Pattern 2: `set_payload` existence check — must catch an exception, not check a return value

**Verified `[VERIFIED: live Qdrant v1.18.2 test, this session]`, correcting CONTEXT.md D-25's
assumption:** qdrant-client 1.18.0's `QdrantClient.set_payload()` does **not** silently
no-op on a missing point ID. Calling it against a nonexistent point ID raises
`qdrant_client.http.exceptions.UnexpectedResponse` with `status_code == 404` and body
`{"status":{"error":"Not found: No point with id ... found"}}`. `retrieve()` on a missing ID,
by contrast, returns `[]` with no exception (confirmed empirically).

This means D-25's protocol method (`set_payload(collection, point_id, payload) -> bool`)
must be implemented as:

```python
# Source: verified empirically in this session against live Qdrant v1.18.2
# (docker container healthlake-qdrant-1), qdrant-client 1.18.0.
from qdrant_client.http.exceptions import UnexpectedResponse

def set_payload(self, collection: str, point_id: str, payload: dict) -> bool:
    """Merge ``payload`` into an existing point. Returns False if the point
    does not exist (never raises for that case) -- callers use the return
    value to drive D-24's self-healing demote-to-new-path branch."""
    try:
        self._client.set_payload(
            collection_name=collection, payload=payload, points=[point_id]
        )
        return True
    except UnexpectedResponse as e:
        if e.status_code == 404:
            log.warning(
                "qdrant_store.set_payload.point_missing",
                collection=collection, point_id=point_id,
            )
            return False
        raise
```

This keeps D-26's "one method, no speculative `retrieve`" constraint intact — the
existence check is folded into `set_payload`'s own exception handling rather than a
separate `retrieve()` pre-check call, which would otherwise require adding a second
protocol method.

### Pattern 3: JSONB column must stay SQLite-test-harness compatible

**Verified pitfall `[VERIFIED: this session, SQLAlchemy 2.0.51]`:** This codebase's unit
tests for `pipeline/index.py` (`tests/unit/test_index_payload.py`, and the identical pattern
in `test_enrich.py`) monkeypatch `registry.db.get_engine` to an in-memory SQLite engine via
`StaticPool` — they do **not** use the real Postgres the integration suite uses. A column
declared with bare `sqlalchemy.dialects.postgresql.JSONB` fails `Base.metadata.create_all()`
against that SQLite engine with `CompileError: ... can't render element of type JSONB`
(reproduced directly in this session). CONTEXT.md's D-11 says "`contributors` (JSONB,
default `[]`)" — this is achievable without breaking the SQLite unit-test harness via:

```python
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

contributors: Mapped[list] = mapped_column(
    JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
)
```

Confirmed working against both a real SQLite in-memory engine (`create_all` succeeds) and
implicitly against Postgres (the `.with_variant` selects `JSONB` there). Alternatively, the
project's own established convention (`registry/models.py`'s `_JSON` fallback, used by
`Source.config`, and other JSON-ish columns) uses generic `sqlalchemy.JSON` with no
dialect-specific JSONB at all — either is acceptable; **bare, undecorated `postgresql.JSONB`
is the one option that breaks the existing test harness.**

### Recommended Project Structure
```
src/knowledge_lake/
├── pipeline/
│   ├── dedup.py         # NEW — normalize_for_dedup, point_id_for_text, dedup_chunks
│   ├── chunk.py         # unchanged (dedup does not go inside it, D-16)
│   ├── embed.py         # unchanged signature; receives fewer chunks
│   ├── index.py         # extended: duplicate_chunks kwarg, set_payload branch
│   └── process.py       # +1 call site: dedup_chunks() between chunk() and embed()
├── registry/
│   ├── models.py        # + ChunkDedupLedger
│   └── alembic/versions/0011_chunk_dedup_ledger.py  # NEW
├── plugins/
│   ├── protocols.py     # VectorStorePlugin + set_payload
│   └── builtin/qdrant_store.py  # + set_payload implementation
└── dagster_defs/
    └── assets.py        # + dedup_chunks asset; core_pipeline_e2e_job selection updated
```

### Anti-Patterns to Avoid
- **Branching on `INSERT...ON CONFLICT`'s `.rowcount`** — unreliable (`-1`) under this
  project's exact psycopg3/SQLAlchemy 2.0 combination (verified above). Use `.returning()`.
- **Assuming `set_payload` silently no-ops on a missing point** — it raises. A naive
  `if not vstore.set_payload(...): demote()` without exception handling will crash on the
  self-heal path this is specifically meant to catch.
- **Bare `postgresql.JSONB` on the ledger model** — breaks the SQLite-backed unit-test
  harness convention already established for `index.py`/`enrich.py` tests.
- **Reusing `_normalize_whitespace()` from `clean.py`** — deliberately avoided per D-03;
  confirmed still correct after the line-number shift (lines 115-127) — it collapses
  blank-line runs and preserves single newlines, a cosmetic-readability contract, not an
  exact-dedup-key contract.
- **Naming the new test file `test_dedup.py`** — that filename is already taken by
  `tests/unit/test_dedup.py`, which tests `compute_minhash`/`remove_boilerplate` (the
  pretrain-path MinHash near-dup logic, CLEAN-03) — an entirely different concern from this
  phase's exact index-time dedup. Use a distinct name, e.g. `test_index_dedup.py` or
  `test_chunk_dedup_ledger.py`, to avoid confusing the two dedup concepts in the test suite.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Concurrent-safe "claim this key" semantics | A manual `SELECT ... FOR UPDATE` + check-then-insert loop | `INSERT ... ON CONFLICT DO NOTHING` + `.returning()` | Postgres's native atomic upsert already solves the race; `FOR UPDATE` requires holding a lock across a round trip and is more failure-prone |
| Existence check before a Qdrant mutation | A speculative `retrieve()` call before every `set_payload()` (2 round trips) | Try `set_payload()`, catch `UnexpectedResponse` with `status_code == 404` | 1 round trip in the common case (point exists); avoids adding a second protocol method (D-26) |
| Text normalization for exact dedup | A general-purpose "clean" pass reusing `clean.py`'s cosmetic whitespace normalizer | The narrowly-scoped `normalize_for_dedup()` (NFKC + whitespace collapse only) | D-02/D-03 — conflating the two would let a future cosmetic tweak silently repartition the dedup key space |

**Key insight:** Both novel primitives this phase introduces (atomic Postgres upsert,
Qdrant existence-aware payload mutation) have narrow, well-defined native solutions in the
already-pinned stack. The temptation to hand-roll locking or pre-check round trips would
add latency and race conditions the native primitives already close.

## Common Pitfalls

### Pitfall 1: `core_pipeline_e2e_job`'s asset selection must include the new `dedup_chunks` asset
**What goes wrong:** Dagster silently drops a `deps=` edge whose target asset is outside a
job's selected asset set (this is exactly how the KL-06 scheduling race reached production —
see `assets.py`'s KL-06 docstring and `tests/unit/test_asset_ordering.py`, which now pins
this). If `dedup_chunks` is added to the module but not to
`core_pipeline_e2e_job`'s `AssetSelection.assets(...)` tuple (currently at
`assets.py` lines 1017-1028), the asset exists and looks correctly wired in the abstract
graph, but the job people actually run silently executes `embed_chunks` directly off
`chunk_document` again (or fails to materialize at all, depending on how the new deps are
declared), which for THIS phase specifically means "L3 must precede L4" style guarantees
between chunk() and embed() being at risk if a deps ordering assumption is bypassed.
**Why it happens:** Job asset selections in Dagster are pinned in code
(`define_asset_job(..., selection=AssetSelection.assets(...))`) and are NOT automatically
kept in sync with new assets added to the module.
**How to avoid:** Add `dedup_chunks` to `core_pipeline_e2e_job`'s selection tuple in the
same commit that adds the asset. Extend `test_asset_ordering.py`'s
`TestCorePipelineE2eJobSelectionPreservesOrdering` class with an equivalent assertion for
`dedup_chunks` (D-18's parity-test spirit extends naturally to this).
**Warning signs:** `test_asset_ordering.py`'s existing tests only assert
`curate_document_asset`/`enrich_document` membership — they will NOT fail if
`dedup_chunks` is missing from the selection unless a new assertion is added for it.

### Pitfall 2: Reindex path (`reindex_collection` / `copy_all_points`) must not attempt to re-key IDs
**What goes wrong:** `copy_all_points()` (qdrant_store.py:269) already copies points
verbatim by `id`, which satisfies D-08's forward-only requirement automatically — no code
change needed there. The risk is a future contributor "fixing" what looks like an
inconsistency (old chunk-ID-derived IDs coexisting with new uuid5 IDs in the same
collection) by attempting a re-key during reindex, which D-08 explicitly says NOT to do.
**Why it happens:** The dual-ID-scheme transitional state is unusual enough that it invites
"cleanup."
**How to avoid:** Add the dual-ID-scheme note to `reindex_collection()`'s docstring
(CONTEXT.md D-08 already calls this out) so the intent is documented in the exact function a
future contributor would touch.
**Warning signs:** A PR that adds ID-rewriting logic to `copy_all_points` or
`reindex_collection`.

### Pitfall 3: `dedup_chunks()`'s conservation invariant must count at the point-routing level, not the ledger-write level
**What goes wrong:** QUAL-05's established pattern (Phase 17, extended by Phase 20's
`_assert_chunk_conservation_invariant`) asserts `kept + rejected == total`. For D-20's
analogous invariant (`len(new) + len(duplicates) == len(chunks_in)`), the natural mistake
is asserting this only for chunks that successfully wrote a NEW ledger row, silently
dropping chunks whose ledger insert failed for an unrelated reason (e.g. a transient DB
error) from either bucket.
**Why it happens:** The self-healing branch (D-24) already reroutes "point missing"
duplicates back to the `new` path — it's easy to reuse that same reroute machinery for
error handling and lose the strict partition guarantee.
**How to avoid:** Assert the invariant unconditionally at the end of `dedup_chunks()`,
exactly mirroring `_assert_chunk_conservation_invariant`'s log-then-raise (never bare
assert) shape from `chunk.py` lines 315-337.
**Warning signs:** A test that processes N chunks but the `new`+`duplicates` count is off by
however many chunks the ledger write failed to classify.

### Pitfall 4: Ledger `id` prefix and `new_id()` helper
**What to verify before writing the migration:** confirm the exact `new_id()` helper
signature/prefix convention used elsewhere (`new_id("artifact")` produces `art_<uuidv7>` per
`VectorCollection`). Use the same helper for `ChunkDedupLedger.id` rather than a bespoke ID
generator, to stay consistent with every other registry model.

## Runtime State Inventory

Not applicable — this is a greenfield additive phase (new table, new module, new asset,
new protocol method), not a rename/refactor/migration phase. Skipped per the trigger
condition in the research protocol.

## Code Examples

### Full point-ID / dedup-key derivation (pure, D-01/D-02/D-04/D-06)
```python
# Source: derived directly from CONTEXT.md D-01/D-02/D-04/D-06 — no external
# reference needed, this is pure stdlib.
from __future__ import annotations

import hashlib
import unicodedata
import uuid

KLAKE_DEDUP_NAMESPACE = uuid.UUID("<generate once, hardcode, never change>")


def normalize_for_dedup(text: str) -> str:
    """NFKC-normalize and collapse all whitespace runs to a single space.

    Deliberately does NOT casefold, strip punctuation, or remove stopwords
    (D-02) -- this is exact dedup, not near-dup. Deliberately does NOT reuse
    clean.py's _normalize_whitespace() (D-03) -- that function serves a
    line-oriented cosmetic-readability contract, not an exact-key contract.
    """
    normalized = unicodedata.normalize("NFKC", text)
    collapsed = " ".join(normalized.split())
    return collapsed.strip()


def text_sha256_for(text: str) -> str:
    return hashlib.sha256(normalize_for_dedup(text).encode("utf-8")).hexdigest()


def point_id_for_text(text: str) -> str:
    return str(uuid.uuid5(KLAKE_DEDUP_NAMESPACE, text_sha256_for(text)))
```

### Existing `_resolve_document_payload_fields` reuse point (unchanged, index.py lines 64-129)
Confirmed byte-for-byte still the right reuse target for the primary's payload
(D-22) — no modification needed, called once per `parsed_artifact_id` exactly as it is
today for the `new` path; the same helper should be called for the primary's
`parsed_artifact_id` on first-write of a duplicate's ledger row too, so a duplicate's point
still gets full PAYLOAD-01/02 fields at creation time (before any duplicate ever arrives).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Chunk-ID-derived Qdrant point IDs (`_strip_prefix(chunk_id)`) | uuid5-derived point IDs from `text_sha256` | This phase (DEDUP-02) | Re-index becomes idempotent by construction; enables cross-document dedup lookup by ID |
| Check-then-insert for registry uniqueness (e.g. `register_vector_collection`) | Atomic `INSERT...ON CONFLICT DO NOTHING` + `.returning()` for the dedup ledger | This phase (DEDUP-01, first use of this pattern in the codebase) | Removes the race window between two concurrent Dagster runs indexing the same boilerplate |

**Deprecated/outdated:** None — `_strip_prefix()` is retained (D-07) for resolving pre-v2.6
points; it is not deprecated, just no longer called on the write path for new dense chunk
points.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The concrete `KLAKE_DEDUP_NAMESPACE` UUID literal has not yet been generated/chosen (Claude's Discretion per CONTEXT.md) | Code Examples | None if generated once and hardcoded before first write, per D-05 — the risk is entirely in the "never change it" constraint, not the initial value |
| A2 | `new_id("artifact")`-style helper is the right ID-prefix convention for `ChunkDedupLedger.id` (Pitfall 4) | Common Pitfalls | Low — if repo.py's actual helper differs slightly, the model still works, just with an inconsistent prefix; easy to fix during code review |

**All other claims in this research were verified empirically against the live dev-stack
Postgres/Qdrant instances in this environment, or via direct file reads in this session —
no other assumptions carried forward from training-data-only knowledge.**

## Open Questions

1. **Should the ledger track a `qdrant_collection_physical` alongside the alias `collection`?**
   - What we know: D-12 scopes the unique constraint to `(collection, text_sha256)` where
     `collection` is the alias (matching the codebase-wide "collection is always the alias"
     convention).
   - What's unclear: after a `reindex_collection(hybrid=True)` operator-triggered migration,
     the alias points at a new physical collection but D-08 says points are copied verbatim
     (not re-keyed) — so a ledger row's `point_id` should still resolve correctly in the new
     physical collection via `copy_all_points`. This appears self-consistent but is worth a
     planner-level test: process the same two-document-duplicate scenario, reindex, and
     assert the ledger row and the reindexed point still agree.
   - Recommendation: no schema change needed; add an integration test asserting ledger/Qdrant
     agreement survives a `reindex_collection()` call (non-hybrid, default path).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL | Ledger table, atomic upsert | ✓ | 16-alpine (container `healthlake-postgres-1`), confirmed live at localhost:5432 | — |
| Qdrant | `set_payload` extension, point storage | ✓ | v1.18.2 (container `healthlake-qdrant-1`), confirmed live at localhost:6333, matches pinned `qdrant-client==1.18.0` | — |
| psycopg | DB driver | ✓ | 3.3.4 (matches CLAUDE.md pin) | — |
| SQLAlchemy | ORM / atomic upsert | ✓ | 2.0.51 (matches CLAUDE.md pin) | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None — everything this phase needs is already
running in this dev environment and version-matched to the pinned stack.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest, `xfail_strict = true` (pyproject.toml `[tool.pytest.ini_options]`) |
| Config file | `pyproject.toml` lines 121-129 |
| Quick run command | `uv run pytest tests/unit/test_<new_file>.py -x` |
| Full suite command | `uv run pytest` (971+ tests as of Phase 20 completion) |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DEDUP-01 | Two docs with identical boilerplate text produce exactly 1 Qdrant point; both chunk artifacts persist | unit + integration | `uv run pytest tests/unit/test_index_dedup.py -x` (new) | Wave 0 |
| DEDUP-01 | `normalize_for_dedup` is exact-only: no casefolding/punctuation/stopword removal | unit | `uv run pytest tests/unit/test_index_dedup.py -k normalize -x` (new) | Wave 0 |
| DEDUP-01 | Conservation invariant: `len(new)+len(duplicates)==len(chunks_in)` | unit | `uv run pytest tests/unit/test_index_dedup.py -k conservation -x` (new) | Wave 0 |
| DEDUP-02 | Re-processing the same document produces the same point ID (idempotent re-index) | unit | `uv run pytest tests/unit/test_index_dedup.py -k idempotent -x` (new) | Wave 0 |
| DEDUP-02 | CLI/Dagster parity: identical point IDs + ledger state for the same input (D-18) | integration | `uv run pytest tests/integration/test_dedup_cli_dagster_parity.py -x` (new) | Wave 0 |
| DEDUP-03 | Deduplicated point filterable by source_id/domain/format (PAYLOAD-01/02 unaffected) | unit | `uv run pytest tests/unit/test_index_dedup.py -k payload_filter -x` (new) | Wave 0 |
| DEDUP-03 | `contributors[]` lists all source docs; primary = earliest `primary_created_at`; cap at 50 with `contributor_count` exact | unit | `uv run pytest tests/unit/test_index_dedup.py -k contributors -x` (new) | Wave 0 |
| DEDUP-03 | `set_payload` self-heals when ledger row exists but Qdrant point is gone (D-24) | unit (mocked vstore) | `uv run pytest tests/unit/test_index_dedup.py -k self_heal -x` (new) | Wave 0 |
| — | New asset `dedup_chunks` is present in `core_pipeline_e2e_job`'s selection | unit | extend `tests/unit/test_asset_ordering.py` (existing file, new test method) | Wave 0 |

### Sampling Rate
- **Per task commit:** targeted `uv run pytest tests/unit/test_index_dedup.py -x` (or the
  file under active edit)
- **Per wave merge:** `uv run pytest tests/unit -x` plus the new integration parity test
- **Phase gate:** Full suite green (`uv run pytest`) before `/gsd-verify-work`, `xfail_strict`
  holds

### Wave 0 Gaps
- [ ] `tests/unit/test_index_dedup.py` — new file covering `normalize_for_dedup`,
      `point_id_for_text`, `dedup_chunks()` conservation invariant, contributor cap/primary
      logic, and the `set_payload` self-heal branch (mocked `VectorStorePlugin`). Do NOT name
      this `test_dedup.py` — that filename is taken by the unrelated MinHash near-dup tests.
- [ ] `tests/integration/test_dedup_cli_dagster_parity.py` — new file, D-18's parity guard:
      same fixture input through `process.py`'s CLI path and the Dagster asset path must
      produce identical point IDs and identical `chunk_dedup_ledger` rows.
- [ ] Extend `tests/unit/test_asset_ordering.py`'s
      `TestCorePipelineE2eJobSelectionPreservesOrdering` with an assertion that
      `dedup_chunks` is present in `core_pipeline_e2e_job`'s selection (Pitfall 1).
- [ ] `tests/unit/test_qdrant_store_set_payload.py` (or add to an existing qdrant_store test
      file) — unit test for the new `set_payload()` method against a real or fixture-backed
      Qdrant collection, asserting both the success path and the 404-caught-as-False path.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-------------------|
| V2 Authentication | No | This phase touches no auth surface |
| V3 Session Management | No | — |
| V4 Access Control | No | Ledger/point access is internal-pipeline only, no new external-facing endpoint |
| V5 Input Validation | Yes | `text_sha256`/`point_id` are derived deterministically from chunk text already validated by Phase 19/20's substance gate — no new untrusted-input surface introduced. `collection` string is already validated at the alias-resolution layer (existing code, unchanged) |
| V6 Cryptography | Yes (SHA-256/UUID5, not secrecy) | `hashlib.sha256` and `uuid.uuid5` are used here as **content-addressing** primitives, not for confidentiality or authentication — no key material, no secret hashing. No new crypto library needed; stdlib is correct and sufficient for this purpose |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|----------------------|
| Ledger row exists but Qdrant point is silently gone (data loss via out-of-band collection wipe) | Denial of Service / Repudiation (silent data loss) | D-24's self-healing demote-to-new-path branch, driven by the `set_payload` existence check documented above — already designed for in CONTEXT.md |
| Two concurrent writers racing to claim the same `text_sha256` | Tampering (lost update) | The atomic `ON CONFLICT DO NOTHING` + `.returning()` pattern verified in this research — eliminates the check-then-insert race window entirely |
| A `contributors[]` payload growing unbounded on a corpus-wide-common boilerplate string | Denial of Service (payload bloat, slow queries) | D-23's 50-entry cap on the Qdrant mirror, with the ledger (Postgres) retaining the unbounded true count via `contributor_count` |

## Sources

### Primary (HIGH confidence)
- Direct file reads of this session's codebase state: `pipeline/index.py`, `pipeline/embed.py`,
  `pipeline/chunk.py`, `pipeline/process.py`, `pipeline/clean.py`, `dagster_defs/assets.py`,
  `registry/models.py`, `registry/repo.py`, `plugins/protocols.py`,
  `plugins/builtin/qdrant_store.py`, `registry/alembic/versions/0010_sources_domain_column.py`,
  `tests/unit/test_asset_ordering.py`, `tests/unit/test_index_payload.py`,
  `tests/unit/test_chunk_substance_gate.py`, `tests/unit/test_process_crawled_clean.py`,
  `tests/unit/test_dedup.py`
- Live empirical verification in this session against `healthlake-postgres-1` (Postgres
  16-alpine) and `healthlake-qdrant-1` (Qdrant v1.18.2) docker containers already running in
  this dev environment: `set_payload` 404-raise behavior, `retrieve()` empty-list-on-missing
  behavior, `ON CONFLICT DO NOTHING` + `.returning()` first-writer detection,
  `.rowcount` unreliability, and `postgresql.JSONB` vs. SQLite `CompileError`.
- `uv pip show psycopg sqlalchemy structlog qdrant-client` — version confirmation against
  CLAUDE.md's pinned stack, this session.

### Secondary (MEDIUM confidence)
- CONTEXT.md's D-01..D-26 — treated as locked design input per the task instructions, not
  re-derived; cross-checked against the actual code where explicitly asked to (line numbers,
  shapes).

### Tertiary (LOW confidence)
- None — every claim in this document was either read directly from the current codebase or
  verified empirically against the live dev stack.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages, all versions confirmed installed and matching pins
- Architecture: HIGH — CONTEXT.md's design fully specified; this research only confirmed
  drift-corrected line numbers and shape-compatibility, no architectural gaps found
- Pitfalls: HIGH — the two most consequential pitfalls (set_payload exception semantics,
  rowcount unreliability, JSONB/SQLite incompatibility) were reproduced empirically against
  the live stack, not inferred from documentation

**Research date:** 2026-07-17
**Valid until:** 30 days (stable stack; no fast-moving dependencies in this phase's scope) —
but re-verify line numbers again if any further Phase 20 hotfixes land before Phase 21 starts
implementation, since this research already found one full round of such drift.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DEDUP-01 | Index-time exact deduplication: dedup stage between chunk and embed, corpus-wide, Postgres ledger with `sha256(normalized_text)` lookup, chunk artifacts stay per-document | `## Architecture Patterns` Pattern 1 (atomic upsert), `## Code Examples` (normalize_for_dedup/text_sha256_for), `## Common Pitfalls` Pitfall 3 (conservation invariant), `## Validation Architecture` test map rows 1-3 |
| DEDUP-02 | Qdrant point IDs use `uuid5(NAMESPACE, sha256(normalized_text))`, idempotent re-index, O(1) dedup lookup | `## Code Examples` (point_id_for_text), `## Canonical References (Corrected)` (D-07/D-08 forward-only confirmed unchanged), `## Common Pitfalls` Pitfall 2 (reindex must not re-key), `## Validation Architecture` test map rows 4-5 |
| DEDUP-03 | Single point payload carries primary source metadata (earliest created_at) + additive `contributors[]`; PAYLOAD-01/02 filters remain functional | `## Architecture Patterns` Pattern 2 (set_payload exception semantics), Pattern 3 (JSONB/SQLite compatibility), `## Code Examples` (`_resolve_document_payload_fields` reuse point), `## Security Domain` (contributors payload-bloat mitigation), `## Validation Architecture` test map rows 6-8 |
</phase_requirements>
