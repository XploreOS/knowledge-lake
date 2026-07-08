# Phase 7: Metadata Foundation - Research

**Researched:** 2026-07-08
**Domain:** Qdrant payload fields, payload index creation, registry source-metadata join, filter extension
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Resolve all source-derived fields in the single `get_session()` block already present in `index.py` (lines ~90–104), once per `index()` call — not once per chunk.
- **D-02:** Field → source mapping (source_id from Artifact, source_name/url/format/tags/organization from Source row and config, title from enriched metadata_).
- **D-03:** Graceful degradation — every field except `source_id` degrades to None/[] when unavailable.
- **D-04:** `format` sourced from `Source.source_type` (not Artifact.mime_type).
- **D-05:** Extend `register_source` to persist `tags` and `organization` into `Source.config` alongside `domain`.
- **D-06:** Minimal data-only change — persist metadata already in sources.yaml; no new crawl/enrich behavior.
- **D-07:** Add idempotent `ensure_payload_indexes()` to QdrantVectorStore with keyword indexes on `source_name`, `format`, `source_id`, `tags`, `domain`, `document_type`.
- **D-08:** Call `ensure_payload_indexes()` from `ensure_aliased_collection()` and from `reindex()` output.
- **D-09:** `tags` uses a keyword index — Qdrant keyword indexes match array-contains natively.
- **D-10:** Extend `search()` with four additive optional kwargs: `source_name`, `format`, `tags`, `source_id`.
- **D-11:** `tags` filter: single tag → `MatchValue(value=tag)`, multiple tags → `MatchAny(any=[...])` (OR).
- **D-12:** CLI flags: `--source-name`, `--format`, `--source-id`, `--tag` (repeatable). API: `source_name`, `format`, `source_id`, `tags` (repeated/CSV).
- **D-13:** New fields populate only on chunks indexed after this phase. Filters on new fields simply don't match pre-Phase-7 points. No forced backfill in this phase.

### Claude's Discretion
- Exact CLI flag naming nuances (`--tag` vs `--tags`), whether the API takes repeated `tags=` vs a CSV string, and the precise ordering of `must` conditions.
- Whether `ensure_payload_indexes()` lives as a new method or folds into existing `ensure_*` methods — as long as D-07/D-08 hold.

### Deferred Ideas (OUT OF SCOPE)
- Quality-score-aware ranking/filtering (QUALITY-01, v2.1).
- Object tags / domain-scoped storage keys (Phase 9, STORE-01/02/03).
- Sparse/hybrid filtering interplay (Phase 10, RETR).
- Adding `organization:` field to healthcare `sources.yaml` (optional nice-to-have).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PAYLOAD-01 | Every indexed chunk carries expanded Qdrant payload: source_id, source_name, source_url, format, tags, title, organization — assembled at the index-time enrichment join, backward-compatible with existing points. | Source row join in repo.py; field mapping table (D-02); graceful degradation pattern (D-03). |
| PAYLOAD-02 | A user can filter search results by source_name, format, tags (array-contains), and source_id across both CLI and REST API, backed by Qdrant keyword payload indexes on each filterable field. | Qdrant create_payload_index API verified; MatchValue/MatchAny confirmed; CLI/API extension pattern established. |
</phase_requirements>

## Summary

Phase 7 is a pure code-extension phase with no new dependencies, no migrations, and no breaking changes. Every touchpoint is an additive extension of an established pattern already present in the v1.0 codebase. The five files to change are `pipeline/index.py`, `pipeline/search.py`, `plugins/builtin/qdrant_store.py`, `registry/repo.py`, `pipeline/ingest.py`, plus CLI (`cli/app.py`) and API (`api/app.py` + `api/schemas.py`) surface additions.

**Critical pre-research discovery:** The CLI `cmd_init` path and the API `load_domain_endpoint` already persist `tags` and `crawl_config` into `Source.config` — they call `registry_repo.create_source()` directly. The ONLY gap is the `register_source()` pipeline function in `ingest.py` (called from `crawl.py` and `discover.py`) which currently only persists `domain`. D-05 scope is narrower than it might appear: extend `register_source()` to accept and persist `tags`/`organization`; do NOT change the CLI init or API load_domain paths.

