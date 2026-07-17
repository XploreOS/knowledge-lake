---
gsd_state_version: 1.0
milestone: v2.6
milestone_name: Data Quality & Enrichment
current_phase: 20
current_phase_name: chunk-substance-gate-export-gate
status: verifying
stopped_at: Completed 20-04-PLAN.md
last_updated: "2026-07-17T06:55:50.407Z"
last_activity: 2026-07-17
last_activity_desc: Phase 20 execution started
progress:
  total_phases: 5
  completed_phases: 4
  total_plans: 13
  completed_plans: 13
  percent: 80
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-15)

**Core value:** Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.
**Current focus:** Phase 20 — chunk-substance-gate-export-gate

## Current Position

Phase: 20 (chunk-substance-gate-export-gate) — EXECUTING
Plan: 4 of 4
Status: Phase complete — ready for verification
Last activity: 2026-07-17 — Phase 20 execution started

## Performance Metrics

**Velocity:**

- Total plans completed: 61 (v1.0: 25, v2.0: 38, v2.5: 14)
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
| 17 | 4 | - | - |
| 18 | 1 | - | - |
| 19 | 4 | - | - |

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
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 17 P01 | 13min | 2 tasks | 2 files |
| Phase 17 P02 | 6min | 2 tasks | 2 files |
| Phase 17 P03 | 8min | 2 tasks | 2 files |
| Phase 17 P04 | 6min | 2 tasks | 4 files |
| Phase 18 P01 | 4min | 2 tasks | 2 files |
| Phase 19 P01 | 6 min | 2 tasks | 4 files |
| Phase 19 P02 | 8min | 2 tasks | 4 files |
| Phase 19 P03 | 6min | 2 tasks | 2 files |
| Phase 19 P04 | 12 min | 2 tasks | 2 files |
| Phase 20 P01 | 13min | 3 tasks | 4 files |
| Phase 20 P02 | 6min | 3 tasks | 4 files |
| Phase 20 P03 | ~40min (session-interrupted, resumed) | 2 tasks | 4 files |
| Phase 20 P04 | 10min | 2 tasks | 2 files |

## Accumulated Context

### Decisions

| ID | Decision | Rationale | Date |
|----|----------|-----------|------|
| D-1 | Crawler extraction DEFERRED | No-op today (bronze is dead-end, nothing reads it); section classifier covers superset; Crawl4AI bug #582 strips bolded drug names | 2026-07-15 |
| D-2 | Forward-only CONFIRMED | Existing data is test data; fresh stack via `docker compose down -v` before production use | 2026-07-15 |
| D-3 | Dedup at index time (after L3) | Dedup before substance gate makes BM25 worse (IDF inversion); most duplicates are boilerplate removed by L3 anyway | 2026-07-15 |
| D-4 | No FilterPlugin seam | DataTrove called directly (precedent: `curate.py:119`); variability is by domain not tool — use domain-pack rail | 2026-07-15 |
| D-5 | 30-char floor rejected | Wrong unit (token-based system), wrong target (kills ICD codes, dosage instructions); use composite predicate with domain allowlist | 2026-07-15 |

