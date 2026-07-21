---
gsd_state_version: 1.0
milestone: v2.7
milestone_name: Governed Dataset Production and Release Lifecycle
current_phase: 23
current_phase_name: Dataset Project + Specification Foundation
status: executing
stopped_at: Completed 23-03-PLAN.md
last_updated: "2026-07-21T10:27:55.373Z"
last_activity: 2026-07-21
last_activity_desc: Phase 23 execution started
progress:
  total_phases: 10
  completed_phases: 0
  total_plans: 7
  completed_plans: 3
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-07-18)

**Core value:** Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.
**Current focus:** Phase 23 — Dataset Project + Specification Foundation

## Current Position

Phase: 23 (Dataset Project + Specification Foundation) — EXECUTING
Plan: 4 of 7
Status: Ready to execute
Last activity: 2026-07-21 — Phase 23 execution started

Progress: [████░░░░░░] 43%

## Performance Metrics

**Velocity:**

- Total plans completed: 76 (v1.0: 25, v2.0: 38, v2.5: 14)
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
| 20 | 4 | - | - |
| 21 | 8 | - | - |
| 22 | 3 | - | - |

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
| Phase 21 P01 | 12min | 2 tasks | 4 files |
| Phase 21 P02 | 5min | 2 tasks | 3 files |
| Phase 21 P03 | 8min | 2 tasks | 4 files |
| Phase 21 P04 | 9min | 2 tasks | 2 files |
| Phase 21 P05 | 11min | 2 tasks | 2 files |
| Phase 21 P06 | 8min | 1 tasks | 3 files |
| Phase 21 P07 | 7min | 2 tasks | 3 files |
| Phase 21 P08 | 18min | 2 tasks | 2 files |
| Phase 22 P01 | 16min | 2 tasks | 3 files |
| Phase 22 P02 | 6min | 1 tasks | 2 files |
| Phase 22 P03 | 73min | 1 tasks | 0 files |
| Phase quick P260718-6fu | 4min | 2 tasks | 2 files |
| Phase 23 P01 | 5min | 2 tasks | 3 files |
| Phase 23 P03 | 10min | 2 tasks | 3 files |

## Accumulated Context

### Decisions

