# Phase 9: Storage Segmentation - Research

**Researched:** 2026-07-09
**Domain:** S3/MinIO object storage key layout, boto3 tagging API, Python urllib URL-encoding
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Key format changes to `{zone}/{domain}/{source_id}/{hash}.{ext}` for raw, bronze, and silver zones. `_unclassified` is the fallback when `domain` is `None` or empty — a real routed segment, never an empty string, `//`, or the literal `"None"`.
- **D-02:** `put_raw` gains `domain: Optional[str] = None` kwarg. Callers resolve domain via `get_domain_for_source(source_id, session)` and pass it in. The storage layer (`s3.py`) never calls the registry.
- **D-03:** Same pattern for `put_bronze(..., domain=None)` — domain-scoped bronze key.
- **D-04:** Silver-zone key construction updated in `parse.py` and `clean.py`; callers resolve domain via `get_domain_for_source()` inside their existing `get_session()` block.
- **D-05:** `get_artifact_by_hash` no-op MUST remain ordered BEFORE key construction in `put_raw`/`put_bronze`. Domain enters only at Layer 3 (key construction), never before.
- **D-06:** Forward-only. Existing raw/bronze/silver keys are never rewritten. No Alembic migration, no backfill.
- **D-07:** `put_object` gains `tags: Optional[dict[str, str]] = None` kwarg. URL-encoded via private helper `_format_tags(tags)` and passed to `_client.put_object(Tagging=...)`. Atomic with the object write.
- **D-08:** Tagging is inline in the same `put_object` call — not via `put_object_tagging()`. Avoids partial-state risk.
- **D-09:** Four standard tags: `domain`, `source_name`, `format`, `artifact_type`. Values capped at 256 chars. Total = 4 (within S3 10-tag limit).
- **D-10:** Tagging is best-effort only — a `ClientError` MUST NOT abort the object write. Log a warning and retry `put_object` without `Tagging=`.
- **D-11:** Tags populated at each write site — raw/bronze/silver/gold all pass different `artifact_type` values.
- **D-12:** Gold-zone key format: `{s.export.gold_prefix}/{domain}/rag_corpus/{export_id}.parquet`, `/pretrain/{export_id}.jsonl`, `/finetune/{dataset_id}.jsonl`.
- **D-13:** Gold-zone `domain` comes from the `domain` filter argument on the export functions. If `domain=None`, use `_unclassified`.
- **D-14:** No new parameters are needed in the export function signatures — the existing `domain` filter kwarg doubles as the key-segment value.

### Claude's Discretion

- Whether `_format_tags` is a module-level function or a static method on `StorageBackend` in `s3.py`.
- Exact URL-encoding implementation for the tag string (`urllib.parse.urlencode` is the obvious choice).
- Exact `ClientError` error codes to catch for the tagging fallback (broad `ClientError` + warning log acceptable).
- Whether `get_domain_for_source` is called at the pipeline function entry point or inside the `get_session()` block — must stay inside the session.
- Exact naming of the domain kwarg in `put_raw`/`put_bronze` (`domain` is the clearest choice).

### Deferred Ideas (OUT OF SCOPE)

- Backfill of existing raw/bronze/silver objects to domain-scoped keys.
- Object lock / WORM bucket policy changes.
- Tag-based S3 lifecycle policies or cost-allocation tagging.
- Per-domain S3 bucket segmentation.
- Multi-domain export with per-domain gold objects as batched splits.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| STORE-01 | Objects written under `{zone}/{domain}/{source_id}/{hash}.{ext}` with `_unclassified` fallback, forward-only, dedup/lineage ordering preserved | s3.py Layer 3 key construction change; parse.py/clean.py f-string updates; ingest.py/crawl.py caller domain resolution |
| STORE-02 | Every object write applies S3 object tags within 10-tag limit, best-effort only | `put_object` Tagging= kwarg; `_format_tags` helper; ClientError fallback pattern |
| STORE-03 | Gold zone segmented by domain and dataset type | export.py key f-string updates; `domain or "_unclassified"` segment |
</phase_requirements>

## Summary

Phase 9 is a **code-only, forward-only refactoring phase** — no migrations, no new packages, no schema changes. Every change is an additive, backward-compatible extension to existing function signatures and key-construction f-strings. The four-layer WORM immutability contract in `s3.py` is preserved exactly; domain only enters at Layer 3 (after the hash is known and registry no-op has passed).

