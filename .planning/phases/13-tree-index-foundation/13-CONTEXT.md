# Phase 13: Tree Index Foundation - Context

**Gathered:** 2026-07-13
**Status:** Ready for planning

> Captured in `--auto` mode: all gray areas auto-resolved to the recommended
> (deterministic-first, pattern-reuse) option. Decisions are logged in
> `13-DISCUSSION-LOG.md`. Review before planning if any default is wrong.

<domain>
## Phase Boundary

Deliver hierarchical **tree-index generation** from parsed documents as a new
silver-zone artifact type with full lineage. A tree index is a JSON tree whose
nodes carry `title`, `summary`, `page range`, and `children`. Generation:

- Runs as a **Dagster asset that fans out from `clean_document`**, parallel to
  `chunk_document` / `enrich_document` (TREE-05) — neither blocks the other.
- Is **deterministic by default** (node summaries derived from heading text, no
  LLM call) with an **opt-in LLM-summary mode** gated by the existing budget cap
  (TREE-03, TREE-04).
- Is **content-hash de-duplicated** — re-running on an unchanged document (same
  mode) is a full no-op, including zero LLM calls (TREE-02).
- Is registered as a `tree_index` artifact with lineage parent = `parsed_document`
  (TREE-01).

**In scope:** tree schema contract, IndexerPlugin protocol, deterministic tree
builder from `ParsedDoc.sections`, LLM-summary mode behind the plugin boundary,
silver-zone JSON persistence + registry artifact, content-hash no-op, Dagster
asset, config surface (`TreeSettings`).

**Out of scope (later phases / deferred):** tree *retrieval* / traversal
(Phase 14), query routing (Phase 15), OpenKB wiki (Phase 16), tree schema
versioning/migration and corpus-level meta-tree (TREE-06/07, deferred to v2.6+).

</domain>

<decisions>
## Implementation Decisions

### Tree schema contract (define FIRST — Pitfall 4)
- **D-01:** Add `TreeNode` and `TreeIndex` dataclasses to
  `src/knowledge_lake/plugins/protocols.py`, alongside the existing `Section`,
  `ParsedDoc`, `VectorPoint`, and `Hit` seam types. This shared contract is
  defined and frozen **before** either the deterministic builder or any plugin
  implementation, so indexer↔retriever (Phase 14) never couple on ad-hoc dicts.
- **D-02:** `TreeNode` fields: `node_id`, `title`, `summary`, `page_start`,
  `page_end`, `level` (heading depth), `section_path`, `children: list[TreeNode]`.
  `TreeIndex` wrapper fields: `doc_id` / `parsed_artifact_id`, `source_id`,
  `roots: list[TreeNode]`, `mode` (`deterministic` | `llm`), `schema_version`,
  `content_hash`. Persisted as JSON.

### PageIndex integration & deterministic construction
- **D-03:** The **deterministic tree is built directly from `ParsedDoc.sections`**
  — nest by `section_path` depth / heading `level`, one node per section, summary
  = heading text, `page_start/page_end` derived from each section's `page_ref`.
  No PageIndex dependency, no LLM, zero cost. Reuses the parse output already in
  memory (same in-memory `ParsedDoc` that `chunk_document` consumes).
- **D-04:** **PageIndex (`0.3.0.dev3`) is used only inside the LLM-mode builtin
  indexer**, behind the `IndexerPlugin` seam — never in deterministic mode. This
  isolates the pre-release dependency behind the plugin boundary; the documented
  vendoring fallback (6 files) is validated during execution if the pinned
  pre-release API breaks.
- **D-05:** Add a `runtime_checkable` **`IndexerPlugin` Protocol** to
  `protocols.py` and register the builtin via the existing entry-point /
  `plugins/resolver.py` + `plugins/builtin/__init__.py` mechanism (same pattern as
  `docling_parser`, `qdrant_store`). Satisfies the tool-agnostic / swappability
  constraint (FOUND-08).