| ID | Decision | Rationale | Date |
|----|----------|-----------|------|
| D-1 | Crawler extraction DEFERRED | No-op today (bronze is dead-end, nothing reads it); section classifier covers superset; Crawl4AI bug #582 strips bolded drug names | 2026-07-15 |
| D-2 | Forward-only CONFIRMED | Existing data is test data; fresh stack via `docker compose down -v` before production use | 2026-07-15 |
| D-3 | Dedup at index time (after L3) | Dedup before substance gate makes BM25 worse (IDF inversion); most duplicates are boilerplate removed by L3 anyway | 2026-07-15 |
| D-4 | No FilterPlugin seam | DataTrove called directly (precedent: `curate.py:119`); variability is by domain not tool — use domain-pack rail | 2026-07-15 |
| D-5 | 30-char floor rejected | Wrong unit (token-based system), wrong target (kills ICD codes, dosage instructions); use composite predicate with domain allowlist | 2026-07-15 |
| D-6 | v2.7 roadmap: 46 not 43 requirements | REQUIREMENTS.md footer said "43 total" but a direct count of `**CATEGORY-NN**` markers under `## v1 Requirements` found 46 distinct IDs; footer was stale. All 46 mapped, traceability corrected. | 2026-07-21 |
| D-7 | v2.7 roadmap: 10 phases (23-32), not the research's 11 | Merged research's separate "Validation Run/Result" phase into Phase 28 (no dedicated REQ category — QCON-02 already defines the structured outcome shape); merged reproducibility manifest into the Release phase (REL-03 already lists `reproduce.yaml` as a bundle file, so splitting REPRO into a later phase would leave Phase 30 unable to satisfy its own manifest-bundle criterion) | 2026-07-21 |
| D-8 | Flagship domain pack split into two roadmap touches | Phase 24 (early, no owned requirement) scaffolds real non-healthcare data for every later phase to build against; Phase 32 (last) formally owns FLAGSHIP-01/02 once Release + Lineage Explorer exist — matches PITFALLS.md Pitfall 9's "surface the healthcare-only tuning gap early" guidance without violating single-requirement-per-phase ownership | 2026-07-21 |
| D-9 | SURFACE-01/02/03 mapped to Phase 23 only | These are structural CLI/API/MCP conventions (mirror domain sub-Typer pattern, schema reuse, thin MCP shims), proven once with the first new surface and then followed by every later phase as part of THAT phase's own feature requirement (e.g. POLICY-05, DIFF-01 already specify their own CLI/API delivery) — not re-claimed per phase | 2026-07-21 |
| D-10 | SEC-01..04 distributed, not centralized | SEC-04 (dependency pinning) → Phase 27 (DataTrove backend); SEC-03 (secrets redaction + prompt-injection boundary) → Phase 28 (first LLM-as-judge validator); SEC-01/02 (release immutability trigger, public/private mode) → Phase 30 (where release cutting happens) | 2026-07-21 |

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
- [Phase ?]: 21-01: contributors column reuses the module's existing _JSON alias (not JSON().with_variant(JSONB)) per the plan's locked Task 1 action text, consistent with Source.config/Artifact.metadata_
- [Phase ?]: 21-01: ChunkDedupLedger.id uses new_id('artifact') (art_<uuidv7>), matching VectorCollection's precedent for a generic non-lineage registry row
- [Phase ?]: 21-02: KLAKE_DEDUP_NAMESPACE hardcoded as a literal uuid4-generated constant, never derived from settings/env/collection name (D-05)
- [Phase ?]: 21-02: normalize_for_dedup deliberately does not reuse clean.py's line-oriented _normalize_whitespace() (D-03) to keep the exact-dedup key contract decoupled from cosmetic cleaning changes
- [Phase ?]: 21-03: set_payload() catches UnexpectedResponse(404) and returns False; any other status code re-raises unchanged (T-21-06)
- [Phase ?]: 21-03: No speculative retrieve() pre-check added before set_payload() — the try/except merge call IS the existence check, in one round trip (D-26)
- [Phase ?]: 21-04: dedup_chunks() router atomically claims each chunk against the corpus-wide ChunkDedupLedger in a single get_session() transaction, satisfying D-14's ordering invariant (ledger durable before any subsequent Qdrant write)
- [Phase ?]: 21-04: Conservation-invariant test calls _assert_dedup_conservation_invariant directly (mirrors chunk.py precedent) rather than monkeypatching claim_dedup_ledger_entry to desync counts, since the per-chunk loop structurally appends to exactly one bucket per successful claim
- [Phase ?]: 21-05: Extended index()'s empty-input guard to (not chunks and not duplicate_chunks) so an all-duplicates document batch still runs the contributor-append branch
- [Phase ?]: 21-05: Added explicit RuntimeError None-guards around get_dedup_ledger_entry() (self-heal loop) and _build_capped_contributors_mirror()'s primary-entry lookup, caught by mypy as new union-attr/list-item errors
- [Phase ?]: 21-06: process_crawled() wires dedup_chunks() between chunk() and embed()/index(); 5 test_process_crawled_clean.py tests extended with pass-through dedup_chunks mocks to avoid KeyError('text') regression now that dedup_chunks() is a real required stage
- [Phase ?]: 21-07: definitions.py registered the new dedup_chunks asset (not in plan's files_modified) — required for Dagster Definitions to load without DagsterInvalidDefinitionError
- [Phase ?]: 21-07: dedup_chunks asset placed physically between tree_index_document and embed_chunks in assets.py (not immediately after chunk_document) to minimize diff churn — graph position (between chunk_document and embed_chunks), not file position, is what the plan/tests require
- [Phase ?]: 21-08: Dagster path exercised via direct invocation of dedup_chunks/embed_chunks/index_chunks asset functions (materialize() lacks input_values in this Dagster version) with real PostgresResource/QdrantResource, rather than a full graph run from raw ingest
- [Phase ?]: 21-08: Both new integration tests use fully synthetic parsed_artifact_id/source_id strings (no seeded Source/Artifact rows) after confirming index()'s payload-field resolution degrades gracefully for unknown artifact ids
- [Phase ?]: Phase 22 P01: export read-back uses export.py's _make_storage() factory (not a fresh StorageBackend) so tests can patch one storage double for both export_rag_corpus()'s write and the caller's read-back
- [Phase ?]: Phase 22 P01: this_run_chunk_ids initialized once before the per-source loop (corpus-wide, not per-source) so D-04 scoping spans every source in a single export_rag_corpus() call
- [Phase ?]: Phase 22 P02: run_full_pipeline_audit()'s actual committed return shape matched the plan's <interfaces> contract exactly (no drift from Plan 22-01) — CLI wiring needed no adjustment
- [Phase ?]: Phase 22 P03: chunk_garbage_rate (45.64%) measures gate-rejection-rate of candidates, not garbage remaining in corpus -- export_junk_rate (0.0%, down from 33% baseline) is the direct successor metric to the milestone's original criteria and met its <2% target decisively
- [Phase ?]: CI-LINT-01: CI's Lint (ruff) job only scopes src/, not tests/ — 299 pre-existing tests/ lint findings are out of scope for this and future lint-only quick tasks unless CI's job scope changes
- [Phase ?]: DatasetSpec has no status column — immutability is structural (insert-only); DatasetProject.status is the single source of truth
- [Phase ?]: Dataset.dataset_project_id/dataset_spec_id nullable with no backfill — pre-v2.7 rows stay permanently unscoped, satisfying legacy-fallback detection
- [Phase ?]: prohibited_uses/intended_uses documented as declarative-only in Phase 23 — no enforcement gate exists yet (arrives via Phase 25 Policy Engine)
- [Phase ?]: 23-03: Task 1 (implementation) committed before Task 2 (validate_spec() + full test authorship), mirroring 23-02's feat-before-test task-boundary precedent
- [Phase ?]: 23-03: _spec_version_to_dict() extracted as a shared helper so create_spec_version()/get_latest_spec() build the identical return-dict shape from one place

### Pending Todos

None yet.

### Blockers/Concerns

**Open — carried forward into v2.7:**

- [Tech debt, CR-01]: MCP `_search_handler` uses `hasattr(h, "_asdict")`, always False for dataclasses — crashes on non-empty results. Needs `dataclasses.asdict(h)`. **MCP search is unusable in production until fixed.**
- [Tech debt, CR-02]: `mode` param dual-semantics — `?mode=hybrid&route=tree` passes API validation but reaches `tree_search()` with an invalid value; needs a split into `mode`/`tree_mode`.
- [Tech debt]: Domain path-traversal regex has 3 independent copies (`domains/loader.py`, `api/app.py`, `pipeline/domains.py`) — if one drifts, the guards diverge.
- [Tech debt]: `sources.config["domain"]` is still dual-written alongside the new column — remove the dual-write.
- [Tech debt, KL-16]: Domain packs cannot contribute Dagster jobs without editing framework source. v2.7's PITFALLS.md research confirms this stays deferred unless the flagship pack (Phase 24/32) needs a genuinely distinct Dagster schedule/sensor, not just parameterized asset behavior.
- [Tech debt]: `st_embedder.py` uses a module constant `_LITELLM_ALIAS` rather than settings — an alias not a provider ID, so the LLM-gateway constraint holds, but it is the one alias that isn't configurable.
- [Phase 13]: PageIndex pinned to pre-release `0.3.0.dev3` — API may change; vendoring fallback plan exists but is untested.
- [Phase 14]: Tree traversal prompt quality unvalidated — no ground-truth benchmarks for the healthcare domain.
- [Phase 16]: Entity cross-link IDF threshold needs empirical tuning for useful link density.
- [Wart, KL-01]: `_unclassified` still labels an all-domain export (`domain=` means "no filter, all domains").
- [Tech debt, v2.6]: `/gsd-secure-phase` only ran for Phase 22, not phases 17-21, despite `security_enforcement: true` in config — unlike Nyquist, this was not reconciled this milestone. Worth a retroactive `/gsd-secure-phase 17` through `21` pass, or confirming intentionally out of scope for a backend-only, no-new-trust-boundary milestone.

**Standing gotchas — do not relearn these:**

- `pipeline/route.py` binds `search` at import time (`from ... import search`), so patching `pipeline.search.search` never affects `routed_search` — patch `pipeline.route.search`. This silently neutered 4 tests (KL-19).
- `xfail_strict = true` is active. Any test that passes while marked xfail fails the build. Never add an xfail marker to make a red test go away — a stale marker is exactly what hid two API endpoints returning 500s for months.
- Keep the Docker base pinned to `.python-version`. A `python:3.14-slim` base that could not build left a 13-day-old image silently serving, which is why the 500s stayed invisible. `/health` now reports the running version.
- Dagster code-location reload is required after `definitions.py` changes for new assets/sensors to appear in the live daemon.
- `docs/openapi.json` must be regenerated after adding any API endpoint (determinism gate: `test_openapi_export.py`).
- `Dataset.name` is `UNIQUE` and mutated in place by `update_dataset_export()`; `export_finetune_dataset(dataset_name)` is called unversioned from CLI, REST, MCP, and a Dagster asset today — Phase 23 must update all four call sites in the same commit that introduces spec versioning (PITFALLS.md Pitfall 2).
- `license_type="unknown"` is the unenforced default at every existing source-creation call site — Phase 25's policy gate must ship its grandfather/backfill report before enforcing anything, or it fails closed on nearly the entire existing 34-source corpus (PITFALLS.md Pitfall 3).

**Resolved in v2.5 (2026-07-15):** E2E gap analysis CLOSED — all 19 findings resolved (see `.planning/milestones/v2.5-E2E-GAP-ANALYSIS.md`). Includes KL-18 (three endpoints returning 500 via `DetachedInstanceError`), the Dockerfile landmine, and parse section persistence (the section-less path was collapsing 38 sections into 1 chunk; now 51 per-section chunks, ~30x faster). Suite: 971 passed, 0 failed.

**Resolved in v2.6 (2026-07-18):** Milestone audit's two open tech-debt items CLOSED (see `.planning/milestones/v2.6-MILESTONE-AUDIT.md`, Phase 22). Real measurement now exists: export_junk_rate fell 33%→0.0% (decisively meets <2% target — resolved via UAT as the criterion-#1 metric); chunk_garbage_rate came out at 45.64% (a different, expected-high metric — the gate's own live rejection rate, not delivered-corpus quality). Nyquist reconciliation for all 6 phases (17-22) also CLOSED this milestone — `/gsd-validate-phase` re-run for each, all now `status: validated`, `nyquist_compliant: true`, zero coverage gaps found. Milestone audit re-run post-reconciliation: PASSED (20/20 requirements, 19/19 integration links wired, 6/6 Nyquist-compliant). Suite: 1181 passed, 0 failed.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260715-3w5 | Write E2E gap analysis report | 2026-07-15 | 9d1666e | [260715-3w5-write-e2e-gap-analysis-report](./quick/260715-3w5-write-e2e-gap-analysis-report/) |
| 260715-4b9 | Fix CI integration tests (KL-03) and add aviation reference pack | 2026-07-15 | ea14046 | [260715-4b9-fix-ci-integration-tests-kl-03-and-add-a](./quick/260715-4b9-fix-ci-integration-tests-kl-03-and-add-a/) |
| 260715-51d | Fix KL-01 domain filtering in exports and KL-02 LLM pricing | 2026-07-15 | 6ea82c2 | [260715-51d-fix-kl-01-domain-filtering-in-exports-an](./quick/260715-51d-fix-kl-01-domain-filtering-in-exports-an/) |
| 260715-5pb | Fix KL-07, KL-04/05/06, KL-11, KL-16, KL-10 | 2026-07-15 | bf8b6ac | [260715-5pb-fix-kl-07-kl-04-05-06-kl-11-kl-16-kl-10](./quick/260715-5pb-fix-kl-07-kl-04-05-06-kl-11-kl-16-kl-10/) |
| 260715-bgt | Fix KL-18 detached-session 500s, KL-08 stale container, KL-09 tree-index CLI | 2026-07-15 | b974337 | [260715-bgt-fix-kl-18-detached-session-500s-kl-08-st](./quick/260715-bgt-fix-kl-18-detached-session-500s-kl-08-st/) |
| 260715-chy | Fix remaining low findings, CI image build guard, parse section persistence | 2026-07-15 | 1c0159f | [260715-chy-fix-remaining-low-findings-ci-image-buil](./quick/260715-chy-fix-remaining-low-findings-ci-image-buil/) |
| 260718-6fu | Fix CI lint failure: ruff I001 import sort in predicates.py and chunk.py | 2026-07-18 | e1af6b1 | [260718-6fu-fix-ci-lint-failure-ruff-i001-import-sor](./quick/260718-6fu-fix-ci-lint-failure-ruff-i001-import-sor/) |

