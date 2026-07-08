---
phase: 01-foundation-end-to-end-spike
reviewed: 2026-07-03T00:00:00Z
depth: standard
files_reviewed: 33
files_reviewed_list:
  - src/knowledge_lake/__init__.py
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/ids.py
  - src/knowledge_lake/version.py
  - src/knowledge_lake/lineage.py
  - src/knowledge_lake/pipeline/ingest.py
  - src/knowledge_lake/pipeline/parse.py
  - src/knowledge_lake/pipeline/chunk.py
  - src/knowledge_lake/pipeline/embed.py
  - src/knowledge_lake/pipeline/index.py
  - src/knowledge_lake/pipeline/search.py
  - src/knowledge_lake/pipeline/run.py
  - src/knowledge_lake/plugins/protocols.py
  - src/knowledge_lake/plugins/resolver.py
  - src/knowledge_lake/plugins/builtin/docling_parser.py
  - src/knowledge_lake/plugins/builtin/st_embedder.py
  - src/knowledge_lake/plugins/builtin/qdrant_store.py
  - src/knowledge_lake/registry/models.py
  - src/knowledge_lake/registry/repo.py
  - src/knowledge_lake/registry/db.py
  - src/knowledge_lake/registry/alembic/env.py
  - src/knowledge_lake/registry/alembic/versions/0001_core_schema.py
  - src/knowledge_lake/storage/s3.py
  - src/knowledge_lake/storage/bootstrap.py
  - src/knowledge_lake/api/app.py
  - src/knowledge_lake/api/schemas.py
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/dagster_defs/assets.py
  - src/knowledge_lake/dagster_defs/definitions.py
  - src/knowledge_lake/dagster_defs/resources.py
  - tests/conftest.py
  - docker-compose.yml
  - pyproject.toml
findings:
  critical: 9
  warning: 9
  info: 4
  total: 22
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-07-03
**Depth:** standard
**Files Reviewed:** 33
**Status:** issues_found

## Summary

This review covers the full Phase 1 foundation: settings, ID generation, lineage, all five pipeline stages, all three plugin builtins, the registry ORM + repo + DB session, Alembic migration, S3 storage, FastAPI app, Typer CLI, Dagster assets/resources/definitions, and the test conftest.

The walking skeleton is structurally sound. The plugin protocol seam, content-addressed immutability layers, parameterised SQL (T-01-13), and LiteLLM constraint (CLAUDE.md) are all correctly implemented. However, the review surfaces nine blockers — several of which can cause silent data corruption, silent test pollution, security issues, or runtime crashes.

The most serious clusters are:

1. **SSRF completeness** — `ingest_url` blocks non-https schemes but allows all https hostnames, including private/internal IP ranges (cloud IMDS `169.254.169.254`, RFC-1918). The Phase 1 note defers this to Phase 2, but no kill-switch or warning gate prevents it being called in prod today.
2. **Silent transaction scope race** — the parse/chunk stages split registry reads and writes across two separate `get_session()` blocks with storage I/O in between. A second concurrent call for the same content can race past the dedup read, then both calls attempt to insert the same `(content_hash, artifact_type)`, hitting the unique constraint and rolling back with an unhandled `IntegrityError`.
3. **`os.environ.get` calls outside Settings** — two builtins (`st_embedder.py` and `qdrant_store.py`) read env vars directly, violating the CLAUDE.md constraint that prohibits any module other than settings from calling `os.getenv`/`os.environ`.
4. **Dagster asset function parameter shadowing** — asset functions name their parameters the same as the asset they depend on (e.g., `parsed_document(ingest_raw_document: dict)`) which shadows the module-level asset object and will cause `NameError` at materialise time when Dagster tries to resolve it.
5. **Temp-file persistence on Windows / POSIX with `delete=False`** — the Docling parser writes raw PDF bytes to a temp file with `delete=False` and relies on a `finally` block for cleanup, which is best-effort and can leave megabytes of temp files on disk if the process is killed.

---

## Critical Issues

### CR-01: SSRF — `ingest_url` permits requests to private/cloud-metadata IP ranges