### Dedup / content-hash (TREE-02 no-op)
- **D-06:** The tree artifact `content_hash` = `sha256(parsed_doc.content_hash +
  mode + tree_schema_version)`. No-op check mirrors `chunk.py`:
  `registry_repo.get_artifact_by_hash(session, content_hash, "tree_index")` — if a
  match exists, return the existing node and skip all processing (including any
  LLM call). **Mode is part of the hash** so switching deterministic→LLM produces
  a distinct artifact instead of a false cache hit.

### Storage layout & artifact type
- **D-07:** Store at `tree_index/{domain}/{source_id}/{content_hash}.json` in the
  **silver zone**, artifact_type = `tree_index`, lineage parent =
  `parsed_document`. Mirrors `chunk.py`'s `_CHUNK_PREFIX` key convention and its
  registry-write flow. Raw zone is never touched.

### Config surface & mode gating
- **D-08:** Add a `TreeSettings` submodel to `config/settings.py` (mirrors
  `EnrichSettings`): `mode: Literal["deterministic", "llm"] = "deterministic"`,
  `budget_usd: float = 5.0`, LLM routed through the **`cheap_model`** task alias
  (never a hardcoded provider ID). Env override via `KLAKE_TREE__MODE` etc.
- **D-09:** LLM mode reuses the **enrich.py budget pattern verbatim**:
  cache-check → budget-check (`get_llm_spend(session, scope="global")` vs
  `tree.budget_usd`) → `litellm.completion()` → validate → registry-write. The
  builder **never raises out of a budget/LLM failure** — it returns a status dict
  and halts gracefully (`status: skipped_budget_exceeded`), exactly like
  `enrich_document` (D-05 / D-14 of Phase 4).

### CLI / asset surface
- **D-10:** Primary surface is the **Dagster `tree_index_document` asset** (TREE-05).
  A thin `klake tree-index <parsed_artifact_id>` CLI wrapper calling the same
  `pipeline.tree_index` function is a nice-to-have; keep asset and CLI as thin
  shells over one `tree_index()` function — no logic duplicated (same convention
  as `chunk_document` / `chunk`).

### Claude's Discretion
- Exact `node_id` scheme (e.g. `section_path`-derived vs sequential), JSON
  serialization helper choice, and whether `schema_version` starts at `"1"` or
  `"1.0.0"` are left to the planner/executor — provided the schema contract
  (D-01/D-02) is stable and documented.

### Process / execution
- **D-11:** Per the invocation directive, **sub-agent executors run on the
  `sonnet` model**. Pinned via `model_overrides.gsd-executor: "sonnet"` in
  `.planning/config.json` (also the `adaptive`-profile default for gsd-executor).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### v2.5 project research (read first — grounds the whole milestone)
- `.planning/research/SUMMARY.md` — synthesis; confirms tree indexing = parallel
  fan-out off `clean_document`, deterministic-first, 4 net-new deps.
- `.planning/research/ARCHITECTURE.md` — integration points; `pipeline/tree_index.py`
  design, plugin protocols, zero-migration approach.
- `.planning/research/PITFALLS.md` — Pitfall 1 (LLM budget burn → content-hash +
  deterministic-only first), Pitfall 4 (schema coupling → shared contract first),
  Pitfall 9 (content-hash dedup from day 1).
- `.planning/research/STACK.md` — `pageindex 0.3.0.dev3` exact pin, PyPDF2/pymupdf
  transitive deps, vendoring fallback note.
- `.planning/research/FEATURES.md` — deterministic vs LLM mode expectations.

### Requirements & roadmap
- `.planning/ROADMAP.md` § "Phase 13: Tree Index Foundation" — goal + 5 success criteria.
- `.planning/REQUIREMENTS.md` § "Tree Indexing" — TREE-01…TREE-05.

### Source files to mirror (existing v2.0 patterns)
- `src/knowledge_lake/pipeline/chunk.py` — content-hash no-op (`get_artifact_by_hash`),
  `_CHUNK_PREFIX` storage-key convention, registry-write flow. **The tree builder
  is the closest analog.**
- `src/knowledge_lake/pipeline/enrich.py` — LLM budget-cap flow (cache→budget→
  `litellm.completion(cheap_model)`→validate→write; never raises on budget). **The
  LLM-summary mode mirrors this.**
- `src/knowledge_lake/plugins/protocols.py` — `@runtime_checkable` seam + dataclasses;
  add `TreeNode` / `TreeIndex` / `IndexerPlugin` here.