### Roadmap Evolution

- Phase 22 added: Address tech debt: measure garbage/junk rates end-to-end, reconcile Nyquist validation
- v2.7 roadmap created (2026-07-21): 10 phases (23-32) derived from 46 v1 requirements (46/46 mapped, 100% coverage — REQUIREMENTS.md's stale "43 total" footer corrected). Phase 24 (Flagship Domain Pack Foundation) intentionally carries zero directly-owned requirements — it is infrastructure scaffolded early per PITFALLS.md Pitfall 9, formally completed by Phase 32.

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
| Curation Engines | CENGINE-03 (second CurationEngine backend) | Deferred | v2.7 planning |
| Evaluation Depth | EVALRUN-03 (full RAGAS/RAG-FiT integration) | Deferred | v2.7 planning |
| Contamination Depth | SPLIT-03 (embedding + LLM-judge decontamination) | Deferred | v2.7 planning |
| Interop | DIFF-02 (Croissant JSON-LD export) | Deferred | v2.7 planning |
| Domain Expansion | DOMAIN-07 (domain-pack-owned Dagster jobs, KL-16) | Deferred | v2.7 planning |

## Session Continuity

Last session: 2026-07-21T10:27:55.356Z
Stopped at: Completed 23-03-PLAN.md
Resume file: None

## Operator Next Steps

- Review the v2.7 roadmap draft (.planning/ROADMAP.md) and approve or request revisions
- Once approved, run `/gsd-plan-phase 23` to begin Phase 23 (Dataset Project + Specification Foundation)
