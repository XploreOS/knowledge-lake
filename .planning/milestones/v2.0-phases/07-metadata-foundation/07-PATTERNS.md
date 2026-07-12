# Phase 7: Metadata Foundation - Pattern Map

**Mapped:** 2026-07-08
**Files analyzed:** 7
**Analogs found:** 7 / 7

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/knowledge_lake/pipeline/index.py` | pipeline stage | transform | itself (lines 90-126) | exact |
| `src/knowledge_lake/pipeline/search.py` | pipeline stage | request-response | itself (lines 85-92) | exact |
| `src/knowledge_lake/plugins/builtin/qdrant_store.py` | plugin | request-response | itself — `ensure_collection`, `upsert`, `search` methods | exact |
| `src/knowledge_lake/registry/repo.py` | repository | CRUD | `get_domain_for_source` (lines 820-830), `get_artifact` (line 323) | exact |
| `src/knowledge_lake/pipeline/ingest.py` | pipeline stage | CRUD | itself — `register_source` (lines 277-286) | exact |
| `src/knowledge_lake/api/app.py` | controller | request-response | `search_endpoint` (lines 229-245) | exact |
| `src/knowledge_lake/cli/app.py` | CLI command | request-response | `cmd_search` (lines 633-685) | exact |

---

## Pattern Assignments

### `src/knowledge_lake/pipeline/index.py` — extend payload dict + source join

**Analog:** itself, lines 87-126

**Existing source join pattern** (lines 90-104):
```python
with get_session() as session:
    parsed_artifact = registry_repo.get_artifact(session, parsed_artifact_id)
    domain = (
        registry_repo.get_domain_for_source(session, parsed_artifact.source_id)
        if parsed_artifact is not None
        else None
    )

    enriched = registry_repo.get_enriched_artifact_for_parsed(session, parsed_artifact_id)
    if enriched is not None:
        enrichment_metadata = enriched.metadata_ or {}
        quality_score = enriched.quality_score
    else:
        enrichment_metadata = {}
        quality_score = None
```

**Extension target: add a second source lookup inside the same `with get_session()` block** to fetch `Source` row fields (name, url, source_type, license_type, tags from config). Follow this pattern:
```python
# After the existing domain = get_domain_for_source(...) call, still inside the same session:
source = registry_repo.get_source(session, parsed_artifact.source_id) if parsed_artifact else None
source_name = source.name if source else None
source_url = source.url if source else None
source_type = source.source_type if source else None
license_type = source.license_type if source else None
tags = (source.config or {}).get("tags", []) if source else []
```

**Existing payload dict** (lines 115-126):
```python
payload = {
    "document": parsed_artifact_id,
    "section_path": chunk.get("section_path", ""),
    "page": chunk.get("page", 1),
    "chunk_id": full_chunk_id,
    "qdrant_id": qdrant_point_id,
    "text": chunk.get("text", ""),
    "domain": domain,
    "document_type": enrichment_metadata.get("document_type"),
    "keywords": enrichment_metadata.get("keywords", []),
    "quality_score": quality_score,
}
```

**Extension target: append 7 new fields to the payload dict** following the same `key: value_or_default` style:
```python
    "source_name": source_name,
    "source_url": source_url,
    "source_type": source_type,
    "license_type": license_type,
    "tags": tags,
    # source_id already carried as part of document lineage — add explicit field
    "source_id": parsed_artifact.source_id if parsed_artifact else None,
    # ingested_at from source.created_at — ISO string or None
    "ingested_at": source.created_at.isoformat() if source and source.created_at else None,
```

---

### `src/knowledge_lake/pipeline/search.py` — add filter kwargs + MatchAny import

**Analog:** itself, lines 20-92

**Existing filter pattern** (lines 25, 85-92):
```python
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range

must: list = []
if domain:
    must.append(FieldCondition(key="domain", match=MatchValue(value=domain)))
if document_type:
    must.append(FieldCondition(key="document_type", match=MatchValue(value=document_type)))
if min_quality_score is not None:
    must.append(FieldCondition(key="quality_score", range=Range(gte=min_quality_score)))
query_filter = Filter(must=must) if must else None
```

**Extension target: add `MatchAny` to the import** and add 4 new `if` blocks following the exact same pattern:
```python
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue, Range

# New kwargs in function signature (after existing ones):
#   tags: Optional[list[str]] = None,
#   source_name: Optional[str] = None,
#   source_type: Optional[str] = None,
#   source_id: Optional[str] = None,

if tags:
    must.append(FieldCondition(key="tags", match=MatchAny(any=tags)))
if source_name:
    must.append(FieldCondition(key="source_name", match=MatchValue(value=source_name)))
if source_type:
    must.append(FieldCondition(key="source_type", match=MatchValue(value=source_type)))
if source_id:
    must.append(FieldCondition(key="source_id", match=MatchValue(value=source_id)))