- [Phase ?]: Split plan's two tightly-coupled tasks (WR-05 hash + parsed_doc forwarding vs conservation invariant) into 4 TDD commits instead of 1 combined commit, while still shipping CLEAN-01/CLEAN-03 together in Task 1 per RESEARCH.md Pitfall 1
- [Phase ?]: Task 2 (tdd=true) proves behavior Task 1 already implemented — test passed on first run by plan design, not a stale/no-op test (see 17-02-SUMMARY.md TDD Gate Compliance)
- [Phase ?]: Patched source modules (parse/clean/chunk/embed/index) not the consuming process.py namespace, since process_crawled uses function-local imports — the route.py module-level-import gotcha doesn't apply here
- [Phase ?]: Split Task 1 (tdd=true) into true RED/GREEN commits and Task 2's boundary tests into a separate immediately-green commit, matching plan task boundaries
- [Phase ?]: Patched source modules (pipeline.parse, pipeline.clean, pipeline.quality_audit) rather than the importer's namespace since quality_audit.py and cmd_quality_audit both use function-local imports — the mirror image of the route.py module-level-import gotcha
- [Phase ?]: GATE-01: Gate boilerplate patterns frozen as static copy in crawl.py; Phase 19 BOILERPLATE_PATTERNS extensions will not alter stored source signatures or trigger spurious re-crawls
- [Phase 19 P01]: pipeline/quality/ duplicates tiktoken token_count() locally instead of importing pipeline.chunk (which pulls registry.db/storage.s3 at module scope), mirroring crawl.py's GATE-01 duplication-for-isolation precedent — keeps QUAL-01's zero-I/O contract intact
- [Phase 19 P01]: Added check_terminal_punct_ratio as a 7th predicate beyond D-11's named six, to satisfy D-03's explicit substance-threshold description; documented as a non-exhaustive reading of D-11 in predicates.py's module docstring
- [Phase 19 P01]: Zero-I/O import-boundary test runs in a subprocess, not in-process sys.modules inspection — tests/conftest.py's autouse _clear_settings_cache fixture imports registry.db/sqlalchemy before every test body, which would always fail an in-process check regardless of pipeline.quality's actual behavior
- [Phase 19 P02]: DomainLoader.filters (DomainFilters | None) added as an explicit optional-load branch (step 3b) that never raises FileNotFoundError for filters.yaml's absence — the one exception to the four mandatory-file raise-on-missing convention in DomainLoader.__init__
- [Phase 19 P02]: DomainFilters.thresholds validated but intentionally unconsumed by classify_sections() in Phase 19 (RESEARCH.md Assumptions Log A3) — reserved field for a future phase's override-vs-compose semantics, avoiding a schema-breaking change later
- [Phase 19]: BOILERPLATE_PATTERNS extended additively via a single .extend() call (4->9 entries); gov-disclaimer pattern anchored to specific multi-word phrases only, not a bare disclaimer/warning keyword, to keep genuine clinical safety text intact — Preserves byte-identical indices 0-3 so the Phase 18 frozen gate signature (crawl.py) stays decoupled; regression-tested against a realistic clinical disclaimer sentence
- [Phase 19]: [Phase 19 P04] Kept-section annotations reuse classification["reason"] (e.g. "substance_ok" or the allowlist match reason) rather than inventing a new literal for the kept branch — The plan's "reason string used for that branch" language only names explicit reason strings for the two rejection branches (empty_after_boilerplate_removal, classified_as_boilerplate) — reusing classify_sections()'s own computed reason for the kept branch keeps the annotation coherent and non-redundant.
- [Phase 19]: [Phase 19 P04] TDD RED phase tested classify_sections() directly (pure-function contract) rather than duplicating Task 2's clean()-level acceptance tests — Keeps the RED/GREEN cycle focused on the new function's own contract (nav vs. clinical classification, allowlist override) while Task 2 separately adds the full clean()-level integration tests as ordinary test additions, per the plan's task split.
- [Phase ?]: 20-01: Extracted _apply_substance_gate() as a pure DB-free helper for independent unit-testability, rather than inlining gate logic directly in chunk()'s persistence loop
- [Phase ?]: 20-01: ChunkQualitySettings.filter_config_version defaults to '1.0' (distinct from CurateSettings' 'v1') — chunk-gate cache is intentionally independent from document-level curation cache
- [Phase ?]: 20-02: process.py resolves domain_filters via function-local get_settings() import (matching existing local-import convention) rather than adding a settings param to process_crawled()'s public signature
- [Phase ?]: 20-02: New domain_filters wiring tests patch knowledge_lake.config.settings.get_settings and knowledge_lake.domains.loader.DomainLoader.from_name (source modules), mirroring this file's established interception pattern
- [Phase ?]: 20-03: EXPORT-02 delivered as versioning-only (payload["version"] tag), not migration — pre-Phase-20 DatasetExample rows stay unversioned until an operator re-runs the existing, unmodified `klake generate-dataset` CLI against re-processed artifacts; documented in 20-03-PLAN.md's <operational_followup> per plan-checker review
- [Phase ?]: 20-03: export_rag_corpus()'s substance_passed gate treats an explicit None the same as False (excluded) via meta.get('substance_passed', True) — deliberate, tested distinction from a missing key (defaults True/included)
- [Phase ?]: 20-03: executor session was cut off by a Claude Code usage-limit reset mid-Task-2 (RED commit landed, GREEN uncommitted); recovered by verifying the in-progress working-tree diff against Task 2's own RED tests/acceptance criteria before committing — no plan content altered
- [Phase ?]: 20-04: Every must_not_reject.yaml fixture text deliberately matches one of healthcare filters.yaml's 7 normative_allowlists patterns, making the fixture set a direct proof of Plan 20-02's DomainLoader wiring rather than relying on some entries clearing FineWebQualityFilter/threshold defaults naturally

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

Last session: 2026-07-17T06:55:50.396Z
Stopped at: Completed 20-04-PLAN.md
Resume file: None

## Operator Next Steps

- Begin execution with `/gsd-plan-phase 17` (Close the Bypass + Measurement)
- Phase 18 (Gate Decouple) is parallelizable with 17 if desired
