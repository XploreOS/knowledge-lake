# Phase 10: Hybrid Retrieval - Pattern Map

**Mapped:** 2026-07-10
**Files analyzed:** 15 (7 modified source, 1 config, 1 dep manifest, 6 new tests) + 1 optional new module
**Analogs found:** 15 / 15 (every file has an in-repo analog — this is an extend/refactor phase, not greenfield)

All excerpts below are verbatim from the live codebase with real line numbers. Planner: reference the analog file + lines directly in each plan's action section.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/knowledge_lake/plugins/builtin/qdrant_store.py` (MODIFY) | vectorstore plugin | request-response + batch | itself (extend in place) | self / exact |
| `src/knowledge_lake/plugins/builtin/sparse_embedder.py` (NEW, optional D-01) | embedder utility | transform | `plugins/builtin/` embedder builtins + `sparse_doc/sparse_query` in RESEARCH §Code Examples (b) | role-match |
| `src/knowledge_lake/pipeline/search.py` (MODIFY) | pipeline/service | request-response | itself (thread `mode`/`sparse_query`) | self / exact |
| `src/knowledge_lake/pipeline/index.py` (MODIFY) | pipeline/service | batch (upsert) | itself (`index()`, `reindex_collection()`) | self / exact |
| `src/knowledge_lake/plugins/protocols.py` (MODIFY) | model / contract | — | `VectorPoint` (l.82), `VectorStorePlugin.search` (l.314), `CrawlPageResult.http_status_code` (l.451, additive-default precedent) | self / exact |
| `src/knowledge_lake/config/settings.py` (MODIFY) | config | — | `IndexSettings` (l.282) + `search: SearchSettings` field on `Settings` | role-match (exact pattern) |
| `src/knowledge_lake/cli/app.py` (MODIFY) | CLI | request-response | `cmd_search` (l.671), `cmd_reindex` (l.757) | self / exact |
| `src/knowledge_lake/api/app.py` (MODIFY) | route | request-response | `search_endpoint` (l.155) | self / exact |
| `src/knowledge_lake/api/schemas.py` (MODIFY) | model | — | `SearchParams` (l.30), `SearchHit` (l.57) | self / exact |
| `pyproject.toml` (MODIFY) | config | — | existing `qdrant-client==1.18.0` pin (l.19) | self |
| `tests/unit/test_qdrant_hybrid.py` (NEW) | test | — | `tests/unit/test_qdrant_payload_indexes.py` (mock_store `__new__` fixture) | exact |
| `tests/unit/test_settings_search.py` (NEW) | test | — | `tests/unit/test_settings.py` (`Settings(_env_file=None)`) | exact |
| `tests/unit/test_search_mode.py` (NEW) | test | — | `tests/unit/test_search_filters.py` (fake_embedder/fake_vstore monkeypatch) | exact |
| `tests/unit/test_cli_search_mode.py` (NEW) | test | — | `tests/unit/test_cli_init_index.py` + `test_search_filters.py` | role-match |
| `tests/unit/test_api_search_mode.py` (NEW) | test | — | `test_search_filters.py` (TestClient style API tests) | role-match |
| `tests/integration/test_qdrant_hybrid_migration.py` (NEW) | test | — | `tests/integration/test_qdrant_alias_reindex.py` | exact |

## Pattern Assignments

### `plugins/builtin/qdrant_store.py` (vectorstore plugin) — MODIFY

**Analog:** itself. This is the largest change surface. Six methods change; two helpers are added.

**Model-import pattern to extend** (`__init__`, lines 53-61). New qdrant models (`SparseVectorParams`, `SparseIndexParams`, `Modifier`, `SparseVector`, `Prefetch`, `FusionQuery`, `Fusion`) follow this same lazy-import-and-cache convention, OR are imported inline inside methods as the file already does for alias ops (lines 131, 156, 263-268):
```python
def __init__(self, qdrant_url: str = "http://localhost:6333") -> None:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams
    self._Distance = Distance
    self._PointStruct = PointStruct
    self._VectorParams = VectorParams
    self._client = QdrantClient(url=qdrant_url)
```

**Create-path to convert to named+sparse (D-05, D-13).** THREE create sites currently hard-code an unnamed `vectors_config`. All move to `vectors_config={"dense": ...}` + `sparse_vectors_config={"sparse": SparseVectorParams(modifier=Modifier.IDF)}`:
- `ensure_collection` (lines 97-100)
- `ensure_aliased_collection` (lines 126-129)
- `reindex` (lines 255-258)

Current shape (repeated at all three):
```python
self._client.create_collection(
    collection_name=physical,
    vectors_config=self._VectorParams(size=dim, distance=dist),
)
```
Target (RESEARCH §Code Examples (a)): add `sparse_vectors_config={"sparse": SparseVectorParams(modifier=Modifier.IDF)}` and wrap dense as `{"dense": VectorParams(...)}`. Keep the existing `self.ensure_payload_indexes(physical)` call that already follows each create (lines 101, 140, 261) — this is D-14 free.

