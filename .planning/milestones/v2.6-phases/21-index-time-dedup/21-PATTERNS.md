# Phase 21: Index-Time Dedup - Pattern Map

**Mapped:** 2026-07-17
**Files analyzed:** 9 (1 new module, 1 new migration, 7 modified)
**Analogs found:** 9 / 9

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/knowledge_lake/pipeline/dedup.py` (NEW) | service (pure transform + ledger-backed router) | CRUD (ledger upsert) + transform | `src/knowledge_lake/pipeline/embed.py` (stage shape) + `src/knowledge_lake/pipeline/chunk.py` `_apply_substance_gate`/`_assert_chunk_conservation_invariant` (gate/invariant shape) | role-match (composite) |
| `src/knowledge_lake/registry/models.py` (+`ChunkDedupLedger`) | model | CRUD | `VectorCollection` (same file, lines 453-489) | exact |
| `src/knowledge_lake/registry/alembic/versions/0011_chunk_dedup_ledger.py` (NEW) | migration | batch/DDL | `0010_sources_domain_column.py` | exact |
| `src/knowledge_lake/pipeline/index.py` (extend `index()`, add duplicate-routing) | service | request-response / CRUD | itself (`index()` lines 132-249, `_resolve_document_payload_fields` lines 64-129) | exact (self-extension) |
| `src/knowledge_lake/pipeline/process.py` (+1 call site) | controller/CLI wiring | request-response | itself, lines 113-134 (`chunk()`→`embed()`→`index()` call chain) | exact |
| `src/knowledge_lake/dagster_defs/assets.py` (+`dedup_chunks` asset, +selection entry) | orchestration asset | event-driven (Dagster op) | `embed_chunks` asset (lines 559-590) as the shape template; `chunk_document` (lines 367-415) for the settings/domain_filters plumbing pattern | exact |
| `src/knowledge_lake/plugins/protocols.py` (+`set_payload` method on `VectorStorePlugin`) | interface/protocol | request-response | existing `VectorStorePlugin` methods, e.g. `ensure_aliased_collection` (lines 241-...), `refresh_all_points_payload` docstring reference (line 221) | exact |
| `src/knowledge_lake/plugins/builtin/qdrant_store.py` (+`set_payload` impl) | service (plugin impl) | request-response | `refresh_all_points_payload()` (lines 306-352) — closest existing payload-mutation-without-re-embed analog | exact |
| `tests/unit/test_index_dedup.py` (NEW) | test | — | `tests/unit/test_chunk_substance_gate.py`, `tests/unit/test_index_payload.py` (SQLite `StaticPool` harness pattern) | role-match |

## Pattern Assignments

### `src/knowledge_lake/pipeline/dedup.py` (NEW — service, CRUD+transform)

**Analog A (pure-function style):** `src/knowledge_lake/pipeline/chunk.py` — `_build_fineweb_filter`/`_fineweb_predicate`/`_assert_chunk_conservation_invariant`/`_apply_substance_gate` (lines 280-425)

**Conservation-invariant pattern to copy** (`chunk.py` lines 315-337):
```python
def _assert_chunk_conservation_invariant(
    *,
    kept_count: int,
    rejected_count: int,
    total_generated: int,
    parsed_artifact_id: str,
) -> None:
    """QUAL-05 conservation invariant: rejected + kept == total_generated.

    Mirrors clean.py's log-then-raise shape exactly -- never a bare assert.
    """
    if kept_count + rejected_count != total_generated:
        log.error(
            "chunk.substance_gate.conservation_invariant_violated",
            parsed_artifact_id=parsed_artifact_id,
            total_generated=total_generated,
            kept=kept_count,
            rejected=rejected_count,
        )
        raise RuntimeError(
            f"chunk: conservation invariant violated for {parsed_artifact_id!r}: "
            f"{kept_count} + {rejected_count} != {total_generated}"
        )
```
D-20 wants the identical shape: `assert len(new) + len(duplicates) == len(chunks_in)` — copy this log-then-raise structure verbatim, renaming the event to `dedup.conservation_invariant_violated`.

**Structured completion log pattern to copy** (`chunk.py` lines 413-421, and `embed.py` lines 45/49):
```python
log.info(
    "chunk.substance_gate.complete",
    parsed_artifact_id=parsed_artifact_id,
    total_generated=len(raw_chunks),
    kept=kept_count,
    rejected=rejected_count,
    rejection_reasons=rejection_reason_counts,
    gate_mode=s.chunk_quality.gate_mode,
)
```
D-20 wants `dedup.complete` with `total`, `unique`, `duplicates`, `collection`, `embed_calls_saved` — same dotted-stage-scoped event-name convention (`embed.start`/`embed.complete` in `embed.py` lines 45, 49; `index.upsert`/`index.complete` in `index.py` lines 244, 248).

**Stage-function signature/settings-resolution pattern to copy** (`embed.py` lines 22-50, full file — small enough to copy the whole shape):
```python
def embed(
    chunks: list[dict],
    *,
    settings: Settings | None = None,
) -> tuple[list[list[float]], int]:
    if not chunks:
        return [], 0
    s = settings or get_settings()
    ...