**Qdrant keyword index for arrays:** Confirmed via direct import that qdrant-client 1.18.0 uses a single `PayloadSchemaType.KEYWORD` for all keyword-indexed fields — whether the payload value is a scalar string or a list of strings. There is no separate "array_keyword" enum value. Qdrant's server interprets keyword-indexed array fields as "contains" matches automatically. `create_payload_index` is idempotent on the REST level.

**Primary recommendation:** Implement in this order — (1) `ensure_payload_indexes()` in qdrant_store, (2) `get_source_metadata()` in repo.py, (3) extend the join in index.py, (4) extend search.py kwargs + filter builder, (5) extend register_source(), (6) extend CLI/API surface, (7) update SearchHit schema.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Payload assembly (7 new fields) | API / Backend (index.py) | Database/Storage (registry join) | index() is the pipeline stage that writes Qdrant points; source metadata comes from the registry |
| Payload index creation | API / Backend (qdrant_store.py) | — | QdrantVectorStore owns all Qdrant schema operations |
| Filter building | API / Backend (search.py) | — | search() is the pipeline function; Filter construction is backend logic |
| CLI filter surface | Frontend Server (CLI) | — | typer app.py exposes user-facing flags that delegate to pipeline |
| REST API filter surface | API / Backend (api/app.py) | — | FastAPI endpoint parameters; SearchHit schema in schemas.py |
| tags persistence | API / Backend (ingest.py) | — | register_source() is a pipeline function; Source.config is the storage target |

## Standard Stack

No new packages in this phase. All work uses already-installed libraries.

### Core (No Changes)

| Library | Installed Version | Purpose | Role in Phase 7 |
|---------|------------------|---------|-----------------|
| qdrant-client | 1.18.0 [VERIFIED: pip show] | Qdrant operations | `create_payload_index`, `MatchAny` addition |
| SQLAlchemy | 2.0.x | ORM | `session.get(Source, source_id)` pattern for source join |
| Pydantic | 2.x | Schema validation | SearchHit schema extension |
| typer | 0.x | CLI | New search flags |
| fastapi | 0.x | REST API | New query params |

**Installation:** None required — this phase adds no new dependencies.

## Package Legitimacy Audit

No new packages are installed in this phase.

| Package | Registry | Verdict | Disposition |
|---------|----------|---------|-------------|
| qdrant-client (existing) | PyPI | OK | Already installed at 1.18.0 |

**Packages removed due to SLOP verdict:** none
**Packages flagged as suspicious SUS:** none

## Architecture Patterns

### System Architecture Diagram

```
sources.yaml
    │
    ▼
DomainLoader / register_source()
    │  (persist tags, organization in Source.config)
    ▼
Source registry row
 .name  .url  .source_type  .config={domain, tags, crawl_config}
    │
    │  index() call
    ▼
get_session() join block (index.py lines 90-104, EXTENDED)
    ├── get_artifact(session, parsed_artifact_id) → Artifact (has .source_id)
    ├── get_domain_for_source(session, artifact.source_id) → domain str
    ├── [NEW] get_source_metadata(session, artifact.source_id) → {name, url, source_type, config}
    └── get_enriched_artifact_for_parsed(session, ...) → enriched metadata (has title)
         │
         ▼
    payload dict assembly (index.py lines 115-126, EXTENDED)
         ├── existing: document, section_path, page, chunk_id, text, domain, document_type, keywords, quality_score
         └── new: source_id, source_name, source_url, format, tags, title, organization
         │
         ▼
    VectorPoint.upsert() → Qdrant collection
         │
         ▼
    ensure_payload_indexes() [NEW — called from ensure_aliased_collection() + reindex()]
         └── create_payload_index(physical_collection, field, PayloadSchemaType.KEYWORD)
             for: source_name, format, source_id, tags, domain, document_type

User query
    │
    ▼
search(query, source_name=?, format=?, tags=?, source_id=?, ...) [search.py EXTENDED]
    │
    ├── Filter.must  ← FieldCondition(key="source_name", match=MatchValue(...))
    ├── Filter.must  ← FieldCondition(key="format", match=MatchValue(...))
    ├── Filter.must  ← FieldCondition(key="source_id", match=MatchValue(...))
    └── Filter.must  ← FieldCondition(key="tags", match=MatchValue(single) | MatchAny(multi))
         │
         ▼
    vstore.search(collection, query_vector, top_k, query_filter)
         │
         ▼
    Hit list → SearchHit (API) / CLI output (with new fields rendered)
```

### Recommended Project Structure

No new directories or modules. All changes are additive to existing files:

