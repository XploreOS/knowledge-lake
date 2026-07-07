---
phase: 01-foundation-end-to-end-spike
fixed_at: 2026-07-03T06:20:00Z
review_path: .planning/phases/01-foundation-end-to-end-spike/01-REVIEW.md
iteration: 1
findings_in_scope: 18
fixed: 18
skipped: 0
status: all_fixed
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-07-03T06:20:00Z
**Source review:** .planning/phases/01-foundation-end-to-end-spike/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 18 (9 Critical + 9 Warning; Info findings excluded by fix_scope=critical_warning)
- Fixed: 18
- Skipped: 0

---

## Fixed Issues

### CR-01: SSRF — private/cloud-metadata IP blocking added

**Files modified:** `src/knowledge_lake/pipeline/ingest.py`
**Commit:** 25a0ecc
**Applied fix:** Added `_PRIVATE_NETS` list covering RFC-1918 (10.x, 172.16-31.x, 192.168.x), link-local/cloud IMDS (169.254.0.0/16), loopback (127.0.0.0/8), IPv6 loopback (::1/128), and IPv6 ULA (fc00::/7). Updated `_validate_url_scheme` to resolve the hostname via `socket.gethostbyname` and check the resolved address against all private networks. Raises `ValueError` with a descriptive SSRF message if matched. Also removed the deferred Phase 2 note from the docstring.

---

### CR-02: Race condition — parse session blocks consolidated

