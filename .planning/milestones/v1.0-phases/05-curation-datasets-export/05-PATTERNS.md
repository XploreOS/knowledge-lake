# Phase 5: Curation, Datasets & Export - Pattern Map

**Mapped:** 2026-07-06
**Files analyzed:** 13
**Analogs found:** 13 / 13

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `src/knowledge_lake/pipeline/curate.py` (NEW) | service (pipeline stage) | batch / transform | `src/knowledge_lake/pipeline/clean.py` | exact (registry-first stage + batch MinHash reuse) |
| `src/knowledge_lake/pipeline/datasets.py` (NEW) | service (LLM generation) | request-response (per-unit LLM call) | `src/knowledge_lake/pipeline/enrich.py` | exact (D-07 mandates structural copy) |
| `src/knowledge_lake/pipeline/export.py` (NEW) | service (batch export) | batch / file-I/O | `src/knowledge_lake/storage/s3.py` (`put_raw`/`put_bronze`) + `pipeline/clean.py` (silver write) | role-match |
| `src/knowledge_lake/quality/scorer.py` (EXTEND — add `compute_composite_quality_score()`) | utility | transform | `src/knowledge_lake/quality/scorer.py` (existing `compute_quality_score`) | exact (same file, same weighted-heuristic convention) |
| `src/knowledge_lake/registry/models.py` (EXTEND — `Dataset` real columns, NEW `DatasetExample`) | model | CRUD | `src/knowledge_lake/registry/models.py` (`LlmSpend`, `VectorCollection` — small annotation tables) | exact |
| `src/knowledge_lake/registry/repo.py` (EXTEND — `create_curated_artifact`, `create_dataset`, `create_dataset_example`, `batch_dedup` lookups) | model/repo (CRUD) | CRUD | `src/knowledge_lake/registry/repo.py` (`create_enriched_artifact`, `create_cleaned_artifact`, `get_llm_spend`/`record_llm_spend`) | exact |
| `src/knowledge_lake/config/settings.py` (EXTEND — `CurateSettings`, `DatasetSettings`, `ExportSettings`) | config | transform | `src/knowledge_lake/config/settings.py` (`EnrichSettings`, `CleanSettings`) | exact |
| `src/knowledge_lake/storage/s3.py` (EXTEND — `_GOLD_PREFIX` / gold-zone helper) | utility (storage) | file-I/O | `src/knowledge_lake/storage/s3.py` (`_SILVER_PREFIX` in `pipeline/clean.py`, `put_bronze`) | exact |
| `src/knowledge_lake/dagster_defs/assets.py` (EXTEND — `curate_document`, `generate_dataset`, `export_*` assets) | controller (Dagster asset) | event-driven / batch | `src/knowledge_lake/dagster_defs/assets.py` (`enrich_document`, `chunk_document` assets) | exact |
| `src/knowledge_lake/cli/app.py` (EXTEND — `curate`, `dedupe`, `generate-dataset`, `export` commands) | controller (CLI) | request-response | `src/knowledge_lake/cli/app.py` (`cmd_enrich`, `cmd_clean`) | exact |
| Alembic migration (NEW) | migration | CRUD (schema) | existing migration 0006/0007 style (referenced in RESEARCH.md Code Examples) | role-match |
| `src/knowledge_lake/pipeline/datasets.py::QAPairResult`/`InstructionPairResult` (Pydantic schemas) | model (validation) | transform | `src/knowledge_lake/pipeline/enrich.py::EnrichmentResult` | exact |
| Tests (`tests/pipeline/test_curate.py`, `test_datasets.py`, `test_export.py`) | test | — | `tests/pipeline/test_enrich.py` / `test_clean.py` (if present — mirror existing test module naming) | role-match |

## Pattern Assignments

### `src/knowledge_lake/pipeline/curate.py` (service, batch/transform)

**Analog:** `src/knowledge_lake/pipeline/clean.py` (registry-first stage shape) + `src/knowledge_lake/pipeline/enrich.py` (composite-score sibling lookup pattern)

