# Phase 14: Tree Retrieval - Pattern Map

**Mapped:** 2026-07-13
**Files analyzed:** 8 (2 new, 6 modified)
**Analogs found:** 8 / 8 (every file mirrors an existing, tested pattern)

> Phase 14 is a near-1:1 pattern-mirroring phase. Every new/modified file has a
> direct in-repo analog with exact line numbers. The planner should treat each
> "copy from" excerpt below as the literal template — deviations are smells.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/knowledge_lake/pipeline/tree_search.py` (NEW) | pipeline / orchestrator | request-response (query→hits); parallel file-I/O | `pipeline/tree_index.py` (serialize) + `pipeline/search.py` (stage 1) + `pipeline/crawl.py` (async load) | composite exact |
| `src/knowledge_lake/plugins/builtin/pageindex_retriever.py` (NEW) | plugin (retriever builtin) | transform (tree→hits); opt-in event-driven LLM | `plugins/builtin/pageindex_indexer.py` | exact (sibling seam) |
| `src/knowledge_lake/plugins/protocols.py` (EDIT) | protocol/contract | — | `Hit` (L114) + `IndexerPlugin` (L665) in same file | exact (in-file) |
| `src/knowledge_lake/plugins/resolver.py` (EDIT) | resolver / factory | request-response | `get_indexer()` (L335) | exact |
| `src/knowledge_lake/config/settings.py` (EDIT) | config | — | `TreeSettings` (L199) + `indexer` key (L480) + validator (L513) | exact |
| `src/knowledge_lake/cli/app.py` (EDIT) | CLI (thin shim) | request-response | `cmd_search` (L632) | exact |
| `src/knowledge_lake/plugins/builtin/__init__.py` (EDIT) | docs/registration note | — | existing indexers note (L11) | exact |
| `pyproject.toml` (EDIT) | build config | — | `knowledge_lake.indexers` group (L110) | exact |

## Pattern Assignments

### `plugins/protocols.py` — EDIT (protocol, in-file)

**Analog:** `Hit` (L114-129) and `IndexerPlugin` (L665-699) in the same file.

**Add `citation_source` to `Hit`** — additive default, mirrors the `VectorPoint.sparse = None` back-compat convention (L102):
```python
# Source: protocols.py:114 (Hit) + :102 (sparse additive-default precedent)
@dataclass
class Hit:
    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)
    citation_source: str = "chunk"   # NEW (D-02): tree search sets "tree"
```

**Add `RetrieverPlugin` Protocol** — mirror `IndexerPlugin` (L665-699), same `@runtime_checkable` + `name: str` + single method shape. Consumes `TreeIndex`/`TreeNode` (L598/L633) as-is:
```python
# Source: protocols.py:665 IndexerPlugin template + CONTEXT D-03
@runtime_checkable
class RetrieverPlugin(Protocol):
    name: str
    def search(
        self, tree_index: TreeIndex, query: str, *,
        top_k: int = 5, mode: str = "heuristic", settings: Any | None = None,
    ) -> list[Hit]:
        ...
```
The `TreeIndex`/`TreeNode` field names (node_id, title, summary, page_start, page_end, level, section_path, children / parsed_artifact_id, source_id, roots, mode, schema_version, content_hash) are the exact keys the retriever reads and `_dict_to_tree` reconstructs.

---

### `plugins/resolver.py` — EDIT (resolver)

**Analog:** `get_indexer()` (L335-359), which uses `_resolve_with_kwargs` (L215-242).

**Core pattern** — copy `get_indexer` verbatim, rename to `get_retriever`, swap group + key:
```python
# Source: resolver.py:335 get_indexer
GROUP_RETRIEVERS = "knowledge_lake.retrievers"  # add near other GROUP_* constants

def get_retriever(settings: Settings) -> Any:
    name = settings.retriever
    kwargs = (
        {"litellm_url": settings.litellm_url, "litellm_api_key": settings.litellm_api_key}
        if name == "pageindex"
        else {}
    )
    return _resolve_with_kwargs(GROUP_RETRIEVERS, name, **kwargs)
