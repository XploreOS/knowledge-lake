---
phase: 14-tree-retrieval
reviewed: 2026-07-14T00:00:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - src/knowledge_lake/cli/app.py
  - src/knowledge_lake/config/settings.py
  - src/knowledge_lake/pipeline/tree_search.py
  - src/knowledge_lake/plugins/builtin/__init__.py
  - src/knowledge_lake/plugins/builtin/pageindex_retriever.py
  - src/knowledge_lake/plugins/protocols.py
  - src/knowledge_lake/plugins/resolver.py
findings:
  critical: 1
  warning: 4
  info: 3
  total: 8
status: issues_found
---

# Phase 14: Code Review Report

**Reviewed:** 2026-07-14T00:00:00Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Reviewed the Phase 14 tree-retrieval seam: the two-stage `tree_search()` orchestrator, the
built-in `PageIndexRetriever` (heuristic + opt-in LLM-nav), the `RetrieverPlugin` protocol/`Hit`
additions, the resolver wiring, `TreeSearchSettings`, and the `klake tree-search` CLI shim.

The module's own docstring makes an explicit contract: `tree_search()` "never raises on a
missing tree_index artifact or a failed tree load ... a document simply contributes no Hits in
that case." That contract is violated in one concrete spot (CR-01) — a malformed or absent
`storage_uri` on a resolved `tree_index` artifact crashes the whole call instead of being
skipped like every other per-document failure path already is (parse failure, load failure,
missing artifact). Beyond that, the LLM-nav mode has a design/data-flow bug that undermines its
own stated purpose (WR-02), and cost tracking for that mode silently never uses the project's
established, more accurate cost helper (WR-01). Several smaller robustness/consistency gaps are
listed as warnings and info.

## Critical Issues

### CR-01: Unhandled exception on malformed/missing tree_index storage_uri crashes the entire query

**File:** `src/knowledge_lake/pipeline/tree_search.py:190-199`
**Issue:**

```python
with get_session() as session:
    for parsed_id in top_docs:
        artifact = registry_repo.get_child_artifact_by_type(
            session, parsed_id, "tree_index"
        )
        if artifact is None:
            log.info("tree_search.no_tree_index", document=parsed_id)
            continue
        resolved.append((parsed_id, uri_to_key(artifact.storage_uri)))
```

`registry_repo.create_tree_index_artifact()` (`registry/repo.py:306-336`) declares
`storage_uri: str | None = None` — it is a legitimately optional field, not guaranteed
non-null for every persisted `tree_index` row (e.g. a partially-written row, a future code
path, or DB-level corruption). `uri_to_key()` (`pipeline/utils.py:11-34`) calls
`uri.startswith("s3://")` with no `None` guard: if `storage_uri` is `None`, this raises
`AttributeError: 'NoneType' object has no attribute 'startswith'`; if it's a non-`s3://`
string, `uri_to_key` raises `ValueError`. Neither is caught here.

This is a real contradiction of the function's documented invariant. Every *other* per-document
failure path in this same module is defensively wrapped (missing artifact → `continue`; S3 load
failure → caught in `_load_all` and represented as `None`; malformed tree JSON → caught around
`orjson.loads`/`_dict_to_tree_index`). This one path is not, and because it executes inside the
shared `for parsed_id in top_docs:` loop rather than per-document error isolation, one bad
artifact aborts resolution for *all* other shortlisted documents too — turning a single
bad row into a total query failure instead of a partial-result degrade, and propagating an
uncaught exception all the way to the CLI (`klake tree-search` would print a raw traceback,
not the graceful "no results" message the design promises).

**Fix:**
```python
with get_session() as session:
    for parsed_id in top_docs:
        artifact = registry_repo.get_child_artifact_by_type(
            session, parsed_id, "tree_index"
        )
        if artifact is None:
            log.info("tree_search.no_tree_index", document=parsed_id)
            continue
        try:
            key = uri_to_key(artifact.storage_uri)
        except (ValueError, AttributeError) as exc:
            log.warning(
                "tree_search.bad_storage_uri",
                document=parsed_id,
                storage_uri=artifact.storage_uri,
                error=str(exc),
            )
            continue
        resolved.append((parsed_id, key))
```

## Warnings

### WR-01: LLM-nav cost extraction reimplements — and breaks — the project's shared cost helper