**Imports pattern** (`clean.py` lines 13-28):
```python
from __future__ import annotations
import hashlib
import re
from typing import Optional
import structlog
from datasketch import MinHash, MinHashLSH
from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.pipeline.utils import uri_to_key as _uri_to_key
from knowledge_lake.registry.db import get_session
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.storage.s3 import StorageBackend
log = structlog.get_logger(__name__)
```
New imports to add: `from datatrove.data import Document`, `from datatrove.pipeline.filters.gopher_quality_filter import GopherQualityFilter`, `from datatrove.pipeline.filters.gopher_repetition_filter import GopherRepetitionFilter`, `from datatrove.pipeline.filters.c4_filters import C4QualityFilter`.

**Registry-first stage pattern** (`clean.py` lines 162-339, `clean()` function): fetch parent artifact by ID via `get_session()` -> raise `ValueError` if missing/wrong type -> retrieve text via `StorageBackend.get_object(_uri_to_key(storage_uri))` -> compute deterministic result outside any session -> re-open a session to check exact-dup / write. Copy this exact 3-session-block discipline (fetch -> compute -> write) for `curate_document()`.

**Direct filter-call loop** (never `.run()` — see RESEARCH.md Pattern 1 for the exact code, already vetted against DataTrove v0.9.0 source):
```python
_FILTERS = [GopherRepetitionFilter(), GopherQualityFilter(min_doc_words=50, max_doc_words=100_000), C4QualityFilter(filter_no_terminal_punct=False)]
def score_document(cleaned_text: str, artifact_id: str) -> dict[str, dict]:
    doc = Document(text=cleaned_text, id=artifact_id, metadata={})
    results: dict[str, dict] = {}
    for f in _FILTERS:
        outcome = f.filter(doc)
        passed, reason = (outcome, None) if isinstance(outcome, bool) else outcome
        results[type(f).__name__] = {"passed": passed, "reason": reason}
    return results
```

**Batch MinHash dedup** — reuse `compute_minhash()` verbatim from `clean.py` lines 131-156 (do not reimplement); replace `clean.py`'s per-call transient-LSH block (lines 237-276, the literal T-03-06 code being retired) with a genuine one-pass batch loop:
```python
lsh = MinHashLSH(threshold=settings.clean.minhash_threshold, num_perm=settings.clean.minhash_num_perm)
minhashes = {}
for artifact in cleaned_artifacts:  # registry_repo.list_cleaned_artifacts(session)
    text = storage.get_object(_uri_to_key(artifact.storage_uri)).decode("utf-8")
    mh = compute_minhash(text, num_perm=settings.clean.minhash_num_perm, shingle_size=settings.clean.minhash_shingle_size)
    minhashes[artifact.id] = mh
    lsh.insert(artifact.id, mh)
dedup_status = {aid: ("near_dup" if [m for m in lsh.query(mh) if m != aid] else "unique") for aid, mh in minhashes.items()}
```

**Sibling-lookup for composite score** (Pitfall 4 in RESEARCH.md — `curated_document` and `enriched_document` are cousins, both children of the same `cleaned_document`): mirror `registry_repo.get_enriched_artifact_for_parsed()` (`repo.py` line 704) — query for the `enriched_document` whose `parent_artifact_id` equals the SAME `cleaned_document.id` that `curated_document`'s own parent points to, not an ancestor walk.

**Error handling / never-raise-on-failure:** `clean.py` never swallows exceptions from the filter loop; but for the LLM-adjacent composite score computation, follow `enrich.py`'s D-05 "never raise out of an optional step" discipline (lines 286-292) — return a status dict, log a warning, do not crash the batch job on a single document's failure.

---

### `src/knowledge_lake/pipeline/datasets.py` (service, request-response, per-unit LLM call)

**Analog:** `src/knowledge_lake/pipeline/enrich.py` (D-07 mandates a direct structural copy — see AI-SPEC.md Section 3 for the fully worked example, already reviewed).