**`get_collection_dim` — must branch on named shape** (lines 293-296). Current:
```python
def get_collection_dim(self, alias: str) -> int:
    info = self._client.get_collection(alias)
    return info.config.params.vectors.size
```
Target (RESEARCH Pitfall 2): `isinstance(vectors, dict)` → `vectors["dense"].size` else `vectors.size`.

**`upsert` — vector-shape branch for back-compat** (lines 298-322). Current builds bare `vector=p.vector`. Named collections need `vector={"dense": v, "sparse": SparseVector(...)}`; legacy unnamed collections keep bare `vector=v` (RESEARCH Pitfall 1). Add a cached `_is_named(collection)` helper reading `get_collection(...).config.params.vectors` (`dict` ⇒ named).

**`reindex` — insert the parity gate** (lines 260-283). The gate goes BETWEEN `upsert_fn`/`ensure_payload_indexes` (lines 260-261) and the `update_collection_aliases` call (lines 281-283), so a mismatch raises before the alias ops list is applied (RESEARCH Pitfall 5, D-06). Skip when `old_physical is None` (line 271 already tests this). Use `self._client.count(name, exact=True)`.
```python
upsert_fn(next_physical)
self.ensure_payload_indexes(next_physical)
# ← PARITY GATE HERE (D-06): if old_physical and count(old)!=count(new): raise, do NOT swap
change_aliases_operations: list[Any] = []
if old_physical is not None:
    change_aliases_operations.append(
        DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=alias)))
...
self._client.update_collection_aliases(change_aliases_operations=change_aliases_operations)
```

**`search` — add `mode`/`sparse_query`, prefetch+RRF, fail-loud** (lines 324-365). Current single `query_points`:
```python
def search(self, collection, query, top_k, query_filter=None) -> list[Hit]:
    result = self._client.query_points(
        collection_name=collection, query=query, limit=top_k, query_filter=query_filter,
    )
    hits = [Hit(id=str(s.id), score=float(s.score), payload=dict(s.payload or {}))
            for s in result.points]
    return hits
```
Target signature (keyword-only, back-compat): `search(self, collection, query, top_k, query_filter=None, *, mode="dense", sparse_query=None, offset=0)`. Branch per RESEARCH §Code Examples (d)/(e): hybrid = two `Prefetch(..., using="dense"/"sparse", filter=query_filter, limit=top_k+offset)` + `query=FusionQuery(fusion=Fusion.RRF)`; dense = `using="dense"` (named) or bare (legacy); sparse = `SparseVector` + `using="sparse"`. Fail-loud probe (D-10, §Code Examples (g)) runs BEFORE querying when `mode in ("hybrid","sparse")`. Note `Prefetch`'s filter field is named `filter`, top-level is `query_filter`. Hit-construction loop (lines 355-362) is reused verbatim.

**Server preflight helper (D-07, §Code Examples (f)):** new method using `self._client.info().version` + `packaging.version.Version`, gating migration and hybrid queries.

---

### `pipeline/search.py` (pipeline/service) — MODIFY

**Analog:** itself. The filter-builder block (lines 104-122) is reused VERBATIM across all modes (D-14) — do not touch it.

**Signature extension (additive, back-compat)** — mirror how filter kwargs were added at lines 34-47. Add `mode: Optional[str] = None` (defaults to `settings.search.mode` after `s = settings or get_settings()` at line 81) and build `sparse_query` when `mode in ("hybrid","sparse")` via the fastembed path (D-03). Then thread to the store:
```python
# current (line 125):
hits = vstore.search(collection, query_vector, top_k=top_k, query_filter=query_filter)
# target: add mode=mode, sparse_query=sparse_query (keyword-only)
```
The qdrant model imports already live at line 25 (`FieldCondition, Filter, MatchAny, MatchValue, Range`) — the module already accepts coupling to the Qdrant filter shape (docstring lines 12-15).

---

### `pipeline/index.py` (pipeline/service) — MODIFY

**Analog:** itself.

**`index()` upsert path** (VectorPoint build, lines 148-182): each `VectorPoint` gains a synthesized `sparse` value. The payload dict already carries `payload["text"]` at line 158 — this IS the re-embed source the migration reads (RESEARCH Runtime State Inventory). No new registry join needed.

**`reindex_collection()`** (lines 189-238) is the migration driver. Current swaps in `_copy_fn` (lines 213-214) which calls `copy_all_points`. The hybrid migration swaps `_copy_fn` → a `re_embed_fn` (RESEARCH §Code Examples (h)) that scrolls old physical (`with_vectors=True, with_payload=True`), reuses the scrolled dense vector, synthesizes sparse from `payload["text"]`, and upserts named points. `get_collection_dim` call at line 211 works once the store-side fix (Pitfall 2) lands. Registry re-registration block (lines 219-226) is unchanged. Add server preflight (D-07) before `vstore.reindex(...)` at line 217.

