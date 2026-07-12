# Phase 9: Storage Segmentation - Pattern Map

**Mapped:** 2026-07-09
**Files analyzed:** 8 files (6 modified, 2 new test files + new test classes in 2 existing test files)
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/knowledge_lake/storage/s3.py` | storage | request-response | `src/knowledge_lake/storage/s3.py` (self — surgical additions) | exact |
| `src/knowledge_lake/pipeline/parse.py` | pipeline stage | transform | `src/knowledge_lake/pipeline/clean.py` | exact |
| `src/knowledge_lake/pipeline/clean.py` | pipeline stage | transform | `src/knowledge_lake/pipeline/parse.py` | exact |
| `src/knowledge_lake/pipeline/export.py` | pipeline stage | batch | `src/knowledge_lake/pipeline/export.py` (self — key f-strings only) | exact |
| `src/knowledge_lake/pipeline/ingest.py` | pipeline stage | request-response | `src/knowledge_lake/pipeline/crawl.py` `_write_artifacts` | role-match |
| `src/knowledge_lake/pipeline/crawl.py` | pipeline stage | event-driven | `src/knowledge_lake/pipeline/ingest.py` | role-match |
| `tests/unit/test_put_raw_domain.py` | test | — | `tests/unit/test_put_bronze.py` | exact |
| `tests/unit/test_put_object_tags.py` | test | — | `tests/unit/test_put_bronze.py` | exact |
| `tests/unit/test_format_tags.py` | test | — | `tests/unit/test_put_bronze.py` (simple unit, no fixtures) | role-match |
| `tests/unit/test_parse_silver_key.py` | test | — | `tests/unit/test_export.py` (mock storage pattern) | role-match |
| `tests/unit/test_clean_silver_key.py` | test | — | `tests/unit/test_export.py` (mock storage pattern) | role-match |

## Pattern Assignments

---

### `src/knowledge_lake/storage/s3.py` (storage, request-response)

**Analog:** Self — three surgical additions to the existing file.

**Existing imports** (lines 19-37 — `urllib.parse` must be added):
```python
from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Optional

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from sqlalchemy.exc import IntegrityError

from knowledge_lake.config.settings import StorageSettings
```
Add `import urllib.parse` to this block.

**Addition 1: `_format_tags` module-level helper (insert before `class StorageBackend`):**
```python
def _format_tags(tags: dict[str, str]) -> str:
    """Encode tag dict to URL-encoded string for S3 Tagging= parameter.

    S3 tag value limit is 256 characters; values are truncated defensively.
    """
    return urllib.parse.urlencode({k: v[:256] for k, v in tags.items()})
```

**Addition 2: `put_object` signature change (line 81 — old signature → new):**

Old (line 81–94):
```python
def put_object(self, key: str, data: bytes) -> None:
    self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
    log.debug("stored", bucket=self._bucket, key=key, size=len(data))
```

New pattern (best-effort tagging with ClientError fallback — D-07, D-08, D-10):
```python
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

**Addition 3: `put_raw` signature + Layer 3 key + Layer 5 tags (lines 153–259):**

Signature change — add `domain` and `tags` kwargs (backward-compatible defaults):
```python
def put_raw(
    self,
    source_id: str,
    data: bytes,
    ext: str,
    session: "Session",
    mime_type: Optional[str] = None,
    domain: Optional[str] = None,
    tags: Optional[dict[str, str]] = None,
) -> "Artifact":
```

Layer 3 key construction change (line 219 — the ONLY line that changes in the body):
```python
# Old: key = f"raw/{source_id}/{content_hash}.{ext}"
domain_seg = domain or "_unclassified"
key = f"raw/{domain_seg}/{source_id}/{content_hash}.{ext}"
```

Layer 5 write change (line 230 — pass tags through):
```python
# Old: self.put_object(key, data)
self.put_object(key, data, tags=tags)
```

**Addition 4: `put_bronze` signature + Layer 3 key + Layer 5 tags (lines 263–361):**

Signature change — add `domain` and `tags` kwargs after `parent_artifact_id`:
```python
def put_bronze(
    self,
    source_id: str,
    data: bytes,
    ext: str,
    session: "Session",
    *,
    parent_artifact_id: str,
    domain: Optional[str] = None,
    tags: Optional[dict[str, str]] = None,
) -> "Artifact":
```