The work divides cleanly across six files: `s3.py` receives three additions (a `_format_tags` helper, `tags=` on `put_object`, and `domain=` on `put_raw`/`put_bronze`); `parse.py` and `clean.py` each receive one f-string update plus a domain resolution call (moved inside the existing session block); `export.py` receives three f-string updates plus a `domain` kwarg on each export function (see Pitfall 2 below); and `ingest.py`/`crawl.py` receive domain resolution and tag dict construction at each `put_raw`/`put_bronze` call site.

**Primary recommendation:** Build in this order: (1) `_format_tags` + `put_object` tagging + best-effort fallback, (2) `put_raw`/`put_bronze` domain-scoped key, (3) `parse.py`/`clean.py` silver domain scope, (4) `ingest.py`/`crawl.py` caller domain resolution, (5) `export.py` gold domain scope. Write unit tests for each layer before moving to the next.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| S3 key layout (domain scoping) | Storage layer (`s3.py`) | Pipeline callers | Key construction lives in `s3.py` so all zone-level writers benefit automatically |
| Domain resolution | Pipeline layer (callers) | Registry (`repo.py`) | Storage layer must stay registry-free (D-02); callers resolve and pass domain down |
| S3 object tag encoding | Storage layer (`s3.py`) | — | Tag format is an S3 API concern; `_format_tags` lives beside `put_object` |
| Tag value population | Pipeline layer (callers) | — | Only callers know context-specific values (source_name, artifact_type) |
| Gold key segmentation | Pipeline export layer (`export.py`) | — | Gold-zone prefix lives in the export stage, mirrors `_SILVER_PREFIX` / `_GOLD_PREFIX` pattern |

## Standard Stack

### No new packages required

This phase makes NO new package additions. All required APIs are already available:

| API | Module | Purpose |
|-----|--------|---------|
| `boto3.client.put_object(Tagging=...)` | `boto3` (1.43.x, already installed) | S3 object tagging, inline with write |
| `urllib.parse.urlencode` | Python stdlib | URL-encode tag dict to `key=val&key=val` string |
| `botocore.exceptions.ClientError` | `botocore` (already installed, imported in `s3.py`) | Catch tagging-related errors for best-effort fallback |
| `get_domain_for_source(session, source_id)` | `knowledge_lake.registry.repo` | Domain resolution from `Source.config["domain"]`; already imported where needed |

**No `npm install`, `pip install`, or `pyproject.toml` changes required for this phase.** [VERIFIED: codebase grep]

## Package Legitimacy Audit

> No external packages are introduced in this phase. This section is not applicable.

## Architecture Patterns

### System Architecture Diagram: STORE-01/02/03 Data Flow

```
Pipeline caller (ingest.py / crawl.py / parse.py / clean.py / export.py)
  │
  ├─ resolve domain: repo.get_domain_for_source(session, source_id) or "_unclassified"
  ├─ build tags dict: {domain, source_name, format, artifact_type}
  │
  └─► storage.put_raw(source_id, data, ext, session, domain=domain, tags=tags)
          │
          Layer 1: content_hash = sha256(data)                     ← UNCHANGED
          Layer 2: registry no-op check (get_artifact_by_hash)     ← UNCHANGED
          Layer 3: key = f"raw/{domain}/{source_id}/{hash}.{ext}"  ← CHANGED (domain added)
          Layer 4: head_object guard                                ← UNCHANGED
          Layer 5: put_object(key, data, tags=tags)                ← CHANGED (tags added)
                     │
                     ├─ primary: _client.put_object(Bucket=, Key=, Body=, Tagging=_format_tags(tags))
                     └─ fallback: on ClientError → log warning → _client.put_object(Bucket=, Key=, Body=)
          Layer 6: create registry artifact node                    ← UNCHANGED
```

**Silver-zone flow (parse.py / clean.py):**
```
with get_session() as session:
  domain = repo.get_domain_for_source(session, source_id) or "_unclassified"  ← ADDED
  silver_key = f"silver/{domain}/{source_id}/{content_hash}.md"               ← CHANGED
  storage.put_object(silver_key, bytes, tags={...})                            ← CHANGED
```