**Imports pattern** (`enrich.py` lines 18-37):
```python
from __future__ import annotations
import hashlib
from typing import Optional
import structlog
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy.exc import IntegrityError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.llm.pricing import bootstrap_llm_pricing, compute_call_cost
from knowledge_lake.registry.db import get_session
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.storage.s3 import StorageBackend
log = structlog.get_logger(__name__)
```

**Result schema pattern** (`enrich.py` lines 83-102, `EnrichmentResult`) — bound every field with `max_length`/`ge`/`le` before it reaches the registry:
```python
class QAPairResult(BaseModel):
    question: str = Field(max_length=500)
    answer: str = Field(max_length=2000)
```
Note (AI-SPEC Section 3 Pitfall 1): `citation_chunk_id` must NOT be part of the LLM-produced schema — assign it programmatically after validation from the already-known chunk_id, exactly as `GeneratedQAExample` wraps `QAPairResult`.

**`_strip_json_fences` helper** — copy verbatim, unmodified (`enrich.py` lines 113-125):
```python
def _strip_json_fences(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.removeprefix("```json").removeprefix("```")
        stripped = stripped.removesuffix("```").strip()
    return stripped
```

**Retried LLM-call helper** (`enrich.py` lines 139-189, `_call_llm_for_enrichment`) — same `tenacity` policy, same `openai/` prefix quirk, same "accumulate cost on every attempt including failed-validation retries" discipline (WR-03):
```python
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10),
       retry=retry_if_exception_type((RuntimeError, ValidationError)), reraise=True)
def _call_llm_for_qa_generation(system_prompt, user_prompt, settings, attempt_costs) -> tuple[QAPairResult, object]:
    import litellm  # noqa: PLC0415
    try:
        response = litellm.completion(
            model="openai/eval_model",  # D-06 — never cheap_model
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            api_base=settings.litellm_url, api_key=settings.litellm_api_key,
            max_tokens=768, temperature=0.2,
        )
    except Exception as exc:
        raise RuntimeError(f"qa generation LLM call failed: {exc}") from exc
    attempt_costs.append(compute_call_cost(response, settings))
    content = _strip_json_fences(response.choices[0].message.content or "")
    return QAPairResult.model_validate_json(content), response