**File:** `src/knowledge_lake/pipeline/ingest.py:46-57`
**Issue:** `_validate_url_scheme` only checks that the scheme is `https`. It does not block private IP ranges (RFC-1918: `10.x`, `172.16-31.x`, `192.168.x`) or link-local cloud metadata endpoints (`169.254.169.254` for AWS/GCP/Azure IMDS, `fd00:ec2::254` IPv6). A caller supplying `https://169.254.169.254/latest/meta-data/iam/security-credentials/...` will receive a valid response from the EC2 metadata service, exposing cloud credentials. The comment "Private-IP blocking is deferred to Phase 2 (INGEST-02)" documents the gap but provides no guard against it shipping to prod.

**Fix:**
```python
import ipaddress
import socket

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / cloud IMDS
    ipaddress.ip_network("127.0.0.0/8"),       # loopback
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 ULA
]

def _validate_url_scheme(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Only https:// URLs are allowed (SSRF prevention). Got: {parsed.scheme!r}")
    # Resolve hostname and block private ranges
    hostname = parsed.hostname or ""
    try:
        addr = ipaddress.ip_address(socket.gethostbyname(hostname))
    except Exception:
        raise ValueError(f"Cannot resolve hostname {hostname!r}")
    for net in _PRIVATE_NETS:
        if addr in net:
            raise ValueError(
                f"URL {url!r} resolves to private/link-local address {addr} — "
                "SSRF prevention blocks requests to private networks."
            )
```

---

### CR-02: Race condition — `parse` and `chunk` stages split dedup check and write across separate sessions

**File:** `src/knowledge_lake/pipeline/parse.py:91-128` and `src/knowledge_lake/pipeline/chunk.py:66-105`
**Issue:** Both stages open one session to check for an existing artifact (`get_artifact_by_hash`), close it, perform storage I/O, then open a second session to write the new artifact. Under concurrent execution (two Dagster materialise runs for the same document), both calls can pass the dedup read simultaneously, then both attempt to INSERT the same `(content_hash, artifact_type)` row. The database's UNIQUE constraint (`uq_artifacts_hash_type`) will catch one and roll back with `sqlalchemy.exc.IntegrityError`, which propagates as an unhandled exception crashing the asset. The idempotent path is never taken.

The same pattern exists in `storage/s3.py:put_raw` but is partially mitigated there because both the registry check and the S3 write happen inside a single session block — the split only occurs between the S3 write and the registry insert, which is a narrower window.

**Fix:** Perform the dedup check AND the artifact insert within a single `get_session()` block, using `INSERT ... ON CONFLICT DO NOTHING RETURNING id` (or an advisory lock) so the operation is atomic:
```python
# In parse.py — keep both the no-op check and the INSERT inside ONE session block.
with get_session() as session:
    existing = registry_repo.get_artifact_by_hash(session, content_hash, "parsed_document")
    if existing is not None:
        return {"artifact_id": existing.id, ...}, parsed_doc
    # Storage write still happens outside (unavoidable), but registry write is atomic.
    storage.put_object(silver_key, parsed_bytes)
    silver_uri = storage.object_uri(silver_key)
    artifact = registry_repo.create_parsed_artifact(session, ...)
    session.flush()
    result = {...}
# No second session needed.
```
The same consolidation applies to `chunk.py`.

---

### CR-03: `os.environ.get` outside Settings — violates CLAUDE.md constraint in two plugin builtins

**File:** `src/knowledge_lake/plugins/builtin/st_embedder.py:122` and `src/knowledge_lake/plugins/builtin/qdrant_store.py:45`
**Issue:** Both builtins call `os.environ.get` directly to read KLAKE_* config, bypassing the Settings module. CLAUDE.md states: "No other module in this codebase should call os.getenv() or read environment variables directly." This means these values are not validated by Pydantic, not overridable in tests via the `settings` fixture, and silently fall back to hardcoded defaults (`http://localhost:4000`, `http://localhost:6333`) even when the test isolation fixture clears KLAKE_* vars.

`st_embedder.py:122`:
```python
self._proxy_url: str = os.environ.get("KLAKE_LITELLM_URL", "http://localhost:4000")
```
`qdrant_store.py:45`:
```python
qdrant_url: str = os.environ.get("KLAKE_QDRANT_URL", "http://localhost:6333")
```