**Gold-zone flow (export.py):**
```
def export_rag_corpus(*, domain: Optional[str] = None, settings=None):        ← domain kwarg ADDED
  seg = domain or "_unclassified"
  key = f"{gold_prefix}/{seg}/rag_corpus/{export_id}.parquet"                 ← CHANGED
```

### Recommended Project Structure (no changes needed)

```
src/knowledge_lake/
├── storage/
│   └── s3.py          # PRIMARY CHANGE TARGET: _format_tags, put_object(tags=), put_raw(domain=), put_bronze(domain=)
├── pipeline/
│   ├── parse.py        # Silver key f-string + domain resolution (move key construction into session block)
│   ├── clean.py        # Silver/cleaned key f-string + domain resolution (move into session block)
│   ├── export.py       # Gold key f-strings + domain kwarg on 3 export functions
│   ├── ingest.py       # Caller: resolve domain + pass to put_raw
│   └── crawl.py        # Caller: resolve domain in _write_artifacts session block + pass to put_raw/put_bronze
└── registry/
    └── repo.py         # NO CHANGES — get_domain_for_source already exists
```

### Pattern 1: `_format_tags` Helper

**What:** Encodes a dict of tag key-value pairs into the URL-encoded string S3's `Tagging=` parameter expects.
**When to use:** Before every `put_object` call that receives a `tags` dict.

```python
# Source: boto3 docs (S3 PutObject Tagging parameter)
import urllib.parse

def _format_tags(tags: dict[str, str]) -> str:
    """Encode a tag dict to the URL-encoded string S3's Tagging= parameter expects.

    S3 tag value limit is 256 characters. Values are truncated defensively.
    """
    safe = {k: v[:256] for k, v in tags.items()}
    return urllib.parse.urlencode(safe)
```

### Pattern 2: Best-Effort Tagging in `put_object`

**What:** Wraps the S3 write with inline `Tagging=`; on `ClientError`, falls back to writing without tags.
**When to use:** The single write primitive in `s3.py`. All zone-specific writers inherit this automatically.

```python
# Source: boto3 S3 docs — put_object Tagging parameter
def put_object(self, key: str, data: bytes, tags: Optional[dict[str, str]] = None) -> None:
    kwargs: dict = {"Bucket": self._bucket, "Key": key, "Body": data}
    if tags:
        kwargs["Tagging"] = _format_tags(tags)
    try:
        self._client.put_object(**kwargs)
    except ClientError:
        if tags:
            # Best-effort: retry without tags so the object is always written (D-10)
            log.warning("put_object: tagging failed, retrying without tags", key=key)
            self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        else:
            raise
    log.debug("stored", bucket=self._bucket, key=key, size=len(data))
```

### Pattern 3: Domain-Scoped Key with `_unclassified` Fallback

**What:** Every key-construction f-string inserts `domain or "_unclassified"` as the segment after the zone prefix.
**When to use:** Layer 3 of `put_raw`, Layer 3 of `put_bronze`, silver key in `parse.py`/`clean.py`, gold keys in `export.py`.

```python
# Source: codebase (s3.py Layer 3, CONTEXT.md D-01)
domain_seg = domain or "_unclassified"
key = f"raw/{domain_seg}/{source_id}/{content_hash}.{ext}"
```

**Critical:** Never `f"raw/{domain}/{source_id}/..."` where `domain` might be `None` — that produces `"raw/None/..."`. Always use the `or "_unclassified"` guard.

### Pattern 4: Domain Resolution at Call Site (within session boundary)

**What:** Callers call `get_domain_for_source` inside the same `with get_session() as session:` block that reads/writes artifacts.
**When to use:** Every pipeline function that needs domain for key construction.

```python
# Source: codebase (repo.py:822, CONTEXT.md D-02, D-04)
with get_session() as session:
    domain = registry_repo.get_domain_for_source(session, source_id) or "_unclassified"
    key = f"silver/{domain}/{source_id}/{content_hash}.md"
    storage.put_object(key, data, tags={"domain": domain, "source_name": source_name, ...})
```

**Signature reminder:** `get_domain_for_source(session, source_id)` — `session` is the FIRST argument. [VERIFIED: codebase grep]

### Anti-Patterns to Avoid