Layer 3 key construction change (line 323):
```python
# Old: key = f"bronze/{source_id}/{content_hash}.{ext}"
domain_seg = domain or "_unclassified"
key = f"bronze/{domain_seg}/{source_id}/{content_hash}.{ext}"
```

Layer 5 write change (line 334):
```python
# Old: self.put_object(key, data)
self.put_object(key, data, tags=tags)
```

**Critical constraint:** Layers 1, 2, 4, and 6 are UNCHANGED. The `get_artifact_by_hash` registry no-op (Layer 2) must remain ordered BEFORE key construction (Layer 3). Domain only enters at Layer 3.

---

### `src/knowledge_lake/pipeline/parse.py` (pipeline stage, transform)

**Analog:** `src/knowledge_lake/pipeline/clean.py` lines 295–340 (identical session-block discipline)

**Existing constants** (line 29 — unchanged):
```python
_SILVER_PREFIX = "silver"
```

**Existing imports** (lines 10–26 — `registry_repo` is already imported):
```python
from knowledge_lake.registry import repo as registry_repo
```

**Current silver key construction (line 100 — OUTSIDE session block, must move INSIDE):**
```python
# CURRENT (line 100, before "with get_session() as session:" at line 113):
silver_key = f"{_SILVER_PREFIX}/{source_id}/{content_hash}.md"
```

**New pattern (move key construction inside session block at line 113, add domain + source_name resolution):**
```python
with get_session() as session:
    # NEW: resolve domain and source_name for key + tags (Pitfall 3: must be inside session)
    domain = registry_repo.get_domain_for_source(session, source_id) or "_unclassified"
    source_obj = registry_repo.get_source(session, source_id)
    source_name = source_obj.name if source_obj else "unknown"
    # CHANGED: domain segment inserted (was: f"{_SILVER_PREFIX}/{source_id}/{content_hash}.md")
    silver_key = f"{_SILVER_PREFIX}/{domain}/{source_id}/{content_hash}.md"

    existing = registry_repo.get_artifact_by_hash(session, content_hash, "parsed_document")
    if existing is not None:
        # ... existing no-op return (UNCHANGED) ...

    # CHANGED: pass tags to put_object (was: storage.put_object(silver_key, parsed_bytes))
    storage.put_object(silver_key, parsed_bytes, tags={
        "domain": domain,
        "source_name": source_name,
        "format": "md",
        "artifact_type": "parsed_document",
    })
```

**Critical constraint (Pitfall 3):** The `silver_key = f"..."` line currently lives at line 100 BEFORE the `with get_session()` block at line 113. It MUST be moved inside the session block because `get_domain_for_source` requires an active session.

---

### `src/knowledge_lake/pipeline/clean.py` (pipeline stage, transform)

**Analog:** `src/knowledge_lake/pipeline/parse.py` (mirrors same session-block discipline)

**Existing constants** (line 39 — unchanged):
```python
_SILVER_PREFIX = "silver"
```

**Current cleaned key construction (line 300 — IMMEDIATELY BEFORE session block at line 301):**
```python
# CURRENT (line 300, just before "with get_session() as session:" at line 301):
cleaned_key = f"{_SILVER_PREFIX}/{source_id}/cleaned/{content_hash}.md"
with get_session() as session:
```

**New pattern (move key construction INSIDE session block; same domain + source_name resolution as parse.py):**
```python
with get_session() as session:
    # NEW: resolve domain and source_name (Pitfall 3: must be inside session)
    domain = registry_repo.get_domain_for_source(session, source_id) or "_unclassified"
    source_obj = registry_repo.get_source(session, source_id)
    source_name = source_obj.name if source_obj else "unknown"
    # CHANGED: domain segment inserted
    cleaned_key = f"{_SILVER_PREFIX}/{domain}/{source_id}/cleaned/{content_hash}.md"

    # Step 5: Exact dedup check — unchanged
    existing = registry_repo.get_artifact_by_hash(session, content_hash, "cleaned_document")
    if existing is not None:
        # ... unchanged ...

    # Step 9: CHANGED — pass tags
    storage.put_object(cleaned_key, cleaned_bytes, tags={
        "domain": domain,
        "source_name": source_name,
        "format": "md",
        "artifact_type": "cleaned_document",
    })
```

---

### `src/knowledge_lake/pipeline/export.py` (pipeline stage, batch)

**Analog:** Self — three key f-string changes + three signature additions.

**Critical pitfall (Pitfall 2):** CONTEXT.md claimed `domain` kwarg already exists on export functions. Code inspection shows it does NOT. All three functions need `domain: Optional[str] = None` added to their signatures.