```
src/knowledge_lake/
├── pipeline/
│   ├── index.py          # extend get_session() join + payload dict (7 new fields)
│   ├── search.py         # extend search() kwargs + must-filter builder + MatchAny import
│   └── ingest.py         # extend register_source() with tags/organization params
├── plugins/builtin/
│   └── qdrant_store.py   # add ensure_payload_indexes(); call from ensure_aliased_collection + reindex
├── registry/
│   └── repo.py           # add get_source_metadata() getter
├── cli/
│   └── app.py            # extend cmd_search with 4 new flags + render new payload fields
└── api/
    ├── app.py            # extend search_endpoint with 4 new query params; call search() with them
    └── schemas.py        # extend SearchHit with 7 new fields
```

### Pattern 1: Qdrant Payload Index Creation (D-07, D-08, D-09)

**What:** Idempotent keyword index creation on a physical collection.
**When to use:** After creating a new physical collection (bootstrap) or after `upsert_fn` in reindex.
**Example:**

```python
# Source: direct .venv inspection of qdrant_client 1.18.0 installed package
from qdrant_client.models import PayloadSchemaType

def ensure_payload_indexes(self, collection: str) -> None:
    """Create keyword payload indexes on all filterable fields (idempotent).

    Keyword indexes apply to both scalar string fields and array-of-string
    fields — PayloadSchemaType.KEYWORD is the single correct schema type for
    both. Qdrant interprets keyword-indexed arrays as 'contains' at query time.
    Safe to call multiple times (create_payload_index is idempotent on the
    Qdrant REST API — re-creating an existing index is a no-op).
    """
    _KEYWORD_FIELDS = [
        "domain",           # existing filter — index retroactively
        "document_type",    # existing filter — index retroactively
        "source_name",      # new Phase 7 filter
        "format",           # new Phase 7 filter
        "source_id",        # new Phase 7 filter
        "tags",             # new Phase 7 filter (array field; KEYWORD handles it)
    ]
    for field in _KEYWORD_FIELDS:
        self._client.create_payload_index(
            collection_name=collection,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )
    log.info("qdrant_store.ensure_payload_indexes", collection=collection)
```

Call sites in the same class:

```python
# In ensure_aliased_collection(), after creating the physical collection:
self.ensure_payload_indexes(physical)
return (physical, True)

# In reindex(), after upsert_fn(next_physical) but before the alias swap:
upsert_fn(next_physical)
self.ensure_payload_indexes(next_physical)  # index the new physical collection
# ... alias swap operations follow
```

### Pattern 2: Source Metadata Getter in repo.py

**What:** A single session.get() call returning name, url, source_type, and config — exactly parallel to `get_domain_for_source`.
**When to use:** From the `index.py` join block, once per index() call.
**Example:**

```python
# Source: direct read of repo.py lines 820-830 (existing get_domain_for_source pattern)
def get_source_metadata(
    session: Session, source_id: str
) -> Optional[dict]:
    """Return a dict of Source fields needed for the Phase 7 payload join.

    Returns None if the source row does not exist.
    Returns a dict with keys: name, url, source_type, config (may be None).
    """
    source = session.get(Source, source_id)
    if source is None:
        return None
    return {
        "name": source.name,
        "url": source.url,
        "source_type": source.source_type,
        "config": source.config or {},
    }
```

Usage in `index.py` join block (extending lines 90-104):

```python
with get_session() as session:
    parsed_artifact = registry_repo.get_artifact(session, parsed_artifact_id)
    source_id = parsed_artifact.source_id if parsed_artifact is not None else None

    domain = (
        registry_repo.get_domain_for_source(session, source_id)
        if source_id is not None
        else None
    )
    source_meta = (
        registry_repo.get_source_metadata(session, source_id)
        if source_id is not None
        else None
    )

    enriched = registry_repo.get_enriched_artifact_for_parsed(session, parsed_artifact_id)
    if enriched is not None:
        enrichment_metadata = enriched.metadata_ or {}
        quality_score = enriched.quality_score
    else:
        enrichment_metadata = {}
        quality_score = None

# Derive new payload fields from source_meta (all degrade gracefully to None/[])
_sm = source_meta or {}
_sc = _sm.get("config") or {}
source_name = _sm.get("name")
source_url = _sm.get("url")
fmt = _sm.get("source_type")        # D-04: source_type IS the format label
tags = _sc.get("tags", [])
organization = _sc.get("organization")
title = enrichment_metadata.get("title")
```