**Session-boundary rule (Phase 9):** the recommended re-embed reads `payload["text"]` from the Qdrant scroll, so NO `get_session()` block is needed for text (research simplification). Keep the existing registry `get_session()` block (lines 219-225) as-is.

---

### `plugins/protocols.py` (model / contract) — MODIFY

**Analog:** itself. The additive-default precedent is `CrawlPageResult.http_status_code` (lines 451-458): a new optional field defaulting to `None` "so all existing constructions remain valid."

**`VectorPoint`** (lines 82-101): add `sparse: Optional[Any] = None` (default None → back-compat, Claude's discretion note in CONTEXT).
```python
@dataclass
class VectorPoint:
    id: str
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)
    # ADD: sparse: Optional[Any] = None
```

**`VectorStorePlugin.search`** (lines 314-336): add keyword-only `mode="dense"`, `sparse_query=None` to the Protocol signature, matching the concrete impl. Update the docstring like the existing one.

---

### `config/settings.py` (config) — MODIFY

**Analog:** `IndexSettings` (lines 282-295) — copy this nested-`BaseModel` pattern exactly.
```python
class IndexSettings(BaseModel):
    """Vector index / alias configuration (INDEX-02, D-06).
    Nested under Settings as settings.index. Environment variable pattern:
    KLAKE_INDEX__COLLECTION_ALIAS, etc.
    """
    collection_alias: str = "klake_chunks"
    keep_old_collections: bool = True
```
Target `SearchSettings` (D-08): `mode: Literal["hybrid","dense","sparse"] = "hybrid"`, docstring env `KLAKE_SEARCH__MODE`. Then add `search: SearchSettings = SearchSettings()` field on `Settings` (near line 302, mirroring how `index`/`storage`/`domain` nested fields attach). The `env_nested_delimiter="__"` config already present (line 316) makes `KLAKE_SEARCH__MODE` resolve with no custom parsing.

---

### `cli/app.py` (CLI) — MODIFY

**Analog:** `cmd_search` (lines 671-726). Add a `--mode` option mirroring the existing `typer.Option` filter flags (lines 678-699) and thread it into the `search(...)` call (lines 715-726):
```python
domain: Optional[str] = typer.Option(None, "--domain", help="Filter results to this domain."),
# ADD e.g.:
# mode: Optional[str] = typer.Option(None, "--mode", help="Search mode: hybrid|dense|sparse."),
```
For the migration surface (D-04, Claude's discretion), `cmd_reindex` (lines 757-778) is the analog — add a `--hybrid` flag that swaps the driver to the re-embed path; its `try/except (ValueError, LookupError)` + `typer.Exit(code=1)` error style (lines 771-778) is the pattern for surfacing the server-preflight abort.

---

### `api/app.py` + `api/schemas.py` (route + model) — MODIFY

**Route analog:** `search_endpoint` (app.py lines 155-198). Add a `mode: Optional[str] = Query(default=None, ...)` param mirroring the existing `Query(...)` filter declarations (lines 167-197), then pass `mode=mode` into the delegated `search(...)` call (app.py line 258). Reuse the existing validation style (lines 235-242) — invalid `mode` values are rejected by the `Literal` at the pydantic/enum boundary (Security Domain V5), not at the store.

**Schema analog:** `SearchParams` (schemas.py lines 30-52) — add a bounded `mode` field. The bounded-enum precedent is `ExportRequest.kind` (`pattern=r"^(rag-corpus|pretrain|finetune)$"`, lines 168-172) and `GenerateDatasetRequest.kind` (line 560). `SearchHit` (lines 57-112) needs no change unless a mode echo is desired.

---

### `pyproject.toml` — MODIFY

Add `fastembed>=0.8,<0.9` adjacent to `qdrant-client==1.18.0` (line 19) and `sentence-transformers==5.6.0` (line 18). This is qdrant-client's own declared extra (RESEARCH §Standard Stack). Executor: `checkpoint:human-verify` after `uv add` (RESEARCH Open Question 2) — first-use downloads the `Qdrant/bm25` ONNX model.

## Shared Patterns

### Additive / back-compat signatures
**Source:** `plugins/protocols.py:451` (`CrawlPageResult.http_status_code = None`), `pipeline/search.py:34-47` (filter kwargs), `test_search_filters.py:180` (`test_backward_compatible_no_new_kwargs`).
**Apply to:** every signature touched — `VectorPoint.sparse=None`, `VectorStorePlugin.search(*, mode="dense", sparse_query=None)`, `pipeline.search(mode=None)`, CLI `--mode`, API `?mode=`. New kwargs default to today's behavior so existing callers and pre-migration collections keep working.
```python
http_status_code: int | None = None
"""...Defaults to None so all existing CrawlPageResult constructions remain valid..."""
```

### Nested settings via `KLAKE_*__*`
**Source:** `config/settings.py:282` (`IndexSettings`) + `model_config` (lines 314-320).
**Apply to:** `SearchSettings`. No custom env parsing — `env_nested_delimiter="__"` handles `KLAKE_SEARCH__MODE`.

### Alias-swap reindex + keep-old rollback
**Source:** `qdrant_store.py:235` (`reindex`), `index.py:189` (`reindex_collection`), `settings.py:293` (`keep_old_collections=True`).
**Apply to:** the live migration. Only three deltas vs today: named create-config, re-embed `upsert_fn`, parity gate before the alias op. The old collection is retained for rollback.

### Filter builder reused verbatim across modes
**Source:** `pipeline/search.py:104-122`.
**Apply to:** dense, sparse, AND both hybrid prefetch branches + top-level (D-14). The same `Filter` object attaches to each `Prefetch(filter=...)` and the top-level `query_filter=...`.

### Mock-client store tests (`__new__` bypass)
**Source:** `tests/unit/test_qdrant_payload_indexes.py:28-41`.
**Apply to:** `test_qdrant_hybrid.py` — build `QdrantVectorStore.__new__(QdrantVectorStore)`, assign `MagicMock()` to `_client` and the cached model attrs; assert on `_client.create_collection` / `query_points` call kwargs (named config shape, prefetch limits == top_k+offset, `Fusion.RRF`, preflight raise, sparse-presence raise).
```python
store = QdrantVectorStore.__new__(QdrantVectorStore)
store._client = MagicMock()
store._Distance = MagicMock()
store._PointStruct = MagicMock()
store._VectorParams = MagicMock()
```

### Pipeline-search unit tests (monkeypatch fixtures)
**Source:** `tests/unit/test_search_filters.py:19-32`.
**Apply to:** `test_search_mode.py` (fail-loud, mode threading), `test_cli_search_mode.py`, `test_api_search_mode.py`. Monkeypatch `get_embedder`/`get_vectorstore` on `search_module`; assert on `fake_vstore.search.call_args.kwargs` (now including `mode` / `sparse_query`). Extend this file per D-14 to assert the filter attaches on each prefetch branch.
```python
@pytest.fixture()
def fake_vstore(monkeypatch):
    vstore = MagicMock()
    vstore.search.return_value = []
    monkeypatch.setattr(search_module, "get_vectorstore", lambda _s: vstore)
    return vstore
```

### Settings env-resolution tests
**Source:** `tests/unit/test_settings.py:21-58` (`Settings(_env_file=None)`).
**Apply to:** `test_settings_search.py` — assert `Settings(_env_file=None).search.mode == "hybrid"` default and `KLAKE_SEARCH__MODE=dense` override via `patch.dict(os.environ, ...)`.

### Live-Qdrant integration tests
**Source:** `tests/integration/test_qdrant_alias_reindex.py` — `pytestmark = pytest.mark.integration` (line 25), `store` fixture from `get_settings().qdrant_url` (lines 28-31), `alias` fixture with teardown cleanup of created physicals (lines 34-45).
**Apply to:** `test_qdrant_hybrid_migration.py` — reuse the fixtures wholesale; add asserts for: re-embed parity (count old==new), all migrated points have a `"sparse"` vector (scroll `with_vectors=True`), `Modifier.IDF` present in `get_collection(...).config.params.sparse_vectors`, payload-index survival, dense-on-both-shapes, real RRF ordering.
```python
pytestmark = pytest.mark.integration

@pytest.fixture
def store() -> QdrantVectorStore:
    return QdrantVectorStore(qdrant_url=get_settings().qdrant_url)
```

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none) | — | — | Every file has a strong in-repo analog. The single genuinely-new symbol is the fastembed BM25 wrapper (RESEARCH §Code Examples (b)); if placed in `plugins/builtin/sparse_embedder.py` it has no exact structural analog, but it is ~15 lines of the verified research snippet and follows the `plugins/builtin/` embedder-builtin convention. |

## Metadata

**Analog search scope:** `src/knowledge_lake/{plugins/builtin,plugins,pipeline,config,cli,api}/`, `tests/unit/`, `tests/integration/`
**Files scanned:** 12 source/test files read in full or targeted ranges (qdrant_store.py, search.py, index.py, protocols.py, settings.py §282-349, cli/app.py §660-779, api/app.py §140-258, api/schemas.py, test_search_filters.py, test_qdrant_alias_reindex.py, test_settings.py, test_qdrant_payload_indexes.py)
**Pattern extraction date:** 2026-07-10