**File:** `src/knowledge_lake/plugins/builtin/pageindex_retriever.py:313-328`
**Issue:** `PageIndexRetriever._extract_cost` duplicates cost-computation logic instead of
calling the existing, tested `knowledge_lake.llm.pricing.compute_call_cost()` (used elsewhere,
e.g. `enrich.py`/`tree_index.py`), which tries `litellm.completion_cost()` first (accurate,
works once `bootstrap_llm_pricing()` has registered the project's Bedrock model IDs) and only
falls back to a token-count estimate on failure.

Here, `_extract_cost` instead checks `getattr(usage, "total_cost", None)` — a `litellm` chat
completion response's `.usage` object (a standard `Usage`/`CompletionUsage` object with
`prompt_tokens`/`completion_tokens`/`total_tokens`) does not carry a `total_cost` attribute in
practice, so that branch is effectively dead code. The function therefore *always* falls
through to the cruder per-1k-token fallback estimate (`s.enrich.fallback_cost_per_1k_input/output`)
even though `bootstrap_llm_pricing()` has already registered accurate per-token pricing for
exactly this purpose. This means the `tree_search.budget_usd` cap (D-06/D-07) is enforced
against a systematically less-accurate cost figure than every other budget-gated LLM call in
the codebase, and the logic is duplicated instead of reused (maintenance hazard — a future
pricing fix in `llm/pricing.py` will not apply here).

**Fix:**
```python
from knowledge_lake.llm.pricing import compute_call_cost

@staticmethod
def _extract_cost(response: Any, s: Any) -> float:
    return compute_call_cost(response, s)
```
(Remove the bespoke `usage.total_cost` / manual token-math branch entirely.)

### WR-02: LLM-nav mode can only reorder already-truncated top-k candidates — defeats its purpose

**File:** `src/knowledge_lake/plugins/builtin/pageindex_retriever.py:204-213, 249-257`
**Issue:**
```python
heuristic_hits = self._heuristic_hits(tree_index, terms)[:top_k]   # line 208 — truncated!
if mode != "llm":
    return heuristic_hits
return self._llm_nav_search(tree_index, terms, heuristic_hits, top_k, settings)
```
```python
all_nodes = list(_iter_nodes(tree_index.roots))                    # line 252 — ALL nodes
...
heuristic_by_id = {h.id: h for h in heuristic_hits}                 # only top_k entries
for node_id in validated.node_ids:
    ...
    hit = heuristic_by_id.get(node_id)
    if hit is not None and hit not in ordered:
        ordered.append(hit)
```
`_llm_nav_search` builds its prompt from *every* node in the tree (`all_nodes`), giving the LLM
visibility into the full document structure — but it can only select/reorder Hits that already
survived the keyword-overlap `top_k` truncation performed *before* the LLM ever runs
(`heuristic_by_id` only contains the pre-truncated `top_k` hits). Any node the LLM judges highly
relevant from its full-tree view, but which ranked below `top_k` on raw keyword overlap (a
classic case an LLM is supposed to fix — e.g. synonym/paraphrase matches with zero literal
keyword overlap), is silently dropped by the `if hit is not None` check and can never appear in
the final result. In effect, "opt-in LLM-guided navigation" (RETR-06) can only ever *re-order*
the same `top_k` set the pure-heuristic mode already returns — it can add no value beyond
re-ranking a fixed, keyword-only-selected shortlist, despite the cost/latency/budget spend of a
real LLM call.

**Fix:** Pass a wider candidate pool into `_llm_nav_search` (e.g. all non-zero-score heuristic
hits, or `top_k * N` for a reasonable `N`) and only truncate to the caller's `top_k` *after* the
LLM has re-ranked:
```python
candidate_pool = self._heuristic_hits(tree_index, terms)   # untruncated
heuristic_hits = candidate_pool[:top_k]
if mode != "llm":
    return heuristic_hits
return self._llm_nav_search(tree_index, terms, candidate_pool, top_k, settings)[:top_k]
```

### WR-03: `asyncio.run()` in a sync function has no running-loop guard

