# Phase 2: Ingestion - Pattern Map

**Mapped:** 2026-07-03
**Files analyzed:** 24 new/modified
**Analogs found:** 22 / 24

All new files copy patterns from existing Phase 1 code. The codebase is small and internally consistent — every seam this phase touches (plugin Protocol + entry-point resolver, registry ORM + repo functions, Alembic migration, S3 content-addressed writes, pydantic-settings sub-models, Typer CLI, FastAPI thin-wrapper endpoints) already has a working exemplar. Planner should extend these seams, not invent new ones.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `plugins/protocols.py` (ADD CrawlerPlugin, DiscoveryPlugin, CrawlJob, CrawlPageResult, DiscoveryResult) | protocol/model | request-response | `plugins/protocols.py` (EmbedderPlugin, ParserPlugin, dataclasses) | exact |
| `plugins/resolver.py` (ADD GROUP_CRAWLERS, GROUP_DISCOVERY, get_crawler, get_discovery) | resolver | request-response | `plugins/resolver.py` (GROUP_*, get_vectorstore) | exact |
| `plugins/builtin/crawl4ai_adapter.py` | plugin adapter | streaming/request-response | `plugins/builtin/st_embedder.py` (builtin plugin class) | role-match |
| `plugins/builtin/scrapy_adapter.py` | plugin adapter | event-driven (subprocess) | `plugins/builtin/st_embedder.py` | role-match |
| `plugins/builtin/scrapy_spider.py` | subprocess entry module | batch | none (subprocess child) | no analog |
| `plugins/builtin/playwright_adapter.py` | plugin adapter | streaming | `plugins/builtin/st_embedder.py` | role-match |
| `crawl/select.py` (auto-selection probe) | utility | request-response | `pipeline/ingest.py` `_validate_url_scheme` (httpx + urlparse) | partial |
| `crawl/robots.py` (Protego robots + Crawl-delay) | utility | request-response | none (new concern) | no analog |
| `crawl/ratelimit.py` (three-tier resolver) | utility | transform | `pipeline/ingest.py` helper functions | partial |
| `pipeline/ingest.py` (EXTEND dedup-aware, shared `validate_public_url`) | service | request-response | `pipeline/ingest.py` (self) | exact |
| `pipeline/crawl.py` (NEW orchestrator) | service | event-driven | `pipeline/ingest.py` (session + storage + repo pattern) | role-match |
| `pipeline/discover.py` (NEW) | service | request-response | `pipeline/ingest.py` + SearXNG httpx | role-match |
| `registry/models.py` (ADD CrawlState; EXTEND Job; Source.normalized_url) | model | CRUD | `registry/models.py` `Source`, `Artifact` | exact |
| `registry/repo.py` (ADD create_crawl_job, upsert_crawl_state, pending_states, get_source_by_normalized_url, create_bronze_artifact) | service | CRUD | `registry/repo.py` `create_source`, `create_raw_artifact`, `get_artifact_by_hash` | exact |
| `registry/alembic/versions/0002_source_normalized_url.py` (plan 02-01) | migration | DDL | `registry/alembic/versions/0001_core_schema.py` | exact |
| `registry/alembic/versions/0003_crawl_jobs_states.py` (plan 02-02) | migration | DDL | `registry/alembic/versions/0001_core_schema.py` | exact |
| `storage/s3.py` (ADD put_bronze) | service | file-I/O | `storage/s3.py` `put_raw` | exact |
| `config/settings.py` (ADD searxng_url, crawler, discovery, CrawlSettings) | config | — | `config/settings.py` `StorageSettings` + swap keys | exact |
| `cli/app.py` (ADD add-source, upload, crawl, discover) | route/CLI | request-response | `cli/app.py` `cmd_ingest_url`, `cmd_search` | exact |
| `api/app.py` (ADD /sources, /uploads, /crawl-jobs, /discover) | controller | request-response | `api/app.py` `search_endpoint` | exact |
| `api/schemas.py` (ADD request/response models) | model | — | `api/schemas.py` `SearchHit`, `LineageNode` | exact |
| `ids.py` (ADD `job`/`crawl_state` prefixes) | utility | — | `ids.py` `_PREFIX` map | exact |
| `pyproject.toml` (ADD crawler/discovery entry-points + deps) | config | — | `pyproject.toml` `[project.entry-points."knowledge_lake.embedders"]` | exact |
| tests (unit + integration, Wave 0) | test | — | existing `tests/` structure | role-match |

## Pattern Assignments

### `plugins/protocols.py` — ADD CrawlerPlugin, DiscoveryPlugin + dataclasses (protocol, request-response)