### Pattern 3: Search Filter Extension (D-10, D-11)

**What:** Extend `search()` kwargs and the `must` list with four new additive conditions.
**When to use:** Any call to search() that wants to filter by source metadata.
**Example:**

```python
# Source: direct read of search.py lines 84-92 (existing filter pattern)
# Add MatchAny to existing import:
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue, Range

def search(
    query: str,
    *,
    collection: str = "klake_chunks",
    top_k: int = 5,
    domain: Optional[str] = None,
    document_type: Optional[str] = None,
    min_quality_score: Optional[float] = None,
    source_name: Optional[str] = None,      # new
    format: Optional[str] = None,           # new
    tags: Optional[list[str]] = None,       # new
    source_id: Optional[str] = None,        # new
    settings: Optional[Settings] = None,
) -> list[Hit]:
    ...
    must: list = []
    if domain:
        must.append(FieldCondition(key="domain", match=MatchValue(value=domain)))
    if document_type:
        must.append(FieldCondition(key="document_type", match=MatchValue(value=document_type)))
    if min_quality_score is not None:
        must.append(FieldCondition(key="quality_score", range=Range(gte=min_quality_score)))
    # Phase 7 additions:
    if source_name:
        must.append(FieldCondition(key="source_name", match=MatchValue(value=source_name)))
    if format:
        must.append(FieldCondition(key="format", match=MatchValue(value=format)))
    if source_id:
        must.append(FieldCondition(key="source_id", match=MatchValue(value=source_id)))
    if tags:
        if len(tags) == 1:
            must.append(FieldCondition(key="tags", match=MatchValue(value=tags[0])))
        else:
            must.append(FieldCondition(key="tags", match=MatchAny(any=tags)))
    query_filter = Filter(must=must) if must else None
```

### Pattern 4: CLI Flag Extension (D-12)

**What:** Add four typer.Option flags to cmd_search, mirroring `--domain`/`--document-type` style.
**When to use:** Search command, immediately following existing filter flags.

```python
# Source: direct read of cli/app.py lines 633-663 (existing cmd_search pattern)
source_name: Optional[str] = typer.Option(
    None, "--source-name", help="Filter results to this source_name."
),
format: Optional[str] = typer.Option(
    None, "--format", help="Filter results to this format (e.g. 'html', 'pdf')."
),
source_id: Optional[str] = typer.Option(
    None, "--source-id", help="Filter results to this source_id."
),
tag: Optional[list[str]] = typer.Option(
    None, "--tag", help="Filter results to chunks tagged with this tag (repeatable; OR logic)."
),
```

Note: typer uses `list[str]` with a repeated `--tag` flag for multi-value. Pass as `tags=tag` to `search()`.

### Pattern 5: API Query Param + SearchHit Schema Extension (D-12)

**What:** Add four Query() params to search_endpoint and 7 new fields to SearchHit.
**Example:**

```python
# Source: direct read of api/app.py lines 153-225 (existing search_endpoint pattern)
source_name: Optional[str] = Query(default=None, description="Filter by source_name."),
format: Optional[str] = Query(default=None, description="Filter by format (e.g. 'html', 'pdf')."),
source_id: Optional[str] = Query(default=None, description="Filter by source_id."),
tags: Optional[list[str]] = Query(default=None, description="Filter by tags (repeatable; OR logic)."),
```

For `SearchHit` in schemas.py, add 7 new optional fields matching the payload additions.

### Anti-Patterns to Avoid

- **Per-chunk DB query:** Do not call `session.get(Source, ...)` inside the chunk loop. The existing pattern does ONE join per `index()` call. Phase 7 must follow the same discipline.
- **Separate PayloadSchemaType for arrays:** `PayloadSchemaType.KEYWORD` handles both scalar and array fields. Do not invent a non-existent `ARRAY_KEYWORD` value.
- **format = mime_type:** D-04 is explicit: `format = Source.source_type` (already the short label). Do not map `Artifact.mime_type` through a mime→format table.
- **Backfill via reindex_collection:** The existing `reindex_collection()` in `index.py` calls `copy_all_points()` which copies payloads verbatim. This does NOT synthesize new fields. Document the backward-compat contract in the docstring — do not change the copy logic.
- **create_payload_index on alias name:** Always call on the physical collection name, not the alias. The alias resolves at query time; index operations target the physical layer.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Keyword index for array fields | Custom "array contains" post-filter | `create_payload_index(field_schema=PayloadSchemaType.KEYWORD)` + `MatchValue`/`MatchAny` | Qdrant handles array containment natively at the index level; a post-filter would defeat the performance goal |
| Multi-value OR filter | Custom Python-side intersection | `MatchAny(any=[...])` | Already in qdrant_client.models; one line |
| Source metadata join | New API call per chunk | Single `session.get(Source, source_id)` once per `index()` call (D-01) | N+1 query problem |

