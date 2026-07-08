---
phase: 04-enrichment-embedding-search
reviewed: 2026-07-06T00:00:00Z
depth: standard
files_reviewed: 27
files_reviewed_list:
  - src/knowledge_lake/api/app.py
  - src/knowledge_lake/api/schemas.py
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/dagster_defs/assets.py
  - src/knowledge_lake/dagster_defs/definitions.py
  - src/knowledge_lake/ids.py
  - src/knowledge_lake/llm/__init__.py
  - src/knowledge_lake/llm/pricing.py
  - src/knowledge_lake/pipeline/deterministic.py
  - src/knowledge_lake/pipeline/enrich.py
  - src/knowledge_lake/pipeline/index.py
  - src/knowledge_lake/pipeline/search.py
  - src/knowledge_lake/plugins/builtin/qdrant_store.py
  - src/knowledge_lake/plugins/protocols.py
  - src/knowledge_lake/registry/alembic/versions/0007_enrichment_index_tables.py
  - src/knowledge_lake/registry/models.py
  - src/knowledge_lake/registry/repo.py
  - src/knowledge_lake/quality/scorer.py
  - src/knowledge_lake/plugins/builtin/st_embedder.py
  - src/knowledge_lake/plugins/resolver.py
  - docker-compose.yml
  - infra/litellm/config.yaml
  - infra/postgres/init.sql
  - tests/unit/test_deterministic.py
  - tests/unit/test_enrich.py
  - tests/unit/test_index_alias.py
  - tests/unit/test_index_payload.py
  - tests/unit/test_plugin_resolver.py
  - tests/unit/test_registry.py
  - tests/unit/test_search_filters.py
  - tests/unit/test_settings.py
  - tests/unit/test_builtin_plugins.py
  - tests/integration/test_migrations.py
  - tests/integration/test_qdrant_alias_reindex.py
findings:
  critical: 1
  warning: 5
  info: 3
  total: 9
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-07-06
**Depth:** standard
**Files Reviewed:** 35 (see `files_reviewed_list`)
**Status:** issues_found

## Summary

Phase 4 delivers cached/budget-capped LLM enrichment (04-02), an alias-based
Qdrant index/search layer (04-03), and the registry/settings foundation
(04-01), plus six infra/plugin files patched during a live Bedrock checkpoint
run. The overall design is careful — deterministic-first extraction, explicit
prompt-injection mitigation with a validated Pydantic result schema, zero-
downtime alias reindexing with atomic swap, and ORM-only queries throughout
(no SQL injection surface found).

