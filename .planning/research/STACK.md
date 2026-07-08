# Stack Research — v2.0 Agent-Ready Lake (additions only)

**Domain:** AI-ready knowledge-lake framework (Python data pipeline)
**Researched:** 2026-07-08
**Confidence:** HIGH (versions cross-checked against installed `.venv` + PyPI JSON API on 2026-07-08; Qdrant/Crawl4AI APIs confirmed by importing the pinned versions already in the repo)

> Scope: this milestone ADDS features to a shipped v1.0. The full validated stack (Python 3.12/uv/Pydantic 2/FastAPI/Typer/SQLAlchemy 2/Dagster 1.13/Crawl4AI 0.9/Docling/Qdrant 1.18/MinIO+boto3/LiteLLM/DataTrove/sentence-transformers/structlog/tenacity) lives in `.planning/milestones/v1.0-research/STACK.md` and is NOT re-litigated here. This file only covers what the 5 new capability areas require. **Net new runtime dependencies: 2 (`mcp`, `fastembed`). Everything else reuses packages already pinned in `pyproject.toml`.**

---

## Recommended Additions

### New Core Dependencies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `mcp` (official Model Context Protocol Python SDK) | `>=1.28,<2.0` (latest 1.28.1, 2026-06-26) | MCP server exposing lake ops over stdio + SSE/streamable-HTTP | Anthropic's reference SDK; **bundles FastMCP** (`mcp.server.fastmcp.FastMCP`) so one dep gives decorator-based tools AND all three transports (`stdio`, `sse`, `streamable-http`). No extra framework needed — the HTTP transports expose a Starlette/ASGI app that mounts on the existing FastAPI/uvicorn server. |
| `fastembed` | `>=0.8,<0.9` (latest 0.8.0, 2026-03-23) | Client-side sparse (BM25) vector generation for hybrid search | Qdrant's own companion library. `SparseTextEmbedding("Qdrant/bm25")` produces term-frequency sparse vectors; pair with a collection-level `Modifier.IDF` so Qdrant computes corpus-global IDF server-side. Pure-lexical (stemmer/tokenizer) — **not** an LLM call, so it does not touch the LiteLLM-only constraint and keeps the BM25 path deterministic (fits the "deterministic first" rule). |

### Reused — No New Dependency

| Feature area | Package already in `pyproject.toml` | How it satisfies the requirement |
|--------------|-------------------------------------|----------------------------------|
| Hybrid BM25 + dense + RRF | `qdrant-client==1.18.0` | `models.{FusionQuery, Fusion, Prefetch, SparseVector, SparseVectorParams, NamedSparseVector, Modifier}` all present (verified by import). The 1.18 Query API (`query_points`) already drives dense search in `qdrant_store.py`; hybrid is the same call with `prefetch=[...]` + `query=FusionQuery(fusion=Fusion.RRF)`. No client or server upgrade. |
| Adaptive rate limiting (429/403 backoff, per-host cooldown) | `crawl4ai==0.9.0` + `tenacity==9.1.4` | Crawl4AI exports `RateLimiter(base_delay, max_delay, max_retries, rate_limit_codes)` (exponential backoff on configurable status codes) and `MemoryAdaptiveDispatcher`/`SemaphoreDispatcher` — verified by import. `crawl/ratelimit.py::PerHostLimiter` + three-tier `resolve_delay()` already do per-host cooldown; Crawl4AI's `RateLimiter` adds the reactive 429/403 backoff. `tenacity` (already pinned) covers the non-Crawl4AI single-URL `httpx` path. |
| Dagster re-crawl sensor + content-hash change detection | `dagster==1.13.11` | `@dg.sensor`, `RunRequest`, `SkipReason`, `SensorResult`, and `context.cursor` are core Dagster 1.13 — no add-on. Per-source `crawl_schedule` and last-seen content hash live in the sensor cursor / run_key. |
| Static OpenAPI export (`klake openapi` → `docs/openapi.json`) | `fastapi==0.139.0` + `orjson==3.11.9` | `app.openapi()` returns the full spec dict; serialize with `orjson` (already a dep) and write `docs/openapi.json`. A Typer command wraps it. |
| OpenAI-format tool definitions from Pydantic schemas | `pydantic==2.13.4` (+ `litellm==1.90.2`) | `Model.model_json_schema()` → wrap as `{"type":"function","function":{name, description, parameters}}`. Pydantic's `GenerateJsonSchema` with a flat `ref_template` (or manual `$defs` inlining) yields OpenAI-compatible parameter schemas. LiteLLM (already present) is the runtime consumer if an agent calls back through the gateway — no `openai` SDK needed. |