```
`_resolve_with_kwargs` (L215) already raises `LookupError` on an unknown name — reuse unchanged.

---

### `config/settings.py` — EDIT (config)

**Analog:** `TreeSettings` (L199-220) submodel, `indexer: str = "pageindex"` swap key (L480), `_validate_swap_key` field-validator (L513), and how `tree`/`search` submodels are wired via `Field(default_factory=...)` (L471-496).

**New `TreeSearchSettings` submodel** — mirror `TreeSettings` shape (Literal mode, budget_usd, model_alias):
```python
# Source: settings.py:199 TreeSettings + :359 SearchSettings
class TreeSearchSettings(BaseModel):
    mode: Literal["heuristic", "llm"] = "heuristic"
    shortlist_k: int = 20
    max_docs: int = 3
    top_k: int = 5
    concurrency: int = 5
    budget_usd: float = 5.0
    model_alias: str = "cheap_model"   # A1: added beyond D-12 literal list — D-06 needs cheap_model
```

**Wire submodel + swap key** (mirror L477 / L480):
```python
tree_search: TreeSearchSettings = Field(default_factory=TreeSearchSettings)
retriever: str = "pageindex"   # Entry-point group knowledge_lake.retrievers (D-04)
```

**Add `retriever` to the validator tuple** (L513) — A2/ASVS V5, mirrors T-13-03:
```python
@field_validator("crawler", "discovery", "embedder", "indexer", "parser", "retriever", "vectorstore", mode="after")
```
Env override `KLAKE_TREE_SEARCH__*` / `KLAKE_RETRIEVER` resolves automatically via the existing `env_nested_delimiter='__'`.

---

### `pipeline/tree_search.py` — NEW (orchestrator)

**Analogs:** `search.py:search` (stage 1), `repo.py` helpers (stage-2 resolve/spend), `tree_index.py` (serialize inverse + budget gate + DFS), `crawl.py` (async-wrap-sync), `s3.py` (get_object).

**Stage-1 grouping** — call `search()` (search.py:35) unchanged with higher `top_k`, group by `payload.get("document")`:
```python
# Source: search.py:35 reuse (UNCHANGED) + ARCHITECTURE §4
hits = search(query, collection=collection, top_k=s.tree_search.shortlist_k, settings=s)
doc_scores: dict[str, float] = {}
for h in hits:
    doc = h.payload.get("document")            # Pitfall 2: .get, never []
    if not doc:
        continue
    doc_scores[doc] = max(doc_scores.get(doc, float("-inf")), h.score)  # max per doc (D-08)
top_docs = [d for d, _ in sorted(doc_scores.items(), key=lambda kv: (-kv[1], kv[0]))[: s.tree_search.max_docs]]
```

**Stage-2 tree resolution** — `get_child_artifact_by_type` (repo.py:765), skip-on-None (D-09):
```python
# Source: repo.py:765
with get_session() as session:
    artifact = registry_repo.get_child_artifact_by_type(session, parsed_id, "tree_index")
if artifact is None:
    log.info("tree_search.no_tree_index", parsed_artifact_id=parsed_id)  # skip, never fail
    continue
```

**Parallel S3 load** — mirror `crawl.py:354` `run_in_executor` + Semaphore; `s3.py:136 get_object` is sync. `tree_search()` stays sync and drives one `asyncio.run(...)`:
```python
# Source: crawl.py:354 run_in_executor precedent + s3.py:136 sync get_object
async def _load_all(keys: list[str], storage, concurrency: int) -> list[bytes | None]:
    sem = asyncio.Semaphore(concurrency)
    loop = asyncio.get_running_loop()
    async def _one(key: str):
        async with sem:
            try:
                return await loop.run_in_executor(None, storage.get_object, key)
            except Exception as exc:                 # missing/failed tree → skip (D-09)
                log.warning("tree_search.tree_load_failed", key=key, error=str(exc))
                return None
    return await asyncio.gather(*[_one(k) for k in keys])

