---
phase: 01-foundation-end-to-end-spike
plan: "04"
subsystem: plugins
tags: [plugin-protocols, entry-points, tdd, embedder, parser, vector-store, tool-agnostic]
status: complete

dependency_graph:
  requires:
    - 01-01 (walking skeleton, config/settings, pyproject.toml foundation)
  provides:
    - EmbedderPlugin, ParserPlugin, VectorStorePlugin Protocols (runtime_checkable)
    - ParsedDoc, Section, VectorPoint, Hit dataclasses
    - resolve(group, name) entry-point resolver
    - get_parser/get_embedder/get_vectorstore convenience functions
    - DoclingParser built-in (application/pdf, section-aware, citation fields)
    - SentenceTransformerEmbedder built-in (local, 384-dim MiniLM, zero AWS creds)
    - LiteLLMEmbedder built-in (litellm, 1536-dim, embedding_model alias)
    - QdrantVectorStore built-in (cosine, citation-payload upsert, ANN search)
  affects:
    - 01-05 (pipeline plan uses resolve/get_* to obtain plugins)
    - 01-06 (Dagster assets wrap the same pipeline functions)

tech_stack:
  added:
    - "entry-point groups: knowledge_lake.parsers/.embedders/.vectorstores"
    - "docling 2.108 (already installed) wired as DoclingParser"
    - "sentence-transformers 5.6 (already installed) wired as SentenceTransformerEmbedder"
    - "qdrant-client 1.18 (already installed) wired as QdrantVectorStore"
    - "litellm 1.90 (already installed) wired as LiteLLMEmbedder via embedding_model alias"
  patterns:
    - "typing.Protocol + @runtime_checkable for tool-agnostic seam (FOUND-08)"
    - "importlib.metadata.entry_points(group=) for config-keyed resolution (no pluggy)"
    - "Single resolver.resolve(group, name) function with LookupError naming group+name"
    - "Task alias only (embedding_model) in LiteLLMEmbedder — no provider model IDs"
    - "Citation payload: document/section_path/page/chunk_id on every VectorPoint/Hit"
    - "TDD: RED (test_plugin_resolver.py collected but failed) → GREEN (protocols+resolver implemented)"

key_files:
  created:
    - src/knowledge_lake/plugins/__init__.py
    - src/knowledge_lake/plugins/protocols.py (EmbedderPlugin, ParserPlugin, VectorStorePlugin, ParsedDoc, Section, VectorPoint, Hit)
    - src/knowledge_lake/plugins/resolver.py (resolve, get_parser, get_embedder, get_vectorstore)
    - src/knowledge_lake/plugins/builtin/__init__.py
    - src/knowledge_lake/plugins/builtin/docling_parser.py (DoclingParser)
    - src/knowledge_lake/plugins/builtin/st_embedder.py (SentenceTransformerEmbedder, LiteLLMEmbedder)
    - src/knowledge_lake/plugins/builtin/qdrant_store.py (QdrantVectorStore)
    - tests/unit/test_plugin_resolver.py (15 tests)
    - tests/unit/test_builtin_plugins.py (29 tests)
  modified:
    - pyproject.toml (3 entry-point groups + 4 built-in registrations)

decisions:
  - "plain config-keyed resolver (no pluggy) for Phase 1 — pluggy deferred to Phase 3 fallback chains"
  - "SentenceTransformerEmbedder uses all-MiniLM-L6-v2 (384-dim) as the zero-creds local default (D-13)"
  - "LiteLLMEmbedder dim=1536 (Amazon Titan Text Embeddings V2 default via Bedrock alias)"
  - "TDD RED/GREEN cycle for Task 1 (protocols+resolver); Task 2 implemented directly with test coverage"
  - "Qdrant upsert uses keyword-arg style (collection_name=) per qdrant-client 1.18 API"

metrics:
  duration: "~35 minutes"
  completed: "2026-07-02"
  tasks_completed: 2
  files_created: 9
  tests_passing: 61
---

# Phase 01 Plan 04: Plugin Protocols + Built-in Implementations Summary