- **`f"raw/{domain}/..."` where `domain` may be `None`:** Produces `"raw/None/src123/..."` — a literal "None" string in the key. Always use `domain or "_unclassified"`.
- **`f"raw//{source_id}/..."` (empty segment):** Occurs when `domain=""` is not guarded. Also avoided by `or "_unclassified"`.
- **Separate `put_object_tagging()` call after `put_object`:** Introduces partial-state risk (object written, tagging not). Use inline `Tagging=` parameter (D-08).
- **Calling `get_domain_for_source` outside a `with get_session()` block:** Results in `DetachedInstanceError` on lazy-loaded SQLAlchemy attributes. The call must stay inside an active session context.
- **Calling `get_domain_for_source` from inside `s3.py`:** Violates D-02 (storage layer must not call the registry). Domain resolution always happens in the calling pipeline function.
- **Rewriting existing raw keys:** Violates WORM immutability. STORE-01 is forward-only — existing keys keep their original `storage_uri` in the registry (D-06).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Tag string encoding | Custom `&`-join logic | `urllib.parse.urlencode(tags)` | Handles special characters, already available, one line |
| S3 conditional write | `If-None-Match` header | `head_object` guard + registry no-op (existing layers 1-4) | MinIO gap (FOUND-04) — already documented and handled |
| Per-zone `StorageBackend` instances | Multiple `StorageBackend` constructors | Single `_make_storage(s)` call, reuse same instance | FOUND-03 established single-client pattern; don't deviate |

**Key insight:** This phase is surgical — the existing four-layer WORM contract, the `_SILVER_PREFIX`/`_GOLD_PREFIX` constants, the `get_domain_for_source` function, and the `registry_repo` import pattern are all already in place. The work is inserting domain and tags into the correct positions in existing patterns.

## Common Pitfalls

### Pitfall 1: `get_domain_for_source` argument order

**What goes wrong:** The CONTEXT.md code example writes `get_domain_for_source(source_id, session)` — arguments in the wrong order. This will produce a `TypeError` at runtime.

**Why it happens:** Documentation error in CONTEXT.md code snippet. The actual function signature at `repo.py:822` is:
```python
def get_domain_for_source(session: Session, source_id: str) -> Optional[str]:
```

**How to avoid:** Always call `repo.get_domain_for_source(session, source_id)` — session first.

**Warning signs:** `TypeError: argument of type 'str' is not iterable` or similar at the call site. Confirmed by tests at `tests/unit/test_registry.py:466` which call `get_domain_for_source(session, source.id)`.

### Pitfall 2: Export functions have NO existing `domain` kwarg

**What goes wrong:** D-14 states "no new parameters are needed — the existing `domain` filter kwarg doubles as the key-segment value." But inspection of the actual source code shows that all three export functions (`export_rag_corpus`, `export_pretrain_corpus`, `export_finetune_dataset`) have NO `domain` parameter in their current signatures.

**Why it happens:** CONTEXT.md assumed domain filtering was already implemented in the export functions; it is not.

**How to avoid:** The planner MUST add `domain: Optional[str] = None` to all three export function signatures. D-14's intent is that this should be the only signature change — no additional filter logic beyond `domain or "_unclassified"` for the key segment.

The gold-key pattern:
```python
def export_rag_corpus(*, domain: Optional[str] = None, settings: Optional[Settings] = None) -> dict:
    ...
    domain_seg = domain or "_unclassified"
    key = f"{s.export.gold_prefix}/{domain_seg}/rag_corpus/{export_id}.parquet"
```

**Warning signs:** `TypeError: export_rag_corpus() got an unexpected keyword argument 'domain'` if callers pass domain before the signature change.

### Pitfall 3: Silver key construction happens OUTSIDE the session block in `parse.py`

**What goes wrong:** In `parse.py`, the silver key is constructed at line 100 BEFORE the `with get_session() as session:` block at line 113. Moving domain resolution into the key construction line without moving the key construction into the session block results in `get_domain_for_source` being called without an active session.

**Why it happens:** Current code computes the key ahead of the session block for clarity, then passes it into the session for dedup check and artifact creation. With domain resolution required, the key must be constructed inside the session block.

**How to avoid:** Move the `silver_key = f"..."` assignment from line 100 to inside the `with get_session() as session:` block (after line 113), immediately after resolving domain. The `storage.put_object(silver_key, parsed_bytes)` call is already inside the session block at line 129.

The same issue applies to `clean.py`: `cleaned_key = f"..."` is at line 300, immediately before the `with get_session() as session:` block at line 301. Move it inside.

