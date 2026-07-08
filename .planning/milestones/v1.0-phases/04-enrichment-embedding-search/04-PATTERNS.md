# Phase 4: Enrichment, Embedding & Search - Pattern Map

**Mapped:** 2026-07-05
**Files analyzed:** 13 (new + extended)
**Analogs found:** 13 / 13

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `src/knowledge_lake/pipeline/enrich.py` (NEW) | service (pipeline stage) | request-response (LLM call) + CRUD (registry write) | `src/knowledge_lake/pipeline/clean.py` (stage shape) + `src/knowledge_lake/quality/scorer.py::maybe_llm_spot_check` (LLM call) | exact (composite of two analogs) |
| `src/knowledge_lake/pipeline/deterministic.py` (NEW) | utility (pure transform) | transform | `src/knowledge_lake/pipeline/clean.py` (`_normalize_whitespace`, `detect_language` — pure helper functions, no I/O) | role-match |
| `src/knowledge_lake/llm/pricing.py` (NEW) | config/bootstrap | request-response (startup call) | `src/knowledge_lake/plugins/builtin/st_embedder.py::LiteLLMEmbedder` (direct `litellm.*` call, try/except wrap) | role-match |
| `src/knowledge_lake/pipeline/index.py` (EXTEND) | service (pipeline stage) | CRUD (Qdrant upsert) | itself (existing file) — extend with alias resolution + enrichment payload join | exact (self) |
| `src/knowledge_lake/pipeline/search.py` (EXTEND) | service (pipeline stage) | request-response (query) | itself (existing file) — extend with filter kwargs | exact (self) |
| `src/knowledge_lake/plugins/builtin/qdrant_store.py` (EXTEND) | service (plugin) | CRUD + event-driven (alias swap) | itself — extend `ensure_collection`/add `ensure_aliased_collection`/`reindex` | exact (self) |
| `src/knowledge_lake/registry/models.py` (EXTEND) | model | CRUD | itself — extend `Artifact` with `quality_score` Mapped column; add `VectorCollection` model modeled on `Source`/`CrawlJob` table shape | exact (self) |
| `src/knowledge_lake/registry/repo.py` (EXTEND) | service (repo/DAO) | CRUD | `create_cleaned_artifact`/`create_chunk_artifact` (lines ~194-278) — template for `create_enriched_artifact()`; `get_artifact_by_hash` (lines 284-303) — reuse verbatim for cache check | exact |
| `src/knowledge_lake/config/settings.py` (EXTEND) | config | — | `CleanSettings`/`ChunkSettings` (lines 96-134) — template for `EnrichSettings`; top-level `qdrant_url`/`litellm_url`/`tika_server_url` (lines 161-173) — template for any new top-level URL/alias config | exact |
| `src/knowledge_lake/dagster_defs/assets.py` (EXTEND) | controller (Dagster asset) | event-driven (asset graph) | `clean_document` asset (lines 237-...) — template for new `enrich_document` asset (parallel dep on `parsed_document`'s output, i.e. `clean_document`'s dict) | exact |
| `src/knowledge_lake/cli/app.py` (EXTEND) | controller (CLI command) | request-response | existing `klake parse/clean/chunk` commands (not read in full this pass — follow same Typer subcommand + pipeline-call-through pattern) | role-match |
| `src/knowledge_lake/api/app.py` (EXTEND) | controller (API route) | request-response | existing FastAPI routes wrapping `pipeline.search.search`/`pipeline.index.index` (not read in full this pass — additive query params only) | role-match |
| `src/knowledge_lake/registry/alembic/versions/0007_*.py` (NEW) | migration | batch | `0006_parse_clean_chunk_columns.py` (not read this pass, referenced in RESEARCH.md as the analog for adding a `quality_score`-shaped column) | role-match |

## Pattern Assignments

### `src/knowledge_lake/pipeline/enrich.py` (NEW)

**Analogs:** `src/knowledge_lake/pipeline/clean.py` (stage skeleton: cache/dedup check → transform → registry write, all within `get_session()` blocks) and `src/knowledge_lake/quality/scorer.py::maybe_llm_spot_check` (the LiteLLM call convention).

