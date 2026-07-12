# Phase 12: Agent Surfaces - Pattern Map

**Mapped:** 2026-07-11
**Files analyzed:** 21 (create + modify)
**Analogs found:** 18 / 21 (3 net-new files have no in-repo analog — MCP SDK boilerplate from RESEARCH.md)

Scope note: this is a pure surface layer. Every handler is a thin shim over an
existing `pipeline/*.py` function; the "core pattern" for most new files is
*copy the invocation body from the matching FastAPI endpoint or CLI command*,
because those are already the thin-caller reference implementations (D-03, D-06).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/knowledge_lake/agent/registry.py` | registry/config | transform (schema) | `api/schemas.py` model reuse + `pipeline/__init__.py` | role-match |
| `src/knowledge_lake/agent/server.py` | provider (MCP core) | request-response | `api/app.py` endpoint→service dispatch | role-match |
| `src/knowledge_lake/agent/stdio.py` | transport | streaming (stdio) | `__init__.py:20` `_configure_logging` (logger factory) | partial (no MCP analog) |
| `src/knowledge_lake/agent/http.py` | transport | request-response | `api/app.py:FastAPI(...)` ASGI app wiring | partial (no MCP analog) |
| `src/knowledge_lake/agent/openai_defs.py` | utility | transform (schema) | RESEARCH.md D-15 snippet | no in-repo analog |
| `pipeline` `process_crawled()` | service | batch | `cli/app.py:578` `cmd_process_crawled` (extract) | exact (same body) |
| `pipeline`/`repo` `list_sources()` | service | CRUD (read) | `api/app.py:1236` + `crawl.py:211` | exact (session-safe) |
| `pipeline` `stats()` | service | CRUD (read/aggregate) | `qdrant_store.py:349` count + ORM counts | role-match (net-new) |
| `pipeline`/`domains` `load_domain()`/`init_domain()` | service | batch | `api/app.py:1494` `_register_domain_sources` | exact (already extracted) |
| `cli/app.py` `klake mcp` verb | route (CLI) | request-response | `cli/app.py:672` `cmd_search`, `:578` handler | exact |
| `cli/app.py` `klake openapi` verb | route (CLI) | file-I/O | `cli/app.py` command + `app.openapi()` | role-match |
| `cli/app.py` refactor `cmd_process_crawled` | route (CLI) | batch | self (calls extracted fn) | exact |
| `api/schemas.py` extend `SearchParams` + new input models | model | transform | `api/schemas.py:30` `SearchParams` | exact |
| `plugins/builtin/qdrant_store.py` `count_points()` | utility | CRUD (read) | `qdrant_store.py:349` internal count | exact |
| `docs/openapi.json` | config artifact | file-I/O | `docs/*.md` (committed docs) | role-match |
| `skills/*.md` (×4) | doc | — | none (new artifact type) | no analog |
| `tests/unit/test_surface_parity.py` | test | — | `tests/unit/test_api_search_mode.py` | role-match |
| `tests/integration/test_stdio_lockdown.py` | test | streaming | `tests/integration/*` subprocess tests | partial |
| `tests/integration/test_mcp_http.py` | test | request-response | `tests/integration/test_api_new_endpoints.py:22` TestClient fixture | exact |
| `tests/unit/test_*` (registry/handlers/readonly/openapi/skills/extractions) | test | — | `tests/integration/test_api_new_endpoints.py` | role-match |
| `pyproject.toml` (`mcp==1.28.1`) | config | — | existing pins | exact |

## Pattern Assignments

### `pipeline` `process_crawled()` — EXTRACT from CLI (service, batch)

**Analog / extraction source:** `src/knowledge_lake/cli/app.py:578-669` `cmd_process_crawled`.

The full body already exists inline. Move lines 596-669 into a service function
returning a structured summary; refactor the CLI to call it and `typer.echo` the
summary. The `typer.echo` progress lines become summary-dict fields.

Core pattern to lift (`cli/app.py:606-669`):
```python
with get_session() as session:
    ParsedChild = aliased(Artifact)
    has_parsed_child = (
        select(ParsedChild.id)
        .where(and_(ParsedChild.parent_artifact_id == Artifact.id,
                    ParsedChild.artifact_type == "parsed_document"))
        .correlate(Artifact).exists())
    stmt = (select(Artifact).where(Artifact.artifact_type == "raw_document")
            .where(~has_parsed_child))
    if source_id: stmt = stmt.where(Artifact.source_id == source_id)
    stmt = stmt.order_by(Artifact.created_at.desc()).limit(limit)
    unprocessed = session.execute(stmt).scalars().all()
    raw_docs = [(a.id, a.source_id, a.storage_uri, a.mime_type) for a in unprocessed]
# ... parse→chunk→embed→index loop, count processed/failed/total_chunks
return {"processed": processed, "chunks_indexed": total_chunks, "failed": failed}
```
Note: rows are materialized to tuples *inside* the session (line 632) — keep that;
it is the same DetachedInstanceError guard used everywhere in this phase.

**Suggested signature:** `def process_crawled(*, source_id=None, limit=100, collection="klake_chunks") -> dict`

---

### `pipeline`/`repo` `list_sources()` — session-safe read (service, CRUD read)

**Analogs:** `api/app.py:1236-1273` `list_sources_endpoint` (query + Python-side
domain filter) and `pipeline/crawl.py:211-241` `list_sources_for_crawl_all`
(the namedtuple materialization pattern). RESEARCH.md:309-323 gives the exact
merged body.

Materialize dict rows inside the session (mirror `crawl.py:237-241`):
```python
with get_session() as session:
    if domain is not None:
        rows = [s for s in session.execute(
                    select(Source).order_by(Source.created_at.desc())).scalars()
                if (s.config or {}).get("domain") == domain][offset:offset+limit]
    else:
        rows = list(session.execute(select(Source).order_by(Source.created_at.desc())
                    .limit(limit).offset(offset)).scalars())
    return [{"source_id": s.id, "name": s.name, "url": s.url,
             "source_type": s.source_type, "license_type": s.license_type,
             "domain": (s.config or {}).get("domain"),
             "created_at": s.created_at.isoformat() if s.created_at else ""} for s in rows]
```
Then refactor `list_sources_endpoint` (api/app.py:1236) to call this and map
dicts → `SourceListItem` (schemas.py:651). Do NOT return ORM objects across the
session boundary (the whole reason `crawl.py:211` exists).

---

### `pipeline` `stats()` — net-new read aggregate (service, CRUD read)

**Analogs:** ORM counts (same `get_session()` + `select()` pattern as above);
Qdrant count from `plugins/builtin/qdrant_store.py:349` `self._client.count(col, exact=True).count`.

`stats()` must NOT reach into `_client` — first add a public wrapper:

**`plugins/builtin/qdrant_store.py` `count_points()`** (copy the internal call at :349):
```python
def count_points(self, collection: str) -> int:
    """Exact point count for a collection; 0 if the collection is absent."""
    try:
        return self._client.count(collection, exact=True).count
    except Exception:
        return 0
```
Then `stats()` calls `get_vectorstore(settings).count_points(collection)`
(resolver at `plugins/resolver.py:250`). Shape per RESEARCH.md:341-349:
`{"sources", "documents", "artifacts_by_type": {...}, "qdrant_points", "collection"}`.

---

### `pipeline`/`domains` `load_domain()` — EXTRACT (already half-done) (service, batch)

**Analog:** `api/app.py:1494` `_register_domain_sources(name) -> dict` ALREADY
returns `{loaded_count, skipped_count, upload_required_count}` and is called by
`load_domain_endpoint` (api/app.py:1574-1610). The CLI twin `cmd_init`
(cli/app.py:1034-1130+) inlines the same DomainLoader + `create_source` loop with
URL-dedup and cron validation.

Action: promote `_register_domain_sources` into `pipeline`/`domains` as the shared
`load_domain(name) -> dict`, then point BOTH `load_domain_endpoint` and `cmd_init`
at it (A4 — confirm cmd_init's extra cron-validation branch at :1105-1116 is
preserved in the shared fn). The `init_domain` tool shims this directly. Domain
name is guarded by `_DOMAIN_NAME_RE` (`^[a-zA-Z][a-zA-Z0-9_-]{0,63}$`) at
cli/app.py:1056 and schemas.py:710 — keep that guard.

---

### 7 direct shims — no extraction (service handlers, D-06)

Each MCP handler unpacks the validated input model and calls the fn; the FastAPI
endpoint body is the reference for *how each is invoked and what it returns*:

| Tool | pipeline fn | Invocation reference | Async? |
|------|-------------|---------------------|--------|
| `search` | `pipeline/search.py:35` `search()` | `cmd_search` cli/app.py:672 | sync |
| `ingest_url` | `pipeline/ingest.py:337` | `run_document` (cli/app.py:562) | sync |
| `add_source` | `pipeline/ingest.py:230` `register_source` | — | sync |
| `crawl` | `pipeline/crawl.py:244` `crawl_source` | **`await` directly** (RESEARCH.md:223-233) | async |
| `crawl_all` | `pipeline/crawl.py:911` `crawl_all_sources` | **`await` directly** | async |
| `export` | `pipeline/export.py:243/357/449` | `export_endpoint` api/app.py:1155-1217 (dispatch on kind) | sync |
| `lineage` | `lineage.resolve_ancestry` | `lineage_endpoint` api/app.py:1087-1136 | sync |

Copy the export dispatch (kind → `export_rag_corpus`/`export_pretrain_corpus`/
`export_finetune_dataset`) and its `TrainEvalContaminationError`/`ValueError`
handling verbatim from api/app.py:1191-1204.

**CRITICAL (RESEARCH.md D-12 correction):** inside the async `call_tool` handler
`await crawl_source(...)` — do NOT `asyncio.run(...)` (raises RuntimeError inside
the running loop). `asyncio.run` is only for sync callers (CLI/Dagster).

---

### `api/schemas.py` — extend + add input models (model, transform)

**Analog:** `api/schemas.py:30` `SearchParams`. Reuse existing models as tool
`input_model` (D-02): `SearchParams:30`, `ExportRequest:170`, `SourceCreate:204`,
`CrawlJobCreate:266`, `DomainLoadRequest:710`, `SourceListItem:651`.

**Pitfall 4 (RESEARCH.md:295-297):** `SearchParams` only has `q, top_k, collection,
mode` but `search()` (search.py:35-48) also accepts `domain, document_type,
min_quality_score, source_name, format, tags, source_id`. Extend `SearchParams`
with those fields (preferred — keeps GET /search + tool identical) following the
existing `Field(default=None, description=..., pattern=...)` style at schemas.py:52-60.

Add net-new input models for `stats`, `process_crawled`, `list_sources`,
`init_domain` where no request schema exists (D-02).

---

### `cli/app.py` — `klake mcp` / `klake openapi` verbs (route)

**Analog:** existing `@app.command` handlers — `cmd_search` (:672) for option
plumbing, `cmd_process_crawled` (:578) for the try/except + `typer.Exit(code=1)`
error style, `cmd_export` (:1010-1031) for result echoing.

Verb pattern (copy structure at cli/app.py:672-705):
```python
@app.command(name="mcp")
def cmd_mcp(
    sse: bool = typer.Option(False, "--sse", help="Serve over Streamable HTTP instead of stdio."),
    port: int = typer.Option(3001, "--port", help="HTTP port (localhost only)."),
) -> None:
    ...
```
`klake openapi` dumps `app.openapi()` deterministically (Pitfall 3):
`json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"` → `docs/openapi.json`.
`app` is the FastAPI object at api/app.py:145.

---

### `agent/stdio.py` — fd-level stdout lockdown (transport, streaming)

**Analog:** `src/knowledge_lake/__init__.py:20-47` `_configure_logging` — this is
the *corruption source*: `structlog.PrintLoggerFactory()` at line 42 has no
`file=` and defaults to stdout. The lockdown must reconfigure it to stderr.

No MCP analog in repo — use RESEARCH.md Pattern 2 (lines 164-187) verbatim:
`os.dup(1)` BEFORE `os.dup2(2, 1)`, pass preserved handle as
`stdio_server(stdout=preserved)`, reconfigure structlog with
`PrintLoggerFactory(file=sys.stderr)` mirroring the factory call at __init__.py:42.

---

### `agent/server.py` / `agent/http.py` / `agent/openai_defs.py`

No in-repo MCP analog — build from RESEARCH.md Patterns 1 (server, lines 124-162),
3 (http, lines 189-221), and the openai_defs snippet (lines 326-337). The
endpoint→service dispatch *shape* mirrors api/app.py endpoints (validate → call
pipeline fn → serialize). Read/write filtering per RESEARCH.md:235-242.

---

### Tests

**HTTP test analog:** `tests/integration/test_api_new_endpoints.py:22-28` — the
`TestClient(app)` module-scoped fixture pattern. Reuse for `test_mcp_http.py`
against the Starlette app. Tests use `@pytest.mark.integration` and graceful
import-guard (`_IMPORT_OK`) at lines 12-19.

**Parity test analog:** `tests/unit/test_api_search_mode.py` (unit-level schema
assertions). `test_surface_parity.py` needs the `normalize(schema)` helper from
RESEARCH.md Pitfall 2 (lines 285-289) — drop `title`, canonicalize `$ref`/`$defs`,
`json.dumps(sort_keys=True)`.

**stdio lockdown test:** RESEARCH.md D-08 — spawn `klake mcp` as a subprocess,
send a trivial JSON-RPC call, assert stdout is only well-formed JSON-RPC.
Subprocess-test analogs exist under `tests/integration/` (e.g. scrapy subprocess test).

## Shared Patterns

### Session-safe row materialization
**Source:** `pipeline/crawl.py:237-241` (namedtuple) / `api/app.py:1261-1273`.
**Apply to:** `list_sources`, `stats`, `process_crawled` (already at cli/app.py:632).
Materialize plain dicts/tuples inside `with get_session()` — never return ORM
instances across the boundary (DetachedInstanceError guard).

### Thin caller, no logic duplication
**Source:** every FastAPI endpoint (`export_endpoint` api/app.py:1176-1217,
`lineage_endpoint` :1111-1136) — imports the pipeline fn and calls it.
**Apply to:** all MCP handlers (D-03). REST and MCP are siblings over `pipeline/*`,
never layered (MCP-01 hard rule).

### Expected-error contract
**Source:** `export_endpoint` api/app.py:1199-1204 and `cmd_export` cli/app.py:1019-1024
(`TrainEvalContaminationError`/`ValueError`/`LookupError` → clean message).
**Apply to:** MCP `call_tool` — catch `ValueError`/`LookupError`/store fail-loud
error → `CallToolResult(isError=True)` (D-13); unexpected exceptions propagate.

### Domain-name path-traversal guard
**Source:** `_DOMAIN_NAME_RE = ^[a-zA-Z][a-zA-Z0-9_-]{0,63}$` at cli/app.py:1056,
schemas.py:710, api/app.py:1587.
**Apply to:** `init_domain` / `load_domain` input model + service fn.

### Nested pydantic-settings for `KLAKE_MCP__*`
**Source:** `config/settings.py:304` `SearchSettings(BaseModel)` + `:431`
`search: SearchSettings = Field(default_factory=...)`; env delimiter `__` at
settings.py:346-347.
**Apply to:** new `McpSettings(BaseModel)` (`token`, `readonly`, `host`, `port`)
mounted on `Settings` as `mcp: McpSettings`, driving `KLAKE_MCP__TOKEN` /
`KLAKE_MCP__READONLY`.

### Deterministic committed-artifact export
**Source:** RESEARCH.md Pitfall 3.
**Apply to:** `docs/openapi.json` and any committed OpenAI-defs JSON —
`json.dumps(obj, indent=2, sort_keys=True) + "\n"` so re-runs are no-op diffs.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `agent/server.py`, `agent/http.py`, `agent/openai_defs.py` | MCP core/transport | request-response | No MCP SDK usage exists in repo; use RESEARCH.md Patterns 1/3/openai snippet |
| `agent/stdio.py` | transport | streaming | fd-level lockdown is novel; only the structlog factory (`__init__.py:42`) is the reconfiguration target |
| `skills/*.md` (×4) | doc | — | No Claude Code skill files exist yet; frontmatter + tool-name workflow per D-16 |

## Metadata

**Analog search scope:** `src/knowledge_lake/{pipeline,api,cli,config,plugins}/`,
`tests/{unit,integration}/`, `docs/`, `skills/`.
**Files scanned:** ~20 read (targeted ranges); signatures grepped across `pipeline/*.py`.
**Pattern extraction date:** 2026-07-11
</content>
</invoke>