However, one concrete correctness bug was found: **the deterministic title
extracted during enrichment is silently dropped to an empty string for every
invocation through the public CLI (`klake enrich`) and API (`POST /enrich`)
paths** — the only paths that populate the title are Dagster asset runs,
because those are the only call sites that pass `parsed_doc` through to
`enrich_document()`. This directly defeats the guarantee the code's own
comments describe ("without this explicit merge the persisted artifact would
have no title at all, silently failing ENRICH-03/D-01") for the two most
commonly used entry points into the pipeline.

Beyond that, there are several budget/cost-accounting robustness gaps around
concurrent enrichment (TOCTOU on the spend cap and the enrichment cache), a
mismatch between the Bedrock model IDs registered for cost tracking and the
model IDs actually configured in `infra/litellm/config.yaml`, and a couple of
minor code-quality items (an `assert` used for production input validation,
dead/unused Pydantic schemas).

## Critical Issues

### CR-01: Enrichment title is always empty when invoked via CLI/API (not Dagster)

**File:** `src/knowledge_lake/pipeline/enrich.py:184-243, 295-299`
**File:** `src/knowledge_lake/api/app.py:678-706` (specifically the call at line 695)
**File:** `src/knowledge_lake/cli/app.py:288-313` (specifically the call at line 305)

**Issue:** `enrich_document()` derives the persisted `title` field exclusively
from the (optional) `parsed_doc` argument:

```python
parsed_metadata = parsed_doc.metadata if parsed_doc is not None else {}
sections = parsed_doc.sections if parsed_doc is not None else []
deterministic = extract_deterministic_fields(parsed_metadata, sections, cleaned_text)
...
enriched_metadata = {**result.model_dump(), "title": deterministic["title"]}
```

`extract_title()` (pipeline/deterministic.py) returns `""` whenever
`parsed_metadata` has no `"title"` key AND `sections` is empty — which is
exactly what happens whenever `parsed_doc` is `None`.

The only caller that ever supplies `parsed_doc` is the Dagster
`enrich_document` asset (`dagster_defs/assets.py:367-411`, which forwards
`clean_document["parsed_doc"]`). Both of the other documented, user-facing
entry points call `enrich_document()` with no `parsed_doc` at all:

- `api/app.py:695` — `result = enrich_document(body.cleaned_artifact_id, body.source_id)`
- `cli/app.py:305` — `result = enrich_document(cleaned_artifact_id, source_id)`

Neither of these reconstructs a `ParsedDoc` from storage the way
`chunk_endpoint`/`cmd_chunk` explicitly do (fetching the parsed artifact's
`storage_uri` and rebuilding a minimal `ParsedDoc`). As a result, every
enrichment produced via `POST /enrich` or `klake enrich` — the two commands
whose own docstrings describe them as producing
"summary/document_type/organization/jurisdiction/keywords/entities/quality_score"
metadata with no caveat about title — silently persists `title: ""`, even
though the upstream `parsed_document` artifact almost always has a real title
in its metadata from the parse stage. This is precisely the failure mode the
inline comment above the merge warns about ("without this explicit merge the
persisted artifact would have no title at all, silently failing
ENRICH-03/D-01"), just reached through a different, very reachable, code path.

`tests/unit/test_enrich.py` never exercises the `parsed_doc=None` path (every
test passes the `parsed_doc` fixture explicitly), so this regression has no
test coverage today.

**Fix:** Either (a) have `enrich_document()` fetch/reconstruct the parsed
document's metadata/sections from the registry+storage when `parsed_doc` is
`None` (mirroring the pattern already used in `chunk_endpoint`/`cmd_chunk`),
or (b) have `api/app.py`/`cli/app.py` do that reconstruction before calling
`enrich_document()`, e.g.:

```python
# in enrich_endpoint / cmd_enrich, before calling enrich_document():
parsed = registry_repo.get_artifact(session, <parsed_artifact_id for this cleaned artifact>)
parsed_doc = ParsedDoc(text=..., sections=[], metadata=parsed.metadata_ or {})
result = enrich_document(cleaned_artifact_id, source_id, parsed_doc=parsed_doc)
```
Add a regression test that calls `enrich_document()` with `parsed_doc=None`
and asserts the persisted title still reflects the parsed document's title
metadata (or explicitly documents/accepts the degraded behavior if that's
truly intended).

## Warnings

### WR-01: Registered Bedrock pricing IDs don't match the model IDs LiteLLM actually invokes

**File:** `src/knowledge_lake/config/settings.py:154-164`
**File:** `infra/litellm/config.yaml:20-34`

**Issue:** `EnrichSettings.cheap_model_bedrock_id` / `strong_model_bedrock_id`
are registered with `litellm.register_model()` (via
`llm/pricing.py::bootstrap_llm_pricing`) so `litellm.completion_cost()` can
resolve a price for the model actually used behind the `cheap_model`/
`strong_model` task aliases. The docstring on `cheap_model_bedrock_id`
explicitly claims it "mirrors this default against infra/litellm/config.yaml's
current cheap_model mapping" — but it does not:

```
settings.py:   cheap_model_bedrock_id  = "bedrock/anthropic.claude-haiku-4-5-20260925-v1:0"
litellm.yaml:  cheap_model model       = "bedrock/us.anthropic.claude-haiku-4-5-20251001-v1:0"

settings.py:   strong_model_bedrock_id = "bedrock/anthropic.claude-sonnet-4-5-20260925-v1:0"
litellm.yaml:  strong_model model      = "bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
```

Both the cross-region inference-profile prefix (`us.`) and the model dates
differ. Since `completion_cost()` looks up pricing by the literal model
string LiteLLM actually invoked (`bedrock/us.anthropic.claude-haiku-4-5-...`),
and that string was never registered, the lookup will not match the
registered entry. `compute_call_cost()` catches the resulting exception and
silently falls back to the coarse `fallback_cost_per_1k_input/output`
estimate for every single enrichment call — defeating the entire purpose of
`bootstrap_llm_pricing()` (RESEARCH.md Pitfall 1, which this code explicitly
set out to solve) and degrading the accuracy of the ENRICH-05 budget cap.

**Fix:** Update `cheap_model_bedrock_id`/`strong_model_bedrock_id` in
`settings.py` to exactly match the `model:` values in
`infra/litellm/config.yaml` (including the `us.` inference-profile prefix),
or better, add a test that fails when the two drift apart (e.g. parse
`infra/litellm/config.yaml` in a test and assert the configured IDs are
registered).

### WR-02: TOCTOU races on the budget cap and enrichment cache under concurrent enrichment

**File:** `src/knowledge_lake/pipeline/enrich.py:246-324`
**File:** `src/knowledge_lake/registry/repo.py:679-701`

**Issue:** `enrich_document()`'s budget/cache logic is split across three
separate sessions with the (uncached, un-locked) LLM call in between:

1. Session A: cache-check (miss) + `current_spend >= budget_usd` check (pass).
2. *(no session)* LLM call.
3. Session B: cache re-check (miss) + `record_llm_spend()` (get-or-create,
   no row locking) + `create_enriched_artifact()` insert.

Under any concurrent invocation of `enrich_document()` for different (or the
same) cleaned artifacts — e.g. Dagster fanning out several document pipelines
in parallel, or two API/CLI calls racing — two calls can both pass the budget
check in step 1 before either records spend in step 3, allowing accumulated
spend to exceed `budget_usd` by more than one call's cost. Separately, two
concurrent calls for the *same* cleaned artifact can both miss the cache in
step 1 and step 3, then both attempt to insert an `Artifact` row with the same
`content_hash`/`artifact_type` — the `UNIQUE(content_hash, artifact_type)`
constraint (`registry/models.py:126`) will reject the second insert with an
`IntegrityError` that `enrich_document()` does not catch, so it propagates
past the `except ValueError` handler in `api/app.py:696` as an unhandled 500.

Migration `0007`'s comment ("enrichment stays serial regardless for Phase 4
MVP") documents this as an assumption, but nothing in the code actually
enforces serial execution — it is one call away from being broken by
concurrency introduced in a later phase or by Dagster's default asset/run
concurrency.

**Fix:** Either enforce single-flight enrichment (e.g. a DB-level advisory
lock keyed on `content_hash`, or `SELECT ... FOR UPDATE` on the `llm_spend`
row before the budget check), or at minimum catch `IntegrityError` around the
final insert in step 3 and treat it as a cache hit (re-select and return the
row the concurrent writer just created) instead of letting it propagate.

### WR-03: Retry-induced LLM cost is undercounted against the budget

**File:** `src/knowledge_lake/pipeline/enrich.py:138-178, 280`

**Issue:** `_call_llm_for_enrichment` is wrapped in
`@retry(stop=stop_after_attempt(3), retry=retry_if_exception_type((RuntimeError, ValidationError)))`.
A `ValidationError` retry means the LLM *did* return a response (a billable
Bedrock call) but with malformed/non-conforming JSON. Each retried attempt
calls `litellm.completion()` again, but `enrich_document()` only calls
`compute_call_cost(response, s)` once, against the final (successful)
response's `usage` — the cost of the earlier failed-but-billed attempt(s) is
never computed or added to `llm_spend`. Over time this silently undercounts
real spend against the `budget_usd` cap whenever the model produces
malformed JSON (which the code itself acknowledges happens in practice, e.g.
the markdown-fence-wrapping behavior noted in `_strip_json_fences`).

**Fix:** Accumulate cost across all attempts (e.g. capture partial responses
inside the retried function via an `outer` variable, or lower-level: catch
and sum cost per attempt) before returning from
`_call_llm_for_enrichment`, and pass the total into `record_llm_spend`.

### WR-04: `assert` used for production input validation in `index()`

**File:** `src/knowledge_lake/pipeline/index.py:70-72`

**Issue:**
```python
assert len(chunks) == len(vectors), (
    f"index: chunks ({len(chunks)}) and vectors ({len(vectors)}) length mismatch"
)
```
`assert` statements are compiled out entirely when Python runs with the `-O`
(or `-OO`) optimization flag, silently removing this guard in that
configuration. If it's ever relied on as protection against a caller bug
(mismatched chunk/vector lists from a buggy embedder), the code would then
fall through to `zip(chunks, vectors)`, which truncates silently to the
shorter list rather than raising — some chunks would simply never be
indexed, with no error surfaced anywhere.

**Fix:** Replace with an explicit runtime check:
```python
if len(chunks) != len(vectors):
    raise ValueError(
        f"index: chunks ({len(chunks)}) and vectors ({len(vectors)}) length mismatch"
    )
```

### WR-05: `parsed_document`/`clean_document`/`chunk_document`/`ingest_raw_document` Dagster assets omit the `litellm` resource

**File:** `src/knowledge_lake/dagster_defs/assets.py:186-240`

**Issue:** `parse()` (invoked by the `parsed_document` asset) can trigger
`quality/scorer.py::maybe_llm_spot_check()`, which is enabled by default
(`ParseSettings.llm_spot_check = True`) and needs a working
`settings.litellm_url`. Unlike the `enrich_document` asset — which explicitly
declares `litellm: LiteLLMResource` and threads
`litellm_url=litellm.litellm_url` into its ad hoc `Settings(...)` — the
`parsed_document`, `clean_document`, `chunk_document`, and
`ingest_raw_document` assets build their `Settings(...)` instances without
the `litellm` resource at all, relying on whatever `KLAKE_LITELLM_URL`
happens to be set in the process environment. This works in the default
docker-compose deployment (env var and resource agree), but any Dagster-UI
run-config override of the `litellm` resource for a specific run will be
silently ignored by the parse stage's optional spot-check, which is otherwise
one of the few places outside `enrich_document` that a raw LiteLLM call
happens in-band with the main pipeline.

**Fix:** For consistency (and to make the resource wiring actually
authoritative, matching the pattern already used by `enrich_document` and
`index_chunks`), add `litellm: LiteLLMResource` to `parsed_document`'s
signature and pass `litellm_url=litellm.litellm_url` into its `Settings(...)`.

## Info

### IN-01: Dead/unused Pydantic schemas drift from the real endpoints

**File:** `src/knowledge_lake/api/schemas.py:30-51` (`SearchParams`)
**File:** `src/knowledge_lake/api/schemas.py:120-128` (`LineageGraph`)

**Issue:** `SearchParams` is never imported/used anywhere — `search_endpoint`
in `api/app.py` re-declares the same query parameters inline instead of using
this model, so the two can silently drift (e.g. `SearchParams.q` allows
`min_length=0` but doesn't bound `top_k`'s validation the same way the actual
endpoint does — they happen to agree today only by accident of duplication).
Similarly, `LineageGraph` is defined but `GET /lineage/{artifact_id}` returns
`list[LineageNode]` directly, never wrapping it in a `LineageGraph`.

**Fix:** Either wire `search_endpoint` to use `SearchParams` as its
dependency/model (removing the duplicated `Query(...)` declarations) and
have `/lineage/{artifact_id}` return `LineageGraph`, or delete the two unused
classes to avoid the maintenance burden of two schemas that must be kept in
sync by hand.

### IN-02: `get_enriched_artifact_for_parsed` silently picks the *first* cleaned/enriched descendant

**File:** `src/knowledge_lake/registry/repo.py:704-734`

**Issue:** If a `parsed_document` is ever cleaned more than once (producing
multiple `cleaned_document` children, e.g. a re-run of `clean()` with updated
logic that changes the content hash), `get_enriched_artifact_for_parsed()`
only looks at the chronologically-first `cleaned_document` child and the
chronologically-first `enriched_document` child of *that* one. If enrichment
only ran against a later `cleaned_document`, this function returns `None`,
and `pipeline/index.py` will silently index that chunk with
`document_type=None`, `keywords=[]`, `quality_score=None` even though real
enrichment data exists elsewhere in the tree.

**Fix:** If multiple `cleaned_document` children are possible in practice,
prefer the most recent one (`order_by(Artifact.created_at.desc())`) or make
the one-cleaned-document-per-parsed invariant explicit/enforced elsewhere and
document it here.

### IN-03: `_strip_json_fences` doesn't handle all markdown-fence variants

**File:** `src/knowledge_lake/pipeline/enrich.py:112-124`
**File:** `src/knowledge_lake/quality/scorer.py:170-173`

**Issue:** Both call sites strip a leading ```` ```json ```` or ```` ``` ````
fence via `removeprefix`, which only matches an exact, case-sensitive prefix
with no leading whitespace. A response like ```` ``` json\n{...} ```` (space
before "json") or ```` ```JSON ```` (different case) — both plausible model
outputs — would not be stripped, and the subsequent
`model_validate_json`/`json.loads` call would then fail on the leftover
fence marker, needlessly consuming a retry attempt (in the enrich path) or
falling back to the heuristic score (in the scorer path).

**Fix:** Use a small regex (e.g. `re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)`)
instead of the two chained `removeprefix` calls, in both places.

---

_Reviewed: 2026-07-06_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