**Warning signs:** `DetachedInstanceError` or `TypeError` when calling `get_domain_for_source` outside a session context.

### Pitfall 4: `source_name` at silver-zone write sites requires an extra registry lookup

**What goes wrong:** `parse()` and `clean()` receive `source_id` but not `source_name`. The tag `source_name` must be resolved with an additional `registry_repo.get_source(session, source_id)` call inside the session block.

**How to avoid:** Inside the same `with get_session() as session:` block that resolves domain, also call:
```python
source_obj = registry_repo.get_source(session, source_id)
source_name = source_obj.name if source_obj else "unknown"
```

`get_source` is already in `repo.py` at line 835. This is a single additional read within the already-open session; no extra session boundary is needed.

### Pitfall 5: Tag values from `source_name` or `domain` may exceed 256 chars

**What goes wrong:** The S3 tag value limit is 256 characters. Long URLs or source names would trigger `ClientError: InvalidTagValue`.

**How to avoid:** Apply `[:256]` truncation in `_format_tags`:
```python
safe = {k: v[:256] for k, v in tags.items()}
return urllib.parse.urlencode(safe)
```

This is already captured in the recommended `_format_tags` implementation.

### Pitfall 6: Existing tests that assert old key formats will fail

**What goes wrong:** `tests/integration/test_raw_immutable.py` asserts `f"raw/{source_id}/{SAMPLE_HASH}.{SAMPLE_EXT}"` and `f"s3://{TEST_BUCKET}/raw/{source_id}/{SAMPLE_HASH}.{SAMPLE_EXT}"`. After the change, the key format is `f"raw/{domain}/{source_id}/{SAMPLE_HASH}.{SAMPLE_EXT}"`. These tests will fail with key-mismatch assertions.

**How to avoid:** Update assertions in existing tests to include the domain segment. When `domain=None` is passed, the expected key uses `"_unclassified"` as the segment: `f"raw/_unclassified/{source_id}/{hash}.ext"`. Pass `domain=None` explicitly in tests that don't set up domain data, OR create a source with a domain in the test fixture and pass that domain.

**Warning signs:** `AssertionError: Expected storage_uri 's3://.../raw/src_123/hash.pdf', got 's3://.../raw/_unclassified/src_123/hash.pdf'`.

## Code Examples

Verified patterns from official sources:

### boto3 `put_object` with `Tagging` parameter

```python
# Source: [CITED: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/put_object.html]
# Tagging expects URL-encoded string: "Key1=Value1&Key2=Value2"
import urllib.parse
tagging_str = urllib.parse.urlencode({"domain": "healthcare", "format": "html"})
client.put_object(Bucket="my-bucket", Key="raw/...", Body=b"data", Tagging=tagging_str)
```

### Exact changes per file

**s3.py — add `_format_tags` (module level, before the class)**

```python
import urllib.parse  # add to existing imports

def _format_tags(tags: dict[str, str]) -> str:
    """Encode tag dict to URL-encoded string for S3 Tagging= parameter."""
    return urllib.parse.urlencode({k: v[:256] for k, v in tags.items()})
```

**s3.py — `put_object` signature and body change**

Old: `def put_object(self, key: str, data: bytes) -> None:`
New: `def put_object(self, key: str, data: bytes, tags: Optional[dict[str, str]] = None) -> None:`

Body wraps `_client.put_object` with optional `Tagging=` and `ClientError` fallback (see Pattern 2 above).

**s3.py — `put_raw` Layer 3 change**

Old: `key = f"raw/{source_id}/{content_hash}.{ext}"`
New:
```python
domain_seg = domain or "_unclassified"
key = f"raw/{domain_seg}/{source_id}/{content_hash}.{ext}"
```
Also: Layer 5 `self.put_object(key, data)` → `self.put_object(key, data, tags=tags)` (tags come from caller via kwarg).

**s3.py — `put_bronze` Layer 3 change**

Old: `key = f"bronze/{source_id}/{content_hash}.{ext}"`
New:
```python
domain_seg = domain or "_unclassified"
key = f"bronze/{domain_seg}/{source_id}/{content_hash}.{ext}"
```

**parse.py — silver key construction (move inside session block)**

