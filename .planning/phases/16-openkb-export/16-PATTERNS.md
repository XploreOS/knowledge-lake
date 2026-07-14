# Phase 16: OpenKB Export - Pattern Map

**Mapped:** 2026-07-14
**Files analyzed:** 6 (new/modified)
**Analogs found:** 6 / 6

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/knowledge_lake/pipeline/wiki.py` | service | batch-transform | `src/knowledge_lake/pipeline/export.py` | exact |
| `src/knowledge_lake/config/settings.py` (add WikiSettings) | config | -- | `src/knowledge_lake/config/settings.py` (ExportSettings L314-338) | exact |
| `src/knowledge_lake/cli/app.py` (add export-wiki cmd) | controller | request-response | `src/knowledge_lake/cli/app.py` (cmd_export L1010-1062) | exact |
| `src/knowledge_lake/api/app.py` (add /export-wiki endpoint) | controller | request-response | `src/knowledge_lake/api/app.py` (export_endpoint L1170-1239) | exact |
| `src/knowledge_lake/api/schemas.py` (add request/response) | model | -- | `src/knowledge_lake/api/schemas.py` (ExportRequest/ExportResponse) | exact |
| `tests/unit/test_wiki.py` | test | -- | `tests/unit/test_tree_index.py` | exact |

## Pattern Assignments

### `src/knowledge_lake/pipeline/wiki.py` (service, batch-transform)

**Analog:** `src/knowledge_lake/pipeline/export.py`

**Imports pattern** (lines 30-45):
```python
from __future__ import annotations

import io
import re

import orjson
import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.ids import new_id
from knowledge_lake.pipeline.utils import uri_to_key as _uri_to_key
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.storage.s3 import _UNCLASSIFIED_DOMAIN, StorageBackend
```

**Storage factory pattern** (lines 94-101):
```python
def _make_storage(s: Settings) -> StorageBackend:
    """Build the single StorageBackend from Settings."""
    return StorageBackend(s.storage)
```

**Core export function signature** (lines 244-270):
```python
def export_rag_corpus(
    *,
    domain: str | None = None,
    settings: Settings | None = None,
) -> dict:
    """Export all chunk artifacts as a Parquet file to the gold zone (EXPORT-01)."""
    s = settings or get_settings()
    storage = _make_storage(s)

    with get_session() as session:
        # ... gather data, transform, write to S3
```

**S3 write pattern** (lines 338-351):
```python
buf = io.BytesIO()
# ... write content to buf
buf.seek(0)

export_id = new_id("dataset")
domain_seg = domain or _UNCLASSIFIED_DOMAIN
key = f"{s.export.gold_prefix}/{domain_seg}/rag_corpus/{export_id}.parquet"
storage.put_object(key, buf.getvalue(), tags={
    "domain": domain_seg,
    "format": "parquet",
    "artifact_type": "rag_corpus",
})
uri = storage.object_uri(key)
```

**Content-hash pattern** (from `pipeline/tree_index.py` lines 24, 251-252):
```python
import hashlib

content_hash = hashlib.sha256(
    f"{parsed_content_hash}:{effective_mode}:{schema_ver}".encode("utf-8")
).hexdigest()
```

---

### `src/knowledge_lake/config/settings.py` (add WikiSettings)

**Analog:** Same file, `ExportSettings` at lines 314-338

**Settings submodel pattern**:
```python
class ExportSettings(BaseModel):
    """Gold-zone export configuration (EXPORT-01..03).

    Nested under Settings as settings.export. Environment variable pattern:
    KLAKE_EXPORT__GOLD_PREFIX, KLAKE_EXPORT__MIN_QUALITY_SCORE_FOR_PRETRAIN, etc.
    """

    gold_prefix: str = "gold"
    """S3 key prefix for gold-zone exports (raw -> bronze -> silver -> gold)."""

    default_finetune_format: str = "openai_chat"
    """Fine-tuning JSONL format: 'openai_chat' (chat-messages shape) is the default."""

    min_quality_score_for_pretrain: float = 0.4
    """Minimum composite_quality_score for a curated_document to be included."""

    contamination_override_artifact_ids: list[str] = Field(default_factory=list)
    """cleaned_document artifact IDs for documented, accepted train/eval overlaps."""