---

## Installation

```bash
# Two new runtime deps — add to pyproject.toml [project].dependencies
uv add "mcp>=1.28,<2.0"
uv add "fastembed>=0.8,<0.9"
uv lock
```

Pin block to append to `pyproject.toml`:

```toml
    "mcp>=1.28,<2.0",        # MCP server (bundles FastMCP; stdio + SSE + streamable-http)
    "fastembed>=0.8,<0.9",   # client-side BM25 sparse vectors for hybrid search
```

> `fastembed` pulls `onnxruntime` transitively. For the `Qdrant/bm25` model this is dormant (BM25 uses a pure stemmer/tokenizer, not ONNX), and it is small relative to the `torch` that `sentence-transformers` already installs. No GPU required — matches the DigitalOcean CPU droplet.

---

## Per-Feature Integration Detail

### 1. MCP server (stdio + SSE/HTTP) — `mcp>=1.28,<2.0`

**SDK choice:** official `mcp` SDK, using its bundled `mcp.server.fastmcp.FastMCP`. **Do NOT add the standalone `fastmcp` package** (v3.4.3) — it duplicates what ships inside `mcp`, drags in its own auth/deploy/OpenAPI machinery, and leaves two MCP stacks to keep in sync. The bundled FastMCP covers decorator tools and every transport this milestone needs.

**Transport serving:**
- `stdio` (`klake mcp`): `FastMCP(...).run(transport="stdio")`. JSON-RPC over stdout.
- SSE / streamable-HTTP (`klake mcp --sse --port 3001`): serve `FastMCP.streamable_http_app()` (current spec, recommended) or `FastMCP.sse_app()` (legacy SSE, still supported) via uvicorn. Two shapes:
  - **Standalone (recommended for `klake mcp --sse`):** run the MCP ASGI app on its own uvicorn at port 3001 — clean process isolation from the main API.
  - **Mounted:** `fastapi_app.mount("/mcp", mcp.streamable_http_app())` on the existing 26-endpoint FastAPI app for single-port. Caveat: streamable-HTTP needs its session-manager lifespan wired into FastAPI's `lifespan` — the standalone form avoids that wiring, so prefer it unless one port is a hard requirement.
- **SSE is deprecated in the MCP spec in favour of streamable-HTTP.** Implement streamable-HTTP as the real transport; keep the `--sse` flag name to match the requirement but back it with `streamable_http_app()`. Document this.

**Tool surface:** wrap the *same* pipeline functions the CLI/API already call (`search`, `ingest_url`, `crawl`, `crawl_all`, `process_crawled`, `add_source`, `list_sources`, `lineage`, `export`, `init_domain`, `stats`) — do not re-implement behavior (mirrors the existing D-02 "CLI and API call one function" rule).

**structlog / stdout pollution (CRITICAL):** `knowledge_lake/__init__.py::_configure_logging()` uses `structlog.PrintLoggerFactory()`, which writes to **stdout**, and selects the renderer from `sys.stdout.isatty()`. Under MCP stdio, stdout is the JSON-RPC channel and is a pipe (not a TTY) → structlog would emit log lines straight into the protocol stream and corrupt every message. **Mitigation (code, not a dependency):** in the `klake mcp` stdio entrypoint, re-point structlog to **stderr** before the server starts — swap `PrintLoggerFactory()` for `PrintLoggerFactory(file=sys.stderr)` (or `WriteLoggerFactory(file=sys.stderr)`) via a small "configure-for-stdio" hook, and/or raise the level to WARNING. The SSE/HTTP transports don't have this hazard (stdout is free), so only the stdio path needs the redirect.

### 2. Hybrid BM25 + dense search — `fastembed` + existing `qdrant-client`