**Imports pattern** (from `clean.py` lines 13-28):
```python
from __future__ import annotations

import hashlib
from typing import Optional

import structlog

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.registry.db import get_session
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.storage.s3 import StorageBackend

log = structlog.get_logger(__name__)
```
Enrichment additionally needs a **lazy** `import litellm` inside the function body (never top-level) — mirrors `scorer.py` line 146's comment: "lazy import — avoids proxy dependency in unit tests".

**Cache-check pattern** (from `clean.py` lines 285-303, exact-dup branch — reuse `get_artifact_by_hash` verbatim, just with a synthetic hash):
```python
with get_session() as session:
    existing = registry_repo.get_artifact_by_hash(session, synthetic_hash, "enriched_document")
    if existing is not None:
        log.info("enrich.cache_hit", content_hash=synthetic_hash, existing_artifact_id=existing.id)
        return {"artifact_id": existing.id, "cached": True}
```

**LLM call pattern** (from `quality/scorer.py` lines 144-176 — direct copy of the calling convention, extended per AI-SPEC Section 3/4 with a system+user message split and Pydantic validation instead of `json.loads`):
```python
try:
    import litellm  # lazy import — avoids proxy dependency in unit tests

    response = litellm.completion(
        model="cheap_model",              # task alias only — never a provider model ID (ENRICH-01)
        messages=[
            {"role": "system", "content": _ENRICHMENT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        api_base=settings.litellm_url,
        max_tokens=512,
        temperature=0.0,
    )
    content = response.choices[0].message.content or ""
    parsed = EnrichmentResult.model_validate_json(content)
except Exception as exc:
    log.warning("enrich.llm_call_failed", error=str(exc))
    # never crash the job — mark skipped_enrichment_failed and continue (D-05 halting philosophy)
```

**Error handling pattern:** `scorer.py`'s broad `except Exception` + `log.warning(..., error=str(exc))` + graceful fallback (never re-raise) is the established convention for LLM-call failure — apply identically for both validation failures and budget-exceeded halts, per AI-SPEC Section 4b ("never crash the job").

**Retry pattern** (from `pipeline/ingest.py` lines 32, 153-159 — `tenacity` decorator, apply to the LiteLLM call only, not the budget-exceeded halt):
```python
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((Exception,)),  # narrow to litellm/httpx transient errors in impl
    reraise=True,
)
def _call_llm_for_enrichment(...): ...
```

**Registry write pattern** (from `clean.py` lines 310-323 — `create_cleaned_artifact` call shape; mirror for `create_enriched_artifact`):
```python
artifact = registry_repo.create_enriched_artifact(
    session,
    source_id=source_id,
    parent_artifact_id=cleaned_artifact_id,   # D-01: parent is cleaned_document, not parsed_document
    content_hash=synthetic_hash,               # D-04: sha256(cleaned_content_hash + ":" + prompt_version)
    metadata=result.model_dump(),              # title/summary/document_type/organization/jurisdiction/keywords/entities
    quality_score=result.quality_score,        # D-07/Pitfall 5: dedicated Mapped column, not just metadata_ JSON
)
session.flush()
```

