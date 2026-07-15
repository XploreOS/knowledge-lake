---
gsd_state_version: 1.0
milestone: v2.5
milestone_name: PageIndex Plugin Integration
status: Awaiting next milestone
stopped_at: Phase 16 context gathered
last_updated: "2026-07-15T15:27:48.115Z"
last_activity: 2026-07-15
last_activity_desc: Milestone v2.5 completed and archived
progress:
  total_phases: 4
  completed_phases: 4
  total_plans: 14
  completed_plans: 14
  percent: 100
current_phase: 15
current_phase_name: Query Router
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-14)

**Core value:** Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.
**Current focus:** Phase 16 — openkb-export

## Current Position

Phase: Milestone v2.5 complete
Plan: —
Status: Awaiting next milestone
Last activity: 2026-07-15 — Milestone v2.5 completed and archived

## Performance Metrics

**Velocity:**

- Total plans completed: 52 (v1.0 + v2.0)
- Average duration: ~10 min
- Total execution time: --

**By Phase (v2.0):**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 7 | 4 | ~12m | ~3m |
| 8 | 6 | ~105m | ~18m |
| 9 | 6 | ~78m | ~13m |
| 10 | 8 | ~56m | ~7m |
| 11 | 6 | ~19m | ~3m |
| 12 | 8 | ~56m | ~7m |
| 13 | 6 | - | - |
| 15 | 2 | - | - |
| 16 | 2 | - | - |
| 14 | 4 | - | - |

**Recent Trend:**

- Last 5 plans: 15m, 3m, 12m, 15m, 10m
- Trend: Stable