- **Sparse approach:** `fastembed.SparseTextEmbedding("Qdrant/bm25")` client-side for term frequencies, **plus** `sparse_vectors_config={"bm25": SparseVectorParams(modifier=Modifier.IDF)}` on the collection so Qdrant applies corpus-global IDF at query time. This is Qdrant's current recommended BM25 recipe; client-only BM25 lacks corpus IDF. **miniCOIL** (`Qdrant/minicoil`) and **SPLADE** (`prithivida/Splade_PP_en_v1`) are documented upgrade paths (learned/neural sparse, higher quality) but pull ONNX models and more CPU — defer; BM25 is the right default for a CPU droplet and the deterministic-first rule.
- **Collection shape:** named vectors — keep the existing dense vector, add a named sparse vector `bm25`. This is an additive collection-config change; fold it into the existing alias-based zero-downtime reindex in `qdrant_store.py` so there is no downtime.
- **Query (RRF):** `client.query_points(collection, prefetch=[Prefetch(query=dense_vec, using="<dense>", limit=k), Prefetch(query=SparseVector(...), using="bm25", limit=k)], query=FusionQuery(fusion=Fusion.RRF), limit=top_k)`. All symbols verified present in `qdrant_client.models` at 1.18.
- **Search-mode switch (RETR-02):** `hybrid | dense | sparse` selects the prefetch composition — extend the existing `pipeline/search.py` signature; the dense-only branch is exactly today's code (backward compatible).
- **Server:** the Qdrant image already in Compose supports sparse + IDF; no server version bump.

### 3. Dagster re-crawl sensor — existing `dagster`

- **Sensor over schedule:** `crawl_schedule` is **per-source** and we want to **skip unchanged** content — that is state/event-driven, i.e. a `@dg.sensor`, not a fixed `@dg.schedule`. Use `RunRequest(run_key=f"{source_id}:{content_hash}")` so unchanged content (same hash) dedupes to a no-op; emit `SkipReason` when nothing is due.
- **Content-hash detection (SCHED-02):** reuse the existing SHA256 content hashing; store last-seen hash + last-run timestamp in `context.cursor` (JSON) or query the document registry. `minimum_interval_seconds` gates tick frequency; per-source `crawl_schedule` decides due-ness inside the tick.
- No new package; wire into the existing Dagster `Definitions`.

### 4. OpenAPI export + OpenAI tool defs — existing `fastapi`/`pydantic`/`orjson`

- **`klake openapi`:** Typer command → `from knowledge_lake.api.app import app; app.openapi()` → `orjson.dumps(..., option=orjson.OPT_INDENT_2)` → write `docs/openapi.json` (committed, static). Add a test asserting the committed file matches `app.openapi()` to prevent drift.
- **OpenAI tool defs:** build from the request Pydantic models with `model_json_schema()`; wrap in `{"type":"function","function":{...}}`. Two Pydantic-v2 gotchas: (a) `$defs`/`$ref` — OpenAI accepts JSON-Schema refs but some consumers want them inlined, so supply a flat `ref_template` or an inliner; (b) strip Pydantic-only keys if targeting OpenAI "strict" mode. No `openai` SDK dependency — pure Pydantic.

### 5. Adaptive rate limiting — existing `crawl4ai` + `tenacity`

- **Native, no new dep.** `crawl4ai.RateLimiter(base_delay=(min,max), max_delay=60.0, max_retries=3, rate_limit_codes=[429, 503])` gives exponential backoff; **add 403 to `rate_limit_codes`** to satisfy CRAWL-03. Drive it through `MemoryAdaptiveDispatcher` (memory-aware concurrency + the rate limiter) in the Crawl4AI adapter for `crawl-all` batch runs.
- **Per-host cooldown** already exists in `crawl/ratelimit.py::PerHostLimiter` (keyed by registrable domain via tldextract) — keep it as the outer politeness layer; Crawl4AI's `RateLimiter` is the inner reactive-backoff layer. `tenacity` (already pinned) stays for the non-Crawl4AI single-URL `httpx` ingest path.