```

---

### `src/knowledge_lake/cli/app.py` (add export-wiki command)

**Analog:** Same file, `cmd_export` at lines 1010-1062

**CLI command pattern**:
```python
@app.command(name="export")
def cmd_export(
    kind: str = typer.Argument(
        ...,
        help="Export kind: 'rag-corpus' (Parquet), 'pretrain' (JSONL), or 'finetune' (JSONL).",
    ),
    dataset_name: str | None = typer.Option(
        None,
        "--dataset-name",
        "-d",
        help="Required for kind=finetune. The logical Dataset name to export.",
    ),
) -> None:
    """Export the curated corpus or a dataset to the gold zone."""
    from knowledge_lake.pipeline.export import (
        TrainEvalContaminationError,
        export_finetune_dataset,
        export_pretrain_corpus,
        export_rag_corpus,
    )

    try:
        if kind == "rag-corpus":
            result = export_rag_corpus()
        # ...
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
```

---

### `src/knowledge_lake/api/app.py` (add /export-wiki endpoint)

**Analog:** Same file, `export_endpoint` at lines 1170-1239

**API endpoint pattern**:
```python
@app.post(
    "/exports",
    response_model=ExportResponse,
    tags=["export"],
    summary="Export the corpus or a dataset to the gold zone (EXPORT-01/02/03)",
    status_code=200,
)
def export_endpoint(body: ExportRequest) -> ExportResponse:
    """Export curated corpus or dataset examples to the gold zone."""
    from knowledge_lake.pipeline.export import (
        TrainEvalContaminationError,
        export_rag_corpus,
    )

    logger.info("api.export", kind=body.kind)

    try:
        result = export_rag_corpus()
    except TrainEvalContaminationError as exc:
        logger.warning("api.export.contamination", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        logger.warning("api.export.error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return ExportResponse(
        dataset_id=result["dataset_id"],
        storage_uri=result["storage_uri"],
        row_count=result["row_count"],
    )
```

---

### `tests/unit/test_wiki.py` (test)

**Analog:** `tests/unit/test_tree_index.py`

**Test infrastructure pattern** (lines 1-40):
```python
"""Tests for pipeline/wiki.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import knowledge_lake.pipeline.wiki as wiki_module
import knowledge_lake.registry.db as registry_db
from knowledge_lake.config.settings import Settings


@pytest.fixture()
def engine():
    """In-memory SQLite engine, shared connection via StaticPool."""
    from knowledge_lake.registry.models import Base

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    return eng
```

---

## Shared Patterns

### Structured Logging
**Source:** All pipeline modules (e.g., `pipeline/export.py` line 45)
**Apply to:** `pipeline/wiki.py`
```python
import structlog
log = structlog.get_logger(__name__)

log.info("wiki.compile.building", domain=domain, doc_count=len(docs))
log.info("wiki.compile.complete", pages_created=n, manifest_uri=uri)
```

### Storage Write (BytesIO, never local file)
**Source:** `pipeline/export.py` lines 338-350
**Apply to:** `pipeline/wiki.py` for all page writes and manifest writes
```python
# For individual Markdown pages (no BytesIO needed — just encode):
page_bytes = page_content.encode("utf-8")
storage.put_object(key, page_bytes, tags={"domain": domain_seg, "format": "markdown"})
```

### Settings Integration
**Source:** `config/settings.py` — all submodels follow same nesting pattern
**Apply to:** WikiSettings addition
```python
# In the Settings class:
wiki: WikiSettings = WikiSettings()
# Env vars: KLAKE_WIKI__MIN_ENTITY_IDF=2.0
```

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none) | -- | -- | All files have exact analogs in the existing codebase |

## Metadata

**Analog search scope:** `src/knowledge_lake/pipeline/`, `src/knowledge_lake/config/`, `src/knowledge_lake/cli/`, `src/knowledge_lake/api/`, `tests/unit/`
**Files scanned:** 8
**Pattern extraction date:** 2026-07-14
