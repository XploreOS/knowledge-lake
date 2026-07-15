# Phase 13: Tree Index Foundation - Research

**Researched:** 2026-07-13
**Domain:** Data pipeline — hierarchical tree-index generation as a new silver-zone artifact type
**Confidence:** HIGH (grounded in direct reads of shipped v2.0 source; every target cites a real file:function)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Add `TreeNode` and `TreeIndex` dataclasses to `src/knowledge_lake/plugins/protocols.py`, alongside `Section`, `ParsedDoc`, `VectorPoint`, `Hit`. Shared contract defined/frozen **before** builder or plugin implementation.
- **D-02:** `TreeNode` fields: `node_id`, `title`, `summary`, `page_start`, `page_end`, `level` (heading depth), `section_path`, `children: list[TreeNode]`. `TreeIndex` wrapper: `doc_id`/`parsed_artifact_id`, `source_id`, `roots: list[TreeNode]`, `mode` (`deterministic`|`llm`), `schema_version`, `content_hash`. Persisted as JSON.
- **D-03:** Deterministic tree built directly from `ParsedDoc.sections` — nest by `section_path` depth / heading `level`, one node per section, summary = heading text, `page_start`/`page_end` from each section's `page_ref`. No PageIndex dep, no LLM, zero cost. Reuses in-memory `ParsedDoc`.
- **D-04:** PageIndex (`0.3.0.dev3`) used **only** inside the LLM-mode builtin indexer, behind the `IndexerPlugin` seam — never in deterministic mode. Isolates the pre-release; vendoring fallback (6 files) validated at execution if the pin breaks.
- **D-05:** Add a `runtime_checkable` `IndexerPlugin` Protocol to `protocols.py`; register the builtin via existing entry-point / `resolver.py` + `builtin/__init__.py` mechanism (same pattern as `docling_parser`, `qdrant_store`). Satisfies FOUND-08.
- **D-06:** Tree artifact `content_hash` = `sha256(parsed_doc.content_hash + mode + tree_schema_version)`. No-op mirrors `chunk.py`: `registry_repo.get_artifact_by_hash(session, content_hash, "tree_index")`. Mode is part of the hash.
- **D-07:** Store at `tree_index/{domain}/{source_id}/{content_hash}.json` in the **silver zone**, artifact_type = `tree_index`, lineage parent = `parsed_document`. Mirrors `chunk.py`'s `_CHUNK_PREFIX` convention. Raw zone untouched.
- **D-08:** Add `TreeSettings` submodel to `config/settings.py` (mirrors `EnrichSettings`): `mode: Literal["deterministic","llm"] = "deterministic"`, `budget_usd: float = 5.0`, LLM routed through **`cheap_model`** alias. Env override `KLAKE_TREE__MODE`.
- **D-09:** LLM mode reuses `enrich.py` budget pattern verbatim: cache-check → budget-check (`get_llm_spend(session, scope="global")` vs `tree.budget_usd`) → `litellm.completion()` → validate → registry-write. Never raises out of budget/LLM failure — returns a status dict (`status: skipped_budget_exceeded`), like `enrich_document`.
- **D-10:** Primary surface is the Dagster `tree_index_document` asset (TREE-05). A thin `klake tree-index <parsed_artifact_id>` CLI wrapper is nice-to-have; asset + CLI are thin shells over one `tree_index()` function.
- **D-11:** Sub-agent executors run on `sonnet` (`model_overrides.gsd-executor: "sonnet"` — confirmed present in `.planning/config.json`).

### Claude's Discretion
- Exact `node_id` scheme (`section_path`-derived vs sequential), JSON serialization helper choice, and whether `schema_version` starts at `"1"` or `"1.0.0"` — planner/executor's call, provided the D-01/D-02 contract stays stable and documented.

### Deferred Ideas (OUT OF SCOPE)
- Tree schema versioning + migration (TREE-06) → v2.6+. Write `schema_version` now as an anchor; no migration logic this phase.
- PageIndex File System / corpus-level meta-tree (TREE-07) → v2.6+.
- Tree *retrieval* / traversal → Phase 14. Do NOT build search here.
- RAPTOR-style bottom-up construction → v2.6+.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TREE-01 | Generate hierarchical tree index (JSON) from any parsed document's sections, stored as a silver-zone artifact with full lineage | Build from `ParsedDoc.sections` (§Schema Contract); persist + register via `create_tree_index_artifact` mirroring `create_chunk_artifact` (`chunk.py:352`); parent = `parsed_document`; no Alembic (§Don't Hand-Roll) |
| TREE-02 | Tree generation skipped when content hash matches an existing tree artifact (no redundant LLM calls) | `get_artifact_by_hash(session, content_hash, "tree_index")` no-op branch, verbatim from `chunk.py:321` / `enrich.py:347` (§Pattern: content-hash no-op) |
| TREE-03 | Each node carries title, summary, page range, child nodes; deterministic mode uses heading text as summary | `TreeNode` schema (D-02); deterministic builder derives fields from `Section` (§Critical Finding 1 — level/page_end must be DERIVED) |
| TREE-04 | LLM node summaries as opt-in mode via config flag, gated by LlmSpend budget cap | `TreeSettings.mode="llm"` + `enrich.py` budget flow verbatim (§Pattern: LLM budget flow); routes `cheap_model` alias |
| TREE-05 | Runs as a Dagster asset parallel to chunking (fan-out from clean_document) | New `tree_index_document` asset, `clean_document: dict` input, `group_name="pipeline"`, `_PIPELINE_RETRY`; wire into `definitions.py` (§Dagster fan-out) |
</phase_requirements>

## Summary