```

Note: `tags` uses `MatchAny` (list match) while scalar string fields use `MatchValue` — copy the Range pattern only for numeric fields.

---

### `src/knowledge_lake/plugins/builtin/qdrant_store.py` — add ensure_payload_indexes()

**Analog:** `ensure_collection` method (lines 74-97) and `ensure_aliased_collection` (lines 99-136)

**Method structure pattern** (lines 74-97):
```python
def ensure_collection(
    self, name: str, dim: int, distance: str = "Cosine"
) -> None:
    """Create a Qdrant collection if it does not already exist (idempotent).
    ...
    """
    if self._client.collection_exists(name):
        log.debug("qdrant_store.collection_exists", collection=name)
        return

    dist = self._distance_from_name(distance)

    log.info("qdrant_store.create_collection", collection=name, dim=dim, distance=distance)
    self._client.create_collection(
        collection_name=name,
        vectors_config=self._VectorParams(size=dim, distance=dist),
    )
```

**New method to add** — follow the same idempotency-guard + structlog pattern:
```python
def ensure_payload_indexes(self, collection: str) -> None:
    """Create keyword payload indexes for filterable fields (idempotent).

    Called once after ensure_aliased_collection() so that tag/source_name/
    source_type/source_id filters use indexed paths instead of full scans.
    Uses create_payload_index() with PayloadSchemaType.KEYWORD.
    Qdrant create_payload_index is idempotent — re-running is safe.
    """
    from qdrant_client.models import PayloadSchemaType

    INDEXED_FIELDS = ["tags", "source_name", "source_type", "source_id"]
    for field in INDEXED_FIELDS:
        log.info("qdrant_store.ensure_payload_index", collection=collection, field=field)
        self._client.create_payload_index(
            collection_name=collection,
            field_name=field,
            field_schema=PayloadSchemaType.KEYWORD,
        )
```

**Imports pattern**: all `qdrant_client.models` imports use lazy local imports inside methods (see lines 127, 217) — follow the same `from qdrant_client.models import ...` inside the method body.

---

### `src/knowledge_lake/registry/repo.py` — add get_source() helper

**Analog:** `get_artifact` (line 323) and `get_domain_for_source` (lines 820-830)

**Simplest getter pattern** (line 323):
```python
def get_artifact(session: Session, artifact_id: str) -> Optional[Artifact]:
    """Fetch an artifact by its primary key.

    Returns None if not found (does not raise).
    """
    return session.get(Artifact, artifact_id)
```

**More complex getter reading config** (lines 820-830):
```python
def get_domain_for_source(session: Session, source_id: str) -> Optional[str]:
    """Return the domain classification stored in Source.config, or None."""
    source = session.get(Source, source_id)
    if source is None or not source.config:
        return None
    return source.config.get("domain")
```

**New helper to add** — follow the `get_artifact` pattern exactly:
```python
def get_source(session: Session, source_id: str) -> Optional[Source]:
    """Fetch a Source by its primary key.

    Returns None if not found (does not raise).
    """
    return session.get(Source, source_id)
```

`Source` is already imported at line 46 — no new import needed.

---

### `src/knowledge_lake/pipeline/ingest.py` — fix register_source to persist tags

**Analog:** itself, lines 277 and 1391-1401 (in app.py `_register_domain_sources`)

**Current config construction** (line 277):
```python
config = {"domain": domain} if domain else None
```

**Domain-pack config that already persists tags** (api/app.py lines 1394-1401):
```python
registry_repo.create_source(
    session,
    ...
    config={
        "domain": name,
        "tags": entry.tags,
        "crawl_config": entry.crawl_config,
        "ingest_type": entry.ingest_type,
    },
)
```

**Extension target**: change `register_source` signature to accept `tags: Optional[list[str]] = None` and expand config:
```python
# Old:
config = {"domain": domain} if domain else None

# New:
config: dict = {}
if domain:
    config["domain"] = domain
if tags:
    config["tags"] = tags
config = config or None
```

---

### `src/knowledge_lake/api/app.py` — extend SearchHit schema + search endpoint params

**Analog:** `search_endpoint` (lines 153-248) and `SearchHit` in `api/schemas.py` (lines 57-85)

**Existing SearchHit fields** (schemas.py lines 57-85):
```python
class SearchHit(BaseModel):
    id: str = Field(...)
    score: float = Field(...)
    document: str = Field(...)
    section_path: str = Field(...)
    page: int = Field(...)
    chunk_id: str = Field(...)
    text: str = Field(default="", ...)
    domain: Optional[str] = Field(default=None, ...)
    document_type: Optional[str] = Field(default=None, ...)
    keywords: list[str] = Field(default_factory=list, ...)
    quality_score: Optional[float] = Field(default=None, ...)
```

**Extension target in schemas.py** — append 7 new fields following the same `Optional[str]` / `list[str]` convention:
```python
    source_name: Optional[str] = Field(default=None, description="Human-readable source name.")
    source_url: Optional[str] = Field(default=None, description="Canonical source URL.")
    source_type: Optional[str] = Field(default=None, description="Source type (e.g. 'web', 'upload').")
    license_type: Optional[str] = Field(default=None, description="SPDX license identifier.")
    tags: list[str] = Field(default_factory=list, description="Source tags from config.")
    source_id: Optional[str] = Field(default=None, description="Registry source ID.")
    ingested_at: Optional[str] = Field(default=None, description="ISO-8601 source ingestion timestamp.")