Old (line 100, outside session): `silver_key = f"{_SILVER_PREFIX}/{source_id}/{content_hash}.md"`
New (inside `with get_session() as session:` at line 113):
```python
domain = registry_repo.get_domain_for_source(session, source_id) or "_unclassified"
source_obj = registry_repo.get_source(session, source_id)
source_name = source_obj.name if source_obj else "unknown"
silver_key = f"{_SILVER_PREFIX}/{domain}/{source_id}/{content_hash}.md"
# ... existing dedup check ...
storage.put_object(silver_key, parsed_bytes, tags={
    "domain": domain,
    "source_name": source_name,
    "format": "md",
    "artifact_type": "parsed_document",
})
```

**clean.py — cleaned key construction (move inside session block)**

Old (line 300, immediately before session): `cleaned_key = f"{_SILVER_PREFIX}/{source_id}/cleaned/{content_hash}.md"`
New (first lines inside `with get_session() as session:` at line 301):
```python
domain = registry_repo.get_domain_for_source(session, source_id) or "_unclassified"
source_obj = registry_repo.get_source(session, source_id)
source_name = source_obj.name if source_obj else "unknown"
cleaned_key = f"{_SILVER_PREFIX}/{domain}/{source_id}/cleaned/{content_hash}.md"
```
Also update `storage.put_object(cleaned_key, cleaned_bytes)` → pass `tags={...}`.

**export.py — gold key changes (three lines)**

```python
# export_rag_corpus: add domain kwarg; change key construction
domain_seg = domain or "_unclassified"
key = f"{s.export.gold_prefix}/{domain_seg}/rag_corpus/{export_id}.parquet"

# export_pretrain_corpus: add domain kwarg; change key construction
domain_seg = domain or "_unclassified"
key = f"{s.export.gold_prefix}/{domain_seg}/pretrain/{export_id}.jsonl"

# export_finetune_dataset: add domain kwarg; change key construction
domain_seg = domain or "_unclassified"
key = f"{s.export.gold_prefix}/{domain_seg}/finetune/{dataset.id}.jsonl"
```

**ingest.py — pass domain and tags to put_raw (two call sites)**

```python
# Inside with get_session() as session: block (line 411 region)
domain = registry_repo.get_domain_for_source(session, source.id) or "_unclassified"
artifact = storage.put_raw(source.id, data, ext, session,
    mime_type=effective_mime,
    domain=domain,
    tags={
        "domain": domain,
        "source_name": source_name,
        "format": ext,
        "artifact_type": "raw_document",
    },
)
```

Note: `source_name` is already a parameter of `ingest_url()` and `ingest_file()` — no extra lookup needed.

**crawl.py — pass domain and tags in `_write_artifacts`**

```python
# Inside with get_session() as session: block (line 677 region)
domain = registry_repo.get_domain_for_source(session, source_id) or "_unclassified"
source_obj = registry_repo.get_source(session, source_id)
source_name = source_obj.name if source_obj else "unknown"

raw_artifact = storage.put_raw(source_id, html, "html", session,
    mime_type="text/html",
    domain=domain,
    tags={"domain": domain, "source_name": source_name, "format": "html", "artifact_type": "raw_document"},
)
if markdown:
    bronze_artifact = storage.put_bronze(source_id, md_bytes, "md", session,
        parent_artifact_id=raw_id,
        domain=domain,
        tags={"domain": domain, "source_name": source_name, "format": "md", "artifact_type": "bronze_document"},
    )
```

## Runtime State Inventory

> SKIPPED — this is a greenfield forward-only code change phase (D-06). No stored data is renamed or migrated. Existing artifacts retain their original `storage_uri` in the registry. No runtime state is affected.

## Environment Availability

> SKIPPED — this phase makes no external dependency additions. All required tools and services (MinIO, PostgreSQL, Python 3.12, boto3) are already provisioned as established by prior phases.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flat `raw/{source_id}/{hash}.ext` keys | `raw/{domain}/{source_id}/{hash}.ext` keys | Phase 9 (forward-only) | S3 lifecycle policies and DuckDB queries can filter by domain via key prefix; existing keys unchanged |
| No S3 object tags | Tags on every write (best-effort) | Phase 9 | S3 cost-allocation, lifecycle, and search features become available; registry remains source of truth |
| Flat `gold/rag_corpus/{id}.parquet` | `gold/{domain}/rag_corpus/{id}.parquet` | Phase 9 | Gold exports are queryable by domain via S3 prefix; no S3 filter API needed for domain isolation |