**`export_rag_corpus` (line 236 — current signature):**
```python
# CURRENT:
def export_rag_corpus(
    *,
    settings: Optional[Settings] = None,
) -> dict:
```
```python
# NEW:
def export_rag_corpus(
    *,
    domain: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> dict:
```

**Key construction change (line 323):**
```python
# CURRENT:
key = f"{s.export.gold_prefix}/rag_corpus/{export_id}.parquet"

# NEW:
domain_seg = domain or "_unclassified"
key = f"{s.export.gold_prefix}/{domain_seg}/rag_corpus/{export_id}.parquet"
```
Also update `put_object` call:
```python
# CHANGED: pass tags (source_name omitted for multi-source gold exports per D-11)
storage.put_object(key, buf.getvalue(), tags={
    "domain": domain_seg,
    "format": "parquet",
    "artifact_type": "rag_corpus",
})
```

**`export_pretrain_corpus` (line 409 key construction):**
```python
# CURRENT:
key = f"{s.export.gold_prefix}/pretrain/{export_id}.jsonl"

# NEW:
domain_seg = domain or "_unclassified"
key = f"{s.export.gold_prefix}/{domain_seg}/pretrain/{export_id}.jsonl"
```

**`export_finetune_dataset` (line 523 key construction):**
```python
# CURRENT:
key = f"{s.export.gold_prefix}/finetune/{dataset.id}.jsonl"

# NEW:
domain_seg = domain or "_unclassified"
key = f"{s.export.gold_prefix}/{domain_seg}/finetune/{dataset.id}.jsonl"
```

**Note:** `export_rag_corpus` already calls `registry_repo.get_domain_for_source` at line 273 for row data — that per-chunk domain resolution is separate from the gold key segment. The gold key segment comes from the function's own `domain` kwarg.

---

### `src/knowledge_lake/pipeline/ingest.py` (pipeline stage, request-response)

**Analog:** `src/knowledge_lake/pipeline/crawl.py` `_write_artifacts` (lines 662–700)

**Existing call site (line 430 — inside `with get_session() as session:` block):**
```python
# CURRENT:
artifact = storage.put_raw(source.id, data, ext, session, mime_type=effective_mime)
```

**New pattern (domain resolution + tags — `source_name` already available as function param):**
```python
# INSIDE the existing with get_session() as session: block, before put_raw:
domain = registry_repo.get_domain_for_source(session, source.id) or "_unclassified"

artifact = storage.put_raw(
    source.id, data, ext, session,
    mime_type=effective_mime,
    domain=domain,
    tags={
        "domain": domain,
        "source_name": source_name,   # already a param of ingest_url()
        "format": ext,
        "artifact_type": "raw_document",
    },
)
```

**Note:** `ingest_url()` has two call sites for `put_raw` (lines 430 and 533). Both must be updated with the same pattern. `source_name` is an existing parameter in both `ingest_url()` and `ingest_file()` — no extra registry lookup needed.

---

### `src/knowledge_lake/pipeline/crawl.py` (pipeline stage, event-driven)

**Analog:** `src/knowledge_lake/pipeline/ingest.py` (same put_raw/put_bronze call pattern)

**Existing `_write_artifacts` function (lines 662–700):**
```python
# CURRENT:
with get_session() as session:
    raw_artifact = storage.put_raw(source_id, html, "html", session, mime_type="text/html")
    session.flush()
    raw_id = raw_artifact.id

    if markdown:
        md_bytes = markdown.encode("utf-8")
        bronze_artifact = storage.put_bronze(
            source_id, md_bytes, "md", session,
            parent_artifact_id=raw_id,
        )
```

**New pattern (domain + source_name resolution inside the session block + tags on both writes):**
```python
with get_session() as session:
    # NEW: resolve domain and source_name inside session boundary
    domain = registry_repo.get_domain_for_source(session, source_id) or "_unclassified"
    source_obj = registry_repo.get_source(session, source_id)
    source_name = source_obj.name if source_obj else "unknown"

    raw_artifact = storage.put_raw(
        source_id, html, "html", session,
        mime_type="text/html",
        domain=domain,
        tags={"domain": domain, "source_name": source_name, "format": "html", "artifact_type": "raw_document"},
    )
    session.flush()
    raw_id = raw_artifact.id

    if markdown:
        md_bytes = markdown.encode("utf-8")
        bronze_artifact = storage.put_bronze(
            source_id, md_bytes, "md", session,
            parent_artifact_id=raw_id,
            domain=domain,
            tags={"domain": domain, "source_name": source_name, "format": "md", "artifact_type": "bronze_document"},
        )
```