raw = asyncio.run(_load_all(keys, storage, s.tree_search.concurrency))
# Comment: no nested asyncio.run — Phase-15 async callers must await _load_all directly (crawl.py:365 CR-02)
```

**`_dict_to_tree` inverse deserializer** — exact inverse of `tree_index.py:184 _tree_to_dict` and the top-level `tree_dict` at `tree_index.py:313`:
```python
# Source: tree_index.py:184 _tree_to_dict + :313 tree_dict wrapper
def _dict_to_tree(d: dict) -> TreeNode:
    return TreeNode(
        node_id=d["node_id"], title=d["title"], summary=d["summary"],
        page_start=d["page_start"], page_end=d["page_end"],
        level=d["level"], section_path=d["section_path"],
        children=[_dict_to_tree(c) for c in d.get("children", [])],
    )
def _dict_to_tree_index(d: dict) -> TreeIndex:
    return TreeIndex(
        parsed_artifact_id=d["parsed_artifact_id"], source_id=d["source_id"],
        roots=[_dict_to_tree(r) for r in d.get("roots", [])],
        mode=d.get("mode", "deterministic"), schema_version=d.get("schema_version", "1"),
        content_hash=d.get("content_hash", ""),
    )
```
Parse bytes with `orjson.loads` (tree_index.py serializes via `orjson.dumps`, L321).

---

### `plugins/builtin/pageindex_retriever.py` — NEW (retriever builtin)

**Analog:** `plugins/builtin/pageindex_indexer.py` (L1-70) — same constructor-injected LiteLLM URL (CR-03: no os.environ), same `name` class attr, same lazy-import of pipeline helpers.

**Class skeleton** (mirror pageindex_indexer.py:25-47):
```python
# Source: pageindex_indexer.py:25
class PageIndexRetriever:
    name: str = "pageindex"
    def __init__(self, litellm_url: str = "http://localhost:4000",
                 litellm_api_key: str = "sk-local-noauth") -> None:
        self._litellm_url = litellm_url        # reserved for LLM-nav mode (D-06)
        self._litellm_api_key = litellm_api_key
    def search(self, tree_index, query, *, top_k=5, mode="heuristic", settings=None): ...
```

**Heuristic DFS scoring** (D-05, pure Python, deterministic) — DFS mirrors `tree_index.py:381 _iter_nodes`; thread ancestor titles for `node_path`; stable tie-break `(-score, section_path)` (Pitfall 5):
```python
# Source: tree_index.py:381 _iter_nodes DFS + RESEARCH node_path example
def _dfs(node, ancestors, query_terms, out, parsed_artifact_id):
    path = ancestors + [node.title]
    score = _score_node(node, query_terms)   # keyword overlap over title+summary+section_path
    if score > 0:
        out.append(Hit(
            id=node.node_id, score=score, citation_source="tree",
            payload={"document": parsed_artifact_id, "node_id": node.node_id,
                     "section_path": node.section_path, "page_start": node.page_start,
                     "page_end": node.page_end, "node_path": " > ".join(path)},
        ))
    for child in node.children:
        _dfs(child, path, query_terms, out, parsed_artifact_id)
# Guard: if not tree_index.roots: return []  (Pitfall 6)
```

**LLM-nav mode** (D-06/D-07, opt-in, never raises) — see Shared Pattern "Budget-capped LLM call" below.

---

### `cli/app.py` — EDIT (thin CLI shim)

**Analog:** `cmd_search` (L632-701). New `cmd_tree_search` mirrors the `@app.command` + typer.Option shape, validates `--mode` against `{"heuristic","llm"}` (like L682-688 does for search modes), then delegates to `tree_search()` with zero logic duplication (D-13):
```python
# Source: cli/app.py:632 cmd_search template
@app.command(name="tree-search")
def cmd_tree_search(query: str = typer.Argument(...),
                    top_k: int = typer.Option(5, "--top-k", "-k"),
                    mode: str | None = typer.Option(None, "--mode", help="heuristic|llm")):
    VALID = {"heuristic", "llm"}
    if mode is not None and mode not in VALID:
        typer.echo(f"Error: --mode must be one of {sorted(VALID)}", err=True); raise typer.Exit(1)
    from knowledge_lake.pipeline.tree_search import tree_search
    hits = tree_search(query, top_k=top_k, mode=mode)
    # render hits (reuse cmd_search's per-hit echo loop)
