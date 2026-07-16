---
gsd_state_version: 1.0
milestone: v2.6
milestone_name: Data Quality & Enrichment
current_phase: 17
current_phase_name: Close the Bypass + Measurement
status: Planning complete — ready for execution
stopped_at: Phase 19 context gathered
last_updated: "2026-07-16T02:50:29.656Z"
last_activity: 2026-07-15
last_activity_desc: v2.6 requirements defined, roadmap created
progress:
  total_phases: 5
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-15)

**Core value:** Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.
**Current focus:** v2.6 — Data Quality & Enrichment (Phases 17–21). Requirements: `.planning/REQUIREMENTS.md`. Ready for `/gsd-plan-phase 17`.

## Current Position

Phase: 17 — Close the Bypass + Measurement
Plan: —
Status: Planning complete — ready for execution
Last activity: 2026-07-15 — v2.6 requirements defined, roadmap created

## Performance Metrics

**Velocity:**

- Total plans completed: 77 (v1.0: 25, v2.0: 38, v2.5: 14)
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

| ID | Decision | Rationale | Date |
|----|----------|-----------|------|
| D-1 | Crawler extraction DEFERRED | No-op today (bronze is dead-end, nothing reads it); section classifier covers superset; Crawl4AI bug #582 strips bolded drug names | 2026-07-15 |
| D-2 | Forward-only CONFIRMED | Existing data is test data; fresh stack via `docker compose down -v` before production use | 2026-07-15 |
| D-3 | Dedup at index time (after L3) | Dedup before substance gate makes BM25 worse (IDF inversion); most duplicates are boilerplate removed by L3 anyway | 2026-07-15 |
| D-4 | No FilterPlugin seam | DataTrove called directly (precedent: `curate.py:119`); variability is by domain not tool — use domain-pack rail | 2026-07-15 |
| D-5 | 30-char floor rejected | Wrong unit (token-based system), wrong target (kills ICD codes, dosage instructions); use composite predicate with domain allowlist | 2026-07-15 |

### Pending Todos

None yet.

### Blockers/Concerns

**Open — carried into v2.6:**

- [v2.6 driver]: The clean stage is architecturally bypassed — `clean_document` forwards the *uncleaned* `parsed_doc` to `chunk_document` / `tree_index_document` / `enrich_document`, so boilerplate removal reaches only the pretrain path. Root cause of ~28% garbage chunks and 33% unusable gold RAG corpus. See `.planning/MILESTONE-CONTEXT.md`.
- [Tech debt, CR-01]: MCP `_search_handler` uses `hasattr(h, "_asdict")`, always False for dataclasses — crashes on non-empty results. Needs `dataclasses.asdict(h)`. **MCP search is unusable in production until fixed.**
- [Tech debt, CR-02]: `mode` param dual-semantics — `?mode=hybrid&route=tree` passes API validation but reaches `tree_search()` with an invalid value; needs a split into `mode`/`tree_mode`.
- [Tech debt]: Domain path-traversal regex has 3 independent copies (`domains/loader.py`, `api/app.py`, `pipeline/domains.py`) — if one drifts, the guards diverge.
- [Tech debt]: `sources.config["domain"]` is still dual-written alongside the new column — remove the dual-write.
- [Tech debt, KL-16]: Domain packs cannot contribute Dagster jobs without editing framework source. Only the misleading `healthcare_e2e_job` name was fixed.
- [Tech debt]: `st_embedder.py` uses a module constant `_LITELLM_ALIAS` rather than settings — an alias not a provider ID, so the LLM-gateway constraint holds, but it is the one alias that isn't configurable.
- [Phase 13]: PageIndex pinned to pre-release `0.3.0.dev3` — API may change; vendoring fallback plan exists but is untested.
- [Phase 14]: Tree traversal prompt quality unvalidated — no ground-truth benchmarks for the healthcare domain.
- [Phase 16]: Entity cross-link IDF threshold needs empirical tuning for useful link density.
- [Wart, KL-01]: `_unclassified` still labels an all-domain export (`domain=None` means "no filter, all domains").

**Standing gotchas — do not relearn these:**

- `pipeline/route.py` binds `search` at import time (`from ... import search`), so patching `pipeline.search.search` never affects `routed_search` — patch `pipeline.route.search`. This silently neutered 4 tests (KL-19).
- `xfail_strict = true` is active. Any test that passes while marked xfail fails the build. Never add an xfail marker to make a red test go away — a stale marker is exactly what hid two API endpoints returning 500s for months.
- Keep the Docker base pinned to `.python-version`. A `python:3.14-slim` base that could not build left a 13-day-old image silently serving, which is why the 500s stayed invisible. `/health` now reports the running version.
- Dagster code-location reload is required after `definitions.py` changes for new assets/sensors to appear in the live daemon.
- `docs/openapi.json` must be regenerated after adding any API endpoint (determinism gate: `test_openapi_export.py`).

**Resolved in v2.5 (2026-07-15):** E2E gap analysis CLOSED — all 19 findings resolved (see `.planning/milestones/v2.5-E2E-GAP-ANALYSIS.md`). Includes KL-18 (three endpoints returning 500 via `DetachedInstanceError`), the Dockerfile landmine, and parse section persistence (the section-less path was collapsing 38 sections into 1 chunk; now 51 per-section chunks, ~30x faster). Suite: 971 passed, 0 failed.

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

Last session: 2026-07-16T02:50:29.645Z
Stopped at: Phase 19 context gathered
Resume file: .planning/phases/19-section-classifier-patterns/19-CONTEXT.md

## Operator Next Steps

- Begin execution with `/gsd-plan-phase 17` (Close the Bypass + Measurement)
- Phase 18 (Gate Decouple) is parallelizable with 17 if desired