**Session discipline note** (from `clean.py`'s own docstring, lines 278-284): keep the dedup-check read and the artifact-insert write in the *same* `get_session()` block to make cache-check + create effectively atomic — same pattern enrichment must follow for the cache path.

---

### `src/knowledge_lake/pipeline/deterministic.py` (NEW)

**Analog:** `src/knowledge_lake/pipeline/clean.py`'s pure-function helpers (`_normalize_whitespace` lines 58-70, `detect_language` lines 88-125) — no I/O, no session, defensive fallback to a neutral default on failure.

**Core pattern to copy:**
```python
def extract_title(parsed_doc_metadata: dict, sections: list) -> str:
    """Pure transform — no LLM call, no I/O (ENRICH-02)."""
    if parsed_doc_metadata.get("title"):
        return parsed_doc_metadata["title"]
    if sections:
        return sections[0].heading or ""
    return ""

def extract_dates(text: str) -> list[str]:
    """Regex over cleaned text — no re-parsing (ENRICH-02, D-02)."""
    import re
    return re.findall(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b[A-Z][a-z]+ \d{1,2}, \d{4}\b", text)
```
Follow `detect_language`'s defensive-fallback shape (try/except around any optional dependency, `log.warning` + safe default, never raise) for any part of this module that touches an optional library.

---

### `src/knowledge_lake/llm/pricing.py` (NEW)

**Analog:** `src/knowledge_lake/plugins/builtin/st_embedder.py::LiteLLMEmbedder.embed()` (lines 139-170) — direct `litellm.*()` call, wrapped in try/except, `RuntimeError` on unrecoverable failure vs. graceful fallback on recoverable failure.

**Bootstrap pattern** (per AI-SPEC Pattern 2, RESEARCH.md Pitfall 1 — concrete code already specified in AI-SPEC lines 258-287, copy directly):
```python
import litellm

def bootstrap_llm_pricing(settings: "Settings") -> None:
    litellm.register_model({
        "bedrock/anthropic.claude-haiku-4-5-20260925-v1:0": {
            "input_cost_per_token": settings.enrich.cheap_model_input_cost_per_token,
            "output_cost_per_token": settings.enrich.cheap_model_output_cost_per_token,
            "litellm_provider": "bedrock",
            "mode": "chat",
        },
    })

def compute_call_cost(response, settings) -> float:
    try:
        return litellm.completion_cost(completion_response=response)
    except Exception as exc:
        log.warning("enrich.cost_calc_failed", error=str(exc))
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0.0
        return (
            usage.prompt_tokens / 1000 * settings.enrich.fallback_cost_per_1k_input
            + usage.completion_tokens / 1000 * settings.enrich.fallback_cost_per_1k_output
        )
```
Call `bootstrap_llm_pricing()` once at app/job/Dagster-resource startup — same "resolve once, reuse" convention as `get_settings()`'s lru-cache pattern in `config/settings.py`.

---

### `src/knowledge_lake/pipeline/index.py` (EXTEND, existing file)

**Analog:** itself. Current `index()` function (lines 29-96) creates the collection, builds `VectorPoint`s with a citation-only payload (lines 71-89), and upserts.

**Extension points:**
1. `vstore.ensure_collection(collection, dim=dim)` (line 64) → replace with `ensure_aliased_collection(client, alias, dim)` per AI-SPEC Pattern 3 (create `{alias}_v1` physical collection + alias on first run; alias resolves transparently thereafter — no client-side resolution layer needed, confirmed live in RESEARCH.md).
2. Payload dict (lines 75-82) → extend with `domain`, `document_type`, `keywords`/`tags`, `quality_score` sourced from the sibling `enriched_document` artifact (D-07) — join via `registry_repo.get_artifact_by_hash`-style lookup on the cleaned artifact's children, and via `session.get(Source, artifact.source_id).config.get("domain")` (RESEARCH.md Pitfall 4 — `domain` is NOT a column, it lives in `Source.config` JSON).
3. Keep `_strip_prefix()` (lines 99-108) and the `collection: str = "klake_chunks"` parameter name unchanged — only the resolution layer underneath changes (D-06).

**Existing payload code to extend (lines 75-82):**
```python
payload = {
    "document": parsed_artifact_id,
    "section_path": chunk.get("section_path", ""),
    "page": chunk.get("page", 1),
    "chunk_id": full_chunk_id,
    "qdrant_id": qdrant_point_id,
    "text": chunk.get("text", ""),
    # NEW (D-07, additive):
    "domain": domain_or_none,
    "document_type": enrichment_metadata.get("document_type") if enrichment_metadata else None,
    "keywords": enrichment_metadata.get("keywords", []) if enrichment_metadata else [],
    "quality_score": enrichment_metadata.get("quality_score") if enrichment_metadata else None,
}
```

---

### `src/knowledge_lake/pipeline/search.py` (EXTEND, existing file)

**Analog:** itself. Current `search()` (lines 23-62) has no filter params.

**Extension pattern** (AI-SPEC/RESEARCH.md Code Example, lines 402-421 of RESEARCH.md — copy directly):
```python
from qdrant_client.models import Filter, FieldCondition, MatchValue, Range

def search(query, *, collection="klake_chunks", top_k=5,
           domain=None, document_type=None, min_quality_score=None, settings=None):
    ...
    must = []
    if domain:
        must.append(FieldCondition(key="domain", match=MatchValue(value=domain)))
    if document_type:
        must.append(FieldCondition(key="document_type", match=MatchValue(value=document_type)))
    if min_quality_score is not None:
        must.append(FieldCondition(key="quality_score", range=Range(gte=min_quality_score)))
    query_filter = Filter(must=must) if must else None
```
Note: `QdrantVectorStore.search()` (`plugins/builtin/qdrant_store.py` lines 108-143) currently takes no `query_filter` param — must be threaded through as a new optional kwarg on `VectorStorePlugin.search()`, defaulting to `None` so existing citation-only callers (no kwargs passed) are unaffected — backward compatible per D-07/INDEX-03.

---

### `src/knowledge_lake/plugins/builtin/qdrant_store.py` (EXTEND, existing file)

**Analog:** itself. `ensure_collection()` (lines 51-80) is idempotent-create; extend/add per AI-SPEC Pattern 3.

**New methods to add** (copy directly from AI-SPEC lines 303-330, verified live against the running Qdrant 1.13.6 server):
```python
from qdrant_client.models import (
    CreateAliasOperation, CreateAlias, DeleteAliasOperation, DeleteAlias,
)

def ensure_aliased_collection(self, alias: str, dim: int) -> str:
    if self._client.collection_exists(alias):
        return alias
    physical = f"{alias}_v1"
    self._client.create_collection(physical, vectors_config=self._VectorParams(size=dim, distance=self._Distance.COSINE))
    self._client.update_collection_aliases(change_aliases_operations=[
        CreateAliasOperation(create_alias=CreateAlias(collection_name=physical, alias_name=alias)),
    ])
    return alias

def reindex(self, alias: str, dim: int, upsert_fn) -> str:
    next_version = self._next_version_name(alias)
    self._client.create_collection(next_version, vectors_config=self._VectorParams(size=dim, distance=self._Distance.COSINE))
    upsert_fn(next_version)
    old_physical = self._resolve_alias_target(alias)
    self._client.update_collection_aliases(change_aliases_operations=[
        DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=alias)),
        CreateAliasOperation(create_alias=CreateAlias(collection_name=next_version, alias_name=alias)),
    ])
    return old_physical  # caller decides when to client.delete_collection(old_physical)
```
Follow the existing constructor pattern (lines 41-49 — lazy `from qdrant_client import ...` inside `__init__`, store client/model classes as instance attrs) for any new qdrant-client model imports.

---

### `src/knowledge_lake/registry/models.py` (EXTEND, existing file)

**Analog:** itself. `Artifact` class (lines 107-...) — currently has `metadata_` JSON (lines 169-175) but no `quality_score`/`language`/`dedup_status` Mapped columns despite migration 0006 adding them physically (RESEARCH.md Pitfall 5).

**Column pattern to copy** (from `page_ref`/`section_path`, lines 163-167 — same `Optional[...]` + docstring convention):
```python
quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
"""LLM-judged quality score for enriched_document rows (Phase 4) — distinct per artifact_type,
no collision with Phase 3's heuristic parse-quality score which lives in metadata_ JSON."""
```
**Decision required at planning time (flagged in CONTEXT.md Specifics):** wire up only `quality_score` (recommended, zero new migration cost per RESEARCH.md Alternatives Considered) — leave `language`/`dedup_status` unaddressed as an explicit scoped decision, not silent inconsistency.

**New table pattern** (for alias→collection registry tracking, D-06) — model on `Source` (lines 54-105) or `CrawlJob` (lines ~271-...) shape: `id`, `alias_name`, `physical_collection`, `is_current: bool`, `created_at`, `reindex_job_id` (optional FK).

---

### `src/knowledge_lake/registry/repo.py` (EXTEND, existing file)

**Analog:** `create_cleaned_artifact` / `create_chunk_artifact` (lines 194-278) — near-identical shape, template for `create_enriched_artifact()`.

**Pattern to copy** (lines 248-278, `create_chunk_artifact`, adapted):
```python
def create_enriched_artifact(
    session: Session,
    *,
    source_id: str,
    parent_artifact_id: str,   # D-01: the cleaned_document artifact, not parsed_document
    content_hash: str,         # synthetic hash (ENRICH-04)
    metadata: Optional[Any] = None,
    quality_score: Optional[float] = None,
) -> Artifact:
    """Persist an enriched_document artifact node.

    ``parent_artifact_id`` must point to the cleaned_document artifact this
    was enriched from (D-01 — the actual text the LLM read).
    """
    art = _make_artifact(
        kind="enriched_document",
        source_id=source_id,
        artifact_type="enriched_document",
        content_hash=content_hash,
        parent_artifact_id=parent_artifact_id,
        metadata=metadata,
    )
    art.quality_score = quality_score  # if the column is wired per models.py extension
    session.add(art)
    return art
```

**Reuse verbatim:** `get_artifact_by_hash` (lines 284-303) — no changes needed, just called with `artifact_type="enriched_document"` and a synthetic hash (ENRICH-04 cache check).

---

### `src/knowledge_lake/config/settings.py` (EXTEND, existing file)

**Analog:** `CleanSettings`/`ChunkSettings` (lines 96-134) — nested `BaseModel`, `KLAKE_<STAGE>__*` env var pattern, inline docstrings per field citing the requirement ID.

**Pattern to copy:**
```python
class EnrichSettings(BaseModel):
    """LLM enrichment configuration (ENRICH-01..05).

    Nested under Settings as settings.enrich. Environment variable pattern:
    KLAKE_ENRICH__BUDGET_USD, etc.
    """

    budget_usd: float = 5.0
    """Global spend cap in USD before the enrichment job halts gracefully (ENRICH-05, D-05)."""

    prompt_version: str = "v1"
    """Bumping this invalidates the enrichment cache (ENRICH-04, D-04)."""

    cache_enabled: bool = True
    """Toggle the content-hash cache check (mainly for testing)."""

    cheap_model_input_cost_per_token: float = 0.0
    cheap_model_output_cost_per_token: float = 0.0
    fallback_cost_per_1k_input: float = 0.0005
    fallback_cost_per_1k_output: float = 0.0015


class IndexSettings(BaseModel):
    """Vector-store alias/collection configuration (INDEX-02, D-06)."""

    collection_alias: str = "klake_chunks"
    keep_old_collections: bool = True
```
Register both as new fields on the top-level `Settings` class (mirror `parse: ParseSettings = ParseSettings()` convention, not read in this pass but implied by the nested-model pattern already established).

---

### `src/knowledge_lake/dagster_defs/assets.py` (EXTEND, existing file)

**Analog:** `clean_document` asset (lines 237-...) — `@asset(description=..., group_name="pipeline")` decorator, receives upstream dict, calls the pipeline function, returns a dict of IDs (no IO manager for bytes — Pitfall 7 convention).

**Pattern to copy** (from `parsed_document`/`clean_document` shape, lines 173-248):
```python
@asset(
    description=(
        "Enrich a cleaned document with LLM-judged metadata (summary, document_type, "
        "organization, jurisdiction, keywords, entities, quality_score). "
        "Calls pipeline.enrich.enrich_document — no logic duplicated."
    ),
    group_name="pipeline",
)
def enrich_document(
    clean_document: dict[str, Any],   # D-01: parallel branch off clean_document, same dep as chunk_document
    postgres: PostgresResource,
) -> dict[str, Any]:
    from knowledge_lake.pipeline.enrich import enrich_document as enrich_fn

    cleaned_artifact_id = clean_document["artifact_id"]
    source_id = clean_document["source_id"]
    result = enrich_fn(cleaned_artifact_id, source_id)
    return result
```
Note the module docstring's asset-ordering comment (lines 10-18) needs updating to show the new parallel branch: `clean_document → {chunk_document, enrich_document}` (both depend on `clean_document`, neither blocks the other — D-01).

---

## Shared Patterns

### LiteLLM direct-call convention (task alias + api_base injection)
**Source:** `src/knowledge_lake/quality/scorer.py::maybe_llm_spot_check` (lines 144-176), `src/knowledge_lake/plugins/builtin/st_embedder.py::LiteLLMEmbedder.embed()` (lines 139-170)
**Apply to:** `pipeline/enrich.py`, `llm/pricing.py`
```python
import litellm  # lazy import — avoids proxy dependency in unit tests
response = litellm.completion(
    model="cheap_model",           # task alias only — NEVER a provider model ID
    messages=[...],
    api_base=settings.litellm_url,
    max_tokens=512,
)
```

### Registry stage skeleton (cache check → transform → session-scoped write)
**Source:** `src/knowledge_lake/pipeline/clean.py` (lines 162-339, full `clean()` function)
**Apply to:** `pipeline/enrich.py`
- Read artifact metadata in one `get_session()` block.
- Do pure computation (deterministic extraction, LLM call) outside any session.
- Do the exact-dedup check + artifact insert inside a single `get_session()` block (atomicity against concurrent identical-content runs).

### Content-hash caching via UNIQUE(content_hash, artifact_type)
**Source:** `src/knowledge_lake/registry/repo.py::get_artifact_by_hash` (lines 284-303)
**Apply to:** `pipeline/enrich.py` — zero new schema, reuse verbatim with a synthetic hash.

### Retry on transient failures
**Source:** `src/knowledge_lake/pipeline/ingest.py::_fetch_with_retry` (lines 32, 153-159)
**Apply to:** `pipeline/enrich.py`'s LiteLLM call
```python
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((...)),
    reraise=True,
)
```

### Nested Settings model per pipeline stage
**Source:** `src/knowledge_lake/config/settings.py::CleanSettings`/`ChunkSettings` (lines 96-134)
**Apply to:** new `EnrichSettings`, `IndexSettings`

### Dagster asset wrapping a pipeline function (no IO manager for bytes)
**Source:** `src/knowledge_lake/dagster_defs/assets.py::clean_document` (lines 237-...)
**Apply to:** new `enrich_document` asset, new reindex asset/job

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `src/knowledge_lake/registry/alembic/versions/0007_enrichment_budget_collections.py` | migration | batch | No Phase 4-specific migration analog read this pass; `0006_parse_clean_chunk_columns.py` is the structural precedent (adds columns to `artifacts`) but was not opened in this session — planner should read it directly before writing 0007 to match its exact `op.add_column`/downgrade style. |
| Budget spend-tracking table/row | model + service | CRUD | No existing "accumulator row" pattern in this codebase (all existing tables are append-only artifact/lineage nodes) — RESEARCH.md's Pattern 2 and Common Pitfall 2 are the only guidance; planner should design this as a small dedicated table with row-level read-then-write inside the same enrichment session, kept serial per D-05/AI-SPEC discretion. |

## Metadata

**Analog search scope:** `src/knowledge_lake/pipeline/`, `src/knowledge_lake/plugins/builtin/`, `src/knowledge_lake/registry/`, `src/knowledge_lake/config/`, `src/knowledge_lake/dagster_defs/`, `src/knowledge_lake/quality/`
**Files scanned:** 13 (full reads) + `cli/app.py`/`api/app.py` sized but not fully read (existing command/route shape assumed consistent per CONTEXT.md's own note: "CLI/API command naming ... consistent with existing `klake parse/clean/chunk` naming")
**Pattern extraction date:** 2026-07-05