**Files modified:** `src/knowledge_lake/pipeline/parse.py`
**Commit:** 656685d
**Applied fix:** Merged the two separate `get_session()` blocks in `parse()` into a single block. The dedup check (`get_artifact_by_hash`), S3 storage write, and registry insert now all happen within one session context, making the dedup + insert atomic and preventing the `IntegrityError` from concurrent calls for the same content hash. Note: requires human verification for the logic — the S3 put_object call is inside the session block (S3 writes are idempotent for the same key). Also includes WR-04 fix (s3:// URI validation).

---

### CR-03: `os.environ.get` replaced with constructor injection

**Files modified:** `src/knowledge_lake/plugins/builtin/st_embedder.py`, `src/knowledge_lake/plugins/builtin/qdrant_store.py`, `src/knowledge_lake/plugins/resolver.py`
**Commit:** 0c4415e
**Applied fix:** `LiteLLMEmbedder.__init__` now accepts `litellm_url: str` parameter instead of calling `os.environ.get`. `QdrantVectorStore.__init__` now accepts `qdrant_url: str` parameter instead of calling `os.environ.get`. Both `os` imports were removed. The resolver's `get_embedder` and `get_vectorstore` functions were updated to pass `litellm_url=settings.litellm_url` and `qdrant_url=settings.qdrant_url` respectively when constructing these plugins, so the URLs flow from Pydantic-validated Settings.

---

### CR-04: Dagster `deps=[]` double-declaration removed

**Files modified:** `src/knowledge_lake/dagster_defs/assets.py`
**Commit:** adbecf4
**Applied fix:** Removed all four `deps=[<upstream_asset>]` keyword arguments from the `@asset` decorators for `parsed_document`, `chunk_document`, `embed_chunks`, and `index_chunks`. The dependency graph is now declared solely via positional parameter injection (Dagster resolves dependencies from parameter names), eliminating the duplicate dependency edges.

---

### CR-05: SQLAlchemy engine made lazy-initialised

**Files modified:** `src/knowledge_lake/registry/db.py`
**Commit:** e118b5d
**Applied fix:** Replaced the module-level `engine: Engine = _build_engine()` call with a `_engine: Engine | None = None` variable and a `get_engine()` function that lazily calls `_build_engine()` on first invocation. `get_session()` now calls `get_engine()` instead of referencing the module-level `engine`. This means importing the module no longer triggers a `.env` read or DNS lookup. Tests can reset `_engine = None` to force a fresh engine build after modifying KLAKE_DATABASE_URL.

---

### CR-06: LIKE wildcard injection fixed in lineage.py

**Files modified:** `src/knowledge_lake/lineage.py`
**Commit:** bdf4943
**Applied fix:** Added `_escape_like(value)` helper that escapes `\`, `%`, and `_` in user-supplied artifact ID prefixes. Updated `_PREFIX_LOOKUP_SQL` to use `ESCAPE :escape_char` clause. Updated `_expand_prefix` to call `_escape_like` on the prefix before building the pattern and to pass `escape_char="\\"` as a bound parameter. Added a minimum length check (4 characters) to reject empty or single-char inputs that would otherwise trigger near-full-table scans. Also includes WR-06 fix (hash display truncation guard).

---

### CR-07: `robots_checked=True` hardcoding removed

**Files modified:** `src/knowledge_lake/pipeline/ingest.py`
**Commit:** 25a0ecc
**Applied fix:** `ingest_url` now accepts `robots_checked: bool = False` and `license_type: str = "unknown"` as keyword arguments. Default `robots_checked=False` correctly reflects that no robots.txt check has been performed. `ingest_file` similarly accepts `license_type` and uses `robots_checked=False` (local uploads don't require robots.txt checking). Committed atomically with CR-01.

---

### CR-08: Docling temp file leak fixed with `TemporaryDirectory`

**Files modified:** `src/knowledge_lake/plugins/builtin/docling_parser.py`
**Commit:** 2d875fa
**Applied fix:** Replaced `NamedTemporaryFile(delete=False)` + `finally: unlink` pattern with `tempfile.TemporaryDirectory()` context manager. The PDF bytes are written to `{tmpdir}/doc{suffix}` and Docling processes the file. The directory and its contents are cleaned up deterministically when the context manager exits, even if the process receives an exception mid-conversion. Removed unused `import io` and `import logging`.

---

### CR-09: LiteLLMEmbedder dimension validation added

**Files modified:** `src/knowledge_lake/plugins/builtin/st_embedder.py`
**Commit:** 0c4415e
**Applied fix:** Added a runtime assertion in `LiteLLMEmbedder.embed()` that checks `len(vectors[0]) != self.dim` after the LiteLLM call returns. If the actual vector dimension does not match the configured `_LITELLM_DIM`, a descriptive `RuntimeError` is raised immediately, preventing silent dimension mismatches from reaching Qdrant upsert. Committed atomically with CR-03 and WR-07.

---

### WR-01: `ConsoleRenderer` replaced with conditional renderer

**Files modified:** `src/knowledge_lake/__init__.py`
**Commit:** 245474c
**Applied fix:** `_configure_logging()` now selects the renderer at runtime: `ConsoleRenderer` when `sys.stdout.isatty()` is True or `KLAKE_LOG_FORMAT=dev` is set; `JSONRenderer` otherwise. This ensures Docker container deployments (non-tty stdout) emit JSON-structured logs that log aggregators can parse, while local interactive development retains human-readable coloured output. Added `import os` and `import sys`.

---

### WR-02: `StorageSettings` changed from `BaseSettings` to `BaseModel`

**Files modified:** `src/knowledge_lake/config/settings.py`
**Commit:** 09a5832
**Applied fix:** Changed `StorageSettings` to inherit from `pydantic.BaseModel` instead of `pydantic_settings.BaseSettings`. Removed the `model_config = SettingsConfigDict(env_prefix="KLAKE_STORAGE__", ...)` from `StorageSettings`. The parent `Settings` class continues to handle env-var resolution for the nested model via `env_nested_delimiter="__"`. This eliminates the double-prefix resolution bug that would occur if `StorageSettings()` was ever instantiated standalone. Committed atomically with WR-03.

---

### WR-03: `get_settings()` LRU cache cleared between tests

**Files modified:** `tests/conftest.py`
**Commit:** 09a5832
**Applied fix:** Added an `autouse=True` fixture `_clear_settings_cache` that calls `get_settings.cache_clear()` before and after each test. Also resets `knowledge_lake.registry.db._engine = None` to force a fresh engine build from the post-isolation environment (complements CR-05). The `settings` fixture was updated to also call `get_settings.cache_clear()` within the `patch.dict` context so global `get_settings()` callers receive the test-configured values.

---

### WR-04: `_uri_to_key` validates `s3://` URI prefix in parse.py

**Files modified:** `src/knowledge_lake/pipeline/parse.py`
**Commit:** 656685d
**Applied fix:** `_uri_to_key` now raises `ValueError` with a descriptive message if the URI does not start with `s3://`, and separately validates that the key portion is non-empty. This provides an early and clear error for misconfigured `storage_uri` values rather than silently producing a wrong S3 key. Committed atomically with CR-02.

---

### WR-05: Chunk dedup hash includes `parent_artifact_id`

**Files modified:** `src/knowledge_lake/pipeline/chunk.py`
**Commit:** a63ebc8
**Applied fix:** The `content_hash` for each chunk is now computed as `sha256(f"{parsed_artifact_id}:{text}")` instead of `sha256(text)`. This ensures chunks with identical text from different parsed documents produce distinct artifact IDs, preventing the lineage corruption where a chunk's registry entry incorrectly pointed to a different document's parsed artifact as its parent.

---

### WR-06: Hash display in `render_tree` shows truncation guard

**Files modified:** `src/knowledge_lake/lineage.py`
**Commit:** bdf4943
**Applied fix:** Changed `content_hash[:16]...` to use a guarded expression: `hash_display = content_hash[:16] + "..." if len(content_hash) > 16 else content_hash`. Added a clarifying annotation `(sha256, truncated — use --json for full hash)` so users know the displayed value is abbreviated. Committed atomically with CR-06.

---

### WR-07: Unused `PointStruct` import removed from `qdrant_store.py`

**Files modified:** `src/knowledge_lake/plugins/builtin/qdrant_store.py`
**Commit:** 0c4415e
**Applied fix:** Removed the `from qdrant_client.models import PointStruct` import from the `search()` method body. The `query_points` API returns `ScoredPoint` objects; `PointStruct` was never used in `search()`. Committed atomically with CR-03 and CR-09.

---

### WR-08: `ingest_url` uses server Content-Type header for MIME type

**Files modified:** `src/knowledge_lake/pipeline/ingest.py`
**Commit:** 9817fe1
**Applied fix:** `_fetch_with_retry` now returns a `(bytes, str)` tuple where the second element is the Content-Type from the response header (stripped of charset parameters, defaulting to `application/octet-stream`). `ingest_url`'s `mime_type` parameter default changed from `"application/pdf"` to `None`. When `mime_type=None`, the effective MIME type is taken from the server's Content-Type header, preventing HTML/text URLs from being silently misclassified as PDFs. Caller-supplied `mime_type` overrides the server header.

---

### WR-09: MinIO default credentials removed from `docker-compose.yml`

**Files modified:** `docker-compose.yml`
**Commit:** 877c479
**Applied fix:** Changed `${KLAKE_STORAGE__ACCESS_KEY_ID:-minioadmin}` to `${KLAKE_STORAGE__ACCESS_KEY_ID:?Set KLAKE_STORAGE__ACCESS_KEY_ID in .env (see .env.example)}` and similarly for `SECRET_ACCESS_KEY`. The `:?` Docker Compose syntax causes the stack to fail at startup with a descriptive error message if the variable is unset, rather than silently using the well-known `minioadmin` credentials. Applied to the `x-common-env` block, the `minio` service, and the `minio-init` service. Added a security note comment at the top of the file.

---

_Fixed: 2026-07-03T06:20:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