**Note:** `registry_repo` is already imported in `crawl.py`. `get_source` is already in `repo.py` at line 835.

---

### `tests/unit/test_put_raw_domain.py` (NEW file, test)

**Analog:** `tests/unit/test_put_bronze.py` (lines 1–80) — identical fixture pattern: SQLite in-memory engine, mocked boto3 client, head_object raises 404.

**Fixture pattern to copy from `test_put_bronze.py` (lines 22–64):**
```python
@pytest.fixture(scope="module")
def engine():
    from knowledge_lake.registry.models import Base
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()

@pytest.fixture()
def session(engine):
    with Session(engine) as sess:
        yield sess
        sess.rollback()

@pytest.fixture()
def mock_storage():
    from knowledge_lake.config.settings import StorageSettings
    from knowledge_lake.storage.s3 import StorageBackend
    storage_settings = StorageSettings(
        endpoint_url="http://minio-test:9000",
        bucket="test-bucket",
        access_key_id="test",
        secret_access_key="test",
    )
    with patch("boto3.client") as mock_boto:
        mock_client = MagicMock()
        mock_boto.return_value = mock_client
        from botocore.exceptions import ClientError
        mock_client.head_object.side_effect = ClientError(
            {"Error": {"Code": "404"}}, "HeadObject"
        )
        backend = StorageBackend(storage_settings)
        yield backend, mock_client
```

**Test cases needed (from RESEARCH.md validation map):**
- `TestPutRawDomainKey` — assert key contains `raw/healthcare/{source_id}/{hash}.ext` when `domain="healthcare"`
- `TestPutRawDomainKey::test_none_domain_uses_unclassified` — assert `raw/_unclassified/...` when `domain=None`
- `TestDeduplicationOrderPreserved` — mock `get_artifact_by_hash` to return existing; assert `put_object` NOT called (no-op before key construction)

---

### `tests/unit/test_put_object_tags.py` (NEW file, test)

**Analog:** `tests/unit/test_put_bronze.py` (same `mock_storage` fixture pattern)

**Test cases:**
- `TestPutObjectTagging::test_tags_passed_as_tagging_kwarg` — mock `_client.put_object`; assert called with `Tagging="domain=healthcare&format=html&..."` (URL-encoded)
- `TestTaggingBestEffortFallback::test_clienterror_retries_without_tags` — make `_client.put_object` raise `ClientError` on first call; assert second call made without `Tagging=`; assert no exception raised

---

### `tests/unit/test_format_tags.py` (NEW file, test)

**Analog:** Simple pure-function test — no fixtures needed (no DB, no S3 mock).

**Pattern (no fixtures required, pure function test):**
```python
from knowledge_lake.storage.s3 import _format_tags

def test_format_tags_produces_urlencode_string():
    result = _format_tags({"domain": "healthcare", "format": "html"})
    assert result == "domain=healthcare&format=html"

def test_tag_value_truncated_at_256_chars():
    long_val = "x" * 300
    result = _format_tags({"key": long_val})
    assert len(result) == len("key=") + 256
```

---

### New test classes in `tests/unit/test_put_bronze.py`

**Add `TestPutBronzeDomainKey` class** — same fixture as the existing `test_put_bronze.py` file; assert bronze key contains `bronze/{domain}/{source_id}/{hash}.md` when `domain="healthcare"` is passed; assert `bronze/_unclassified/...` when `domain=None`.

---

### New test classes in `tests/unit/test_export.py`

**Analog:** Existing `test_export.py` lines 1–60 — engine/session/mock_storage fixture pattern.

**New classes needed (from RESEARCH.md validation map):**
- `TestGoldZoneDomainKey` — call `export_rag_corpus(domain="healthcare")`, assert `put_object` called with key matching `gold/healthcare/rag_corpus/{id}.parquet`
- `TestGoldZoneUnclassified` — call `export_rag_corpus(domain=None)`, assert key is `gold/_unclassified/rag_corpus/{id}.parquet`
- `TestGoldZonePretrain` — same pattern for `export_pretrain_corpus`
- `TestGoldZoneFinetune` — same pattern for `export_finetune_dataset`