```
`dedup_chunks(chunks, *, collection, settings=None) -> dict` should follow this exact `s = settings or get_settings()` idiom and the empty-input early-return guard (`index()` also guards `if not chunks: return []` at `index.py` line 160).

**Atomic ledger upsert pattern (NEW primitive — from RESEARCH.md, verified live):**
```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = (
    pg_insert(ChunkDedupLedger)
    .values(
        id=new_id("artifact"),  # or a dedicated ledger prefix -- see Landmines
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
session.commit()  # commit BEFORE the Qdrant write -- ORDERING INVARIANT (see index.py lines 178-184)
```
**Do NOT branch on `.rowcount`** — verified `-1` under this project's exact psycopg3/SQLAlchemy2.0 pin (RESEARCH.md Pattern 1). Use `.returning()` non-empty/empty as the sole "won the race" signal.

**Pure normalize/hash/id derivation (RESEARCH.md Code Examples — copy near-verbatim):**
```python
import hashlib
import unicodedata
import uuid

KLAKE_DEDUP_NAMESPACE = uuid.UUID("<generate once, hardcode, never change>")

def normalize_for_dedup(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    collapsed = " ".join(normalized.split())
    return collapsed.strip()

def text_sha256_for(text: str) -> str:
    return hashlib.sha256(normalize_for_dedup(text).encode("utf-8")).hexdigest()

def point_id_for_text(text: str) -> str:
    return str(uuid.uuid5(KLAKE_DEDUP_NAMESPACE, text_sha256_for(text)))
```
Explicitly do NOT reuse `clean.py`'s `_normalize_whitespace()` (now at lines 115-127, verified — line-oriented, cosmetic-readability contract, wrong tier per D-03).

**Imports pattern to copy** (`embed.py` lines 12-19 — module-level structlog + settings resolver imports):
```python
from __future__ import annotations

import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session

log = structlog.get_logger(__name__)
```

---

### `src/knowledge_lake/registry/models.py` (+`ChunkDedupLedger`)

**Analog:** `VectorCollection` (same file, lines 453-489)

**Shape to copy verbatim:**
```python
class VectorCollection(Base):
    __tablename__ = "vector_collections"
    __table_args__ = (
        UniqueConstraint("physical_collection", name="uq_vector_collections_physical"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    """Prefixed UUIDv7 -- always ``art_<uuidv7>`` (generic, not a lineage node)."""

    alias_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    physical_collection: Mapped[str] = mapped_column(String(128), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
```
`ChunkDedupLedger` follows this exactly: `__tablename__ = "chunk_dedup_ledger"`, `UniqueConstraint("collection", "text_sha256", name="uq_chunk_dedup_ledger_collection_text_sha256")` (D-12), same prefixed-`String(64)` PK idiom, same `server_default=func.now()` for `created_at`, PLUS an `updated_at` with `onupdate=func.now()` (copy that half from `AgentSpend`-style models elsewhere in `models.py` if present, or `func.now()` for both — D-11 requires both `created_at` and `updated_at`).

**JSONB column — use the RESEARCH.md-corrected pattern, NOT bare `postgresql.JSONB`:**
```python
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

contributors: Mapped[list] = mapped_column(
    JSON().with_variant(JSONB, "postgresql"), default=list, nullable=False
)
```
Bare `postgresql.JSONB` breaks the SQLite `StaticPool` unit-test harness (`test_index_payload.py`-style tests) with a `CompileError` — verified empirically in RESEARCH.md Pattern 3.

---

### `src/knowledge_lake/registry/alembic/versions/0011_chunk_dedup_ledger.py` (NEW)

**Analog:** `0010_sources_domain_column.py` (full file, 70 lines — copy the header/revision-id scaffold verbatim)

**Scaffold to copy:**
```python
"""<one-line summary>.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chunk_dedup_ledger",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("collection", sa.String(128), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("point_id", sa.String(64), nullable=False),
        sa.Column("primary_chunk_id", sa.String(64), nullable=False),
        sa.Column("primary_parsed_artifact_id", sa.String(64), nullable=False),
        sa.Column("primary_source_id", sa.String(64), nullable=True),
        sa.Column("primary_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "contributors",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("contributor_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_chunk_dedup_ledger_collection_text_sha256",
        "chunk_dedup_ledger",
        ["collection", "text_sha256"],
    )
    op.create_index(
        "ix_chunk_dedup_ledger_collection_text_sha256",
        "chunk_dedup_ledger",
        ["collection", "text_sha256"],
    )


def downgrade() -> None:
    op.drop_index("ix_chunk_dedup_ledger_collection_text_sha256", table_name="chunk_dedup_ledger")
    op.drop_constraint("uq_chunk_dedup_ledger_collection_text_sha256", "chunk_dedup_ledger", type_="unique")
    op.drop_table("chunk_dedup_ledger")
```
Note: a unique constraint already gives an index on Postgres in most configs, but `0010` shows the project's convention of explicit named indexes (`create_index`) — keep both for clarity/consistency with `0010`'s explicit-naming style, or drop the redundant `create_index` if the unique constraint already covers the lookup (D-12 just requires "an index" — planner's call).

---

### `src/knowledge_lake/pipeline/index.py` (extend `index()`, add `duplicate_chunks` kwarg)

**Analog:** itself — `index()` (lines 132-249), `_resolve_document_payload_fields()` (lines 64-129), ORDERING INVARIANT comment (lines 178-184)

**Existing point-building loop to extend** (lines 210-245 — new points keep this path unchanged):
```python
points: list[VectorPoint] = []
for chunk, vector in zip(chunks, vectors, strict=True):
    full_chunk_id = chunk["chunk_id"]
    qdrant_point_id = _strip_prefix(full_chunk_id)
    payload = {
        "document": parsed_artifact_id,
        ...
    }
    points.append(
        VectorPoint(
            id=qdrant_point_id,
            vector=vector,
            payload=payload,
            sparse=embed_sparse_doc(chunk.get("text", "")),
        )
    )

log.info("index.upsert", collection=collection, count=len(points))
vstore.upsert(collection, points)
```
For the DEDUP path: replace `qdrant_point_id = _strip_prefix(full_chunk_id)` with `qdrant_point_id = chunk["point_id"]` (already annotated by `dedup_chunks()`, D-07/D-09) on the `new`-path chunks only — `_strip_prefix` stays for reading pre-v2.6 points (D-07), not called on the write path for new dense chunk points.

**ORDERING INVARIANT precedent to mirror for the ledger** (lines 178-184, copy the comment style for the new duplicate-routing commit-before-upsert order per D-14):
```python
# ORDERING INVARIANT: commit the alias registration row HERE, before
# vstore.upsert runs in the separate session block below. ...
session.commit()
```

**`duplicate_chunks` routing — new branch, no direct analog; nearest shape is `refresh_all_points_payload`'s scroll/mutate pattern (qdrant_store.py lines 306-352) applied per-point via `set_payload` instead of full upsert.** For each duplicate chunk: call `vstore.set_payload(collection, chunk["point_id"], {"contributors": [...], "contributor_count": n})`; on `False` (self-heal per D-24), demote to the `new`-path embed+upsert and repair the ledger row (`primary_*` / `point_id` fields) as described in D-24.

---

### `src/knowledge_lake/pipeline/process.py` (+1 call site)

**Analog:** itself, lines 113-134 (the existing `chunk()`→`embed()`→`index()` chain)

**Current chain to extend:**
```python
chunks_list = chunk(parsed_id, src_id, cleaned_doc, domain_filters=domain_filters)
if not chunks_list:
    processed += 1
    continue

vectors, dim = embed(chunks_list)
index(chunks_list, vectors, dim, parsed_id, collection=collection)
```
Insert `dedup_chunks()` between the `if not chunks_list` guard and the `embed()` call:
```python
dedup_result = dedup_chunks(chunks_list, collection=collection)
if not dedup_result["new"] and not dedup_result["duplicates"]:
    processed += 1
    continue

vectors, dim = embed(dedup_result["new"])
index(
    dedup_result["new"], vectors, dim, parsed_id,
    collection=collection,
    duplicate_chunks=dedup_result["duplicates"],
)
```

---

### `src/knowledge_lake/dagster_defs/assets.py` (+`dedup_chunks` asset)

**Analog:** `embed_chunks` (lines 559-590) for the dict-passthrough shape; `chunk_document` (lines 367-415) for the settings-construction + domain_filters resolution idiom.

**Shape to copy** (`embed_chunks`, full body):
```python
@asset(
    description=(
        "Resolve each chunk's text to a deterministic dedup ledger entry; route "
        "first-seen text to embed+upsert and already-seen text to a payload-only "
        "contributor append. Calls pipeline.dedup.dedup_chunks -- no logic duplicated."
    ),
    group_name="pipeline",
    retry_policy=_PIPELINE_RETRY,
)
def dedup_chunks(
    chunk_document: dict[str, Any],
    postgres: PostgresResource,
) -> dict[str, Any]:
    from knowledge_lake.config.settings import Settings
    from knowledge_lake.pipeline.dedup import dedup_chunks as _dedup_chunks

    chunks = chunk_document["chunks"]
    parsed_artifact_id = chunk_document["parsed_artifact_id"]
    source_id = chunk_document["source_id"]
    collection = chunk_document.get("collection", DEFAULT_COLLECTION)

    settings = Settings(
        database_url=postgres.database_url,
        _env_file=None,  # type: ignore[call-arg]
    )

    log.info("dagster.dedup_chunks.start", chunk_count=len(chunks))
    result = _dedup_chunks(chunks, collection=collection, settings=settings)

    out = {
        "new": result["new"],
        "duplicates": result["duplicates"],
        "parsed_artifact_id": parsed_artifact_id,
        "source_id": source_id,
        "collection": collection,
    }
    log.info("dagster.dedup_chunks.complete", **result["stats"])
    return out
```
Note the `_env_file=None` Dagster-settings-override convention (also in `chunk_document` line 393-396, `index_chunks` line 619-622) — copy verbatim, this is an established pattern across every asset.

**Wire the new asset between `chunk_document` and `embed_chunks`:** `embed_chunks` currently takes `chunk_document: dict[str, Any]` as its sole input (line 559) — change its parameter to `dedup_chunks: dict[str, Any]` and read `dedup_chunks["new"]` instead of `chunk_document["chunks"]` (Dagster wires by parameter name matching the upstream asset's function name, matching every other asset in this file — see `chunk_document`'s param named `clean_document` at line 368, `index_chunks`' param named `embed_chunks` at line 602).

**`index_chunks` (lines 601-...) must also gain the `duplicates` passthrough** — add a `dedup_chunks: dict[str, Any]` parameter (or thread `duplicates` through `embed_chunks`'s output dict) so `index(..., duplicate_chunks=...)` has data to pass. Simplest: have `embed_chunks` forward `duplicates` unchanged in its output dict (it already forwards `parsed_artifact_id`, `source_id`, `collection` — add `duplicates` to that same dict).

**`core_pipeline_e2e_job` selection — MUST add `dedup_chunks` (RESEARCH.md Pitfall 1, verified live):**
```python
core_pipeline_e2e_job = define_asset_job(
    name="core_pipeline_e2e_job",
    selection=AssetSelection.assets(
        ingest_raw_document,
        parsed_document,
        clean_document,
        enrich_document,
        curate_document_asset,
        chunk_document,
        dedup_chunks,      # NEW -- omitting this silently breaks L3-before-L4 ordering (KL-06-style regression)
        embed_chunks,
        index_chunks,
    ),
    ...
)
```
This is the exact same class of mistake that caused the KL-06 scheduling race — `tests/unit/test_asset_ordering.py`'s `TestCorePipelineE2eJobSelectionPreservesOrdering` must be extended with an equivalent assertion for `dedup_chunks` membership (D-18's parity-test spirit).

---

### `src/knowledge_lake/plugins/protocols.py` (+`set_payload` on `VectorStorePlugin`)

**Analog:** existing protocol method docstring style, e.g. `ensure_collection` (lines 229-239)

**Shape to copy:**
```python
def set_payload(self, collection: str, point_id: str, payload: dict) -> bool:
    """Merge ``payload`` keys into an existing point without touching its
    vector or other payload fields. Returns False if the point does not
    exist (never raises for that case) -- callers use the return value to
    drive the duplicate-hit self-healing demote-to-new-path branch (D-24).

    Args:
        collection: Alias or physical collection name.
        point_id:   Bare-UUID or unsigned-int point ID.
        payload:    Partial payload dict to merge in (e.g. {"contributors": [...], "contributor_count": n}).
    """
    ...
```
Also update the class docstring's method-list block (lines 215-226) to add a `set_payload(collection, point_id, payload) -> bool` line, matching the existing one-line-per-method summary convention.

---

### `src/knowledge_lake/plugins/builtin/qdrant_store.py` (+`set_payload` implementation)

**Analog:** `refresh_all_points_payload()` (lines 306-352) for structured-log style; RESEARCH.md Pattern 2 for the exact exception-handling shape (verified live against Qdrant v1.18.2 — `set_payload` raises `UnexpectedResponse`(404), it does NOT silently no-op).

**Implementation to copy near-verbatim (from RESEARCH.md, empirically verified):**
```python
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
**Do NOT add a speculative `retrieve()` pre-check** (D-26, RESEARCH.md "Don't Hand-Roll") — the try/except IS the existence check, in one round trip.

---

## Shared Patterns

### Structured logging (dotted, stage-scoped event names)
**Source:** `embed.py` lines 45, 49 (`embed.start`, `embed.complete`); `index.py` lines 171, 244, 248 (`index.ensure_aliased_collection`, `index.upsert`, `index.complete`); `chunk.py` lines 413, 328 (`chunk.substance_gate.complete`, `chunk.substance_gate.conservation_invariant_violated`)
**Apply to:** `dedup.py` (`dedup.complete`, `dedup.conservation_invariant_violated`), `qdrant_store.py`'s new `set_payload` (`qdrant_store.set_payload.point_missing`), the new `dedup_chunks` Dagster asset (`dagster.dedup_chunks.start`/`.complete`, matching `dagster.chunk_document.start`/`.complete` at `assets.py` lines 398, 414 and `dagster.embed_chunks.start`/`.complete` at lines 576, 589).

### Settings resolution + Dagster `_env_file=None` override
**Source:** `embed.py` line 41 (`s = settings or get_settings()`); `assets.py` lines 393-396, 619-622 (`Settings(database_url=postgres.database_url, _env_file=None)`)
**Apply to:** every new/modified pipeline function (`dedup_chunks`) and the new Dagster asset.

### ORDERING INVARIANT (commit Postgres row before external-system write)
**Source:** `index.py` lines 178-184 (register_vector_collection commit before vstore.upsert)
**Apply to:** `dedup.py`'s ledger insert (D-14 — commit the atomic-upsert row before the Qdrant write); `index.py`'s new duplicate-routing branch.

### Conservation invariant (log-then-raise, never bare assert)
**Source:** `chunk.py` lines 315-337 (`_assert_chunk_conservation_invariant`); precedent QUAL-05 from Phase 17
**Apply to:** `dedup.py`'s `len(new) + len(duplicates) == len(chunks_in)` assertion (D-20).

### `_resolve_document_payload_fields()` reuse (unchanged)
**Source:** `index.py` lines 64-129
**Apply to:** both the `new`-path point build (unchanged, existing call at line 191) AND the primary's payload on first-write of a duplicate's ledger row (per RESEARCH.md Code Examples note — call once per `parsed_artifact_id`, same caching idiom as `_build_payload_refresh_fn`, lines 269-286).

### Prefixed-UUID ID generation via `new_id()`
**Source:** `src/knowledge_lake/ids.py` lines 32-47 (`_PREFIX` dict), line 50 (`new_id(kind)`)
**Apply to:** `ChunkDedupLedger.id`. **Landmine:** `_PREFIX` is a closed dict — there is no `"chunk_dedup_ledger"` kind yet. Two options: (a) reuse `new_id("artifact")` → `art_<uuidv7>`, following `VectorCollection`'s own precedent exactly (`VectorCollection.id` docstring literally says "always `art_<uuidv7>` (generic, not a lineage node)", `models.py` line 468); or (b) add a new `"chunk_dedup_ledger": "led"` (or similar) entry to `_PREFIX` in `ids.py` for a self-describing prefix. RESEARCH.md's Pitfall 4 flags this as needing verification before writing the migration — recommend (a) for consistency with the direct analog model.

## No Analog Found

None — every file in this phase's scope has a close existing analog (this phase is additive/extension work, not a novel subsystem).

## Metadata

**Analog search scope:** `src/knowledge_lake/pipeline/`, `src/knowledge_lake/registry/`, `src/knowledge_lake/registry/alembic/versions/`, `src/knowledge_lake/plugins/`, `src/knowledge_lake/dagster_defs/`, `src/knowledge_lake/ids.py`
**Files scanned:** `pipeline/index.py`, `pipeline/embed.py`, `pipeline/chunk.py`, `pipeline/process.py`, `pipeline/clean.py` (referenced, not modified), `registry/models.py`, `registry/repo.py`, `registry/alembic/versions/0010_sources_domain_column.py`, `dagster_defs/assets.py`, `plugins/protocols.py`, `plugins/builtin/qdrant_store.py`, `ids.py`
**Pattern extraction date:** 2026-07-17