```

---

### `pyproject.toml` + `plugins/builtin/__init__.py` — EDIT (entry-point registration)

**Analog:** `knowledge_lake.indexers` group (pyproject.toml:110-111) and the builtins docstring note (`__init__.py:11`).
```toml
# Source: pyproject.toml:110
[project.entry-points."knowledge_lake.retrievers"]
pageindex = "knowledge_lake.plugins.builtin.pageindex_retriever:PageIndexRetriever"
```
Add a matching line to `builtin/__init__.py`'s docstring (mirror L11). **Plan must include an editable reinstall (`uv pip install -e .` / `uv sync`) before the resolver conformance test** — a new entry-point group is invisible to `importlib.metadata` until dist-info is refreshed (Pitfall 1; Phase 13 hit this exact issue).

## Shared Patterns

### Budget-capped LLM call that never raises (LLM-nav, D-06/D-07)
**Source:** `tree_index.py:293` (budget gate) + `tree_index.py:388-418` (`_summarize_nodes_llm`) + `enrich.py:356-383` (spend-check → try/except degrade).
**Apply to:** `pageindex_retriever.py` LLM-nav mode only.
```python
# Source: tree_index.py:295 + enrich.py:356 — scope changed to "tree_search" (D-07, Pitfall 4)
with get_session() as session:
    current_spend = registry_repo.get_llm_spend(session, scope="tree_search")
    if current_spend >= settings.tree_search.budget_usd:
        log.warning("tree_search.budget_exceeded", current_spend=current_spend)
        return heuristic_hits              # degrade, never raise (D-06)

import litellm  # noqa: PLC0415 — lazy import (tree_index.py:398)
response = litellm.completion(
    model=f"openai/{settings.tree_search.model_alias}",   # cheap_model alias, NEVER provider ID
    messages=[{"role": "system", "content": _NAV_SYSTEM_PROMPT},
              {"role": "user", "content": node_summaries_blob}],
    api_base=settings.litellm_url, api_key=settings.litellm_api_key, temperature=0.0,
)
# validate with a bounded Pydantic model (mirror NodeSummaryResult, tree_index.py:78) BEFORE building Hits
# record spend: registry_repo.record_llm_spend(session, scope="tree_search", cost_usd=cost)  (repo.py:803)
```
Wrap the whole LLM path in `try/except Exception` → degrade to heuristic (mirror enrich.py:377). Bound node text sent to LLM (mirror `_NODE_EXCERPT_CHARS`, tree_index.py:403) — ASVS V5 prompt-injection surface.

### Spend accounting
**Source:** `repo.py:793 get_llm_spend` / `repo.py:803 record_llm_spend` (UNIQUE(scope) get-or-create).
**Apply to:** LLM-nav mode with `scope="tree_search"` (distinct from Phase-13's `tree_index` scope and from `global`).

### Structured logging
**Source:** codebase-wide `structlog` (every pipeline module). Use event-name-first keys: `log.warning("tree_search.tree_load_failed", key=..., error=...)`.

### Additive-default back-compat
**Source:** `VectorPoint.sparse = None` (protocols.py:102). **Apply to:** `Hit.citation_source="chunk"`, `TreeSearchSettings`, `retriever="pageindex"` — no existing caller changes; chunk `search()` path stays byte-identical.

## No Analog Found

None. Every file has a direct in-repo template.

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none) | — | — | Phase 14 is pure composition; heuristic scoring formula + LLM-nav prompt are the only novel logic, both small and bounded (Claude's discretion). |

## Metadata

**Analog search scope:** `src/knowledge_lake/{pipeline,plugins,plugins/builtin,config,cli,registry,storage}/`, `pyproject.toml`
**Files scanned:** protocols.py, resolver.py, tree_index.py, enrich.py, search.py, crawl.py, settings.py, cli/app.py, repo.py, s3.py, pageindex_indexer.py, builtin/__init__.py, pyproject.toml
**Pattern extraction date:** 2026-07-13