---

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| standalone `fastmcp` (3.x) | Duplicates the FastMCP bundled inside the official `mcp` SDK; two MCP stacks, extra auth/deploy deps not needed | `mcp.server.fastmcp.FastMCP` from the `mcp` dep |
| `openai` / `anthropic` SDKs (for tool schemas) | OpenAI tool defs are plain JSON from Pydantic; a provider SDK violates the LiteLLM-only gateway rule | `pydantic.model_json_schema()` + envelope; LiteLLM for any model call |
| `rank-bm25`, Elasticsearch/OpenSearch, `pyserini` | A second retrieval engine to operate; Qdrant sparse vectors already do BM25 with RRF fusion in-store | Qdrant sparse vector `bm25` + `Modifier.IDF` |
| `APScheduler`, Celery, cron, `schedule` | New scheduler alongside Dagster; fragments orchestration and breaks the "Dagster from day 1" constraint | Dagster `@sensor` + `RunRequest`/cursor |
| a new backoff/retry lib (`backoff`, custom loop) for crawling | Crawl4AI `RateLimiter` + existing `tenacity` already cover exponential backoff and retries | Crawl4AI `RateLimiter` (inner) + `PerHostLimiter` (outer) + `tenacity` (HTTP) |
| re-adding `tenacity` / `httpx` / `orjson` | Already pinned in `pyproject.toml` | reuse existing pins |
| a second web framework / uvicorn stack for SSE | MCP HTTP transport is an ASGI app; run it on uvicorn (already a dep) or mount on FastAPI | `FastMCP.streamable_http_app()` on uvicorn |
| `qdrant-client[fastembed]` extra as the install vector | Works, but implicit; prefer an explicit top-level `fastembed` pin so the sparse dep is visible and version-controlled | explicit `fastembed>=0.8,<0.9` |
| upgrading `qdrant-client` for hybrid | 1.18 already has `FusionQuery`/`Prefetch`/`SparseVectorParams`/`Modifier` (verified) | keep `qdrant-client==1.18.0` |

---

## Version Compatibility

| Package | Constraint | Notes |
|---------|------------|-------|
| `mcp` 1.28.x | Python ≥3.10 | Compatible with 3.12; bundles FastMCP + stdio/sse/streamable-http. Built on Starlette/anyio — same async stack as FastAPI, mounts cleanly. |
| `fastembed` 0.8.x | Python ≥3.10 | Pulls `onnxruntime` (CPU); coexists with `torch` from `sentence-transformers`. `Qdrant/bm25` needs no GPU. |
| `qdrant-client` 1.18.0 | pinned | Hybrid/RRF API present; matches the running Qdrant server image. Sparse + `Modifier.IDF` supported server-side. |
| `crawl4ai` 0.9.0 | pinned | `RateLimiter`, `MemoryAdaptiveDispatcher`, `SemaphoreDispatcher` verified importable. |
| `typer` `<0.25.0` (pinned by docling-core) | UNCHANGED | New `klake mcp` / `klake openapi` subcommands add to the existing Typer app; neither MCP nor fastembed pressures the pin. |
| `structlog` 26.x | UNCHANGED | Requires a code-level stderr redirect for the stdio MCP path (Feature 1); not a version issue. |

---

## Sources

- Installed `.venv` introspection (2026-07-08) — `crawl4ai` exports (`RateLimiter` signature `(base_delay, max_delay, max_retries, rate_limit_codes)`, `MemoryAdaptiveDispatcher`, `SemaphoreDispatcher`); `qdrant_client.models` presence of `FusionQuery/Fusion/Prefetch/SparseVector/SparseVectorParams/NamedSparseVector/Modifier`. Confidence HIGH (executed against the exact pinned versions).
- PyPI JSON API (2026-07-08) — `mcp` 1.28.1 (2026-06-26, requires-python ≥3.10), `fastmcp` 3.4.3 (2026-07-05), `fastembed` 0.8.0 (2026-03-23). Confidence HIGH.
- Repo `pyproject.toml` — current pins (`qdrant-client==1.18.0`, `crawl4ai==0.9.0`, `dagster==1.13.11`, `fastapi==0.139.0`, `tenacity==9.1.4`, `orjson==3.11.9`, `typer<0.25.0`). Confidence HIGH.
- `src/knowledge_lake/__init__.py` — structlog `PrintLoggerFactory` → stdout + `sys.stdout.isatty()` renderer switch (the stdio pollution hazard). Confidence HIGH (read directly).
- `src/knowledge_lake/plugins/builtin/qdrant_store.py`, `crawl/ratelimit.py`, `pipeline/search.py` — integration seams for hybrid search, rate limiting, and search-mode switching. Confidence HIGH (read directly).
- MCP transport guidance (streamable-HTTP current, SSE deprecated; ASGI mount) — MCP SDK design; Confidence MEDIUM (spec direction — confirm the exact `streamable_http_app()`/lifespan API against the installed 1.28.x during phase planning).

---
*Stack research for: Knowledge Lake Framework v2.0 (additions to shipped v1.0)*
*Researched: 2026-07-08*