**Fix:** Accept the URL as a constructor argument (injected by the resolver from settings) rather than reading env vars:
```python
# In resolver.py, pass the URL when instantiating:
def get_vectorstore(settings: "Settings") -> Any:
    factory = _load_ep(GROUP_VECTORSTORES, settings.vectorstore)
    return factory(qdrant_url=settings.qdrant_url)

# In qdrant_store.py:
class QdrantVectorStore:
    def __init__(self, qdrant_url: str = "http://localhost:6333") -> None:
        self._client = QdrantClient(url=qdrant_url)

# Similarly for LiteLLMEmbedder — pass litellm_url from settings.litellm_url.
```

---

### CR-04: Dagster asset parameter names shadow module-level asset objects — `NameError` at materialise time

**File:** `src/knowledge_lake/dagster_defs/assets.py:172-176, 238-252, 282-298, 325-343`
**Issue:** Dagster injects upstream asset outputs into downstream asset functions by parameter name. However, the parameter names here exactly match the names of the module-level asset *functions* (e.g., `parsed_document`, `chunk_document`, `embed_chunks`). Within the function body, those names now refer to the `dict` argument, not the asset object — that is fine. But the issue is that Dagster resolves assets by matching the parameter name to the asset key at materialise time. If Dagster resolves these differently than expected (it injects the *value* from the previous asset's return), the code may work but the shadowing will cause confusing debugging experiences and can break on Dagster version changes. More critically, the `deps=[ingest_raw_document]` / `deps=[parsed_document]` / etc. declarations on lines 165, 229, 274, 316 are **redundant with the positional injection** — having both causes Dagster to see the dependency twice, which can produce duplicate dependency edges or silent errors in the Dagster graph. Pick one pattern (explicit `deps=[]` OR positional input injection, not both).

**Fix:** Use only positional input injection (no `deps=[]`), or use only `deps=[]` with `context.op_config` for passing data:
```python
@asset(group_name="pipeline")  # Remove deps=[ingest_raw_document]
def parsed_document(
    ingest_raw_document: dict[str, Any],  # Dagster injects this from previous asset
    postgres: PostgresResource,
    minio: MinIOResource,
) -> dict[str, Any]:
    ...
```

---

### CR-05: `get_session()` is synchronous but the module-level engine is built at import time — blocks async event loop

**File:** `src/knowledge_lake/registry/db.py:47-48`
**Issue:** The module-level statement `engine: Engine = _build_engine()` runs at import time. `_build_engine()` calls `get_settings()` which in turn calls `Settings()`, loading `.env` from disk. This means **any import of the registry module** (including inside FastAPI startup, test collection, or Dagster code location loading) triggers a `.env` file read and potentially a network DNS lookup if pydantic-settings tries to resolve the database URL. In tests that use the `_isolate_env` fixture, KLAKE_* vars are removed after import, but the engine is already built with whatever URL was active at import time — tests that rely on the `settings` fixture to set `KLAKE_DATABASE_URL` will silently use the module-level engine built from the original (wrong) URL.

**Fix:** Lazy-initialise the engine behind a function call:
```python
_engine: Engine | None = None

def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine

@contextmanager
def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        ...
```
Tests that need a custom engine can then monkey-patch `get_engine` rather than `engine`.

---

### CR-06: `_PREFIX_LOOKUP_SQL` in lineage.py uses `LIKE` with a user-controlled `%` pattern — potential performance denial-of-service

**File:** `src/knowledge_lake/lineage.py:91-96`
**Issue:** The prefix expansion query passes `f"{artifact_id}%"` as the `LIKE` pattern. If `artifact_id` is the empty string (which the endpoint does not reject — FastAPI only validates the path segment is non-empty but does not enforce a minimum meaningful length), the pattern becomes `%`, which performs a full table scan returning up to 10 rows from potentially millions of artifacts. The LIMIT 10 caps the result set, but the scan is unbounded. More critically, if `artifact_id` contains `%` or `_` (SQL LIKE wildcards), the pattern may match far more rows than intended, leaking artifact IDs from other sources to the caller.

**Fix:**
```python
# Escape SQL LIKE wildcards in the user-supplied prefix
import re
def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

# In _expand_prefix:
rows = session.execute(
    _PREFIX_LOOKUP_SQL,
    {"prefix_pattern": f"{_escape_like(artifact_id)}%", "escape_char": "\\"},
).fetchall()
# Also validate that artifact_id is at least 4 characters (type prefix + underscore + first UUID char)
if len(artifact_id) < 4:
    raise ValueError("Artifact ID prefix must be at least 4 characters.")
```

---

### CR-07: `ingest_url` always sets `robots_checked=True` and `license_type="public_domain"` regardless of actual checks

**File:** `src/knowledge_lake/pipeline/ingest.py:121-128`
**Issue:** Every URL ingested via `ingest_url` is registered with `robots_checked=True` and `license_type="public_domain"` unconditionally — no robots.txt check is performed. The CLAUDE.md constraint states: "Respect robots.txt, track source licenses, no private/restricted scraping." By hardcoding `robots_checked=True`, the registry silently marks all web sources as compliant even when they are not. This is not just a deferred feature — it is a false attestation in the compliance field.

`ingest_file` similarly hardcodes `robots_checked=True`, which is appropriate for local uploads but should still not hardcode `license_type="public_domain"` for files that may be proprietary.

**Fix:** Pass `robots_checked=False` as the default and add a `license_type` parameter. Only set `robots_checked=True` when the caller has actually checked robots.txt (Phase 2 responsibility):
```python
def ingest_url(
    url: str,
    source_name: str,
    *,
    mime_type: str = "application/pdf",
    license_type: str = "unknown",      # caller must supply
    robots_checked: bool = False,       # default safe: not checked
    settings: Optional[Settings] = None,
) -> dict:
```

---

### CR-08: Docling temp file written with `delete=False` leaks raw document bytes on process kill

**File:** `src/knowledge_lake/plugins/builtin/docling_parser.py:78-88`
**Issue:** The Docling parser writes raw PDF bytes (up to 50 MB) to a temp file with `delete=False`, then relies on `finally: tmp_path.unlink(missing_ok=True)` for cleanup. If the process is killed (SIGKILL, OOM), the `finally` block does not run and the temp file persists indefinitely. In a long-running server or Dagster worker, accumulated temp files can fill `/tmp`, and raw document bytes (potentially sensitive medical PDFs in a healthcare context) persist in an unprotected location outside the WORM S3 bucket.

**Fix:** Use a temp directory and `shutil.rmtree` in the finally block, or use a `tempfile.TemporaryDirectory` context manager:
```python
import tempfile, shutil

def parse(self, raw: bytes, mime_type: str) -> ParsedDoc:
    if not self.can_parse(mime_type):
        raise ValueError(...)
    suffix = _mime_to_suffix(mime_type)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / f"doc{suffix}"
        tmp_path.write_bytes(raw)
        return self._convert_file(tmp_path)
    # Directory and all contents are removed even on exception
```

---

### CR-09: `LiteLLMEmbedder.dim` is hardcoded to 1536 but actual response dimension is not validated

**File:** `src/knowledge_lake/plugins/builtin/st_embedder.py:117`
**Issue:** `LiteLLMEmbedder.dim = 1536` is a hardcoded assumption about the model behind the `embedding_model` alias. If the operator changes the LiteLLM config to point at a different model (e.g., `text-embedding-ada-002` at 1536 is fine, but `text-embedding-3-small` at 1536 or Cohere embed-v3 at 1024 would be wrong), `dim` will lie. Downstream, `index.py` uses `dim` to call `ensure_collection(collection, dim=dim)` — if the collection was created with dim=1536 and the model now returns 384-dim vectors, every upsert fails with a Qdrant dimension mismatch error. Conversely, if the model returns a larger dim than the collection was created with, the same silent failure occurs.

There is no runtime assertion that `len(vectors[0]) == self.dim`.

**Fix:**
```python
def embed(self, texts: list[str]) -> list[list[float]]:
    ...
    vectors = [item.embedding for item in response.data]
    if vectors and len(vectors[0]) != self.dim:
        actual = len(vectors[0])
        raise RuntimeError(
            f"LiteLLMEmbedder: model returned {actual}-dim vectors but "
            f"dim={self.dim} is configured. Update _LITELLM_DIM or the model alias."
        )
    return vectors
```

---

## Warnings

### WR-01: `__init__.py` configures structlog with `ConsoleRenderer` — JSON output is never used

**File:** `src/knowledge_lake/__init__.py:21-31`
**Issue:** The `_configure_logging()` function installs `structlog.dev.ConsoleRenderer()` which outputs human-readable coloured text. CLAUDE.md states "JSON-structured logs for all application logging." The production deployment (`docker compose up`) should emit JSON logs so they are parseable by log aggregators. `ConsoleRenderer` is appropriate only for local dev.

**Fix:** Use `structlog.processors.JSONRenderer()` (or `structlog.processors.ExceptionRenderer()` + `structlog.processors.JSONRenderer()`) in production, and conditionally use `ConsoleRenderer` only when `sys.stdout.isatty()` or a `KLAKE_LOG_FORMAT=dev` env var is set:
```python
import sys
_renderer = (
    structlog.dev.ConsoleRenderer()
    if sys.stdout.isatty()
    else structlog.processors.JSONRenderer()
)
```

---

### WR-02: `StorageSettings` has a redundant `model_config` with `env_prefix="KLAKE_STORAGE__"` — conflicts with parent Settings nesting

**File:** `src/knowledge_lake/config/settings.py:34-37`
**Issue:** `StorageSettings` is used as a nested model inside `Settings` via `Field(default_factory=StorageSettings)` and `env_nested_delimiter="__"`. When Pydantic-settings resolves a nested model, it uses the parent's prefix + the field name + the nested delimiter. Having `env_prefix="KLAKE_STORAGE__"` on `StorageSettings` itself causes double-prefix resolution when it is used standalone (e.g., `StorageSettings()` in Dagster assets). This means `KLAKE_STORAGE__ENDPOINT_URL` is resolved correctly when read through `Settings`, but when `StorageSettings(...)` is instantiated directly in `assets.py`, the `env_prefix` is applied again, looking for `KLAKE_STORAGE__KLAKE_STORAGE__ENDPOINT_URL`. In practice, the Dagster assets pass kwargs directly to `StorageSettings(endpoint_url=minio.endpoint_url, ...)`, bypassing env-loading entirely, so this does not crash today. But it will silently misbehave for any `StorageSettings()` standalone instantiation.

**Fix:** Remove `model_config` from `StorageSettings` and rely solely on the parent `Settings.model_config` with `env_nested_delimiter="__"`:
```python
class StorageSettings(BaseModel):  # BaseModel, not BaseSettings
    endpoint_url: str | None = None
    bucket: str = "klake-data"
    region: str = "us-east-1"
    access_key_id: str | None = None
    secret_access_key: str | None = None
```

---

### WR-03: `get_settings()` is cached with `@lru_cache` — test fixture leaks: cached instance from one test bleeds into subsequent tests

**File:** `src/knowledge_lake/config/settings.py:105-112`
**Issue:** `get_settings()` is cached with `lru_cache(maxsize=1)`. The test conftest creates `Settings(_env_file=None)` directly in the `settings` fixture (correctly bypassing the cache), but **any code under test that calls `get_settings()` directly** (e.g., `db.py` at import time, `pipeline/ingest.py:112`, etc.) will receive the cached instance from the first test that triggered it — regardless of what `_isolate_env` sets in the environment. Because `db.py` builds its engine at module import time using `get_settings()`, the cache is populated at import time and never reset between tests.

**Fix:** The test suite needs to clear the cache between tests:
```python
# In conftest.py:
@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Generator[None, None, None]:
    from knowledge_lake.config.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```
And the engine must be lazily constructed (see CR-05).

---

### WR-04: `parse.py` reads raw bytes outside the session block then opens a new session — storage read is not covered by the session lifetime

**File:** `src/knowledge_lake/pipeline/parse.py:61-74`
**Issue:** The raw artifact's `storage_uri` is retrieved in session block 1 (lines 62-70), the session closes, then `storage.get_object(key)` is called outside any session (line 74). If `storage.get_object` raises (e.g., `ClientError: NoSuchKey`), the failure is unhandled and the error message gives no context about which artifact or source_id was being fetched. Additionally, calling `_uri_to_key` without validating that `storage_uri` starts with `s3://` could return an incorrect key for non-standard URIs without a clear error.

**Fix:** Validate the URI format:
```python
def _uri_to_key(uri: str) -> str:
    if not uri.startswith("s3://"):
        raise ValueError(f"Expected s3:// URI, got: {uri!r}")
    parts = uri.split("/", 3)
    if len(parts) < 4 or not parts[3]:
        raise ValueError(f"Cannot extract key from URI: {uri!r}")
    return parts[3]
```

---

### WR-05: `chunk.py` — identical chunk texts from different sections get registry no-op with wrong parent

**File:** `src/knowledge_lake/pipeline/chunk.py:75-85`
**Issue:** The dedup check `registry_repo.get_artifact_by_hash(session, content_hash, "chunk")` returns the first chunk artifact with matching content, regardless of which parsed document it belongs to. If a chunk with identical text was previously ingested from a *different* document, the returned artifact will have a different `parent_artifact_id` than the current `parsed_artifact_id`. The lineage chain is then corrupted: the chunk's lineage points to the wrong parent parsed document. The `section_path` and `page` are also taken from the existing artifact even though they may differ.

**Fix:** Include `parent_artifact_id` (or at minimum `source_id`) in the dedup key. Either add a new lookup that filters by `parent_artifact_id`, or include the parent ID in the hash:
```python
# Hash includes parent ID so the same text from different documents creates distinct artifacts
hash_input = f"{parent_artifact_id}:{text}"
content_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
```
Or add a `get_artifact_by_hash_and_parent` repo function.

---

### WR-06: `render_tree` in lineage.py truncates `content_hash` to 16 characters without ellipsis guard

**File:** `src/knowledge_lake/lineage.py:203`
**Issue:**
```python
lines.append(f"  hash:     {content_hash[:16]}...")
```
If `content_hash` is an empty string (which cannot happen with SHA256 but can happen with a corrupt or test row with `content_hash=""`), this emits `  hash:     ...` with no leading hash digits, which is visually indistinguishable from a valid short hash. More importantly, `content_hash[:16]` silently truncates — a user relying on this output to verify a document hash will only see 16 of 64 hex characters, which is insufficient for any meaningful verification. Either show the full hash or clearly label it as truncated.

**Fix:**
```python
hash_display = content_hash[:16] + "..." if len(content_hash) > 16 else content_hash
lines.append(f"  hash:     {hash_display}  (sha256, truncated — use --json for full hash)")
```

---

### WR-07: `qdrant_store.py` imports `PointStruct` in `search()` but never uses it

**File:** `src/knowledge_lake/plugins/builtin/qdrant_store.py:127`
**Issue:**
```python
from qdrant_client.models import PointStruct
```
`PointStruct` is imported inside `search()` but not used. The `query_points` API returns `ScoredPoint` objects, not `PointStruct`. The import is dead code that adds confusion (reader expects PointStruct to be used) and an unnecessary dynamic import on every search call.

**Fix:** Remove the unused import from `search()`.

---

### WR-08: `ingest_url` default `mime_type="application/pdf"` silently misclassifies non-PDF URLs

**File:** `src/knowledge_lake/pipeline/ingest.py:86-89`
**Issue:** `ingest_url(..., mime_type="application/pdf")` is the default. When the caller does not supply a MIME type (e.g., `klake ingest-url https://example.com/doc.html`), the URL will be stored and parsed as if it is a PDF, even though the server returns `Content-Type: text/html`. Docling's `can_parse("application/pdf")` returns True and will attempt to parse HTML bytes as a PDF, producing garbage or an internal Docling error.

The HTTP response `Content-Type` header is available and should be used:
**Fix:**
```python
with httpx.stream("GET", url, timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True) as resp:
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    # ... accumulate chunks
return b"".join(chunks), content_type
# Caller uses the returned MIME type instead of the default
```

---

### WR-09: `docker-compose.yml` uses default MinIO credentials `minioadmin`/`minioadmin` as the compose-file default

**File:** `docker-compose.yml:23-24, 55-56`
**Issue:** The `docker-compose.yml` uses `${KLAKE_STORAGE__ACCESS_KEY_ID:-minioadmin}` and `${KLAKE_STORAGE__SECRET_ACCESS_KEY:-minioadmin}` as fallback defaults. These are the well-known MinIO default credentials and are widely known. A developer who runs `docker compose up` without setting a `.env` will have a MinIO instance accessible on `localhost:9000` with published default credentials. The README should explicitly warn against this, and the default should be changed to a value that forces the operator to act.

**Fix:** Change the defaults to a sentinel value that causes an obvious failure rather than a silent weak credential:
```yaml
KLAKE_STORAGE__ACCESS_KEY_ID: "${KLAKE_STORAGE__ACCESS_KEY_ID:?Set KLAKE_STORAGE__ACCESS_KEY_ID in .env}"
KLAKE_STORAGE__SECRET_ACCESS_KEY: "${KLAKE_STORAGE__SECRET_ACCESS_KEY:?Set KLAKE_STORAGE__SECRET_ACCESS_KEY in .env}"
```
Or document prominently that the `minioadmin` defaults must not be used outside local throwaway development.

---

## Info

### IN-01: `import logging` is imported but unused in `pipeline/ingest.py` and `pipeline/run.py`

**File:** `src/knowledge_lake/pipeline/ingest.py:12`, `src/knowledge_lake/pipeline/run.py:13`
**Issue:** Both files import `logging` from the stdlib but use `structlog.get_logger` for all logging. The stdlib `logging` import is dead code.
**Fix:** Remove `import logging` from both files.

---

### IN-02: `version.py` — `subprocess.run` for git SHA runs at every artifact write

**File:** `src/knowledge_lake/version.py:51-59`
**Issue:** `pipeline_version()` is called by `_make_artifact()` in `repo.py`, which is called for every artifact created (raw, parsed, chunk). Each call spawns a new `subprocess.run(["git", "rev-parse", "--short", "HEAD"])`. For a document with 50 chunks, this forks 52 child processes (1 raw + 1 parsed + 50 chunks). The result is deterministic (the SHA does not change during a run), so this should be cached once per process.

**Fix:**
```python
from functools import lru_cache

@lru_cache(maxsize=1)
def pipeline_version() -> str:
    ...
```

---

### IN-03: `ids.py` — `raw_document` and `parsed_document` both map to prefix `doc_` — ambiguous IDs

**File:** `src/knowledge_lake/ids.py:31-37`
**Issue:**
```python
_PREFIX = {
    "source": "src",
    "raw_document": "doc",
    "parsed_document": "doc",  # same prefix as raw_document
    ...
}
```
Both raw and parsed documents get `doc_` prefixed IDs. The prefix's stated purpose (line 5) is "self-describing" so "logs and CLI output are self-describing." With both types sharing `doc_`, a log line with `doc_019f...` does not tell the reader whether it is a raw or parsed document. The `_expand_prefix` function in lineage.py also uses the type prefix hint to narrow lookups — but since both types share `doc_`, a prefix like `doc_019f` could match either type, increasing ambiguity.

**Fix:** Give parsed documents a distinct prefix, e.g. `"parsed_document": "prs"`.

---

### IN-04: `conftest.py` `settings` fixture does not clear the `get_settings` LRU cache — fixture has no effect on any code that calls `get_settings()`

**File:** `tests/conftest.py:43-66`
**Issue:** The `settings` fixture uses `patch.dict(os.environ, test_env)` to set KLAKE_* env vars, then instantiates `Settings(_env_file=None)` directly. This returns a correctly configured `Settings` object to the test. However, any production code under test that calls `get_settings()` will receive the *cached* instance (populated at first import, before the fixture's `patch.dict` context is active), not the test-configured instance. The fixture is thus only useful when the test explicitly passes the returned `Settings` object as a parameter — it does not affect global `get_settings()` callers.

**Fix:** Add a `get_settings.cache_clear()` call inside the fixture (see also WR-03):
```python
@pytest.fixture
def settings():
    from knowledge_lake.config.settings import Settings, get_settings
    get_settings.cache_clear()
    test_env = {...}
    with patch.dict(os.environ, test_env, clear=False):
        get_settings.cache_clear()
        yield Settings(_env_file=None)
    get_settings.cache_clear()
```

---

_Reviewed: 2026-07-03_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