**Key mock pattern from existing `test_export.py`:**
```python
with patch("knowledge_lake.pipeline.export._make_storage") as mock_make:
    mock_storage = MagicMock()
    mock_make.return_value = mock_storage
    result = export_rag_corpus(domain="healthcare", settings=s)
    call_args = mock_storage.put_object.call_args
    assert "gold/healthcare/rag_corpus/" in call_args[0][0]
```

---

## Shared Patterns

### Domain Resolution at Call Site
**Source:** `src/knowledge_lake/registry/repo.py` lines 822–832
**Apply to:** `ingest.py`, `crawl.py`, `parse.py`, `clean.py`

```python
# Signature (session is FIRST arg — Pitfall 1):
def get_domain_for_source(session: Session, source_id: str) -> Optional[str]:
    source = session.get(Source, source_id)
    if source is None or not source.config:
        return None
    return source.config.get("domain")
```

**Call pattern (always inside `with get_session() as session:` block):**
```python
domain = registry_repo.get_domain_for_source(session, source_id) or "_unclassified"
```

### `_unclassified` Fallback
**Source:** CONTEXT.md D-01 + RESEARCH.md Pattern 3
**Apply to:** All key construction sites in `s3.py`, `parse.py`, `clean.py`, `export.py`

```python
domain_seg = domain or "_unclassified"
key = f"{zone_prefix}/{domain_seg}/{source_id}/{content_hash}.{ext}"
```

Never use `f".../{domain}/..."` directly — `domain` may be `None`, producing literal `"None"` in the key.

### WORM Layer Ordering
**Source:** `src/knowledge_lake/storage/s3.py` lines 205–259
**Apply to:** `put_raw` and `put_bronze` modifications

The four WORM layers are UNCHANGED. Domain enters only at Layer 3 (key construction), AFTER the Layer 2 registry no-op check. Layer ordering must not change:
1. Content hash computation
2. `get_artifact_by_hash` registry no-op (BEFORE key construction)
3. Key construction — domain inserted HERE
4. `head_object` guard
5. `put_object` — tags added HERE
6. Registry artifact creation

### Source Name Resolution (silver/crawl writers)
**Source:** `src/knowledge_lake/registry/repo.py` line 835
**Apply to:** `parse.py`, `clean.py`, `crawl.py` (functions that receive `source_id` but not `source_name`)

```python
source_obj = registry_repo.get_source(session, source_id)
source_name = source_obj.name if source_obj else "unknown"
```

`ingest.py` does NOT need this — `source_name` is already a function parameter.

### Test Fixture Pattern (SQLite + mock boto3)
**Source:** `tests/unit/test_put_bronze.py` lines 22–64
**Apply to:** All new test files for storage layer (`test_put_raw_domain.py`, `test_put_object_tags.py`)

```python
with patch("boto3.client") as mock_boto:
    mock_client = MagicMock()
    mock_boto.return_value = mock_client
    mock_client.head_object.side_effect = ClientError({"Error": {"Code": "404"}}, "HeadObject")
    backend = StorageBackend(storage_settings)
    yield backend, mock_client
```

## No Analog Found

No files lack analogs in this phase. All changes are surgical additions to existing files.

## Critical Anti-Patterns (do not do these)

| Anti-pattern | Consequence | Correct Pattern |
|--------------|-------------|-----------------|
| `f"raw/{domain}/..."` when `domain` may be `None` | `"raw/None/..."` in S3 key | `domain_seg = domain or "_unclassified"` then `f"raw/{domain_seg}/..."` |
| Calling `get_domain_for_source` outside `with get_session()` | `DetachedInstanceError` | Always inside active session block |
| Calling `get_domain_for_source(source_id, session)` (wrong arg order) | `TypeError` | Always `get_domain_for_source(session, source_id)` — session is first |
| Separate `put_object_tagging()` call after `put_object` | Partial-state risk | Inline `Tagging=` parameter in same `put_object` call |
| Moving key construction before registry no-op check | Breaks WORM Layer 2 ordering | Domain enters at Layer 3, after Layer 2 no-op |
| Calling `get_domain_for_source` from inside `s3.py` | Violates D-02 (storage must not call registry) | Resolve domain in pipeline caller, pass as kwarg |

## Metadata

**Analog search scope:** `src/knowledge_lake/storage/`, `src/knowledge_lake/pipeline/`, `src/knowledge_lake/registry/`, `tests/unit/`
**Files scanned:** 7 source files, 3 test files
**Pattern extraction date:** 2026-07-09