- `src/knowledge_lake/plugins/resolver.py`, `plugins/builtin/__init__.py` — builtin
  entry-point registration pattern for the PageIndex indexer.
- `src/knowledge_lake/dagster_defs/assets.py` — `clean_document` (~L265) →
  `chunk_document` (~L335) / `enrich_document` (~L384) fan-out; add
  `tree_index_document` with the same `clean_document: dict` input.
- `src/knowledge_lake/config/settings.py` — `EnrichSettings` (~L139, `budget_usd=5.0`)
  and `SearchSettings` (`mode: Literal[...]`) as the template for `TreeSettings`.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`pipeline/chunk.py` no-op + storage pattern:** `content_hash = sha256(...)`,
  `registry_repo.get_artifact_by_hash(session, content_hash, "chunk")` returns the
  existing node when hashes match; key = `{_CHUNK_PREFIX}/{domain}/{source_id}/{hash}.txt`.
  Tree index copies this with `tree_index` prefix + artifact type (D-06, D-07).
- **`pipeline/enrich.py` budget flow:** global spend check against a per-stage
  `budget_usd`, single `litellm.completion(model="cheap_model", ...)`, returns a
  status dict on budget-exceeded instead of raising. Directly reused by LLM mode (D-09).
- **`ParsedDoc.sections`:** each `Section` carries `section_path` + `page_ref`
  (already consumed by `chunk.py`). The deterministic tree is built entirely from
  these — no re-parse (D-03).
- **`plugins/protocols.py` seam:** established dataclass + `runtime_checkable`
  Protocol convention; the tree schema and `IndexerPlugin` slot in cleanly (D-01/D-05).

### Established Patterns
- **Fan-out off `clean_document`:** `chunk_document` and `enrich_document` are both
  `@asset(group_name="pipeline", retry_policy=_PIPELINE_RETRY)` taking
  `clean_document: dict[str, Any]`. `tree_index_document` is a third parallel branch
  (TREE-05) — same signature shape, uses the forwarded in-memory `ParsedDoc`.
- **Asset = thin shell over pipeline function:** assets call `pipeline.X` with "no
  logic duplicated". Keep `tree_index_document` a shell over `pipeline.tree_index.tree_index()`.
- **Deterministic-first constraint:** free heuristic mode before paid LLM mode —
  applied here as deterministic default + budget-gated opt-in LLM.

### Integration Points
- New module `src/knowledge_lake/pipeline/tree_index.py` (mirrors `chunk.py`).
- New builtin `src/knowledge_lake/plugins/builtin/pageindex_indexer.py`.
- New `TreeNode` / `TreeIndex` / `IndexerPlugin` in `plugins/protocols.py`.
- New `tree_index_document` asset in `dagster_defs/assets.py` (Dagster code-location
  reload required for the new asset to appear — see memory note).
- New `TreeSettings` in `config/settings.py`; wire into `Settings`.
- Registry: reuse `registry_repo.get_artifact_by_hash` / artifact-register helpers;
  **zero Alembic migrations** (research-confirmed).

</code_context>

<specifics>
## Specific Ideas

- PageIndex uses LiteLLM internally — natively compatible with the LLM-gateway
  constraint (all model calls through LiteLLM). Keep it that way; do not let the
  plugin open direct provider SDK calls.
- Deterministic mode must be **reproducible and free** — no network, no LLM, no
  clock/randomness in the tree it produces for a given `ParsedDoc`.

</specifics>

<deferred>
## Deferred Ideas

- **Tree schema versioning + migration strategy (TREE-06)** — deferred to v2.6+
  (STATE.md deferred table). `schema_version` field is written now so future
  migration has an anchor, but no migration logic this phase.
- **PageIndex File System / corpus-level meta-tree (TREE-07)** — deferred to v2.6+.
- **Tree *retrieval* / traversal** — Phase 14 (RETR-04…08). Do not build search here.
- **RAPTOR-style bottom-up construction** — deferred to v2.6+ per research.

</deferred>

---

*Phase: 13-tree-index-foundation*
*Context gathered: 2026-07-13*
