# Phase 17: Close the Bypass + Measurement - Pattern Map

**Mapped:** 2026-07-16
**Files analyzed:** 5 (4 modify, 1 new — audit module optional 6th)
**Analogs found:** 5 / 5 (self-referential — this is a retrofit phase; every "analog" is the sibling stage in the same pipeline)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|-----------------|---------------|
| `src/knowledge_lake/pipeline/clean.py` (`clean()`) | service (pipeline stage) | CRUD (artifact registry) + transform | `src/knowledge_lake/pipeline/chunk.py` (`chunk()`) | exact — same stage shape: fetch parent artifact → transform → hash → dedup-check → write S3 → create registry row |
| `src/knowledge_lake/dagster_defs/assets.py` (`clean_document`) | orchestration asset | request-response (dict-in/dict-out) | same file's `parsed_document` / `chunk_document` assets (adjacent stages) | exact — identical asset wrapper shape already in the same file |
| `src/knowledge_lake/pipeline/process.py` (`process_crawled`) | service (CLI/API/MCP shared function) | batch (loop over raw docs) | itself, pre-existing `parse→chunk→embed→index` loop (this phase inserts one line) | exact — modifying in place, not analog-copying |
| `src/knowledge_lake/cli/app.py` (new `quality-audit` command) | route/CLI command | batch / request-response (read-heavy, prints a table) | `cmd_lineage` (`cli/app.py:938`) and `cmd_reindex` (`cli/app.py:885`) | role-match — both are read-heavy Typer commands that resolve DB state and print a table/tree, no mutation of source-of-truth beyond safe idempotent pipeline re-run |
| `tests/unit/test_clean.py` (extend) | test | unit | existing tests in same file + `tests/unit/test_clean_silver_key.py` (mocking pattern) | exact |
| `tests/unit/test_process_crawled_clean.py` (new) | test | integration-ish unit | `tests/unit/test_pipeline_extractions.py` (process_crawled signature test) | role-match |

## Pattern Assignments

### `src/knowledge_lake/pipeline/clean.py` — `clean()` (service, CRUD+transform)

**Analog:** `src/knowledge_lake/pipeline/chunk.py` (same repo, sibling stage — already implements the WR-05 hash-scoping fix this phase must port into `clean.py`)

**WR-05 parent-scoped hash pattern to copy** (`chunk.py:315-318`):
```python
# Include parsed_artifact_id in the hash so identical chunk text from
# different documents creates distinct artifacts (WR-05: dedup key must
# include parent to prevent lineage corruption across documents)
hash_input = f"{parsed_artifact_id}:{text}"
content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
```
Apply identically in `clean.py`, replacing the current unscoped line at `clean.py:230-232`:
```python
# BEFORE (clean.py:230-232) — unscoped, the CLEAN-03 bug:
cleaned_bytes = cleaned_text.encode("utf-8")
content_hash = hashlib.sha256(cleaned_bytes).hexdigest()

# AFTER:
hash_input = f"{parsed_artifact_id}:{cleaned_text}"
content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
cleaned_bytes = cleaned_text.encode("utf-8")  # still needed for the S3 put_object body
```

**Current signature to extend** (`clean.py:170-175`):
```python
def clean(
    parsed_artifact_id: str,
    source_id: str,
    *,
    settings: Settings | None = None,
) -> dict:
```
Add `parsed_doc: ParsedDoc | None = None` as a new keyword-only parameter (optional, backward compatible — Pitfall 2/3 in RESEARCH.md). When provided, skip the S3 re-fetch at `clean.py:220-224` (`storage.get_object(key)` / `raw_bytes.decode`) and clean sections from the in-memory object instead of (or in addition to) the flat `parsed_text` blob.