**Note:** S3 `Tagging=` inline on `put_object` has been the standard approach since boto3 1.x. `put_object_tagging()` as a separate call is documented as atomic-only when combined with S3 Object Lock conditional writes — not needed here. [ASSUMED: boto3 documentation, training knowledge]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | MinIO supports `Tagging=` on `put_object` (D-08 inline tagging) | Code Examples | Tags silently dropped; best-effort fallback means write still succeeds, but tags are lost |
| A2 | boto3's `put_object` `Tagging` parameter accepts URL-encoded string format | Code Examples | `ClientError: InvalidArgument` — fallback removes tags; object still written |
| A3 | S3 tag value maximum is 256 characters | Common Pitfalls | Values beyond 256 chars → `ClientError: InvalidTagValue`; `[:256]` truncation prevents this |

## Open Questions

1. **Gold-zone `source_name` tag for `export_rag_corpus`**
   - What we know: Gold exports aggregate multiple sources; CONTEXT.md D-11 says `source_name` is "omitted for multi-source exports."
   - What's unclear: If a caller explicitly passes `domain="healthcare"`, should we attempt to find a representative source name from that domain's sources?
   - Recommendation: Omit `source_name` tag for all gold exports (3-tag set: `domain`, `format`, `artifact_type`). The registry is the source of truth per D-02.