```

**Existing payload extraction pattern** (app.py lines 229-245):
```python
result.append(
    SearchHit(
        id=hit.id,
        score=hit.score,
        document=payload.get("document", ""),
        ...
        domain=payload.get("domain"),
        document_type=payload.get("document_type"),
        keywords=payload.get("keywords", []),
        quality_score=payload.get("quality_score"),
    )
)
```

**Extension target**: add 7 new `payload.get(...)` calls to the `SearchHit(...)` constructor following the same pattern.

**Existing Query param pattern** (app.py lines 165-178):
```python
domain: Optional[str] = Query(default=None, description="Filter results to this domain."),
document_type: Optional[str] = Query(default=None, description="..."),
min_quality_score: Optional[float] = Query(default=None, ge=0.0, le=1.0, description="..."),
```

**Extension target**: add 4 new `Query` parameters to `search_endpoint` using the same `Optional[str] = Query(default=None, ...)` form:
```python
tags: Optional[list[str]] = Query(default=None, description="Filter results where payload tags contain any of these values."),
source_name: Optional[str] = Query(default=None, description="Filter results to this source name."),
source_type: Optional[str] = Query(default=None, description="Filter results to this source type."),
source_id: Optional[str] = Query(default=None, description="Filter results to this source ID."),
```

Then pass them through to `search(...)` using the existing positional-pass-through pattern (lines 218-225).

---

### `src/knowledge_lake/cli/app.py` — add new flags to search command

**Analog:** `cmd_search` (lines 633-685)

**Existing flag pattern** (lines 640-648):
```python
domain: Optional[str] = typer.Option(
    None, "--domain", help="Filter results to this domain."
),
document_type: Optional[str] = typer.Option(
    None, "--document-type", help="Filter results to this document_type."
),
min_quality_score: Optional[float] = typer.Option(
    None, "--min-quality-score", help="Filter results to quality_score >= this value."
),
```

**Extension target**: add 4 new `typer.Option` flags using the exact same form:
```python
tags: Optional[list[str]] = typer.Option(
    None, "--tag", help="Filter results where tags contain this value (repeatable: --tag a --tag b)."
),
source_name: Optional[str] = typer.Option(
    None, "--source-name", help="Filter results to this source name."
),
source_type: Optional[str] = typer.Option(
    None, "--source-type", help="Filter results to this source type."
),
source_id: Optional[str] = typer.Option(
    None, "--source-id", help="Filter results to this source ID."
),
```

Note: Typer handles `list[str]` options by allowing `--tag a --tag b` repeated flags natively.

**Existing output pattern** (lines 673-684):
```python
typer.echo(f"      domain:       {payload.get('domain', '?')}")
typer.echo(f"      document_type:{payload.get('document_type', '?')}")
typer.echo(f"      quality_score:{payload.get('quality_score', '?')}")
```

**Extension target**: add source metadata fields to the output block with the same `payload.get(key, '?')` style.

---

## Shared Patterns

### Session context manager
**Source:** `src/knowledge_lake/pipeline/index.py` lines 90-104, `src/knowledge_lake/registry/db.py`
**Apply to:** `index.py` source join extension

```python
with get_session() as session:
    parsed_artifact = registry_repo.get_artifact(session, parsed_artifact_id)
    # All lookups inside one session block — not one session per lookup
```

### Graceful null defaults
**Source:** `src/knowledge_lake/pipeline/index.py` lines 91-104
**Apply to:** `index.py` payload extension

Every new source field must degrade gracefully to `None` or `[]` when the source row is missing (mirrors `domain = None if parsed_artifact is None` pattern). Never raise on missing source.

### structlog field naming
**Source:** `src/knowledge_lake/plugins/builtin/qdrant_store.py` lines 93, 115
**Apply to:** `qdrant_store.py` new method

```python
log.info("qdrant_store.ensure_payload_index", collection=collection, field=field)
# Format: "<module>.<method_short_name>", kwargs = all relevant state
```

### ORM-only queries
**Source:** `src/knowledge_lake/registry/repo.py` (entire file)
**Apply to:** `repo.py` new `get_source()` helper

All queries use `session.get()` or `select(Model).where(...)` — never raw SQL strings (T-01-03).

---

## No Analog Found

All files have strong analogs in the existing codebase. No new patterns are needed from RESEARCH.md.

## Metadata

**Analog search scope:** `src/knowledge_lake/pipeline/`, `src/knowledge_lake/plugins/`, `src/knowledge_lake/registry/`, `src/knowledge_lake/api/`, `src/knowledge_lake/cli/`
**Files scanned:** 7
**Pattern extraction date:** 2026-07-08