**Existing dedup-check + registry-write pattern to preserve exactly** (`clean.py:299-345`, the `with get_session() as session:` block): this is the same "read parent → check `get_artifact_by_hash` → write S3 (idempotent put) → `registry_repo.create_cleaned_artifact(...)`" shape used by `chunk.py`'s per-chunk loop (`chunk.py:311-345`) and `parse.py`'s exact-dedup step (referenced in `clean.py`'s own docstring as "same pattern as parse stage (FOUND-04)"). Do not restructure this block — only add new keys to the `metadata=` dict passed to `create_cleaned_artifact` (see Pattern 2 below) and change the hash line.

**Metadata dict to extend** (`clean.py:340-344`):
```python
metadata={
    "language": language,
    "dedup_status": dedup_status,
    "minhash_num_perm": s.clean.minhash_num_perm,
    # NEW (QUAL-04, QUAL-05) — add here, computed unconditionally before this
    # block, including on the exact-dup early-return path at clean.py:305-320:
    "sections_considered": sections_considered,
    "sections_kept": sections_kept,
    "sections_rejected": sections_rejected,
    "rejection_reasons": rejection_reasons,
},
```

**Conservation invariant — logging + error convention to copy** (this codebase's zero-bare-`assert` convention, verified via grep of `pipeline/*.py`): follow the existing `log = structlog.get_logger(__name__)` (`clean.py:36`) + `log.info/warning` shape already used throughout this file (e.g. `clean.py:307-311` `log.info("clean.exact_dup", ...)`), then raise a plain `RuntimeError` for the conservation violation — matches the existing `ValueError` raises at `clean.py:211-218` for other precondition failures (structlog call immediately followed by a raised exception, not a bare `assert`).

**Section-level boilerplate loop** — no direct analog exists in this codebase (this is genuinely new code within `clean()`), but it must reuse the existing `remove_boilerplate()` helper (`clean.py:81-90`) per-section instead of introducing a second boilerplate implementation. Use `dataclasses.replace()` to build cleaned `Section` copies (stdlib, matches the plain-dataclass shape of `Section`/`ParsedDoc` in `plugins/protocols.py:34-79`) rather than mutating sections in place, to avoid the aliasing hazard flagged in RESEARCH.md Pitfall 3.

---

### `src/knowledge_lake/dagster_defs/assets.py` — `clean_document` (orchestration asset, request-response)

**Analog:** sibling assets in the same file — `parsed_document` (immediately above, ends at line 265) and `chunk_document` (immediately below, starts ~line 340). Same wrapper shape: destructure input dict → call one pipeline function → build output dict → `log.info` start/complete → return.

**Current implementation to modify** (`assets.py:276-335`, read in full this session):
```python
def clean_document(
    parsed_document: dict[str, Any],
    postgres: PostgresResource,
    minio: MinIOResource,
) -> dict[str, Any]:
    ...
    parsed_artifact_id = parsed_document["artifact_id"]
    source_id = parsed_document["source_id"]
    collection = parsed_document.get("collection", DEFAULT_COLLECTION)
    parsed_doc = parsed_document["parsed_doc"]
    ...
    clean_result = clean(parsed_artifact_id, source_id, settings=settings)

    result = {
        "artifact_id": clean_result["artifact_id"],
        "source_id": source_id,
        "collection": collection,
        "parsed_artifact_id": parsed_artifact_id,
        "parsed_doc": parsed_doc,  # forwarded in-memory to chunk_document (Pitfall 7)
        "language": clean_result["language"],
        "dedup_status": clean_result["dedup_status"],
    }
    ...
    return result
```
**Required change (single value swap, D-01 resolution):** thread `parsed_doc=parsed_doc` into the `clean(...)` call, and change `"parsed_doc": parsed_doc` to `"parsed_doc": clean_result["cleaned_doc"]`. No other lines in this function need to change; no changes at all to `chunk_document`, `tree_index_document`, or `enrich_document`, which already do `doc = clean_document["parsed_doc"]` via the identical dict-destructure pattern used by `clean_document` itself on its own input (`parsed_document["parsed_doc"]` at line ~296).

**Existing in-memory-forwarding comment to preserve/extend:** `# forwarded in-memory to chunk_document (Pitfall 7)` — this is the established project convention for why `parsed_doc` is passed as a raw Python object between Dagster assets rather than through an IO manager. Keep this comment style when updating.

---

### `src/knowledge_lake/pipeline/process.py` — `process_crawled` (service, batch)

**Analog:** itself — the fix is a one-line insertion into the existing `try:` block, not a copy from elsewhere.

**Current loop body to modify** (`process.py:102-115`, read in full this session):
```python
try:
    parse_result, parsed_doc = parse(raw_id, src_id, mime_type=mime)
    parsed_id = parse_result["artifact_id"]

    chunks_list = chunk(parsed_id, src_id, parsed_doc)
    if not chunks_list:
        processed += 1
        continue

    vectors, dim = embed(chunks_list)
    index(chunks_list, vectors, dim, parsed_id, collection=collection)

    processed += 1
    total_chunks += len(chunks_list)
except Exception:
    failed += 1
    log.warning("process_crawled: doc %s failed", raw_id, exc_info=True)
```
**Required change (CLEAN-02, full parity with the Dagster path per D-02):**
```python
try:
    parse_result, parsed_doc = parse(raw_id, src_id, mime_type=mime)
    parsed_id = parse_result["artifact_id"]

    clean_result = clean(parsed_id, src_id, parsed_doc=parsed_doc)   # NEW
    cleaned_doc = clean_result["cleaned_doc"]                         # NEW

    chunks_list = chunk(parsed_id, src_id, cleaned_doc)                # CHANGED: was parsed_doc
    if not chunks_list:
        processed += 1
        continue
    ...
```
Add `from knowledge_lake.pipeline.clean import clean` to the existing local-import block at `process.py:52-58` (this module already local-imports every pipeline stage it calls — `chunk`, `embed`, `index`, `parse` — matching pattern, add `clean` alongside them). `chunk()` still receives `parsed_id` as its parent argument (unchanged) — only the `doc` positional argument changes from `parsed_doc` to `cleaned_doc` (never re-parent to the cleaned artifact — Anti-Pattern in RESEARCH.md).

---

### `src/knowledge_lake/cli/app.py` — new `quality-audit` command (CLI route, batch/request-response)

**Analog:** `cmd_lineage` (`cli/app.py:937-969`) for the "resolve state, print a table, no destructive writes" command shape; `cmd_reindex` (`cli/app.py:884-936`, not fully read but same file region) for the "re-run part of the pipeline safely and report counts" shape.

**Command decorator + docstring pattern to copy** (`cli/app.py:937-940`):
```python
@app.command(name="lineage")
def cmd_lineage(
    artifact_id: str = typer.Argument(
        ...,
        help="Artifact ID or unambiguous prefix to trace (e.g. 'chk_019f...' or 'chk_019f').",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Output machine-readable JSON instead of the tree."
    ),
) -> None:
    """Print the full lineage ancestry of an artifact.
    ...
    """
```
Model `quality-audit` on this: a Typer command with `--domain` (default `"healthcare"`) and `--json` options, a docstring describing the read/measurement nature of the command (mirroring `cmd_lineage`'s "Default output is a human-readable tree; use --json for the machine graph"), local imports at the top of the function body (this file's established convention — every command in `cli/app.py` local-imports its pipeline/registry dependencies, not at module top), and `typer.Exit(code=1)` + `typer.echo(..., err=True)` for error paths (copy `cmd_lineage`'s `except (LookupError, ValueError) as exc:` block verbatim in shape).

**Domain-filtering pattern to copy** (`registry/repo.py:906-921`, `get_domain_for_source`):
```python
def get_domain_for_source(session: Session, source_id: str) -> str | None:
    """...
    KL-15: domain is now a first-class indexed column (``Source.domain``,
    migration 0010) and is read from there first. Falls back to the legacy
    ``Source.config["domain"]`` JSON blob only as a defensive belt...
    """
    source = session.get(Source, source_id)
    if source is None:
        return None
    if source.domain:
        return source.domain
    if source.config:
        ...
```
The `quality-audit` command must query `Source.domain == "healthcare"` directly via a parameterized ORM `select(Source).where(Source.domain == domain_value)` (this is the *first-class column* precedent, not `list_sources_for_crawl_all`'s legacy `Source.config['domain']` JSON-scan path at `repo.py:963-974`, which RESEARCH.md's Don't-Hand-Roll table explicitly flags as the stale/legacy variant to avoid for new code). Do not hardcode any expected row count (Pitfall 4 — pack file has 28 entries, "34" refers to a runtime DB state that varies by environment).

---

## Shared Patterns

### Structured logging (structlog)
**Source:** `src/knowledge_lake/pipeline/clean.py:36` — `log = structlog.get_logger(__name__)`, used throughout with event-name-as-first-positional-arg + kwargs style, e.g. `clean.py:205` `log.info("clean.start", parsed_artifact_id=parsed_artifact_id)`.
**Apply to:** All new/modified pipeline-stage code (`clean.py`'s conservation-invariant check, `process.py`'s new `clean()` call — reuses `process.py`'s existing `log = logging.getLogger(__name__)`, note `process.py` uses stdlib `logging` not `structlog`, keep that module's existing convention rather than switching it).

### Registry session discipline (WR-01)
**Source:** `clean.py:299-345` and `process.py:60-87` — both wrap DB reads/writes in `with get_session() as session:` blocks and materialize ORM rows to plain tuples/dicts *before* leaving the session (`process.py:87` comment: "Materialize to tuples inside the session — DetachedInstanceError guard (PAYLOAD-01)").
**Apply to:** The new `quality-audit` command's `Source` query — copy the "materialize inside the session" idiom exactly, since the command will iterate sources outside the query block while calling `parse()`/`clean()` per document (each of which opens its own session internally).

### Idempotent dedup as the audit's safety net (D-07)
**Source:** `clean.py:304-320` (exact-dup short-circuit via `get_artifact_by_hash`) and the equivalent pattern already inside `parse()`/`chunk()`.
**Apply to:** `quality-audit`'s repeated `parse()`/`clean()` calls across a re-run — no new caching layer needed; this dedup-by-hash behavior is what makes D-07's "re-run the real pipeline for measurement" safe and cheap. The audit must NOT call `embed()`/`index()` (only `parse → clean`, since `clean()` alone computes `sections_considered/kept/rejected`).

### Zero-bare-`assert` convention
**Source:** verified via grep across `pipeline/*.py` — zero bare `assert` statements exist; preconditions raise typed exceptions (e.g. `ValueError` at `clean.py:211-218`) preceded by a `structlog`/`logging` call.
**Apply to:** The new QUAL-05 conservation-invariant check inside `clean()` — must be a `log.error(...)` followed by `raise RuntimeError(...)`, never a bare `assert`.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `src/knowledge_lake/pipeline/quality_audit.py` (optional new module, if extracted per D-05/D-03 precedent) | service | batch | Genuinely new aggregation logic (loop sources → loop raw docs → accumulate kept/rejected/reasons → build per-source rows). Closest structural precedent is `process.py` itself ("one function, many callers," D-03) but there is no existing "audit/measurement" module to copy from — this is new code, not a retrofit. |
| Section-level per-loop boilerplate stripping inside `clean()` (the `for section in parsed_doc.sections: ...` block) | transform (in-function) | transform | No existing per-section iteration exists in `clean.py` today (it currently only cleans the flat `parsed_text` blob); RESEARCH.md's Code Examples section (lines 288-340) is the closest thing to a template, provided directly by the researcher rather than found via codebase search. |
| `tests/unit/test_process_crawled_clean.py` (new test file) | test | integration-ish unit | No `test_process*.py` file exists today (confirmed by RESEARCH.md's search); nearest sibling is `tests/unit/test_pipeline_extractions.py`, which only asserts `process_crawled`'s signature, not runtime behavior — use it for import/fixture conventions only, not as a behavioral template. |

## Metadata

**Analog search scope:** `src/knowledge_lake/pipeline/` (clean.py, chunk.py, process.py, parse.py), `src/knowledge_lake/dagster_defs/assets.py`, `src/knowledge_lake/cli/app.py`, `src/knowledge_lake/registry/repo.py`
**Files scanned:** clean.py (full, 361 lines), process.py (full, 123 lines), chunk.py (lines 290-345), assets.py (lines 260-340), cli/app.py (command index + lines 937-1000), registry/repo.py (lines 906-978)
**Pattern extraction date:** 2026-07-16