**Key insight:** Qdrant's keyword index is the single correct primitive for all filterable string/tag fields in this phase — there is no special handling needed for arrays.

## Runtime State Inventory

Not applicable. Phase 7 is a greenfield extension — no rename, rebrand, or migration. Existing Qdrant points are unaffected (backward-compat contract: new fields only on points indexed after this phase).

## Common Pitfalls

### Pitfall 1: create_payload_index on alias vs physical collection

**What goes wrong:** Calling `create_payload_index(collection_name=alias, ...)` where alias is the logical name (e.g. `klake_chunks`). In `ensure_payload_indexes()`, the method receives the physical collection name from the caller — this is correct. Pitfall arises if someone refactors to pass the alias instead.
**Why it happens:** The alias is what users pass to search/index; developers may reflexively reuse it.
**How to avoid:** `ensure_payload_indexes(physical)` always takes the physical collection name. Document this in the method docstring.
**Warning signs:** Index creation succeeds but filtered searches still scan all points (explain endpoint shows no index hit).

### Pitfall 2: Missing MatchAny import in search.py

**What goes wrong:** `MatchAny` is not in the current import in `search.py` (current: `FieldCondition, Filter, MatchValue, Range`). Omitting `MatchAny` causes a NameError at runtime only when multiple tags are passed.
**Why it happens:** Single-tag path (D-11) uses `MatchValue` which is already imported; the multi-tag path (D-11) needs `MatchAny` — easy to add the filter logic but forget the import.
**How to avoid:** Add `MatchAny` to the import line before writing the filter logic.
**Warning signs:** `NameError: name 'MatchAny' is not defined` at search time with multiple `--tag` flags.

### Pitfall 3: register_source() tags gap vs CLI/API init paths

**What goes wrong:** Confusing which path needs the fix. The CLI `cmd_init` and API `load_domain_endpoint` **already** call `registry_repo.create_source()` directly with `config={"domain": ..., "tags": ..., "crawl_config": ...}` — these paths are CORRECT. The ONLY path that needs fixing is the `register_source()` pipeline function in `ingest.py` (called from `crawl.py`).
**Why it happens:** There are three different code paths that register sources; only one is broken for tags.
**How to avoid:** Extend `register_source()` in `ingest.py` with `tags` and `organization` kwargs, update the config dict construction at line 277.
**Warning signs:** Sources registered via `klake crawl` have empty `tags` in payload; sources registered via `klake init` have tags correctly.

### Pitfall 4: Payload index called before points are loaded in reindex

**What goes wrong:** Calling `ensure_payload_indexes(next_physical)` before `upsert_fn(next_physical)` in `reindex()`. The index creation itself succeeds (Qdrant allows indexing empty collections), but it does not matter — what matters is that the alias swap only happens after both `upsert_fn` and `ensure_payload_indexes` have completed on the new physical collection.
**Why it happens:** The natural place for `ensure_payload_indexes` in reindex() is after `upsert_fn` but before the alias swap operations.
**How to avoid:** Order: (1) create_collection, (2) upsert_fn(next_physical), (3) ensure_payload_indexes(next_physical), (4) alias swap. Index creation before or after upsert is functionally fine, but after makes the intent clear.
**Warning signs:** Not a runtime error; just a code-readability/ordering concern.

### Pitfall 5: SearchHit schema not updated for new payload fields

**What goes wrong:** `api/app.py` extracts payload fields into `SearchHit` explicitly (lines 228-245). If `SearchHit` is not updated with the 7 new fields, the API silently drops them even though the underlying Qdrant payload carries them.
**Why it happens:** The payload passthrough in `Hit.payload` is untyped; only fields explicitly extracted in the schema mapping appear in the JSON response.
**How to avoid:** Add all 7 new fields to `SearchHit` in `schemas.py` (source_id, source_name, source_url, format, tags, title, organization) and update the `payload.get(...)` extraction in `app.py`.
**Warning signs:** `/search` returns results but new fields are absent from the JSON response even after re-indexing.