Phase 13 is a **near-mechanical clone** of two shipped pipeline stages. The deterministic tree builder mirrors `pipeline/chunk.py` (content-hash no-op → S3 write → registry artifact); the opt-in LLM-summary mode mirrors `pipeline/enrich.py` (cache → budget-check → `litellm.completion(cheap_model)` → validate → write, never raising on budget). The Dagster asset is a third parallel branch off `clean_document`, structurally identical to the existing `chunk_document` / `enrich_document` / `curate_document_asset` fan-out. There are **zero Alembic migrations** — `Artifact.artifact_type` is a free-form `String`, and `metadata_` is JSONB. The milestone research (`.planning/research/*`) is HIGH confidence and confirmed against source; this phase document translates it into exact file:function edit targets.

Two findings require planner attention before task-writing. **(1) The `Section` dataclass has NO `level` field and NO `page_end`** — it carries only `heading`, `section_path` (a string like `"§3.2"`), `page` (a single begin-page int), `text`, `is_table`. The `TreeNode.level` and `TreeNode.page_end` fields (D-02) must therefore be **derived**: `level` from `section_path` structure, `page_end` from the next section's `page` (or the document's last page for the final node). **(2) D-04 locks PageIndex as the LLM-mode builtin, but PageIndex builds its *own* tree by re-reading the document** (PDF or markdown) via internal LLM calls — it does **not** consume pre-parsed `Section` objects, and its multi-call `index()` does not expose per-call cost for clean `enrich.py`-style budget gating. This is in tension with D-03 ("no re-parse, build from sections") and D-09 ("enrich.py budget pattern verbatim, one `litellm.completion`"). See Open Questions #1 — recommended reconciliation: the `pageindex_indexer` builtin builds the deterministic skeleton from sections (D-03) and generates per-node summaries with a direct `litellm.completion` call (D-09); actual `pageindex` library import is optional/deferred behind the seam.

**Primary recommendation:** Define the `TreeNode`/`TreeIndex`/`IndexerPlugin` contract in `protocols.py` FIRST (Pitfall 4), then build `pipeline/tree_index.py` as a `chunk.py` clone for the deterministic path, add the `enrich.py` budget flow for LLM mode, register a `pageindex_indexer` builtin under a new `knowledge_lake.indexers` entry-point group, add `"tree_index": "idx"` to `ids.py._PREFIX`, add a `create_tree_index_artifact` repo helper, add `TreeSettings`, and wire a `tree_index_document` asset into `assets.py` + `definitions.py`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Tree schema contract (`TreeNode`/`TreeIndex`) | Plugin seam (`protocols.py`) | — | Shared dataclass contract, exactly where `Section`/`ParsedDoc`/`Hit` live; indexer↔retriever (Phase 14) must not couple on ad-hoc dicts |
| Deterministic tree construction | Pipeline (`pipeline/tree_index.py`) | — | Business logic; free heuristic from in-memory `ParsedDoc.sections` (deterministic-first constraint) |
| LLM summary generation | Pipeline (`pipeline/tree_index.py`) + LLM Gateway (LiteLLM) | Plugin (`pageindex_indexer` builtin) | Budget-gated `litellm.completion(cheap_model)`; all model calls through LiteLLM (CLAUDE.md) |
| Tree persistence + dedup | Registry (Postgres) + Storage (S3 silver zone) | — | `create_tree_index_artifact` + `get_artifact_by_hash`; content-addressed JSON, lineage parent = `parsed_document` |
| Config surface | Config (`config/settings.py`) | — | `TreeSettings` submodel, `KLAKE_TREE__*` env resolution |
| Orchestration | Dagster (`dagster_defs/`) | Pipeline | Thin asset shell over `tree_index()`; fan-out off `clean_document` |
| Plugin swap key | Config + Resolver | — | `settings.indexer` → `knowledge_lake.indexers` entry-point group |

## Standard Stack