```
DATA-02 (`generate_instruction_example`) is the identical shape with `model="openai/strong_model"`, `temperature=0.3`, `max_tokens=1024`, and `InstructionPairResult` in place of `QAPairResult` — same helper structure, different constants (AI-SPEC Section 4).

**Entry-point flow** (`enrich.py` lines 195-369, `enrich_document()`): fetch source artifact (session) -> retrieve/bound text (no session) -> cache-check + budget-check (session) -> LLM call (no session) -> re-check-cache + write with `IntegrityError` race-handling (session). Copy this exact 4-step flow for `generate_qa_example()`/`generate_instruction_example()`, but:
- Use a DISTINCT `LlmSpend` scope `"dataset_generation"` (never `"global"` — enrich.py line 267/314 uses `scope="global"`; reusing it silently merges two budgets, per AI-SPEC Common Pitfall 2).
- Cache key: mirror `_enrichment_cache_key()` (lines 108-110) — `hashlib.sha256(f"{content_hash}:{prompt_version}".encode()).hexdigest()`.
- Never raise on LLM failure — return `{"status": "skipped_generation_failed", ...}` mirroring `enrich.py` line 292's `"skipped_enrichment_failed"`.
- Never raise on budget exceeded — return `{"status": "skipped_budget_exceeded"}` mirroring lines 268-275.

**IntegrityError race-handling** — copy `enrich.py` lines 338-361 verbatim pattern (catch `IntegrityError` on the cache-key unique constraint, re-check cache, return the winning writer's row rather than propagating a 500).

---

### `src/knowledge_lake/pipeline/export.py` (service, batch/file-I/O)

**Analog:** `src/knowledge_lake/storage/s3.py` (`put_raw`/`put_bronze` for the zone-write pattern) + `pipeline/clean.py` (silver-zone key-prefix convention, `_SILVER_PREFIX = "silver"` at line 30).

**Zone-prefix constant pattern** (`clean.py` line 30, `storage/s3.py` line 218 `f"raw/{source_id}/{content_hash}.{ext}"` / line 321 `f"bronze/{source_id}/{content_hash}.{ext}"`): add `_GOLD_PREFIX = "gold"` to `storage/s3.py` and build export keys as `f"gold/{export_kind}/{export_id}.{ext}"` (e.g. `gold/rag_corpus/{id}.parquet`, `gold/pretrain/{id}.jsonl`, `gold/finetune/{id}.jsonl`) — same content-addressed-by-zone convention, no new storage backend, `StorageBackend.put_object()`/`object_uri()` reused directly (never a second S3 client — FOUND-03 invariant, see `storage/s3.py` module docstring lines 1-17).

**In-memory buffer write** (RESEARCH.md Pattern 6, already vetted against "no local filesystem as production store"):
```python
import io
import polars as pl
df = pl.DataFrame(rows)
buf = io.BytesIO()
df.write_parquet(buf)  # or df.write_ndjson(buf) for EXPORT-02/03
storage.put_object(f"gold/rag_corpus/{export_id}.parquet", buf.getvalue())
```

**DuckDB query/verification** (RESEARCH.md Code Examples section, "DuckDB verification query pattern"):
```python
def verify_export(settings, export_uri: str) -> int:
    import duckdb
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(
        "SET s3_url_style='path'; SET s3_use_ssl=false; "
        f"SET s3_endpoint='{settings.storage.endpoint_url.replace('http://', '').replace('https://', '')}'; "
        f"SET s3_access_key_id='{settings.storage.access_key_id}'; "
        f"SET s3_secret_access_key='{settings.storage.secret_access_key}';"
    )
    (count,) = con.execute(f"SELECT COUNT(*) FROM read_parquet('{export_uri}')").fetchone()
    return count
```

**Registry-first write for the resulting `Dataset` row** — mirror `create_enriched_artifact`/`create_cleaned_artifact` shape in `repo.py` for a new `create_dataset()` helper (session.add, no commit — commit happens at the `get_session()` context-manager boundary).

---

### `src/knowledge_lake/quality/scorer.py` — EXTEND with `compute_composite_quality_score()`

**Analog:** same file's existing `compute_quality_score()` (lines 28-108) — weighted-heuristic convention, weights summing to 1.0, clamped to `[0.0, 1.0]`, `structlog` debug logging of each component.

**Pattern to copy** (RESEARCH.md Pattern 3, exact code):
```python
def compute_composite_quality_score(
    parse_quality_score: float,
    enrich_quality_score: float,
    filter_results: dict[str, dict],
) -> float:
    filter_pass_ratio = sum(1 for r in filter_results.values() if r["passed"]) / len(filter_results)
    return (
        parse_quality_score * 0.3
        + enrich_quality_score * 0.4
        + filter_pass_ratio * 0.3
    )