**Analog:** `plugins/protocols.py` (self — mirror EmbedderPlugin/ParserPlugin exactly)

**Imports pattern** (lines 23-26):
```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
```

**Dataclass pattern to copy** (lines 74-92, VectorPoint):
```python
@dataclass
class VectorPoint:
    id: str
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)
```
Apply to `CrawlJob`, `CrawlPageResult`, `DiscoveryResult` (shapes given in RESEARCH.md Pattern 1, lines 234-257).

**Protocol pattern to copy** (lines 118-148, EmbedderPlugin — note the `name: str` class attribute + docstring'd `...` methods):
```python
@runtime_checkable
class EmbedderPlugin(Protocol):
    name: str
    dim: int
    def embed(self, texts: list[str]) -> list[list[float]]:
        ...
```
`CrawlerPlugin` gets `name: str` + `start_crawl / poll_status / get_results`. `DiscoveryPlugin` gets `name: str` + `search(query, limit) -> list[DiscoveryResult]`. Keep the thorough docstrings — this file documents each field/method inline (module docstring lines 1-21 explains the swap-a-tool-with-one-settings-key contract).

---

### `plugins/resolver.py` — ADD GROUP_CRAWLERS, GROUP_DISCOVERY, get_crawler, get_discovery (resolver)

**Analog:** `plugins/resolver.py` (self)

**Group constant pattern** (lines 33-35):
```python
GROUP_PARSERS = "knowledge_lake.parsers"
GROUP_EMBEDDERS = "knowledge_lake.embedders"
GROUP_VECTORSTORES = "knowledge_lake.vectorstores"
```
Add `GROUP_CRAWLERS = "knowledge_lake.crawlers"`, `GROUP_DISCOVERY = "knowledge_lake.discovery"`.

**Getter with URL injection pattern** (lines 115-141, get_vectorstore — copy for discovery since SearXNG needs `settings.searxng_url` injected, exactly as qdrant_url is injected here):
```python
def get_vectorstore(settings: "Settings") -> Any:
    name = settings.vectorstore
    for ep in entry_points(group=GROUP_VECTORSTORES):
        if ep.name == name:
            factory = ep.load()
            if name == "qdrant":
                return factory(qdrant_url=settings.qdrant_url)
            return factory()
    raise LookupError(f"No plugin {name!r} registered in entry-point group {GROUP_VECTORSTORES!r}. ...")
```
`get_discovery` injects `searxng_url=settings.searxng_url`; `get_crawler` uses the no-arg `resolve(GROUP_CRAWLERS, settings.crawler)` form (lines 68-80, get_parser) unless config injection is needed. NOTE the CR-03 convention: URLs are injected from settings, never read via `os.environ` inside builtins.

---

### `pipeline/ingest.py` — EXTEND: dedup-aware + shared `validate_public_url` (service, request-response)

**Analog:** `pipeline/ingest.py` (self)

**SSRF guard to EXTRACT and rename** (lines 58-104, `_validate_url_scheme`) — RESEARCH §Security requires this become a shared, reusable `validate_public_url()` called by every crawler fetch and every discovered URL, not just `ingest_url`. Keep the full getaddrinfo + IPv4-mapped-IPv6 logic verbatim:
```python
def _validate_url_scheme(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(...)
    hostname = parsed.hostname or ""
    infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    for (_f, _t, _p, _c, sockaddr) in infos:
        addr = ipaddress.ip_address(sockaddr[0])
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        for net in _PRIVATE_NETS:
            if addr in net:
                raise ValueError(...)
```
`_PRIVATE_NETS` (lines 47-55) already covers RFC-1918 + 169.254 IMDS + loopback + IPv6 ULA — reuse as-is.

**Registry-first write + session pattern to copy for dedup** (lines 185-206):
```python
with get_session() as session:
    source = registry_repo.create_source(session, name=..., source_type="web", url=url, ...)
    session.flush()
    artifact = storage.put_raw(source.id, data, ext, session)
    session.flush()
    result = {"source_id": source.id, "artifact_id": artifact.id, ...}
```
For D-05/D-07: before fetch, call `repo.get_source_by_normalized_url(session, normalize_url(url))`; if found, return the same dict shape with existing IDs (silent success, log INFO). `put_raw` already gives hash-second no-op (see storage/s3.py analog).

**Retry pattern to reuse** (lines 107-112, tenacity decorator) — crawlers reuse this exact decorator config:
```python
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10),
       retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)), reraise=True)
```

**New helper `normalize_url` (D-06)** — RESEARCH Code Examples lines 388-400 gives the exact 6-line stdlib implementation. Do NOT use w3lib (sorts query params, violates D-06).

---

### `storage/s3.py` — ADD put_bronze (service, file-I/O)

**Analog:** `storage/s3.py` `put_raw` (lines 151-243)

**Copy `put_raw` structure exactly**, changing zone prefix `raw/` → `bronze/`, artifact_type `raw_document` → `bronze_document`, and adding a `parent_artifact_id` param (bronze→raw lineage, D-01):
```python
content_hash = hashlib.sha256(data).hexdigest()
existing = repo.get_artifact_by_hash(session, content_hash, "bronze_document")  # no-op path
if existing is not None:
    return existing
key = f"bronze/{source_id}/{content_hash}.{ext}"
if self.exists(key):
    raise RuntimeError(...)
self.put_object(key, data)
artifact = repo.create_bronze_artifact(session, source_id=source_id, content_hash=content_hash,
                                       storage_uri=self.object_uri(key), parent_artifact_id=parent_artifact_id)
```
NOTE the six-layer immutability contract in the docstring (lines 160-198) — bronze zone follows the same WORM semantics per A6/CLAUDE.md immutability constraint. Pitfall 4 (RESEARCH lines 366-370): key crawl_states uniqueness on `(job_id, normalized_url)`, NOT content hash, so identical content under a new URL is a new state row pointing at the no-op'd existing artifact.

---

### `registry/models.py` — ADD CrawlState, EXTEND Job, ADD Source.normalized_url (model, CRUD)

**Analog:** `registry/models.py` `Source` (lines 54-99) and `Artifact` (lines 102-197)

**Column pattern to copy** (Source, lines 63-92):
```python
id: Mapped[str] = mapped_column(String(64), primary_key=True)          # 'cst_<uuidv7>' for CrawlState
url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
robots_checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
config: Mapped[Optional[Any]] = mapped_column(_JSON, nullable=True)     # rate-limit override lives here (D-12 tier 1)
created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
```
Add `Source.normalized_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)` (nullable so existing spike rows stay valid — RESEARCH Runtime State line 340).

**FK + self-FK + UniqueConstraint pattern** (Artifact lines 116-137): CrawlState needs FK `job_id → jobs.id`, artifact FKs (`raw_artifact_id`, `bronze_artifact_id` → artifacts.id, nullable), and `__table_args__ = (UniqueConstraint("job_id", "normalized_url", name="uq_crawl_states_job_url"),)` (Pitfall 4). Columns: `status` (pending/complete/failed/robots_blocked), `fetched_at`.

**EXTEND Job** (lines 257-272) — per Open Question 1 / A5, add `source_id`, `job_type` (default `'crawl'`), `crawler`, `config` (_JSON), `stats` (_JSON), `updated_at`. Reuses `job_` prefix.

---

### `registry/repo.py` — ADD crawl-job/state + bronze + normalized-url functions (service, CRUD)

**Analog:** `registry/repo.py`

**Keyword-only create pattern** (lines 34-85, create_source):
```python
def create_source(session: Session, *, name: str, source_type: str, url=None, ...) -> Source:
    source = Source(id=new_id("source"), name=name, ..., created_at=datetime.datetime.now(datetime.timezone.utc))
    session.add(source)
    return source
```
Apply to `create_crawl_job`, `upsert_crawl_state`, `create_bronze_artifact`. Use `_make_artifact` (lines 91-117) for the bronze artifact with `kind`/`artifact_type="bronze_document"` and `parent_artifact_id` set — mirror `create_parsed_artifact` (lines 156-182) which shows the required-parent pattern.

**ORM select lookup pattern — NO raw SQL, T-01-03** (lines 224-243, get_artifact_by_hash):
```python
stmt = select(Artifact).where(Artifact.content_hash == content_hash).where(Artifact.artifact_type == artifact_type).limit(1)
return session.execute(stmt).scalar_one_or_none()
```
Copy for `get_source_by_normalized_url` (WHERE Source.normalized_url == ...) and `pending_states` (WHERE CrawlState.job_id == job_id AND status == 'pending' — the resume query, D-03).

---

### `registry/alembic/versions/0002_source_normalized_url.py` (plan 02-01) — migration (DDL)

**Analog:** `registry/alembic/versions/0001_core_schema.py`

**Revision header pattern** (lines 35-38):
```python
revision: str = "0002"
down_revision: Union[str, None] = "0001"   # <-- chain to 0001
branch_labels = None
depends_on = None
```

**add_column + index pattern** (lines 94-104 show constraint/index idiom). This migration adds: `op.add_column("sources", sa.Column("normalized_url", sa.Text, nullable=True))` + index on `normalized_url`. Provide symmetric `downgrade()` in reverse order.

### `registry/alembic/versions/0003_crawl_jobs_states.py` (plan 02-02) — migration (DDL)

**Analog:** `registry/alembic/versions/0001_core_schema.py`

**Revision header pattern:**
```python
revision: str = "0003"
down_revision: Union[str, None] = "0002"   # <-- chain to 0002
branch_labels = None
depends_on = None
```

**create_table + add_column + unique-constraint pattern** (lines 43-59 create_table, 62-91 FK column style `sa.ForeignKey("sources.id", ondelete="RESTRICT")`). This migration: `op.add_column` the new Job columns (`source_id`, `job_type`, `crawler`, `config`, `stats`, `updated_at`); `op.create_table("crawl_states", ...)` with FKs; `op.create_unique_constraint("uq_crawl_states_job_url", "crawl_states", ["job_id","normalized_url"])`. Provide symmetric `downgrade()` in reverse order (lines 165-178).

---

### `config/settings.py` — ADD searxng_url, crawler, discovery, CrawlSettings (config)

**Analog:** `config/settings.py`

**Nested BaseModel sub-model pattern** (lines 27-49, StorageSettings — plain `BaseModel`, NOT BaseSettings, per WR-02) for a `CrawlSettings` holding crawl defaults (max_pages, max_depth, global rate limit):
```python
class StorageSettings(BaseModel):
    endpoint_url: str | None = None
    bucket: str = "klake-data"
```
Wire it in with `crawl: CrawlSettings = Field(default_factory=CrawlSettings)` (line 93 pattern). Env: `KLAKE_CRAWL__MAX_PAGES` via `env_nested_delimiter="__"` (lines 64-70).

**Swap-key + service-URL pattern** (lines 76-90):
```python
qdrant_url: str = "http://localhost:6333"
embedder: str = "local"
vectorstore: str = "qdrant"
```
Add `searxng_url: str = "http://localhost:8888"`, `crawler: str = "crawl4ai"`, `discovery: str = "searxng"`. RESEARCH §V5: regex-validate crawler/discovery swap keys.

---

### `cli/app.py` — ADD add-source, upload, crawl, discover (route/CLI)

**Analog:** `cli/app.py` `cmd_ingest_url` (lines 50-84)

**Command + lazy import + error-to-exit pattern** (copy verbatim):
```python
@app.command(name="ingest-url")
def cmd_ingest_url(url: str = typer.Argument(...), source_name: Optional[str] = typer.Option(None, "--source", "-s", ...)):
    from knowledge_lake.pipeline.run import run_document   # lazy import inside command
    try:
        result = run_document(url=url, source_name=effective_name, ...)
        typer.echo(f"  source_id: {result['source_id']}")
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
```
`klake crawl` calls `pipeline.crawl`, `klake discover` calls `pipeline.discover`, `klake add-source`/`upload` call the extended ingest functions. Keep lazy imports (avoids importing crawl4ai/playwright at CLI startup).

---

### `api/app.py` + `api/schemas.py` — ADD /sources, /uploads, /crawl-jobs, /discover (controller + model)

**Analog:** `api/app.py` `search_endpoint` (lines 69-133), `api/schemas.py` `SearchHit`/`LineageNode`

**Thin-wrapper endpoint pattern (D-02 — call the same plain pipeline function the CLI calls)**, with input validation + structlog + 404 mapping (lines 105-133 + 173-180):
```python
if not _COLLECTION_NAME_RE.fullmatch(collection):     # reuse this regex-validation pattern for URLs/swap keys
    raise HTTPException(status_code=422, detail="Invalid ... format.")
logger.info("api.search", q=q[:80], ...)
hits = search(q, collection=collection, top_k=top_k)  # delegate to plain function
```
```python
try:
    nodes = resolve_ancestry(artifact_id)
except (LookupError, ValueError) as exc:
    raise HTTPException(status_code=404, detail=f"... {exc}") from exc
```
Response/request schemas copy the `SearchHit` field-with-description pattern (schemas.py lines 57-73) and the bounded-int validation `top_k: int = Field(ge=1, le=100)` (lines 42-47) for `limit`/`max_pages` params.

---

### `ids.py` — ADD prefixes (utility)

**Analog:** `ids.py` `_PREFIX` map (lines 31-37):
```python
_PREFIX: dict[str, str] = {"source": "src", "raw_document": "doc", "parsed_document": "doc", "chunk": "chk", "artifact": "art"}
```
Add `"crawl_job": "job"`, `"crawl_state": "cst"`, `"bronze_document": "doc"` (or a dedicated bronze prefix). `new_id(kind)` needs no other change.

---

### `pyproject.toml` — ADD entry-points + deps (config)

**Analog:** `pyproject.toml` lines 38-46:
```toml
[project.entry-points."knowledge_lake.embedders"]
local = "knowledge_lake.plugins.builtin.st_embedder:SentenceTransformerEmbedder"
```
Add:
```toml
[project.entry-points."knowledge_lake.crawlers"]
crawl4ai = "knowledge_lake.plugins.builtin.crawl4ai_adapter:Crawl4AIAdapter"
scrapy = "knowledge_lake.plugins.builtin.scrapy_adapter:ScrapyAdapter"
playwright = "knowledge_lake.plugins.builtin.playwright_adapter:PlaywrightAdapter"
[project.entry-points."knowledge_lake.discovery"]
searxng = "knowledge_lake.plugins.builtin.searxng_discovery:SearXNGDiscovery"
```
Deps: `crawl4ai==0.9.0`, `scrapy==2.16.0`, `playwright==1.61.0`, `protego==0.6.2`, `tldextract==5.3.1` (RESEARCH Standard Stack).

## Shared Patterns

### SSRF validation (V13 critical)
**Source:** `pipeline/ingest.py` `_validate_url_scheme` (lines 58-104) + `_PRIVATE_NETS` (lines 47-55)
**Apply to:** EVERY crawler fetch/link-follow, every SearXNG-discovered URL before auto-register (`pipeline/crawl.py`, `pipeline/discover.py`, all three adapters). Extract into a shared `validate_public_url()`. This is the #1 security gap (Pitfall 2) — the existing guard only protects `ingest_url`.

### Registry-first write in a single session
**Source:** `pipeline/ingest.py` lines 185-206
**Apply to:** All ingest/crawl/discover operations — open `with get_session() as session:`, create Source/Artifact/CrawlState + flush inside the same session, build the result dict from the persisted IDs.

### Content-addressed WORM no-op dedup
**Source:** `storage/s3.py` `put_raw` (lines 200-243) + `repo.get_artifact_by_hash` (lines 224-243)
**Apply to:** `put_bronze` and all crawl page writes. Hash-lookup-before-write gives D-07 hash-second dedup for free; content-addressed key makes overwrite structurally impossible.

### tenacity retry decorator
**Source:** `pipeline/ingest.py` lines 107-112
**Apply to:** Playwright adapter, SearXNG discovery calls, auto-selection probe (INGEST-09).

### Keyword-only repo functions, ORM-only (no raw SQL)
**Source:** `registry/repo.py` (all functions — `session: Session, *, ...`, `select(...).where(...)`)
**Apply to:** All new repo functions (T-01-03 injection prevention).

### Input validation at boundary (ASVS V5)
**Source:** `api/app.py` `_COLLECTION_NAME_RE` regex + `Field(ge=1, le=100)` (schemas.py)
**Apply to:** All new API params (URLs, query, crawler/discovery swap keys, limit/max_pages). Pass `q` to httpx as a `params` value, never string-format into the URL (SearXNG SSRF, RESEARCH §Security).

### pydantic-settings sub-model + swap key
**Source:** `config/settings.py` StorageSettings + `env_nested_delimiter="__"`
**Apply to:** CrawlSettings, searxng_url, crawler/discovery swap keys. URLs injected into plugins from settings (CR-03), never read via os.environ in builtins.

## No Analog Found

| File | Role | Data Flow | Reason / Guidance |
|------|------|-----------|-------------------|
| `plugins/builtin/scrapy_spider.py` | subprocess child module | batch | No existing subprocess-launched module. Pattern is external (RESEARCH Pattern 2, lines 260-274): `python -m ... <url> <out.jsonl> <config.json>`, writes JSON-lines. New territory driven by ReactorNotRestartable (Pitfall 1). |
| `crawl/robots.py` | utility | request-response | No robots.txt handling exists yet. Use Protego (RESEARCH Don't Hand-Roll); resolver logic is new. Rate-limit resolver `crawl/ratelimit.py` has RESEARCH exact code (lines 440-446) but no codebase analog. |

## Metadata

**Analog search scope:** `src/knowledge_lake/{plugins,pipeline,registry,storage,config,cli,api}`, `registry/alembic/versions`, `pyproject.toml`
**Files scanned:** 13 source files read in full (protocols, resolver, ingest, models, s3, repo, settings, 0001 migration, cli/app, api/app, api/schemas, ids) + pyproject entry-point block
**Pattern extraction date:** 2026-07-03
</content>
</invoke>