*Updated after each plan completion*
| Phase 13 P01 | 8min | 2 tasks | 3 files |
| Phase 13 P02 | 4min | 3 tasks | 3 files |
| Phase 13 P03 | 6 | 1 tasks | 2 files |
| Phase 13 P04 | 12min | 1 tasks | 1 files |
| Phase 13 P05 | 4min | 1 tasks | 4 files |
| Phase 13 P06 | 4min | 2 tasks | 2 files |
| Phase 14 P01 | 15min | 2 tasks | 2 files |
| Phase 14 P02 | 12min | 2 tasks | 2 files |
| Phase 14 P03 | 25min | 2 tasks | 4 files |
| Phase 14 P04 | 8min | 2 tasks | 2 files |
| Phase 16 P02 | 5min | 2 tasks | 5 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap v2.5]: 4-phase structure derived from requirement categories (Tree Index -> Tree Retrieval -> Query Router -> OpenKB Export); each boundary is a hard dependency (cannot search trees that don't exist; cannot route to search that doesn't exist)
- [Roadmap v2.5]: Phase 16 (OpenKB) depends on Phase 13 only (needs tree indexes + enrichment metadata) — independent of Phases 14-15
- [Roadmap v2.5]: Deterministic-first constraint applied: Phase 13 builds heuristic tree indexing before LLM mode; Phase 14 builds keyword traversal before LLM-guided; Phase 15 builds heuristic routing before any LLM routing (deferred to v2.6+)
- [Phase ?]: Wave 0 test scaffold in RED state: 6 tree-index tests, 2 asset tests, 2 IndexerPlugin conformance stubs fail with ImportError until Wave 1/2 ships — Nyquist compliance — all Wave 1/2 implementation tasks have automated verify targets before code is written
- [Phase ?]: TreeNode.level and page_end are DERIVED by builder — Section has no level/page_end (Finding 1 in 13-RESEARCH.md)
- [Phase ?]: indexer added to _validate_swap_key ASVS V5 regex to prevent malicious entry-point names (T-13-03 mitigated)
- [Phase ?]: test
- [Phase ?]: mime_type defaults to application/json
- [Phase ?]: No Alembic migration for tree_index artifact_type
- [Phase 13]: tree_index_document is a thin shell over pipeline.tree_index.tree_index() — no logic duplicated (TREE-05)
- [Phase 13]: healthcare_e2e_job asset selection unchanged — Assumption A6 excludes non-core assets from the 7-asset E2E job
- [Phase 13]: Dagster code-location reload required after definitions.py change for asset to appear in live daemon
- [Phase 14]: Reused test_tree_index.py's DB fixtures verbatim (StaticPool in-memory SQLite, _patch_engine autouse) for the Wave 0 tree_search scaffold
- [Phase 14]: hand_tree fixture titles/summaries deliberately chosen so query 'budget cap' matches sec1/sec1.1 but not sec2, for deterministic heuristic-scoring ground truth
- [Phase ?]: No TreeHit type added — Hit reused directly per D-01 (overrides ARCHITECTURE.md TreeHit sketch)
- [Phase ?]: model_alias added to TreeSearchSettings beyond D-12 literal field list per Assumption A1 (needed for D-06 LLM-nav cheap_model alias)
- [Phase ?]: retriever added to _validate_swap_key ASVS V5 validator tuple per Assumption A2, mirroring T-13-03
- [Phase 14]: PageIndexRetriever computes heuristic Hits first regardless of mode, so LLM-nav always has an identical fallback (A4)
- [Phase 14]: LLM-nav spend isolated to scope=tree_search, distinct from Phase-13 tree_index and global scopes (D-07)
- [Phase 14]: LLM-nav reorders heuristic Hits by validated node_ids rather than replacing them - invalid/unknown node_ids discarded, unmentioned heuristic hits kept at the end
- [Phase 14]: tree_search() adds a max_docs kwarg (beyond top_k/mode/collection/settings) mirroring the per-request settings-override pattern, required by the test suite's shortlisting calls
- [Phase 14]: tree_search.py imports search() and StorageBackend at module level (not lazily) so tests can patch tree_search_module.search / .StorageBackend directly, mirroring tree_index.py's import style
- [Phase 15]: routed_search() plain function (not QueryRouter class) — function-over-class convention, simpler alias handling
- [Phase 15]: default_route="auto" (classifier-driven) — ops rollback is KLAKE_ROUTER__DEFAULT_ROUTE=chunk (no code change)
- [Phase 15]: MCP _search_handler uses `hasattr(h, "_asdict")` which is always False for dataclasses — CR-01 crash on non-empty results; fix: `dataclasses.asdict(h)`
- [Phase 15]: mode param forwarded to both search() and tree_search() creates dual-semantics bug (CR-02) — needs split into mode/tree_mode
- [Phase ?]: Lazy import compile_wiki inside CLI/API body — consistent with cmd_export pattern
- [Phase ?]: docs/openapi.json must be regenerated after adding new API endpoint (determinism gate test_openapi_export.py)

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 13]: PageIndex pinned to pre-release 0.3.0.dev3 — API may change; vendoring fallback plan exists but untested
- [Phase 14]: Tree traversal prompt quality unvalidated — no ground-truth benchmarks for healthcare domain
- [Phase 14]: Two-stage search latency (3-15s without parallelization) — async loading + concurrency limit needed
- [Phase 15]: CR-01 MCP _search_handler crashes on non-empty results — needs `dataclasses.asdict(h)` fix before MCP search is usable in production
- [Phase 15]: CR-02 mode param dual-semantics — `?mode=hybrid&route=tree` passes API validation but hits tree_search() with invalid value; needs split into mode/tree_mode
- [Phase 16]: Entity cross-link IDF threshold needs empirical tuning for useful link density
- [Audit 2026-07-15]: E2E gap analysis **CLOSED** — see [.planning/E2E-GAP-ANALYSIS.md](./E2E-GAP-ANALYSIS.md). **All 19 findings resolved** (17 original + 2 found during remediation). Also fixed beyond the findings: the Dockerfile landmine (CI now builds the api image) and parse section persistence. Suite: 971 passed, 0 xpassed, 0 failed, 0 errors.
- [KL-18 resolved 2026-07-15]: `/documents`, `/datasets` AND `/curated-documents` returned 500 (`DetachedInstanceError` — responses built after `get_session()` committed and expired the instances). Fixed at the three call sites. Probing every route found the third endpoint, which had no test at all. All GET routes now 5xx-free.
- **[Dockerfile landmine, fixed 2026-07-15]**: the base image had been bumped to `python:3.14-slim`, which **cannot build** (greenlet has no CPython 3.14 support), and `COPY` omitted `LICENSE`/`NOTICE`. The api image was therefore un-rebuildable, and `docker compose up -d` silently kept a 13-day-old image alive — that is the real reason KL-08 happened, and why KL-18 stayed invisible. Base is back to `python:3.12-slim`; `./src` is now bind-mounted and `/health` reports the running version. Keep the base pinned to `.python-version`.
- [Parse sidecar, added 2026-07-15]: `parse()` writes a JSON sections sidecar to the **silver** zone (S3, never Postgres — `Section` carries `text`, so sections are the whole document body). `chunk`/`tree-index` read it and fall back to re-parsing for pre-sidecar artifacts. This fixed a worse bug than recorded: the old section-less path collapsed **38 sections into 1 chunk**; now 51 real per-section chunks, ~30x faster (43s -> 1.4s).
- [Follow-ups, open — all minor]: (1) the domain path-traversal regex still has 3 independent copies (`domains/loader.py`, `api/app.py`, `pipeline/domains.py`) — if one drifts the guards diverge; (2) `st_embedder.py` uses a module constant `_LITELLM_ALIAS` rather than settings — an alias not a provider ID, so the constraint holds, but it's the one alias that isn't configurable; (3) `sources.config["domain"]` is still dual-written alongside the new column — remove the dual-write next release; (4) domain packs still cannot contribute Dagster jobs (KL-16's deferred gap).
- [Testing gotcha, learned 2026-07-15]: `pipeline/route.py` binds `search` at import time (`from ... import search`), so patching `pipeline.search.search` never affects `routed_search` — patch `pipeline.route.search` instead. This silently neutered 4 tests (KL-19).
- [KL-16 deferred]: domain packs still cannot contribute Dagster jobs without editing framework source — roadmap item. Only the misleading `healthcare_e2e_job` name was fixed.
- [KL-01 decision, 2026-07-15]: `domain=` on exports **filters rows**, it does not merely label the output path. `domain=None` remains "no filter, all domains, `_unclassified` path" — pinned by regression test. Known deferred wart: `_unclassified` still labels an all-domain export.
- [Testing, 2026-07-15]: `xfail_strict = true` is now active. Any test that passes while marked xfail fails the build. Do not add an xfail marker to make a red test go away — a stale marker is exactly what hid KL-18 (two API endpoints returning 500) for months.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260715-3w5 | Write E2E gap analysis report | 2026-07-15 | 9d1666e | [260715-3w5-write-e2e-gap-analysis-report](./quick/260715-3w5-write-e2e-gap-analysis-report/) |
| 260715-4b9 | Fix CI integration tests (KL-03) and add aviation reference pack | 2026-07-15 | ea14046 | [260715-4b9-fix-ci-integration-tests-kl-03-and-add-a](./quick/260715-4b9-fix-ci-integration-tests-kl-03-and-add-a/) |
| 260715-51d | Fix KL-01 domain filtering in exports and KL-02 LLM pricing | 2026-07-15 | 6ea82c2 | [260715-51d-fix-kl-01-domain-filtering-in-exports-an](./quick/260715-51d-fix-kl-01-domain-filtering-in-exports-an/) |
| 260715-5pb | Fix KL-07, KL-04/05/06, KL-11, KL-16, KL-10 | 2026-07-15 | bf8b6ac | [260715-5pb-fix-kl-07-kl-04-05-06-kl-11-kl-16-kl-10](./quick/260715-5pb-fix-kl-07-kl-04-05-06-kl-11-kl-16-kl-10/) |
| 260715-bgt | Fix KL-18 detached-session 500s, KL-08 stale container, KL-09 tree-index CLI | 2026-07-15 | b974337 | [260715-bgt-fix-kl-18-detached-session-500s-kl-08-st](./quick/260715-bgt-fix-kl-18-detached-session-500s-kl-08-st/) |
| 260715-chy | Fix remaining low findings, CI image build guard, parse section persistence | 2026-07-15 | 1c0159f | [260715-chy-fix-remaining-low-findings-ci-image-buil](./quick/260715-chy-fix-remaining-low-findings-ci-image-buil/) |

## Deferred Items

Items acknowledged and carried forward:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Eval & Observability | EVAL-01/02 (RAGAS, Langfuse) | Deferred | v2.0 planning |
| Client & Domain Packs | SDK-01, DOMAIN-05/06 | Deferred | v2.0 planning |
| Discovery / UI / Versioning | DISCOVER-01, UI-02, VERSION-01 | Deferred | v2.0 planning |
| Crawl & Retrieval | SITEMAP-01, QUALITY-01 | Deferred | v2.0 planning |
| Enhanced Routing | ROUTE-05/06 (LLM routing, telemetry) | Deferred | v2.5 planning |
| OpenKB Advanced | KB-06/07/08 (watch mode, lint, chat) | Deferred | v2.5 planning |
| Tree Enhancements | TREE-06/07 (schema versioning, meta-tree) | Deferred | v2.5 planning |

## Session Continuity

Last session: 2026-07-14T07:11:17.707Z
Stopped at: Phase 16 context gathered
Resume file: .planning/phases/16-openkb-export/16-CONTEXT.md

## Operator Next Steps

- Start the next milestone with /gsd-new-milestone