```
Add the same `log.debug("quality_scorer.composite", ...)` call with each component and the final score, matching lines 97-107's logging shape. Clamp to `[0.0, 1.0]` exactly as `compute_quality_score()` does at line 95.

---

### `src/knowledge_lake/registry/models.py` — EXTEND `Dataset`, ADD `DatasetExample`

**Analog:** `LlmSpend` (lines 393-423) and `VectorCollection` (lines 426-463) — both are small non-lineage-tree annotation/registry tables with a UUID primary key, a `UniqueConstraint`, and simple typed columns; `Dataset` (lines 465-479) is the exact table being extended.

**Real columns to add to `Dataset`** (per D-08):
```python
dataset_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
format: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
example_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
storage_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
```

**New `DatasetExample` model** (RESEARCH.md Pattern 5, exact code — mirrors `Artifact`'s self-FK-adjacent style and `LineageEvent`'s FK-to-artifacts pattern lines 226-274):
```python
class DatasetExample(Base):
    __tablename__ = "dataset_examples"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(64), ForeignKey("datasets.id", ondelete="CASCADE"), index=True)
    source_artifact_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    example_index: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[Optional[Any]] = mapped_column(_JSON, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```
Use the module's existing `_JSON` alias (defined lines 46-51) for the `payload` column, exactly as `Artifact.metadata_` and `Source.config` already do.

---

### `src/knowledge_lake/registry/repo.py` — EXTEND

**Analog:** `create_enriched_artifact()` (lines 617-663), `create_cleaned_artifact()` (lines 209-257), `get_llm_spend`/`record_llm_spend` (lines 669-701), `list_cleaned_artifacts()` (lines 597-611), `get_artifact_by_hash()` (lines 299-318).

**`create_curated_artifact()`** — copy `create_enriched_artifact`'s shape exactly (parent=`cleaned_document`, `art.quality_score = composite_score`, uses the shared `_make_artifact()` helper with `kind="curated_document", artifact_type="curated_document"`).

**`create_dataset()` / `create_dataset_example()`** — new, simple `session.add(...)`-then-return helpers mirroring `record_llm_spend`'s get-or-create discipline (lines 679-701) for `create_dataset()` if dedup-by-name is wanted, or a plain insert (like `create_cleaned_artifact`) if not.

**Budget scoping** — reuse `get_llm_spend(session, scope=...)`/`record_llm_spend(session, scope=..., cost_usd=...)` verbatim (lines 669-701), called with `scope="dataset_generation"` (a new, distinct scope string — never `"global"`).

**Batch dedup support** — reuse `list_cleaned_artifacts()` verbatim (lines 597-611) as the input list for `curate.py`'s batch MinHash pass; no new repo function needed for corpus enumeration.

---

### `src/knowledge_lake/config/settings.py` — EXTEND with `CurateSettings`, `DatasetSettings`, `ExportSettings`

**Analog:** `CleanSettings` (lines 96-110) for `CurateSettings`'s shape (thresholds, simple floats/ints); `EnrichSettings` (lines 133-182) for `DatasetSettings`'s shape (`budget_usd`, `prompt_version`, `excerpt_chars`, model-id-registration fields already present at lines 162-164 for `strong_model`/`eval_model` forward-compat).

**Pattern to copy** (`CleanSettings`, lines 96-110, verbatim structure):
```python
class CurateSettings(BaseModel):
    """DataTrove-style quality-filter and batch-dedup configuration (CURATE-01..03)."""
    gopher_min_doc_words: int = 50
    gopher_max_doc_words: int = 100_000
    # ... other filter thresholds, gate_on_low_quality: bool = False (flag-only default)
```
```python
class DatasetSettings(BaseModel):
    """LLM-based dataset generation configuration (DATA-01..02)."""
    budget_usd: float = 5.0          # mirrors EnrichSettings.budget_usd (D-07)
    prompt_version: str = "v1"
    excerpt_chars: int = 6000        # DATA-02 excerpt bound, per AI-SPEC Section 4
    cache_enabled: bool = True
```
```python
class ExportSettings(BaseModel):
    """Gold-zone export configuration (EXPORT-01..03)."""
    gold_prefix: str = "gold"
    default_finetune_format: str = "openai_chat"  # vs "alpaca"
```
Register each as a nested `Field(default_factory=...)` on `Settings` (lines 276-295 pattern) and env-prefix docstring exactly like the existing nested models (e.g. `KLAKE_DATASET__BUDGET_USD`).

---

### `src/knowledge_lake/storage/s3.py` — EXTEND with gold-zone prefix

**Analog:** `put_bronze()` (lines 261-359) — copy its exact 6-layer structure (hash -> registry no-op check -> key build -> `head_object` guard -> `put_object` -> registry insert with `IntegrityError` race handling) for any `put_gold()`-style helper, OR simply add a `_GOLD_PREFIX = "gold"` module constant and let `export.py` call `storage.put_object()`/`storage.object_uri()` directly (simpler — exports are not lineage-tree artifacts per D-08, so the full 6-layer `put_*` ceremony with a registry artifact insert is not required; a plain `put_object` + `Dataset`/export-manifest row is sufficient, mirroring `clean.py`'s simpler silver-zone write at lines 305-308 rather than the raw/bronze zone's full ceremony).

---

### `src/knowledge_lake/dagster_defs/assets.py` — EXTEND with `curate_document`, `generate_dataset`, `export_*` assets

**Analog:** `enrich_document` asset (lines 360-413) — thin `@asset` wrapping the plain pipeline function, resource injection via `PostgresResource`/`MinIOResource`/`LiteLLMResource`, `Settings` reconstruction from resources, structured logging before/after.

**Pattern to copy verbatim** (lines 360-413):
```python
@asset(
    description="...",
    group_name="pipeline",
)
def curate_document(
    clean_document: dict[str, Any],
    postgres: PostgresResource,
    minio: MinIOResource,
) -> dict[str, Any]:
    from knowledge_lake.config.settings import Settings, StorageSettings
    from knowledge_lake.pipeline.curate import curate_document as curate_fn
    cleaned_artifact_id = clean_document["artifact_id"]
    source_id = clean_document["source_id"]
    storage_settings = StorageSettings(endpoint_url=minio.endpoint_url, bucket=minio.bucket,
                                        access_key_id=minio.access_key_id, secret_access_key=minio.secret_access_key,
                                        region=minio.region)
    settings = Settings(database_url=postgres.database_url, storage=storage_settings, _env_file=None)
    log.info("dagster.curate_document.start", cleaned_artifact_id=cleaned_artifact_id)
    result = curate_fn(cleaned_artifact_id, source_id, settings=settings)
    log.info("dagster.curate_document.complete", status=result.get("status"))
    return result
```
`generate_dataset` additionally needs `litellm: LiteLLMResource` injected (exactly as `enrich_document` does at line 373) since it makes LLM calls. Export assets need no `LiteLLMResource` (no LLM calls), only `postgres`/`minio`.

---

### `src/knowledge_lake/cli/app.py` — EXTEND with `curate`, `dedupe`, `generate-dataset`, `export` commands

**Analog:** `cmd_enrich` (lines 288-333) — `@app.command(name=...)`, `typer.Argument` positional params, try/except narrowed to `(ValueError, LookupError)` printing `f"Error: {exc}"` to stderr and `raise typer.Exit(code=1)`, success path echoes each result-dict field on its own line.

**Pattern to copy** (lines 288-333, structure only — adapt fields per command):
```python
@app.command(name="curate")
def cmd_curate(
    cleaned_artifact_id: str = typer.Argument(..., help="ID of the cleaned_document artifact to curate."),
    source_id: str = typer.Argument(..., help="Source ID that owns the cleaned artifact."),
) -> None:
    """Run quality filters + composite scoring on a cleaned_document artifact."""
    from knowledge_lake.pipeline.curate import curate_document
    try:
        result = curate_document(cleaned_artifact_id, source_id)
        typer.echo("Curated:")
        for k, v in result.items():
            typer.echo(f"  {k}: {v}")
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
```
Same shape for `dedupe` (no per-artifact argument — runs the whole-corpus batch job), `generate-dataset` (chunk_id/document_id + dataset_id args), `export` (export_kind + output args).

---

## Shared Patterns

### Registry-first, session-scoped pipeline stage
**Source:** `src/knowledge_lake/pipeline/clean.py::clean()` (lines 162-339), `src/knowledge_lake/pipeline/enrich.py::enrich_document()` (lines 195-369)
**Apply to:** `curate.py`, `datasets.py`
```python
with get_session() as session:
    artifact = registry_repo.get_artifact(session, artifact_id)
    if artifact is None:
        raise ValueError(...)
    ...
# I/O and computation OUTSIDE any session
...
with get_session() as session:
    # cache-check / dedup-check, then write, all in one atomic block
    ...
```

### LiteLLM call shape (provider-prefix, retry, cost accumulation)
**Source:** `src/knowledge_lake/pipeline/enrich.py::_call_llm_for_enrichment` (lines 139-189)
**Apply to:** `datasets.py` (both DATA-01 and DATA-02 call sites)
```python
model="openai/eval_model"  # or "openai/strong_model" — never cheap_model, never a raw provider ID
# tenacity retry(stop_after_attempt(3), wait_exponential(...), retry on RuntimeError|ValidationError)
attempt_costs.append(compute_call_cost(response, settings))  # BEFORE validation, so failed-validation retries still count
```

### Budget cap graceful-halt
**Source:** `src/knowledge_lake/pipeline/enrich.py` lines 267-275 + `registry/repo.py::get_llm_spend`/`record_llm_spend` (lines 669-701)
**Apply to:** `datasets.py` — new `scope="dataset_generation"` (distinct from enrich's `"global"` scope)
```python
current_spend = registry_repo.get_llm_spend(session, scope="dataset_generation")
if current_spend >= s.dataset.budget_usd:
    return {"status": "skipped_budget_exceeded", ...}
```

### IntegrityError race-as-cache-hit
**Source:** `src/knowledge_lake/pipeline/enrich.py` lines 338-361, `src/knowledge_lake/storage/s3.py::put_raw`/`put_bronze` (lines 238-251, 338-352)
**Apply to:** any concurrent-safe insert in `curate.py`/`datasets.py`/`export.py`
```python
try:
    ...create + session.flush()
except IntegrityError:
    session.rollback(); session.expire_all()
    existing = registry_repo.get_artifact_by_hash(session, synthetic_hash, "...")
    if existing is None:
        raise
    return {...cached-hit shape...}
```

### Thin Dagster `@asset` wrapping a plain function
**Source:** `src/knowledge_lake/dagster_defs/assets.py` — every asset from `parse_document` through `index_chunks` (lines 90-514), most directly `enrich_document` (lines 360-413)
**Apply to:** `curate_document`, `generate_dataset`, `export_*` assets
```python
@asset(description="...", group_name="pipeline")
def curate_document(clean_document: dict[str, Any], postgres: PostgresResource, minio: MinIOResource) -> dict[str, Any]:
    from knowledge_lake.pipeline.curate import curate_document as curate_fn
    ...
    return curate_fn(...)
```

### Single-file Typer CLI command
**Source:** `src/knowledge_lake/cli/app.py::cmd_enrich` (lines 288-333)
**Apply to:** `curate`, `dedupe`, `generate-dataset`, `export` commands
```python
@app.command(name="curate")
def cmd_curate(...) -> None:
    try:
        result = curate_document(...)
        typer.echo(...)
    except (ValueError, LookupError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
```

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| DataTrove direct-filter-call adapter (inside `curate.py`) | transform | batch | No prior codebase use of DataTrove; RESEARCH.md Pattern 1/AI-SPEC already provide the fully-vetted code shape (sourced directly from DataTrove v0.9.0 upstream) — use that as the primary reference instead of an in-repo analog |
| DuckDB `httpfs`/S3 query layer (inside `export.py`) | query engine | batch | No prior DuckDB usage in this repo; RESEARCH.md Code Examples section provides the vetted pattern (cited against duckdb.org docs) |
| Polars Parquet/JSONL writer (inside `export.py`) | transform | file-I/O | No prior Polars usage in this repo; RESEARCH.md Pattern 6 provides the vetted in-memory-buffer pattern |

## Metadata

**Analog search scope:** `src/knowledge_lake/pipeline/`, `src/knowledge_lake/quality/`, `src/knowledge_lake/registry/`, `src/knowledge_lake/config/`, `src/knowledge_lake/storage/`, `src/knowledge_lake/dagster_defs/`, `src/knowledge_lake/cli/`
**Files scanned:** `enrich.py`, `clean.py`, `scorer.py`, `models.py`, `repo.py`, `settings.py`, `s3.py`, `assets.py`, `app.py` (9 files, ~4,014 lines total; targeted reads only, no full-file re-reads)
**Pattern extraction date:** 2026-07-06