One-liner: Tool-agnostic plugin seam with runtime_checkable Protocols, a config-keyed entry-point resolver, and three built-in implementations (DoclingParser, SentenceTransformerEmbedder/LiteLLMEmbedder, QdrantVectorStore) — swap any tool by changing one settings value, no core code edits (FOUND-08).

## What Was Built

### Task 1 — Plugin Protocols + config-keyed resolver (TDD, FOUND-08)

**RED phase:** `tests/unit/test_plugin_resolver.py` written with 15 tests covering:
- Protocol isinstance checks for all three Protocols (DummyEmbedder/Parser/Store)
- `resolve(group, name)` loads the right entry point and instantiates
- `LookupError` names both group and name when not found
- Swap-by-name proven: different name → different implementation, zero resolver edits
- `get_embedder/get_parser/get_vectorstore` read from `Settings.embedder/parser/vectorstore` keys
- Config change test: two Settings instances with different embedder keys return different types

**GREEN phase:**

`protocols.py` defines:
- `@runtime_checkable class EmbedderPlugin(Protocol)` — `name: str`, `dim: int`, `embed(texts) -> list[list[float]]`
- `@runtime_checkable class ParserPlugin(Protocol)` — `can_parse(mime_type) -> bool`, `parse(raw, mime_type) -> ParsedDoc`
- `@runtime_checkable class VectorStorePlugin(Protocol)` — `ensure_collection`, `upsert`, `search`
- `ParsedDoc`, `Section`, `VectorPoint`, `Hit` dataclasses with citation payload fields

`resolver.py` defines:
- `resolve(group, name)`: iterates `importlib.metadata.entry_points(group=group)`, matches `.name`, calls `.load()()`, raises `LookupError` with group+name in message
- `get_parser/get_embedder/get_vectorstore(settings)`: read the settings swap key and call `resolve()`

All 15 tests GREEN.

### Task 2 — Built-in implementations registered as entry points (D-11, D-13)

**DoclingParser** (`knowledge_lake.parsers` → `docling`):
- Wraps Docling 2.108 `DocumentConverter`
- `can_parse("application/pdf")` → True; all other MIME types → False (Phase 1 scope)
- `parse(bytes, mime_type)` writes to temp file, runs Docling, exports markdown
- `_extract_sections()` walks DocItem tree for heading/section_path/page_ref metadata (D-07)
- Citation fields flow to ParsedDoc.sections — each Section has `heading`, `section_path`, `page`, `text`

**SentenceTransformerEmbedder** (`knowledge_lake.embedders` → `local`):
- `name="local"`, `dim=384`, model: `all-MiniLM-L6-v2`
- Lazy model load on first `embed()` call, cached for instance lifetime
- Zero AWS credentials required (D-13 spike default)
- Returns `list[list[float]]` with len==384 per text