## Code Examples

### Verified qdrant-client 1.18.0 API patterns

#### create_payload_index signature (VERIFIED: .venv/bin/python -c "import inspect; inspect.signature(QdrantClient.create_payload_index)")

```python
client.create_payload_index(
    collection_name="klake_chunks_v1",   # physical collection, NOT alias
    field_name="source_name",
    field_schema=PayloadSchemaType.KEYWORD,  # same type for scalar AND array fields
    wait=True,    # default True — wait for operation to complete
)
# Returns: UpdateResult — idempotent; re-creating an existing index is a no-op
```

#### MatchAny and MatchValue for array field (VERIFIED: .venv/bin/python constructor test)

```python
# Single tag — array-contains semantics (D-11)
FieldCondition(key="tags", match=MatchValue(value="fhir"))

# Multiple tags — OR logic (D-11)  
FieldCondition(key="tags", match=MatchAny(any=["fhir", "hl7"]))

# Note: MatchAny is NOT currently imported in search.py — must be added
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue, Range
```

#### PayloadSchemaType enum values (VERIFIED: .venv inspection)

```python
# qdrant-client 1.18.0 — full list
list(PayloadSchemaType)
# [KEYWORD, INTEGER, FLOAT, GEO, TEXT, BOOL, DATETIME, UUID]
# There is NO ARRAY_KEYWORD value. KEYWORD handles array fields natively.
```

#### session.get(Source, source_id) pattern (VERIFIED: direct read of repo.py line 827)