2. **Integration test `test_raw_immutable.py` key assertions**
   - What we know: Tests assert the exact key format including `s3://{bucket}/raw/{source_id}/{hash}.{ext}`.
   - What's unclear: Whether to update these to pass `domain=None` and assert `_unclassified` segment, or create a new parallel test class.
   - Recommendation: Update the existing assertions to use `domain=None` (no source domain configured), which maps to `_unclassified` segment. Add a new test class that creates a source with a domain and verifies the domain-scoped key format.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/unit/ -v -x` |
| Full suite command | `python -m pytest tests/ -v --ignore=tests/e2e --ignore=tests/integration` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STORE-01 | `put_raw` with domain produces `raw/{domain}/{source_id}/{hash}.ext` key | unit | `pytest tests/unit/test_put_raw_domain.py -x` | ❌ Wave 0 |
| STORE-01 | `put_raw` with `domain=None` produces `raw/_unclassified/{source_id}/{hash}.ext` key | unit | `pytest tests/unit/test_put_raw_domain.py::TestPutRawDomainKey -x` | ❌ Wave 0 |
| STORE-01 | `put_raw` dedup no-op remains ordered before key construction (registry check first) | unit | `pytest tests/unit/test_put_raw_domain.py::TestDeduplicationOrderPreserved -x` | ❌ Wave 0 |
| STORE-01 | `put_bronze` with domain produces `bronze/{domain}/{source_id}/{hash}.ext` key | unit | `pytest tests/unit/test_put_bronze.py::TestPutBronzeDomainKey -x` | ❌ Wave 0 — new class in existing file |
| STORE-01 | Silver key in parse.py uses `silver/{domain}/{source_id}/{hash}.md` | unit | `pytest tests/unit/test_parse_silver_key.py -x` | ❌ Wave 0 |
| STORE-01 | Silver key in clean.py uses `silver/{domain}/{source_id}/cleaned/{hash}.md` | unit | `pytest tests/unit/test_clean_silver_key.py -x` | ❌ Wave 0 |
| STORE-02 | `put_object` passes `Tagging=` when tags dict provided | unit | `pytest tests/unit/test_put_object_tags.py::TestPutObjectTagging -x` | ❌ Wave 0 |
| STORE-02 | `put_object` falls back to tagless write on `ClientError` (best-effort) | unit | `pytest tests/unit/test_put_object_tags.py::TestTaggingBestEffortFallback -x` | ❌ Wave 0 |
| STORE-02 | `_format_tags` produces URL-encoded string | unit | `pytest tests/unit/test_format_tags.py -x` | ❌ Wave 0 |
| STORE-02 | Tag values truncated to 256 chars | unit | `pytest tests/unit/test_format_tags.py::TestTagValueTruncation -x` | ❌ Wave 0 |
| STORE-03 | `export_rag_corpus(domain="healthcare")` produces `gold/healthcare/rag_corpus/{id}.parquet` | unit | `pytest tests/unit/test_export.py::TestGoldZoneDomainKey -x` | ❌ Wave 0 — new class in existing file |
| STORE-03 | `export_rag_corpus(domain=None)` produces `gold/_unclassified/rag_corpus/{id}.parquet` | unit | `pytest tests/unit/test_export.py::TestGoldZoneUnclassified -x` | ❌ Wave 0 |
| STORE-03 | `export_pretrain_corpus` and `export_finetune_dataset` follow same gold key pattern | unit | `pytest tests/unit/test_export.py::TestGoldZonePretrain` and `::TestGoldZoneFinetune` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/unit/ -v -x`
- **Per wave merge:** `python -m pytest tests/ -v --ignore=tests/e2e --ignore=tests/integration`
- **Phase gate:** Full suite green before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/test_put_raw_domain.py` — covers STORE-01 raw key + dedup ordering
- [ ] `tests/unit/test_format_tags.py` — covers STORE-02 tag encoding + truncation
- [ ] `tests/unit/test_put_object_tags.py` — covers STORE-02 inline tagging + best-effort fallback
- [ ] `tests/unit/test_parse_silver_key.py` — covers STORE-01 silver key in parse stage
- [ ] `tests/unit/test_clean_silver_key.py` — covers STORE-01 silver key in clean stage
- [ ] New test classes in existing `tests/unit/test_put_bronze.py` — `TestPutBronzeDomainKey`
- [ ] New test classes in existing `tests/unit/test_export.py` — `TestGoldZoneDomainKey`, `TestGoldZoneUnclassified`, `TestGoldZonePretrain`, `TestGoldZoneFinetune`

## Security Domain

### Applicable ASVS Categories (ASVS Level 1)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes | Tag values capped at 256 chars; `_unclassified` fallback prevents `None`/empty injection into S3 keys |
| V6 Cryptography | no | SHA256 for content addressing is unchanged |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| S3 key segment injection (e.g., `../` in domain name) | Tampering | Domain values come from `Source.config["domain"]` which is populated via `register_source()` — already validated at write time; `_unclassified` fallback for `None`/empty prevents empty segment |
| Tag value exceeding S3 limits | Denial of Service | `[:256]` truncation in `_format_tags`; best-effort fallback prevents tag-related `ClientError` from blocking writes |
| Partial-write state (object written, tags not) | Tampering/Information Disclosure | Tags are inline with `put_object` call (not separate `put_object_tagging`); best-effort fallback means the object always lands even if tags fail |

## Sources

### Primary (HIGH confidence)
- `src/knowledge_lake/storage/s3.py` — full file read; `put_raw`, `put_bronze`, `put_object` signatures and WORM contract confirmed [VERIFIED: codebase grep]
- `src/knowledge_lake/registry/repo.py:822` — `get_domain_for_source(session, source_id)` signature confirmed [VERIFIED: codebase grep]
- `src/knowledge_lake/pipeline/parse.py:100, 113` — silver key construction location and session block boundary confirmed [VERIFIED: codebase grep]
- `src/knowledge_lake/pipeline/clean.py:300-301` — cleaned key construction location confirmed [VERIFIED: codebase grep]
- `src/knowledge_lake/pipeline/export.py:236,323,343,409,429,523` — export function signatures and gold key lines confirmed [VERIFIED: codebase grep]
- `src/knowledge_lake/pipeline/crawl.py:677-700` — `_write_artifacts` function confirmed [VERIFIED: codebase grep]
- `tests/unit/test_registry.py:466` — `get_domain_for_source(session, source.id)` call confirms `session` is first arg [VERIFIED: codebase grep]

### Secondary (MEDIUM confidence)
- `boto3` `put_object` `Tagging` parameter documented in boto3 S3 reference — URL-encoded string format [CITED: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3/client/put_object.html]
- `urllib.parse.urlencode` — produces `key=val&key=val` format required by S3 `Tagging=` [CITED: Python stdlib docs]

### Tertiary (LOW confidence)
- MinIO `put_object` `Tagging` parameter support — assumed to match S3 API (MinIO claims full S3 API compatibility) [ASSUMED]

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all APIs already in codebase
- Architecture: HIGH — change targets confirmed by direct source file inspection
- Pitfalls: HIGH — argument order and missing export params confirmed by code inspection vs. CONTEXT.md claims

**Research date:** 2026-07-09
**Valid until:** 2026-08-09 (stable, no fast-moving dependencies)