**File:** `src/knowledge_lake/pipeline/tree_search.py:210`
**Issue:** `tree_search()` is a plain synchronous function that calls
`asyncio.run(_load_all(...))` internally. `asyncio.run()` raises
`RuntimeError: asyncio.run() cannot be called from a running event loop` if invoked while an
event loop is already running. The module docstring itself flags this as a fragile invariant
("CR-02: never nest that entry point ... a future async caller ... should await `_load_all()`
directly instead of calling `tree_search()` from within a running loop") — i.e. the authors know
this will break, but there is no defensive check in the code, only a comment. Today's only
caller (`cmd_tree_search` in `cli/app.py`) is safely synchronous, but the MCP stdio server
already runs a top-level event loop (`anyio.run(run_stdio, ...)` in `cli/app.py:1211`) and the
FastAPI app is async — the moment either surface adds a tool/endpoint that calls
`tree_search()` directly (a very plausible next step, given `search()` is already exposed via
`agent/registry.py`), this will crash at runtime with an unhelpful low-level asyncio error
instead of a clear, actionable message.
**Fix:** Add a defensive check that fails with a clear error rather than an opaque asyncio
traceback:
```python
try:
    asyncio.get_running_loop()
except RuntimeError:
    pass
else:
    raise RuntimeError(
        "tree_search() cannot be called from within a running event loop; "
        "await _load_all() directly instead (see module docstring, CR-02)."
    )
raw_blobs = asyncio.run(_load_all(keys, storage, s.tree_search.concurrency))
```

### WR-04: Unbounded node count/prompt size sent to the LLM in nav mode

**File:** `src/knowledge_lake/plugins/builtin/pageindex_retriever.py:252-257`
**Issue:** `NavResult.node_ids` bounds the *response* size (`max_length=_MAX_NAV_NODE_IDS = 50`),
but there is no corresponding bound on the *request* side: `all_nodes = list(_iter_nodes(tree_index.roots))`
iterates every node in the tree with no cap, and `node_summaries_blob` concatenates a
(per-node-capped) line for each of them with no total-count or total-length limit. For a
large/deeply-nested document tree (which is exactly the kind of document this feature targets),
this can produce a very large prompt that either fails outright against the model's context
window or silently inflates cost per call — undermining the `budget_usd` cap's intent, since a
single call could consume a large fraction of the budget before the next check.
**Fix:** Cap `all_nodes` (e.g. take the top-N nodes by heuristic score, or hard-cap total node
count/characters) before building `node_summaries_blob`, mirroring the existing
`_NODE_EXCERPT_CHARS` per-node cap and `_MAX_NAV_NODE_IDS` response cap.

## Info

### IN-01: `klake tree-search --top-k` has no bounds validation

**File:** `src/knowledge_lake/cli/app.py:738-741`
**Issue:** Unlike `--limit` on `discover` (`min=1, max=100`), `--top-k` on `tree-search` (and on
`search`, pre-existing) accepts any integer, including 0 or negative values. A negative
`top_k` flows into `results[:effective_top_k]` in `tree_search.py`, which silently drops
elements from the end rather than erroring — confusing behavior for a CLI user who fat-fingers
`-k -5`.
**Fix:** Add `min=1` to the `--top-k` Typer option (mirrors the `discover` command's pattern).

### IN-02: `tree_search()` assumes a unique `tree_index` child per document; resolution order isn't guaranteed

**File:** `src/knowledge_lake/pipeline/tree_search.py:193-199`
**Issue:** `registry_repo.get_child_artifact_by_type(session, parsed_id, "tree_index")` selects
with `.limit(1)` and no `ORDER BY`. If more than one `tree_index` artifact ever exists for the
same parsed document (e.g. a document indexed once in `deterministic` mode and later re-indexed
in `llm` mode — each produces a distinct `content_hash` and thus a distinct artifact row per
`tree_index.py`'s dedup-by-hash logic), which row is returned is not deterministic at the SQL
level. `tree_search()` has no way to know or control which tree it gets. This is a
`registry/repo.py` concern (out of this phase's edited-file scope) but the risk surfaces
directly through `tree_search.py`'s assumption of a single resolvable tree per document.
**Fix:** Either add an `ORDER BY created_at DESC` (most-recent-wins) to
`get_child_artifact_by_type`, or have `tree_search.py` explicitly resolve by a documented
tie-break (e.g. prefer the mode matching `s.tree.mode`) rather than relying on incidental DB
ordering.

### IN-03: Unrecognized `mode` values silently degrade to heuristic with no warning

**File:** `src/knowledge_lake/plugins/builtin/pageindex_retriever.py:210`
**Issue:** `PageIndexRetriever.search()` does `if mode != "llm": return heuristic_hits` — any
value other than the exact literal `"llm"` (e.g. a caller typo like `"LLM"` or `"llm "`) is
silently treated as `"heuristic"` with no logging. The CLI shim validates against an explicit
`VALID_MODES` set before calling `tree_search()`, but `tree_search()`/`PageIndexRetriever.search()`
themselves are public, directly callable APIs (e.g. from `agent/registry.py`-style tool
handlers or tests) with no equivalent validation, so a bad `mode` value silently changes
behavior instead of surfacing the mistake.
**Fix:** Validate `mode` against `{"heuristic", "llm"}` at the top of `search()` and log a
warning (or raise `ValueError`) for unrecognized values instead of falling through by default.

---

_Reviewed: 2026-07-14T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