This phase adds **no new required runtime dependency** for the locked MVP path (deterministic mode + direct-litellm LLM summaries reuse libraries already installed). `pageindex` is the only *candidate* net-new dep and its use is contested (Open Question #1).

### Core (already installed — verified in `pyproject.toml`)
| Library | Version (pinned) | Purpose | Why Standard |
|---------|------------------|---------|--------------|
| litellm | 1.92.0 | LLM gateway for LLM-mode node summaries | CLAUDE.md constraint: all model calls via LiteLLM; `enrich.py` already uses `litellm.completion(model="openai/{alias}", api_base=...)` [VERIFIED: pyproject.toml + enrich.py:227] |
| pydantic | 2.13.4 | Validate LLM summary JSON output (bound attacker-influenced text) | `EnrichmentResult` precedent (`enrich.py:82`) [VERIFIED: pyproject.toml] |
| sqlalchemy | 2.0.51 | Registry writes (`create_tree_index_artifact`) | Existing ORM; no raw SQL [VERIFIED: pyproject.toml] |
| structlog | 26.x | Structured logging | Every stage logs `stage.start`/`stage.complete` [VERIFIED: pyproject.toml] |
| orjson | 3.11.9 | Fast JSON serialization of the tree | Already in stack; Pitfall "Performance Traps" recommends orjson over stdlib json for tree JSON [VERIFIED: pyproject.toml] |
| tenacity | 9.1.4 | Retry the LLM call (LLM mode) | `enrich.py:195` `@retry(stop_after_attempt(3), wait_exponential)` [VERIFIED: pyproject.toml] |

### Candidate (contested — see Open Question #1)
| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| pageindex | ==0.3.0.dev3 | LLM-guided tree construction (D-04) | `[ASSUMED]` — pre-release; builds its own tree by re-reading the doc, does not consume `Section` objects. Recommend deferring actual import; satisfy D-04/D-05 with a builtin *named* `pageindex_indexer` that reuses the deterministic skeleton + direct litellm summaries. If adopted, MUST add `pageindex==0.3.0.dev3`, `PyPDF2==3.0.1`, `pymupdf>=1.26.4,<2` and `[tool.uv] prerelease = "if-necessary-or-explicit"` per `.planning/research/STACK.md`. Gate each install behind `checkpoint:human-verify`. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Direct `litellm.completion` per node for summaries (D-09) | `pageindex.PageIndexClient.index()` full tree build | PageIndex re-reads the PDF/markdown and builds a *different* tree than the deterministic one, bypassing `ParsedDoc.sections` (violates D-03 "no re-parse") and cannot be budget-gated per `enrich.py`'s single-call model. Coarse pre-check + post-hoc spend only. |
| New `knowledge_lake.indexers` entry-point group | Reuse an existing group | Indexer is a genuinely new swappable capability (FOUND-08); mirrors the 5 existing groups exactly. |

**Installation:** No `pip install` required for the recommended MVP path — all libraries already pinned in `pyproject.toml`. (If Open Question #1 resolves toward real PageIndex use, see STACK.md §"Version Pinning Strategy".)

## Package Legitimacy Audit

> The recommended MVP path installs **no new package**. The audit below covers only the contested candidate.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| pageindex | PyPI | pre-release 0.3.0.dev3 (published ~2026-07-10 per STACK.md) | low (pre-release) | github.com/VectifyAI/PageIndex (MIT, ~34k★) | SUS (pre-release / low downloads) | Flagged — planner MUST add `checkpoint:human-verify` before any install; recommended DEFERRED for this phase |
| PyPDF2 | PyPI | final release 3.0.1 (Dec 2022, deprecated) | high | github.com/py-pdf/pypdf | SUS (deprecated) | Only if pageindex adopted; transitive, isolate behind seam |
| pymupdf | PyPI | active | high | github.com/pymupdf/PyMuPDF | OK | Only if pageindex adopted |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** `pageindex`, `PyPDF2` — planner inserts `checkpoint:human-verify` before each install. Legitimacy check + registry verification NOT run this session because the recommended MVP path installs nothing; if the planner chooses the PageIndex path, run the Package Legitimacy Gate (`gsd-tools query package-legitimacy check --ecosystem pypi pageindex PyPDF2 pymupdf` + `pip index versions <pkg>`) before writing the install task.

## Architecture Patterns

### System Data Flow

```
                        ┌─────────────────────────────────────────────┐
   clean_document ──────┤ forwards in-memory ParsedDoc (parsed_doc)    │
   (Dagster asset)      │ + parsed_artifact_id + source_id + collection│
                        └───────────────┬─────────────────────────────┘
                                        │ fan-out (parallel, non-blocking)
             ┌──────────────┬───────────┼───────────────┬───────────────────┐
             ▼              ▼           ▼               ▼                   ▼
       chunk_document  enrich_document  curate_...  tree_index_document (NEW)
                                                        │
                                                        ▼
                                         pipeline.tree_index.tree_index(
                                           parsed_artifact_id, source_id,
                                           parsed_doc, settings)
                                                        │
                     ┌──────────────────────────────────┴───────────────┐
                     ▼                                                    ▼
          content_hash = sha256(                              mode == "llm" ?
            parsed_doc.content_hash + mode + schema_version)     │
                     │                                           ▼
       get_artifact_by_hash(hash,"tree_index") ──HIT──▶ return existing (NO-OP, TREE-02)
                     │ MISS                                      │
                     ▼                              budget-check get_llm_spend("global")
       build TreeNode roots from ParsedDoc.sections         < budget ?  else skipped_budget_exceeded
       (deterministic: summary = heading text)                  │ yes
                     │                              litellm.completion(cheap_model) per node
                     ▼                              → validated summaries (pydantic)
       serialize TreeIndex → orjson JSON                        │
                     ▼◀──────────────────────────────────────────┘
       storage.put_object("tree_index/{domain}/{source_id}/{hash}.json")
                     ▼
       create_tree_index_artifact(parent=parsed_artifact_id, artifact_type="tree_index")
       record_llm_spend("global", cost)   # LLM mode only
```

The `content_hash` is computed from `parsed_doc.content_hash` — the tree parents off `parsed_document` (D-07), so the builder needs the **parsed artifact's** content_hash. `clean_document` forwards `parsed_artifact_id`; the builder loads that artifact (`registry_repo.get_artifact(session, parsed_artifact_id).content_hash`) to seed the hash. Confirm this in the plan.

### Component Responsibilities
| File | New/Modified | Responsibility |
|------|--------------|----------------|
| `src/knowledge_lake/plugins/protocols.py` | MODIFIED | Add `TreeNode`, `TreeIndex` dataclasses + `IndexerPlugin` Protocol (D-01, D-05) |
| `src/knowledge_lake/pipeline/tree_index.py` | NEW | `tree_index()` entry point: build → hash no-op → LLM summaries (opt-in) → store → register. Clone of `chunk.py` + `enrich.py` budget flow |
| `src/knowledge_lake/plugins/builtin/pageindex_indexer.py` | NEW | `IndexerPlugin` builtin (D-04/D-05). Recommended: deterministic skeleton + direct-litellm summaries |
| `src/knowledge_lake/plugins/resolver.py` | MODIFIED | Add `GROUP_INDEXERS = "knowledge_lake.indexers"` + `get_indexer(settings)` (mirror `get_vectorstore`) |
| `src/knowledge_lake/plugins/builtin/__init__.py` | MODIFIED | Add docstring line for the indexers group |
| `src/knowledge_lake/registry/repo.py` | MODIFIED | Add `create_tree_index_artifact()` (mirror `create_chunk_artifact` at :270) |
| `src/knowledge_lake/ids.py` | MODIFIED | Add `"tree_index": "idx"` to `_PREFIX` (REQUIRED — `new_id(kind)` raises `ValueError` on unknown kind, :70) |
| `src/knowledge_lake/config/settings.py` | MODIFIED | Add `TreeSettings` submodel + `tree: TreeSettings = Field(default_factory=...)` + `indexer: str = "pageindex"` swap key |
| `src/knowledge_lake/dagster_defs/assets.py` | MODIFIED | Add `tree_index_document` asset (clone `chunk_document` shape, add `litellm` resource for LLM mode) |
| `src/knowledge_lake/dagster_defs/definitions.py` | MODIFIED | Import + add `tree_index_document` to `assets=[...]`; optionally add to `healthcare_e2e_job` selection |
| `pyproject.toml` | MODIFIED | Add `[project.entry-points."knowledge_lake.indexers"]` with `pageindex = "...pageindex_indexer:PageIndexIndexer"` |

### Pattern 1: Content-hash no-op (TREE-02) — verbatim from `chunk.py:317-333`
**What:** Compute a deterministic hash, look it up by `(hash, artifact_type)`, return the existing node on hit — skipping ALL processing (including any LLM call).
**When to use:** First thing inside `tree_index()`, before any build or LLM work.
**Example:**
```python
# Source: src/knowledge_lake/pipeline/chunk.py:317 (adapted; hash per D-06)
content_hash = hashlib.sha256(
    f"{parsed_content_hash}:{mode}:{tree_schema_version}".encode("utf-8")
).hexdigest()
existing = registry_repo.get_artifact_by_hash(session, content_hash, "tree_index")
if existing is not None:
    return {"artifact_id": existing.id, "cached": True, "status": "cached"}
```

### Pattern 2: LLM budget flow (TREE-04) — verbatim from `enrich.py:345-383`
**What:** cache-check → budget-check → single `litellm.completion` → validate → write; NEVER raise on budget/LLM failure — return a status dict.
**When to use:** LLM mode only (`settings.tree.mode == "llm"`); deterministic mode skips this entirely.
**Example:**
```python
# Source: src/knowledge_lake/pipeline/enrich.py:356 + :227
current_spend = registry_repo.get_llm_spend(session, scope="global")
if current_spend >= s.tree.budget_usd:
    return {"artifact_id": None, "cached": False, "status": "skipped_budget_exceeded"}
# ... outside session:
response = litellm.completion(
    model=f"openai/{s.tree.model_alias}",   # "cheap_model" — never a hardcoded provider ID
    messages=[{"role": "system", "content": SYS}, {"role": "user", "content": node_text}],
    api_base=s.litellm_url, api_key=s.litellm_api_key,
    max_tokens=..., temperature=0.0,
)
# validate via pydantic, then record_llm_spend(session, scope="global", cost_usd=cost)
```
Note the `"openai/{alias}"` prefix (`enrich.py:234`): it declares the wire protocol the LiteLLM proxy speaks (OpenAI-compatible), NOT the provider — the proxy resolves the alias.

### Pattern 3: Dagster fan-out asset (TREE-05) — clone of `chunk_document` (`assets.py:335`) + `enrich_document` (:384)
**What:** New `@asset(group_name="pipeline", retry_policy=_PIPELINE_RETRY)` taking `clean_document: dict[str, Any]`, calling `pipeline.tree_index.tree_index()`.
**Example:**
```python
# Source: src/knowledge_lake/dagster_defs/assets.py:335 (chunk_document) + :384 (enrich_document, for litellm resource)
@asset(group_name="pipeline", retry_policy=_PIPELINE_RETRY, description="...")
def tree_index_document(
    clean_document: dict[str, Any],
    postgres: PostgresResource,
    minio: MinIOResource,
    litellm: LiteLLMResource,   # needed only for LLM mode; deterministic default ignores it
) -> dict[str, Any]:
    parsed_artifact_id = clean_document["parsed_artifact_id"]
    source_id = clean_document["source_id"]
    doc = clean_document["parsed_doc"]           # in-memory ParsedDoc (Pitfall 7: no IO managers)
    settings = Settings(database_url=postgres.database_url,
                        storage=StorageSettings(...), litellm_url=litellm.litellm_url,
                        _env_file=None)
    return tree_index(parsed_artifact_id, source_id, doc, settings=settings)
```
Then register in `definitions.py` `assets=[...]`. **Memory note (`dagster-code-location-reload`):** a running Dagster container holds startup Definitions — the new asset only appears after a code-location reload; a "live daemon" check can be testing stale code.

### Anti-Patterns to Avoid
- **Building the tree from chunks.** Chunking destroys hierarchy. Build from `clean_document["parsed_doc"].sections` (the forwarded in-memory `ParsedDoc`), same object `chunk_document` consumes. (ARCHITECTURE.md Anti-Pattern 1.)
- **Storing the tree JSON in `Artifact.metadata_`.** Trees can be hundreds of KB; `metadata_` is for lightweight fields. Store in S3, register with `storage_uri`. (ARCHITECTURE.md Anti-Pattern 4.)
- **Raising out of a budget/LLM failure.** Return a status dict like `enrich_document` (D-09). Raising breaks the Dagster asset and diverges from the established contract.
- **Adding an Alembic migration for `tree_index`.** `artifact_type` is a free-form `String`; `_make_artifact` accepts any `artifact_type` (`repo.py:119`). Zero migrations (ARCHITECTURE.md §"Zero Alembic migrations").
- **Hardcoding a provider model ID.** Route through the `cheap_model` alias via `"openai/{alias}"` (CLAUDE.md; `test_enrich.py:140 test_no_hardcoded_provider_model_ids` is the precedent test — write the analogous one).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Content-addressed dedup | Custom cache table | `registry_repo.get_artifact_by_hash(session, hash, "tree_index")` | UNIQUE(content_hash, artifact_type) index, O(1), proven in chunk/enrich/curate |
| Artifact ID generation | uuid literals | `new_id("tree_index")` after adding to `_PREFIX` | Prefixed UUIDv7, time-sortable, self-describing (`ids.py`) |
| Artifact row construction | Raw `Artifact(...)` | `create_tree_index_artifact()` wrapping `_make_artifact` | Stamps `pipeline_version`, `created_at`, correct `artifact_type` (`repo.py:119`) |
| LLM spend accounting | Custom counter | `get_llm_spend` / `record_llm_spend(scope="global")` | Get-or-create with UNIQUE(scope); already the enrich budget mechanism (`repo.py:757`) |
| Plugin registration | if/else on name | Entry-point group + `resolver.resolve(GROUP_INDEXERS, name)` | FOUND-08 swappability; matches all 5 existing plugin groups |
| Config env parsing | `os.getenv` | `TreeSettings` submodel + `env_nested_delimiter="__"` | `KLAKE_TREE__MODE` resolves automatically (settings.py:378); no module reads env directly |
| JSON (de)serialization | stdlib `json` for big trees | `orjson` | Already in stack; faster on 100KB+ trees (Pitfall §Performance Traps) |
| Partial/truncated LLM JSON recovery | New parser | Reuse `enrich.py` `_strip_json_fences` / `_extract_longest_valid_prefix` patterns if LLM mode returns structured JSON | Battle-tested against Bedrock Claude fence-wrapping |

**Key insight:** Every hard part of this phase (dedup, IDs, budget, storage keys, plugin seam, config) already has a shipped, tested implementation. The deterministic builder's *only* genuinely new logic is nesting `Section`s into a tree and deriving `level`/`page_end` (see Critical Finding 1).

## Critical Findings (source-grounded)

### Finding 1 — `Section` has NO `level` and NO `page_end`; both TreeNode fields must be DERIVED
`Section` (`protocols.py:34-61`) fields are exactly: `heading: str`, `section_path: str` (e.g. `"§3.2"`, `"§1"`), `page: int` (single **begin** page, 1-indexed), `text: str = ""`, `is_table: bool = False`. There is **no** `level` field and **no** page-range end.

Consequences for the deterministic builder (D-03):
- **`TreeNode.level`** must be derived from `section_path` structure. Sections use `§`-prefixed dot paths (`"§3.2.1"` → depth 3). `chunk.py` produces sub-paths like `"§3.2.1"` by appending `.{i+1}`. Recommended: `level = section_path.count(".") + 1` (with `"§1"` → level 1). Document the exact rule; add to the schema contract note.
- **`TreeNode.page_start`** = `section.page`.
- **`TreeNode.page_end`** must be inferred: the `page` of the next section at the same-or-shallower level minus 1, or `ParsedDoc.metadata.get("page_count")` / last section's page for the final node. There is no stored end page. Flag as a definition the planner locks.
- **Nesting:** one node per `Section` (D-03), nested by `section_path` depth. The builder walks `parsed_doc.sections` in order and attaches each section as a child of the most recent shallower-level node (stack-based nesting). Sections with `is_table=True` become leaf nodes.
- **No-sections fallback:** `chunk.py:204` emits a single `"§1"` chunk when `parsed_doc.sections` is empty. The tree builder needs the analogous single-root fallback (title from `parsed_doc.metadata` title or `"§1"`).

### Finding 2 — `content_hash` seed requires loading the parsed artifact
D-06 hashes `parsed_doc.content_hash`, but the in-memory `ParsedDoc` dataclass has no `content_hash` attribute (`protocols.py:64`). The parsed artifact's content_hash lives in the registry. The `clean_document` asset forwards `parsed_artifact_id` (`assets.py:313`). The builder must fetch it: `registry_repo.get_artifact(session, parsed_artifact_id).content_hash`. Confirm this seed source in the plan (analogous to how `enrich.py:331` reads `cleaned_artifact.content_hash`).

### Finding 3 — `ids.py._PREFIX` change is mandatory, not optional
`new_id(kind)` raises `ValueError` for any `kind` not in `_PREFIX` (`ids.py:70`). `_make_artifact` calls `new_id(kind)` (`repo.py:133`). So `create_tree_index_artifact` will crash unless `"tree_index": "idx"` is added to `_PREFIX` (`ids.py:32`). ARCHITECTURE.md §2 specifies the `"idx"` prefix.

### Finding 4 — PageIndex ↔ D-03/D-09 tension (see Open Question #1)
`.planning/research/STACK.md` (verified against PageIndex source) confirms: `PageIndexClient.index(path)` reads a PDF/markdown file and builds its *own* tree via internal `litellm.completion` calls — it does **not** accept `Section` objects, and `retrieve.py` (the deterministic part) is only for traversal, not construction. Its multi-call index does not surface per-call cost, so `enrich.py`'s single-call budget gate cannot wrap it cleanly (only a coarse pre-check + post-hoc `record_llm_spend`). This conflicts with D-03 ("build from sections, no re-parse") and D-09 ("one `litellm.completion`, enrich.py verbatim"). Recommended reconciliation documented in Open Questions.

## Runtime State Inventory

> This is a greenfield additive phase (new artifact type + new asset + new config), NOT a rename/refactor. No existing runtime state is renamed or migrated.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — new `tree_index` artifacts are additive; no existing rows change | None |
| Live service config | Dagster code location holds startup Definitions; the new `tree_index_document` asset requires a **code-location reload** to appear (memory: `dagster-code-location-reload`) | Reload Dagster after `definitions.py` change (execution step, not data migration) |
| OS-registered state | None | None |
| Secrets/env vars | New `KLAKE_TREE__*` vars are additive with defaults; no existing var renamed | None — verified against settings.py env pattern |
| Build artifacts | New `[project.entry-points."knowledge_lake.indexers"]` requires an editable-install refresh (`uv pip install -e .` / equivalent) for the entry point to be discoverable by `importlib.metadata.entry_points` | Reinstall package after pyproject.toml entry-point add (same as any new builtin) |

## Common Pitfalls

### Pitfall 1: Budget burn on LLM mode (milestone Pitfall 1)
**What goes wrong:** LLM mode makes an LLM call per node; a deep tree burns budget fast.
**How to avoid:** deterministic is the DEFAULT (`TreeSettings.mode = "deterministic"`). LLM mode is opt-in and gated by `get_llm_spend("global") >= s.tree.budget_usd` BEFORE any call, exactly like `enrich.py:356`. Content-hash no-op (TREE-02) means a re-run makes zero calls.
**Warning signs:** second run of the same doc/mode still calls `litellm.completion` → the no-op branch is missing or the hash is non-deterministic (e.g. includes a timestamp).

### Pitfall 2: Schema coupling with the Phase 14 retriever (milestone Pitfall 4)
**What goes wrong:** Indexer and retriever couple on an ad-hoc dict shape.
**How to avoid:** Freeze `TreeNode`/`TreeIndex` in `protocols.py` FIRST (D-01), as typed dataclasses (not `dict[str, Any]`), before writing the builder — mirroring how `Hit`/`VectorPoint` are defined once and shared.

### Pitfall 3: Non-deterministic deterministic mode
**What goes wrong:** Node ordering or `node_id`s vary between runs → hash instability → false cache misses, TREE-02 fails.
**How to avoid:** Iterate `parsed_doc.sections` in list order (stable); derive `node_id` from `section_path` (stable) not `uuid`/insertion time; no clock, no randomness in the tree body. CONTEXT §Specific Ideas: "reproducible and free — no network, no LLM, no clock/randomness."

### Pitfall 4: Forgetting the `_PREFIX` / `create_tree_index_artifact` plumbing
**What goes wrong:** `new_id("tree_index")` raises `ValueError`; or writing `Artifact` directly skips `pipeline_version`/`created_at` stamping.
**How to avoid:** Add `_PREFIX` entry (Finding 3) AND a `create_tree_index_artifact` wrapper over `_make_artifact` (mirror `create_chunk_artifact`, `repo.py:270`).

### Pitfall 5: Storage-key domain/source resolution
**What goes wrong:** Key built without the domain segment diverges from `chunk.py`'s convention and breaks S3 layout consistency.
**How to avoid:** Reuse `chunk.py:305`: `domain = registry_repo.get_domain_for_source(session, source_id) or _UNCLASSIFIED_DOMAIN`; key = `f"tree_index/{domain}/{source_id}/{content_hash}.json"` (D-07). Tag the object like `chunk.py:343` (`domain`, `source_name`, `format="json"`, `artifact_type="tree_index"`).

## Code Examples

### `create_tree_index_artifact` (registry helper) — mirror `create_chunk_artifact`
```python
# Source: src/knowledge_lake/registry/repo.py:270 (create_chunk_artifact), adapted
def create_tree_index_artifact(
    session: Session, *, source_id: str, parent_artifact_id: str,
    content_hash: str, storage_uri: str | None = None,
    mime_type: str | None = "application/json", metadata: Any | None = None,
) -> Artifact:
    """Persist a tree_index artifact node. parent_artifact_id = parsed_document (D-07)."""
    art = _make_artifact(
        kind="tree_index", source_id=source_id, artifact_type="tree_index",
        content_hash=content_hash, storage_uri=storage_uri,
        parent_artifact_id=parent_artifact_id, mime_type=mime_type, metadata=metadata,
    )
    session.add(art)
    return art
```

### `TreeSettings` submodel — mirror `EnrichSettings` (`settings.py:139`)
```python
# Source: src/knowledge_lake/config/settings.py:139 (EnrichSettings) + :335 (SearchSettings Literal)
class TreeSettings(BaseModel):
    """Tree-index generation config (TREE-01..05). Env: KLAKE_TREE__MODE, etc."""
    mode: Literal["deterministic", "llm"] = "deterministic"   # deterministic-first (D-08)
    budget_usd: float = 5.0                                    # mirrors EnrichSettings (D-08/D-09)
    model_alias: str = "cheap_model"                          # never a hardcoded provider ID
    schema_version: str = "1"                                 # D-02 anchor; TREE-06 deferred
    prompt_version: str = "v1"                                # bump to invalidate LLM-mode cache
    max_tokens: int = 1024                                    # LLM summary output cap
# In Settings: tree: TreeSettings = Field(default_factory=TreeSettings)
#              indexer: str = "pageindex"   # add to _validate_swap_key field list at :483
```

### `get_indexer` resolver — mirror `get_vectorstore` (`resolver.py:271`)
```python
# Source: src/knowledge_lake/plugins/resolver.py:271
GROUP_INDEXERS = "knowledge_lake.indexers"
def get_indexer(settings: Settings) -> Any:
    return resolve(GROUP_INDEXERS, settings.indexer)   # or _resolve_with_kwargs if litellm_url needed
```

### `IndexerPlugin` Protocol — mirror the seam style in `protocols.py`
```python
# Source: src/knowledge_lake/plugins/protocols.py (runtime_checkable Protocol convention)
@runtime_checkable
class IndexerPlugin(Protocol):
    """Build a TreeIndex from a ParsedDoc (D-05). Swap via settings.indexer."""
    name: str
    def build_index(self, parsed_doc: ParsedDoc, *, mode: str, metadata: dict[str, Any]) -> TreeIndex:
        ...
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Chunk-only representation of a document | Parallel structural tree index alongside chunks | v2.5 (this milestone) | Enables Phase 14 reasoning retrieval; additive, no change to chunk path |
| stdlib `json` for artifact serialization | `orjson` for large trees | already adopted in stack | Faster serialize/deserialize on 100KB+ JSON |

**Deprecated/outdated:** none relevant to this phase. (PageIndex stable 0.2.8 lacks the `PageIndexClient` API; only 0.3.x pre-release has it — a reason to defer, not adopt, per STACK.md.)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Recommended MVP: LLM mode = deterministic skeleton + direct `litellm.completion` per-node summary (NOT `pageindex.index()`), to honor D-03/D-09; `pageindex_indexer` builtin satisfies D-04/D-05 by name/seam without importing the pre-release library this phase | Summary, Open Q#1 | If planner/user insist on real PageIndex tree construction, budget gating is coarser and the LLM-mode tree diverges from the deterministic tree; extra deps (`pageindex`/`PyPDF2`/`pymupdf`) + `checkpoint:human-verify` required |
| A2 | `TreeNode.level = section_path.count(".") + 1`; `page_end` inferred from the next same/shallower section's `page` (or doc last page) | Finding 1 | Wrong derivation → misleading page ranges / tree depth; needs a locked rule |
| A3 | `content_hash` seed = parsed artifact's registry `content_hash` (loaded via `get_artifact`), since `ParsedDoc` has no `content_hash` attribute | Finding 2 | If seeded from something mutable, TREE-02 no-op breaks |
| A4 | `"tree_index"` prefix = `"idx"` (per ARCHITECTURE.md §2) | Finding 3 | Cosmetic only; any valid short prefix works, but must exist in `_PREFIX` |
| A5 | New entry-point group name = `knowledge_lake.indexers`, swap key `settings.indexer = "pageindex"` (per ARCHITECTURE.md §3 / STACK.md) | Component table | Mismatched group/name → resolver `LookupError` at runtime |
| A6 | `tree_index_document` may be added to `healthcare_e2e_job` selection, but this is optional; the 7-asset E2E job intentionally excludes non-core assets (assets.py:867) | Dagster fan-out | Adding it changes E2E job scope; leave out unless requirements demand it |

## Open Questions

1. **Does LLM mode call the real PageIndex library, or replicate summarization via direct `litellm.completion`?**
   - What we know: D-04 locks PageIndex as the LLM-mode builtin; D-03 says build from sections with no re-parse; D-09 says use the `enrich.py` single-`litellm.completion` budget pattern verbatim. STACK.md (source-verified) shows PageIndex builds its own tree by re-reading the doc and does not consume `Section`s, with no clean per-call budget hook.
   - What's unclear: whether the locked "PageIndex is the builtin" (D-04) means *import and call* `pageindex`, or *name the builtin `pageindex_indexer`* while its internals reuse the deterministic skeleton + direct litellm summaries.
   - Recommendation: Adopt the latter for this phase — `pageindex_indexer` builtin builds the deterministic tree (D-03) and summarizes each node with a budget-gated `litellm.completion(cheap_model)` (D-09). Keep the actual `pageindex==0.3.0.dev3` import as a documented, deferred alternative behind the `IndexerPlugin` seam (vendoring fallback per STACK.md). This honors D-03/D-09 and the deterministic-first + clean-budget constraints, and avoids installing a `[SUS]` pre-release. **Flag to discuss-phase/planner for confirmation** since CONTEXT was auto-resolved.

2. **`page_end` derivation rule for the final node and for table leaves.** Recommendation: last node's `page_end = parsed_doc.metadata.get("page_count", section.page)`; table leaves span a single page (`page_end = page_start`). Lock in the plan.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| LiteLLM proxy | LLM-mode summaries (TREE-04) | Runtime service (existing) | `KLAKE_LITELLM_URL` (dev http://localhost:4000) | Deterministic mode needs NO LLM — full TREE-01..03,05 work with the proxy down |
| Postgres | Registry writes | Existing | — | none (required); tests use in-memory SQLite |
| S3/MinIO | Silver-zone JSON persistence | Existing | — | none (required); tests patch `StorageBackend` |
| pageindex | LLM mode ONLY IF Open Q#1 resolves to real-import | ✗ (not installed) | — | Direct `litellm.completion` (recommended) — no install needed |

**Missing dependencies with no fallback:** none for the recommended path.
**Missing dependencies with fallback:** `pageindex` — direct-litellm summarization is the recommended fallback (and default).

## Validation Architecture

> Nyquist enabled (`workflow.nyquist_validation: true` confirmed in `.planning/config.json`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (+ `pytest-asyncio`, `asyncio_mode = "auto"`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths = ["tests"]`, `addopts = "-v"` |
| Quick run command | `pytest tests/unit/test_tree_index.py -x` |
| Full suite command | `pytest` |
| Test DB pattern | In-memory SQLite via `StaticPool`; `monkeypatch.setattr(registry_db, "get_engine", lambda: engine)`; `Base.metadata.create_all(eng)` (verbatim from `test_enrich.py:45-104`) |
| Mocking pattern | Patch `StorageBackend` at the pipeline module level (`monkeypatch.setattr(tree_index_module, "StorageBackend", lambda *_a, **_k: fake)`); mock LLM via `patch("litellm.completion", MagicMock(...))` (from `test_enrich.py:108-113, 164`) |
| Reusable fixtures | `ParsedDoc(text=..., sections=[Section(heading=..., section_path="§1", page=1)])` — construct directly (`test_enrich.py:117`); seeded Source→raw→parsed chain (`test_enrich.py:78`, extend to parsed only) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TREE-01 | Deterministic tree from a fixture `ParsedDoc` → assert each node's `title`, `summary`(=heading), `page_start`, `page_end`, `level`, `children` nesting; assert a `tree_index` artifact registered with parent=parsed & storage_uri set | unit | `pytest tests/unit/test_tree_index.py::test_deterministic_tree_from_sections -x` | ❌ Wave 0 |
| TREE-01 | Storage key = `tree_index/{domain}/{source_id}/{hash}.json`; object tags correct | unit | `pytest tests/unit/test_tree_index.py::test_tree_storage_key -x` | ❌ Wave 0 |
| TREE-02 | Second run on unchanged doc+mode is a no-op: returns `cached`, no second `put_object`, and (LLM mode) ZERO new `litellm.completion` calls / no `record_llm_spend` delta | unit | `pytest tests/unit/test_tree_index.py::test_content_hash_noop -x` | ❌ Wave 0 |
| TREE-03 | Each node has title/summary/page-range/children; deterministic summary == heading text; no-sections doc → single root fallback | unit | `pytest tests/unit/test_tree_index.py::test_node_fields_and_fallback -x` | ❌ Wave 0 |
| TREE-04 | LLM mode with budget already at cap → returns `status == "skipped_budget_exceeded"`, no artifact, no LLM call (seed via `record_llm_spend(session,"global",budget_usd)`, mirror `test_enrich.py:218`); happy path → summaries populated, `record_llm_spend` called, `cost_usd` in result | unit | `pytest tests/unit/test_tree_index.py::test_llm_mode_budget_cap -x` | ❌ Wave 0 |
| TREE-04 | LLM call uses `cheap_model` alias via `openai/` prefix — no hardcoded provider ID (assert on the mocked call's `model=` kwarg; mirror `test_enrich.py:140`) | unit | `pytest tests/unit/test_tree_index.py::test_no_hardcoded_provider_model_ids -x` | ❌ Wave 0 |
| TREE-05 | `tree_index_document` asset materializes off `clean_document` in parallel to `chunk_document`; asset is a thin shell returning the pipeline result dict | unit | `pytest tests/unit/test_tree_index_asset.py -x` (mirror `test_dagster_e2e_job.py` / `test_dagster_retry_policies.py`) | ❌ Wave 0 |
| Contract | `TreeNode`/`TreeIndex` are `IndexerPlugin`-satisfying dataclasses; builtin passes `isinstance(obj, IndexerPlugin)` (runtime_checkable) — mirror `test_builtin_plugins.py` | unit | `pytest tests/unit/test_builtin_plugins.py -x` (extend) | ⚠️ extend existing |

### Sampling Rate
- **Per task commit:** `pytest tests/unit/test_tree_index.py -x`
- **Per wave merge:** `pytest tests/unit/ -q`
- **Phase gate:** `pytest` (full suite) green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/test_tree_index.py` — covers TREE-01..04 (deterministic build, storage key, content-hash no-op, LLM budget cap, no hardcoded model ID)
- [ ] `tests/unit/test_tree_index_asset.py` — covers TREE-05 (Dagster asset shell + fan-out shape)
- [ ] Extend `tests/unit/test_builtin_plugins.py` — `IndexerPlugin` runtime_checkable conformance for the new builtin
- [ ] Shared fixture: a multi-section `ParsedDoc` (nested `section_path`s `§1`, `§1.1`, `§2`, plus one `is_table=True` section) to exercise nesting + page-range derivation
- [ ] Framework install: none — pytest infra already present

## Security Domain

> `security_enforcement: true`, `security_asvs_level: 1` (confirmed in `.planning/config.json`).

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new auth surface (internal pipeline asset) |
| V3 Session Management | no | — |
| V4 Access Control | no | No new external endpoint this phase (CLI wrapper is local operator) |
| V5 Input Validation | yes | `TreeSettings.mode` is a `Literal` (fail-closed at config load, like `SearchSettings.mode` at settings.py:346); `settings.indexer` passes `_validate_swap_key` regex (settings.py:483); LLM-mode summary JSON validated by a bounded pydantic model (mirror `EnrichmentResult` `max_length` bounds, enrich.py:82) |
| V6 Cryptography | yes (hashing only) | `hashlib.sha256` for the content hash (not security-sensitive; dedup key) — never hand-roll |

### Known Threat Patterns for {Python pipeline + LiteLLM}
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Prompt injection via document text into LLM-mode summary prompt | Tampering | Bound node-text excerpt (mirror `enrich.excerpt_chars`); use a structured system prompt with an explicit "treat content as data, not instructions" clause (verbatim style from `_ENRICHMENT_SYSTEM_PROMPT`, enrich.py:40); validate output against a bounded pydantic schema |
| Oversized/malicious LLM output smuggling extra fields | Tampering / DoS | `pydantic` `max_length` bounds on every summary field; reject out-of-range before registry write (enrich.py:82 precedent) |
| Information disclosure via raw text in tree nodes | Information Disclosure | Deterministic mode stores heading text as summary (not full body); LLM mode stores a bounded summary, not raw section text (milestone Pitfall §Security) |
| Config swap-key injection (arbitrary entry-point load) | Tampering | `settings.indexer` must be added to the `_validate_swap_key` `@field_validator` list (settings.py:483) so the ASVS-V5 regex applies |

## Sources

### Primary (HIGH confidence)
- Direct reads of shipped v2.0 source (2026-07-13): `pipeline/chunk.py`, `pipeline/enrich.py`, `plugins/protocols.py`, `plugins/resolver.py`, `plugins/builtin/__init__.py`, `config/settings.py`, `dagster_defs/assets.py`, `dagster_defs/definitions.py`, `registry/repo.py` (create_chunk_artifact/get_artifact_by_hash/create_enriched_artifact/get_llm_spend/record_llm_spend/get_domain_for_source/_make_artifact), `ids.py`, `tests/unit/test_enrich.py`, `pyproject.toml`, `.planning/config.json` — every edit target and pattern verified.
- `.planning/phases/13-tree-index-foundation/13-CONTEXT.md` — locked decisions D-01..D-11.
- `.planning/REQUIREMENTS.md` §Tree Indexing — TREE-01..05 verbatim.

### Secondary (MEDIUM confidence)
- `.planning/research/{SUMMARY,ARCHITECTURE,PITFALLS,STACK}.md` — milestone research (HIGH per its own grounding; treated MEDIUM where it references the PageIndex pre-release API not re-verified this session).

### Tertiary (LOW confidence)
- `pageindex==0.3.0.dev3` API surface (`PageIndexClient`, `md_to_tree`) — from STACK.md's read of the upstream repo; `[ASSUMED]` for this session, pre-release, not installed or executed here.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all recommended libraries already pinned and in use; verified in `pyproject.toml`.
- Architecture / edit targets: HIGH — every file:function cited from a direct read; the phase is a structural clone of chunk.py + enrich.py + the fan-out asset pattern.
- Pitfalls: HIGH — derived from shipped patterns and two source-grounded findings (Section field gaps, PageIndex tension).
- PageIndex integration: LOW — pre-release, contested against locked decisions; surfaced as Open Question #1 for user confirmation.

**Research date:** 2026-07-13
**Valid until:** 2026-08-12 (30 days — stable internal codebase; re-check only if PageIndex path is chosen, as the pre-release may move).
