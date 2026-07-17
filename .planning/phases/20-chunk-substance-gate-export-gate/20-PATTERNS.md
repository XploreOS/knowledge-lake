# Phase 20: Chunk Substance Gate + Export Gate - Pattern Map

**Mapped:** 2026-07-17
**Files analyzed:** 11 (new + modified)
**Analogs found:** 11 / 11

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `src/knowledge_lake/pipeline/chunk.py` (modify: gate + hash formula + `domain_filters` param) | pipeline/service | transform (CRUD-ish, artifact persist) | `src/knowledge_lake/pipeline/curate.py` (`score_document`, `_build_filters`, `_curation_cache_key`) | exact — same "run DataTrove filters + cache-key-with-version" shape |
| `src/knowledge_lake/pipeline/chunk.py` (predicate wiring) | pipeline/service | transform | `src/knowledge_lake/pipeline/quality/predicates.py` + `pipeline/quality/__init__.py` | exact — `run_predicates()` combinator is the direct dependency |
| `src/knowledge_lake/config/settings.py` (`ChunkQualitySettings` + `Settings.chunk_quality` field) | config | CRUD (settings model) | `src/knowledge_lake/config/settings.py:293` (`CurateSettings`) | exact — same nested-BaseModel-with-`filter_config_version` shape |
| `src/knowledge_lake/pipeline/export.py` (`export_rag_corpus()` — substance filter) | service | transform / batch (Parquet export) | `src/knowledge_lake/pipeline/export.py:290-299` (existing `domain` mismatch `continue` filter, same function) | exact — same function, same row-skip idiom |
| `src/knowledge_lake/pipeline/datasets.py` (`version` field on generated payload dicts) | service | transform / batch | `src/knowledge_lake/pipeline/datasets.py:139` (`_dataset_gen_cache_key`) | exact — identical `prompt_version`-keyed cache-key precedent |
| `src/knowledge_lake/dagster_defs/assets.py` (`chunk_document` asset — `domain_filters` resolution) | controller/orchestration (Dagster asset) | request-response (asset materialization) | `src/knowledge_lake/dagster_defs/assets.py:452-455` (`enrich_document` asset's `DomainLoader` guard) | exact — same `if settings.domain.domain_name:` guard shape, different `.filters` attr instead of `.render_prompt()` |
| `src/knowledge_lake/pipeline/process.py` (`process_crawled()` — `domain_filters` resolution + threaded into `chunk()`) | controller (CLI/API orchestration) | request-response | `src/knowledge_lake/dagster_defs/assets.py:452-455` (same `DomainLoader` guard, CLI-side twin) | role-match — CLI path mirrors the Dagster asset's guard |
| `domains/healthcare/filters.yaml` (add cardinality-constraint pattern) | config (domain pack data) | CRUD | `domains/healthcare/filters.yaml` (existing `normative_allowlists` entries) | exact — same file, additive entry |
| `tests/fixtures/must_not_reject.yaml` (new) | test fixture | batch (parametrized data) | N/A — new fixture pattern; nearest structural analog is `domains/healthcare/filters.yaml`'s YAML-list shape | role-match |
| `tests/test_must_not_reject.py` (new) | test | batch (parametrized pytest) | `tests/unit/test_quality_predicates.py` | exact — same predicate-testing module, extends its parametrize style |
| `tests/unit/test_chunk_substance_gate.py` (new) | test | batch | `tests/unit/test_quality_predicates.py`, `tests/unit/test_chunk_storage.py`, `tests/unit/test_chunk_token.py` | role-match — gate logic tests mirror predicate + chunk-persistence test structure |
| `tests/unit/test_export.py` (modify: `substance_passed` assertions) | test | batch | `tests/unit/test_export_domain_filter.py` (existing analogous domain-filter test in same suite) | exact — same filtering-assertion pattern, different field |
| `tests/unit/test_chunk_storage.py` (modify: cache-key versioning assertions) | test | batch | same file, existing hash-based cache tests | exact |
| `tests/unit/test_datasets.py` (modify: version-tag assertions) | test | batch | same file, existing `_dataset_gen_cache_key` tests | exact |

## Pattern Assignments

### `src/knowledge_lake/pipeline/chunk.py` (pipeline/service, transform)

**Analogs:** `src/knowledge_lake/pipeline/curate.py` (DataTrove wrapping + cache versioning), `src/knowledge_lake/pipeline/quality/__init__.py` + `predicates.py` (predicate combinator), `src/knowledge_lake/dagster_defs/assets.py:452-455` (DomainLoader guard, mirrored inside `process.py`/`chunk_document`, not `chunk.py` itself — `chunk()` just accepts `domain_filters` as a param).

**Imports pattern** (current top of `chunk.py`, lines 28-39):
```python
from __future__ import annotations

import hashlib
import re

import structlog
import tiktoken as _tiktoken

from knowledge_lake.config.settings import Settings, get_settings
from knowledge_lake.plugins.protocols import ParsedDoc
from knowledge_lake.registry import repo as registry_repo
from knowledge_lake.registry.db import get_session
from knowledge_lake.storage.s3 import _UNCLASSIFIED_DOMAIN, StorageBackend
```
Add `run_predicates` and predicate imports from `knowledge_lake.pipeline.quality` at module scope (zero-I/O, safe to import eagerly). Keep the `FineWebQualityFilter` import deferred inside a factory function (see below) — mirrors `curate.py`'s `_build_filters()` deferred-import discipline exactly.

**Deferred-import factory pattern to copy** (from `curate.py:35-58`, `_build_filters`):
```python
def _build_filters(settings: CurateSettings) -> list:
    """Factory returning the configured DataTrove filter instances.
    ... Imports are inside the function so they are deferred ...
    """
    from datatrove.pipeline.filters.c4_filters import C4QualityFilter  # noqa: PLC0415
    from datatrove.pipeline.filters.gopher_quality_filter import (
        GopherQualityFilter,  # noqa: PLC0415
    )
    ...
    return [GopherRepetitionFilter(), GopherQualityFilter(...), C4QualityFilter(...)]
```
Copy this exact shape for a new `_build_fineweb_filter(settings: ChunkQualitySettings)` in `chunk.py`, returning a single configured `FineWebQualityFilter` instance (see RESEARCH.md Pattern 1 for the full body — already drafted and verified against installed `datatrove==0.9.0`).

**Cache-key versioning pattern to copy** (from `curate.py:80-91`, `_curation_cache_key`):
```python
def _curation_cache_key(cleaned_content_hash: str, filter_config_version: str) -> str:
    """Derive the synthetic content_hash used to look up a cached curated artifact.
    Mirrors _enrichment_cache_key exactly:
    sha256(f"{cleaned_content_hash}:{filter_config_version}")
    ...
    """
    return hashlib.sha256(
        f"{cleaned_content_hash}:{filter_config_version}".encode()
    ).hexdigest()
```
Apply directly at the EXISTING hash site in `chunk.py` (current code, lines ~314-317):
```python
# CURRENT (chunk.py, inside the raw_chunks persistence loop):
hash_input = f"{parsed_artifact_id}:{text}"
content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
```
Change to (per RESEARCH.md Pattern 3 / Pitfall 3 — this is a REQUIRED formula change, not additive):
```python
hash_input = f"{parsed_artifact_id}:{s.chunk_quality.filter_config_version}:{text}"
content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
```

**Core gate-wiring pattern** — insert between `raw_chunks = _build_token_chunks(...)` (existing, unchanged) and the existing per-chunk persistence `for raw in raw_chunks:` loop (`chunk.py` around line 309), using `run_predicates()` from `pipeline/quality/`:
```python
import functools
from knowledge_lake.pipeline.quality import (
    check_table_exemption, check_domain_allowlist, check_token_floor,
    check_alpha_ratio, check_link_density, check_stopword_ratio,
    check_terminal_punct_ratio, run_predicates,
)

allowlist_patterns = domain_filters.normative_allowlists if domain_filters else []
allowlist_pred = functools.partial(check_domain_allowlist, allowlist_patterns=allowlist_patterns)
fineweb_pred = functools.partial(_fineweb_predicate, filter_instance=_build_fineweb_filter(s.chunk_quality))

preds = [check_table_exemption, allowlist_pred, fineweb_pred, check_token_floor,
         check_alpha_ratio, check_link_density, check_stopword_ratio, check_terminal_punct_ratio]
exemptions = {check_table_exemption, allowlist_pred}

for raw in raw_chunks:
    result = run_predicates(raw["text"], {"is_table": raw["is_table"]}, preds, exemption_predicates=exemptions)
    raw["substance_passed"] = result.passed
    raw["rejection_reason"] = None if result.passed else result.reason

if s.chunk_quality.gate_mode == "enforce":
    kept = [r for r in raw_chunks if r["substance_passed"]]
else:  # report mode — annotate, keep all
    kept = raw_chunks

rejected_count = len(raw_chunks) - len([r for r in raw_chunks if r["substance_passed"]])
assert rejected_count + len([r for r in raw_chunks if r["substance_passed"]]) == len(raw_chunks)  # QUAL-05 conservation
```
Note: `is_table=True` chunks must be exempt (D-03) — `check_table_exemption` already implements this per Phase 19; verify it inspects `metadata["is_table"]`.

**Verified FineWebQualityFilter wrapper** (RESEARCH.md, empirically tested against installed `datatrove==0.9.0`):
```python
def _fineweb_predicate(text: str, metadata: dict, *, filter_instance) -> PredicateResult:
    from datatrove.data import Document  # noqa: PLC0415
    from knowledge_lake.pipeline.quality import PredicateResult

    doc = Document(text=text, id="chunk", metadata={})
    outcome = filter_instance.filter(doc)
    if isinstance(outcome, tuple):
        passed, reason = outcome
    else:
        passed, reason = bool(outcome), "fineweb_ok"
    return PredicateResult(passed, reason or "fineweb_reject")
```

**Function signature change** — add `domain_filters` param to `chunk()`, mirroring `clean()`'s existing (currently unused-by-callers) parameter shape:
```python
def chunk(
    parsed_artifact_id: str,
    source_id: str,
    parsed_doc: ParsedDoc,
    *,
    settings: Settings | None = None,
    domain_filters: "DomainFilters | None" = None,
) -> list[dict]:
```

**Error handling pattern:** No new try/except needed in `chunk()` itself — `check_domain_allowlist` already catches `re.error` per-pattern internally (Phase 19, `predicates.py`, verified non-fatal). `FineWebQualityFilter.filter()` should get a defensive `import importlib.metadata` at module top per RESEARCH.md Pitfall 4 (belt-and-suspenders against the lazy-binding `AttributeError`).

---

### `src/knowledge_lake/config/settings.py` (config, CRUD)

**Analog:** `CurateSettings` (lines 293-309):
```python
class CurateSettings(BaseModel):
    """DataTrove-style curation and composite quality scoring configuration (CURATE-01..03).

    Nested under Settings as settings.curate. Environment variable pattern:
    KLAKE_CURATE__GOPHER_MIN_DOC_WORDS, etc.
    """

    gopher_min_doc_words: int = 50
    gopher_max_doc_words: int = 100_000
    filter_no_terminal_punct: bool = False

    filter_config_version: str = "v1"
    """Bumping this invalidates the curation cache (mirrors EnrichSettings.prompt_version)."""
```
Copy this exact shape for `ChunkQualitySettings`:
```python
class ChunkQualitySettings(BaseModel):
    """Chunk-scope substance-gate and FineWebQualityFilter configuration (QUAL-02/03, PIPE-01).

    Nested under Settings as settings.chunk_quality. Environment variable pattern:
    KLAKE_CHUNK_QUALITY__GATE_MODE, KLAKE_CHUNK_QUALITY__FILTER_CONFIG_VERSION, etc.
    """

    gate_mode: Literal["enforce", "report"] = "enforce"
    min_token_count: int = ...
    min_alpha_ratio: float = ...
    max_link_density: float = ...
    min_stopword_ratio: float = ...
    fineweb_line_punct_thr: float = ...
    fineweb_short_line_thr: float = ...
    fineweb_short_line_length: int = ...

    filter_config_version: str = "1.0"
    """Bumping this invalidates the chunk gate cache (mirrors CurateSettings.filter_config_version)."""
```
Then register on the top-level `Settings` class exactly like `curate`/`chunk`/`domain` are registered (`settings.py:634,655,686`):
```python
chunk_quality: ChunkQualitySettings = Field(default_factory=ChunkQualitySettings)
```

---

### `src/knowledge_lake/pipeline/export.py` (`export_rag_corpus()`) (service, batch export)

**Analog:** same function, existing `domain` mismatch filter (`export.py:290-299`):
```python
if domain is not None and row_domain != domain:
    filtered_out += 1
    continue
```
**Core pattern to copy** — same row-skip idiom, applied before row-building, using `chunk.metadata_` (D-08/D-09 backward-compat default `True`):
```python
meta = chunk.metadata_ or {}
if not meta.get("substance_passed", True):
    substance_filtered_out += 1
    continue
```
**Logging pattern** — extend the existing `export.rag_corpus.building` structured log (D-10) with the new counter, following the same `structlog` call-site convention used elsewhere in this file for `filtered_out`.

**Anti-pattern to avoid (explicit in RESEARCH.md):** do NOT add `substance_passed`/`rejection_reason` to `_RAG_CORPUS_FIELDS` — that allow-list is a security-reviewed export-column boundary (T-05-08); the gate must remain a pre-filter `continue`, never a new exported field.

---

### `src/knowledge_lake/pipeline/datasets.py` (service, batch)

**Analog:** `_dataset_gen_cache_key` (line 139):
```python
def _dataset_gen_cache_key(source_content_hash: str, prompt_version: str) -> str:
    """... folds content_hash plus the current prompt_version so that changing the prompt ..."""
    return hashlib.sha256(f"{source_content_hash}:{prompt_version}".encode()).hexdigest()
```
Add a `version` field to the generated Q&A/instruction payload dicts (used at `generate_qa_example`, lines ~254-312 and ~472), deriving the value from `s.chunk_quality.filter_config_version` (D-11/D-12) — same "settings field feeds a payload/cache-key field" wiring already proven for `prompt_version`.

---

### `src/knowledge_lake/dagster_defs/assets.py` — `chunk_document` asset (controller/orchestration)

**Analog:** `enrich_document` asset's existing `DomainLoader` guard (lines 452-455, verbatim in codebase):
```python
domain_system_prompt: str | None = None
if settings.domain.domain_name:
    from knowledge_lake.domains.loader import DomainLoader
    domain_system_prompt = DomainLoader.from_name(settings.domain.domain_name).render_prompt("enrich.j2")
```
**Apply to `chunk_document`** (current body at `assets.py:350-392`) — insert before the `chunks = chunk(...)` call:
```python
domain_filters = None
if settings.domain.domain_name:
    from knowledge_lake.domains.loader import DomainLoader
    domain_filters = DomainLoader.from_name(settings.domain.domain_name).filters

chunks = chunk(parsed_artifact_id, source_id, doc, settings=settings, domain_filters=domain_filters)
```
This is the exact fix for RESEARCH.md Pitfall 1 — without it, MEAS-02's must-not-reject fixtures fail end-to-end even though the unit-level predicate test passes.

---

### `src/knowledge_lake/pipeline/process.py` — `process_crawled()` (controller, CLI/API path)

**Analog:** same `DomainLoader` guard pattern as above (`assets.py:452-455`), applied at the existing `chunk(parsed_id, src_id, cleaned_doc)` call site (`process.py:113`):
```python
domain_filters = None
if settings.domain.domain_name:
    from knowledge_lake.domains.loader import DomainLoader
    domain_filters = DomainLoader.from_name(settings.domain.domain_name).filters

chunks_list = chunk(parsed_id, src_id, cleaned_doc, domain_filters=domain_filters)
```

---

### `domains/healthcare/filters.yaml` (config, domain pack data)

**Analog:** existing file itself — `normative_allowlists` list:
```yaml
normative_allowlists:
  - "ICD-10"
  - "LOINC"
  - "RxNorm"
  - "§\\d+\\.\\d+"
  - "\\d+\\s*mg"
  - "PO\\s+BID"
```
**Pattern to copy** — add ONE new narrow entry for the `cardinality_constraint` MEAS-02 category (RESEARCH.md Pitfall 2), following the existing narrow-pattern discipline (never `.*`-broad, per `DomainFilters` docstring in `domains/models.py`):
```yaml
  - "\\d+\\s*(?:of|/)\\s*\\d+"
```

---

### `tests/fixtures/must_not_reject.yaml` (new fixture)

**Structural analog:** `domains/healthcare/filters.yaml`'s YAML-list shape and `DomainLoader`'s `yaml.safe_load()` convention. Each entry: `label`, `text`, `category` (`icd_code`, `dosage`, `loinc`, `hipaa_ref`, `cardinality_constraint`) per D-15.

---

### `tests/test_must_not_reject.py` (new) / `tests/unit/test_chunk_substance_gate.py` (new)

**Analog:** `tests/unit/test_quality_predicates.py` — parametrize style, PredicateResult assertions, and (for the substance-gate test) the module's import-boundary/subprocess-isolation test pattern (lines 1-40 shown below) as a template for any new isolation-sensitive tests:
```python
"""Tests for pipeline/quality/ pure predicate module (QUAL-01)."""
from __future__ import annotations

import subprocess
import sys

from knowledge_lake.pipeline.quality import (
    PredicateResult, check_alpha_ratio, check_domain_allowlist,
    check_link_density, check_stopword_ratio, check_table_exemption,
    check_terminal_punct_ratio, check_token_floor,
    compute_substance_signals, run_predicates,
)
```
Load the YAML fixture with `yaml.safe_load()` (matches `DomainLoader`'s convention) and `pytest.mark.parametrize` over its entries, asserting each passes `run_predicates()` with the full predicate chain (including `check_domain_allowlist` fed the healthcare pack's patterns) and passes `FineWebQualityFilter` directly.

---

### `tests/unit/test_export.py` (modify)

**Analog:** `tests/unit/test_export_domain_filter.py` — same test suite, same "build fake chunk artifacts with specific `metadata_`, call `export_rag_corpus()`, assert row inclusion/exclusion + filtered-out counters" pattern already proven for the `domain` filter; replicate for `substance_passed` including the backward-compat default-`True` case (D-09).

---

### `tests/unit/test_chunk_storage.py` (modify) / `tests/unit/test_datasets.py` (modify)

**Analogs:** existing hash-based cache-key tests in the same files — add assertions that two `chunk()` calls with different `filter_config_version` values produce different `content_hash`/`artifact_id` (mirrors the existing `_curation_cache_key`/`_dataset_gen_cache_key` cache-versioning tests already present in this suite for curate/datasets).

## Shared Patterns

### Deferred-import factory for stateful DataTrove filter classes
**Source:** `src/knowledge_lake/pipeline/curate.py:35-58` (`_build_filters`)
**Apply to:** `chunk.py`'s new `_build_fineweb_filter()` — keeps `pipeline/quality/`'s zero-I/O contract intact; tests that don't exercise the real filter never need `datatrove` at import time.

### Config-version-in-hash cache invalidation
**Source:** `src/knowledge_lake/pipeline/curate.py:80-91` (`_curation_cache_key`) and `src/knowledge_lake/pipeline/datasets.py:139` (`_dataset_gen_cache_key`)
**Apply to:** `chunk.py`'s per-chunk hash formula (must be changed in-place, not additive — see Pitfall 3) and `datasets.py`'s new `version` field derivation.
```python
hashlib.sha256(f"{X}:{filter_config_version}".encode()).hexdigest()
```

### DomainLoader resolution guard
**Source:** `src/knowledge_lake/dagster_defs/assets.py:452-455` (`enrich_document` asset)
**Apply to:** `chunk_document` asset AND `process_crawled()` CLI path — both must resolve `domain_filters` and thread it into `chunk()`, or MEAS-02 fixtures fail end-to-end (Pitfall 1).
```python
if settings.domain.domain_name:
    from knowledge_lake.domains.loader import DomainLoader
    domain_filters = DomainLoader.from_name(settings.domain.domain_name).filters
```

### `run_predicates()` composite gate with exemption ordering
**Source:** `src/knowledge_lake/pipeline/quality/predicates.py`, `pipeline/quality/__init__.py`
**Apply to:** `chunk.py`'s gate. Exemption predicates (`check_table_exemption`, domain-allowlist partial) MUST be listed first so they short-circuit before threshold predicates run.

### Row-skip pre-filter (never a new exported column)
**Source:** `src/knowledge_lake/pipeline/export.py:290-299` (existing `domain` filter `continue`)
**Apply to:** `export_rag_corpus()`'s new `substance_passed` gate — same `continue`-before-row-build idiom, never added to `_RAG_CORPUS_FIELDS`.

### Structured logging with counters
**Source:** `export.rag_corpus.building` event (existing in `export.py`), `structlog.get_logger(__name__)` convention used across all pipeline modules
**Apply to:** New `substance_filtered_out` counter in the export log; gate rejection counts in `chunk()`'s `chunk.raw_chunks`-style `log.info` calls.

## No Analog Found

None — every file in scope has a strong analog (curate.py's DataTrove/cache-versioning pair, quality/predicates.py's combinator, export.py's existing row-filter, enrich_document's DomainLoader guard, datasets.py's version-cache-key precedent). This phase is explicitly "wiring, not building" per RESEARCH.md.

## Metadata

**Analog search scope:** `src/knowledge_lake/pipeline/` (chunk.py, curate.py, export.py, datasets.py, process.py, quality/), `src/knowledge_lake/config/settings.py`, `src/knowledge_lake/dagster_defs/assets.py`, `src/knowledge_lake/domains/` (loader.py, models.py), `domains/healthcare/filters.yaml`, `tests/unit/` (test_quality_predicates.py, test_export.py, test_export_domain_filter.py, test_chunk_storage.py, test_chunk_token.py, test_datasets.py)
**Files scanned:** ~15 source files read directly (full or targeted ranges) plus RESEARCH.md's own verified excerpts (already validated by direct execution against the live codebase)
**Pattern extraction date:** 2026-07-17