```python
# Existing pattern from get_domain_for_source (repo.py:820-830)
def get_source_metadata(session: Session, source_id: str) -> Optional[dict]:
    source = session.get(Source, source_id)  # uses PK lookup — no SELECT needed
    if source is None:
        return None
    return {
        "name": source.name,
        "url": source.url,
        "source_type": source.source_type,   # D-04: this IS the format label
        "config": source.config or {},
    }
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Unindexed payload filters (existing) | Keyword payload indexes per filterable field | Phase 7 | Filtered searches become efficient; full-collection scan eliminated |
| domain/document_type only as filters | +source_name, format, source_id, tags | Phase 7 | Rich metadata filtering for agent and user queries |

**Deprecated/outdated:**
- None in this phase.

## Assumptions Log

All claims in this research were verified directly from the installed codebase and `.venv`. No assumed facts.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| — | (none) | — | — |

**This table is empty:** All claims in this research were verified or cited — no user confirmation needed.

## Open Questions (RESOLVED)

1. **`--tag` vs `--tags` CLI flag name**
   - RESOLVED: `--tag` (repeatable) chosen per Claude's Discretion (CONTEXT.md). Implemented in Plan 04 as `--tag` with `multiple=True`. Convention: `klake search --tag fhir --tag hl7`.

2. **Whether `ensure_payload_indexes()` should also index `keywords` (the LLM-extracted array field)**
   - RESOLVED: `keywords` added opportunistically to `_KEYWORD_FIELDS` in Plan 03. Zero extra cost, same `KEYWORD` type, makes the existing `keywords` field scan-free. Out of PAYLOAD-02 success criteria but included in the implementation.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| qdrant-client | All Qdrant operations | Yes | 1.18.0 | — |
| MatchAny (qdrant_client.models) | tags multi-value filter | Yes | 1.18.0 | — |
| PayloadSchemaType.KEYWORD | ensure_payload_indexes | Yes | 1.18.0 | — |
| PostgreSQL (SQLAlchemy) | Source registry join | Yes (Docker) | 16+ | — |
| Pytest | Unit tests | Yes | 9.1.1 | — |

**Missing dependencies with no fallback:** none
**Missing dependencies with fallback:** none

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run pytest tests/unit/ -v` |
| Full suite command | `uv run pytest tests/ -v -m "not integration"` |
| Integration tests | `uv run pytest tests/integration/ -v -m integration` (requires Docker services) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PAYLOAD-01 | Index() upserts 7 new payload fields when source row has them | unit | `pytest tests/unit/test_index_payload.py -x` | Extend existing |
| PAYLOAD-01 | Index() degrades gracefully when source_meta is None | unit | `pytest tests/unit/test_index_payload.py -x` | Extend existing |
| PAYLOAD-01 | title comes from enriched_metadata.get("title") | unit | `pytest tests/unit/test_index_payload.py -x` | Extend existing |
| PAYLOAD-02 | search() with source_name filter builds correct FieldCondition | unit | `pytest tests/unit/test_search_filters.py -x` | Extend existing |
| PAYLOAD-02 | search() with format filter builds correct FieldCondition | unit | `pytest tests/unit/test_search_filters.py -x` | Extend existing |
| PAYLOAD-02 | search() with source_id filter builds correct FieldCondition | unit | `pytest tests/unit/test_search_filters.py -x` | Extend existing |
| PAYLOAD-02 | search() with single tag uses MatchValue (array-contains) | unit | `pytest tests/unit/test_search_filters.py -x` | Extend existing |
| PAYLOAD-02 | search() with multiple tags uses MatchAny (OR logic) | unit | `pytest tests/unit/test_search_filters.py -x` | Extend existing |
| PAYLOAD-02 | ensure_payload_indexes() calls create_payload_index for each field | unit | `pytest tests/unit/test_qdrant_payload_indexes.py -x` | Wave 0 gap |
| PAYLOAD-02 | ensure_aliased_collection() calls ensure_payload_indexes() on new physical | unit | `pytest tests/unit/test_qdrant_payload_indexes.py -x` | Wave 0 gap |
| PAYLOAD-02 | reindex() calls ensure_payload_indexes() on new physical collection | unit | `pytest tests/unit/test_qdrant_payload_indexes.py -x` | Wave 0 gap |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/unit/ -v -q`
- **Per wave merge:** `uv run pytest tests/ -v -m "not integration"`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/test_qdrant_payload_indexes.py` — covers `ensure_payload_indexes()` (D-07, D-08, D-09). New file needed; mock `QdrantVectorStore._client.create_payload_index` and assert it is called for each field name in `_KEYWORD_FIELDS`. Also verify `ensure_aliased_collection()` calls `ensure_payload_indexes(physical)` and `reindex()` calls `ensure_payload_indexes(next_physical)`.
- The existing `tests/unit/test_index_payload.py` and `tests/unit/test_search_filters.py` extend in-place (no new files, just new test classes).

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes | Existing: top_k bounded, collection name regex, quality_score bounded. New filter params (source_name, format, source_id, tags) must follow same `Optional[str]` / `Optional[list[str]]` Pydantic types — no length/pattern constraints needed beyond what Qdrant safely handles as string payloads |
| V6 Cryptography | no | — |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Qdrant collection enumeration via arbitrary collection param | Information Disclosure | Existing: `_COLLECTION_NAME_RE.fullmatch(collection)` guard in `api/app.py` — unchanged |
| Oversized tags array causing memory pressure | Denial of Service | Pydantic `list[str]` with optional `max_length` on each element; follow existing `max_length=64` pattern from other string params |
| Path traversal via source_name/format filter values | Tampering | Moot — these are search filter strings, not filesystem paths. Qdrant parameterized query handles them safely. |

## Sources

### Primary (HIGH confidence)
- Direct codebase reads + `.venv` Python introspection — qdrant-client 1.18.0 installed package, `PayloadSchemaType`, `MatchAny`, `create_payload_index` signature all confirmed via running Python process in `.venv`
- Direct file reads: `pipeline/index.py`, `pipeline/search.py`, `plugins/builtin/qdrant_store.py`, `registry/repo.py`, `registry/models.py`, `pipeline/ingest.py`, `cli/app.py` (lines 633-685, 933-1030), `api/app.py` (lines 148-247, 1340-1411), `api/schemas.py`, `domains/healthcare/sources.yaml`, `domains/models.py`, `tests/unit/test_index_payload.py`, `tests/unit/test_search_filters.py`

### Secondary (MEDIUM confidence)
- `.planning/research/SUMMARY.md` Phase 7 section — project research confirming no new deps, payload-before-filters ordering, Qdrant keyword-index idiom

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — qdrant-client 1.18.0 verified installed; all model imports confirmed
- Architecture: HIGH — all touchpoints read directly from source; exact line numbers cited
- Pitfalls: HIGH — sourced from direct code inspection of the three parallel registration paths
- Test patterns: HIGH — existing test files read and confirmed passing (11/11)

**Research date:** 2026-07-08
**Valid until:** 2026-08-08 (stable stack; no fast-moving dependencies)