**LiteLLMEmbedder** (`knowledge_lake.embedders` → `litellm`):
- `name="litellm"`, `dim=1536`
- Calls `litellm.embedding(model="embedding_model", ...)` — task alias ONLY, no provider IDs
- Proxy URL from `KLAKE_LITELLM_URL` env var (defaults to http://localhost:4000)
- KLAKE_EMBEDDER=litellm is the pure config switch (ENRICH-06 seam)

**QdrantVectorStore** (`knowledge_lake.vectorstores` → `qdrant`):
- `ensure_collection(name, dim, distance="Cosine")` — idempotent via `collection_exists()` check
- `upsert(collection, points)` — maps `VectorPoint` to `PointStruct` preserving all payload fields
- `search(collection, query, top_k)` — uses `query_points()` API, returns `list[Hit]`
- Citation payload (document/section_path/page/chunk_id) preserved through upsert → search round-trip

**Entry-point registrations in pyproject.toml:**
```toml
[project.entry-points."knowledge_lake.parsers"]
docling = "knowledge_lake.plugins.builtin.docling_parser:DoclingParser"

[project.entry-points."knowledge_lake.embedders"]
local   = "knowledge_lake.plugins.builtin.st_embedder:SentenceTransformerEmbedder"
litellm = "knowledge_lake.plugins.builtin.st_embedder:LiteLLMEmbedder"

[project.entry-points."knowledge_lake.vectorstores"]
qdrant  = "knowledge_lake.plugins.builtin.qdrant_store:QdrantVectorStore"
```

All 29 built-in tests GREEN. Total unit suite: 61 tests passing.

## Acceptance Criteria Verification

| Criterion | Status |
|-----------|--------|
| Three Protocols exist with documented method signatures | PASS — EmbedderPlugin/ParserPlugin/VectorStorePlugin in protocols.py |
| Protocols are runtime_checkable | PASS — isinstance checks work in tests |
| resolve(group, name) loads over entry points | PASS — uses importlib.metadata.entry_points() |
| resolve raises LookupError naming group+name when absent | PASS — tested in test_resolve_raises_lookup_error_for_missing_name |
| get_embedder(settings) selects impl named by Settings.embedder | PASS — tested with dummy entry points |
| Swapping config name changes returned implementation | PASS — test_changing_embedder_config_changes_returned_plugin |
| Each built-in satisfies its Protocol via isinstance | PASS — 3 tests in TestProtocolStructure + 3 in TestBuiltinPlugins |
| Local embedder is default, needs zero AWS creds | PASS — SentenceTransformerEmbedder uses local model |
| LiteLLM embedder uses embedding_model alias, no provider IDs | PASS — test_uses_embedding_model_alias; no hardcoded IDs in source |
| Built-ins registered under three entry-point groups | PASS — TestEntryPointRegistrations (4 tests) |
| Qdrant payload carries citation fields | PASS — test_upsert_payload_carries_citation_fields |
| No pluggy import in plugins/ | PASS — verified by grep |
| No hardcoded provider model IDs in plugins/ | PASS — verified by grep + test_no_hardcoded_provider_model_ids_in_source |
| uv run pytest tests/unit/test_plugin_resolver.py tests/unit/test_builtin_plugins.py green | PASS — 44 tests passing |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Qdrant test using positional call_args[0][0] for keyword-only call**
- **Found during:** Task 2 (test_ensure_collection_calls_qdrant_client)
- **Issue:** `create_collection` in qdrant-client 1.18 is called with keyword args only (`collection_name=`). Test used `call_args[0][0]` (positional) which raised `IndexError`.
- **Fix:** Changed test to `call_args.kwargs.get("collection_name")`.
- **Files modified:** `tests/unit/test_builtin_plugins.py`
- **Commit:** included in 0fe50ff

### Known Non-Issue: Qdrant version warning

The qdrant-client 1.18 library emits a `UserWarning` when connecting to a Qdrant server 1.13.6 (the compose stack version). This is a version-check cosmetic warning — the API surface used (ensure_collection, upsert, query_points) is stable across both versions. The warning is suppressed in unit tests by replacing the client with a mock. No functional impact. Qdrant server version in compose.yml can be upgraded to v1.18.x in a later phase.

## Known Stubs

None. All three built-in implementations are functional:
- DoclingParser: runs real Docling PDF conversion when live (integration tests)
- SentenceTransformerEmbedder: loads and runs real all-MiniLM-L6-v2 model
- QdrantVectorStore: connects to real Qdrant and calls the actual API

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: task-alias-enforcement | plugins/builtin/st_embedder.py | LiteLLMEmbedder passes model='embedding_model' alias (T-01-06 mitigation confirmed). No provider model IDs in code. |

No additional new security surface beyond what was planned in the threat model.

T-01-05 (plugin resolver loads by name) is accepted per plan: names resolve only against entry points declared in this project's own pyproject in Phase 1.
T-01-06 (litellm alias mapping) mitigated: task alias only, provider IDs live in infra/litellm/config.yaml.
T-01-07 (Docling oversized PDF) acknowledged: Phase 1 uses one trusted HHS PDF; download size cap is enforced on the ingest path (01-05).

## Self-Check

PASSED

All 9 created files confirmed on disk. Both task commits verified in git log (05d1df7, 0fe50ff). 61 unit tests passing.
