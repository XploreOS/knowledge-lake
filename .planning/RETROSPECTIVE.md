# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

---

## Milestone: v1.0 — Knowledge Lake Framework MVP

**Shipped:** 2026-07-07
**Phases:** 6 | **Plans:** 25 | **Timeline:** 5 days (2026-07-02 → 2026-07-07)

### What Was Built

- **Full data lake pipeline:** ingest → parse → clean → chunk → enrich → embed → index → curate → generate-dataset → export, with complete lineage at every stage
- **Healthcare domain pack:** 28 curated seed sources (HL7 FHIR, CMS, HIPAA/OCR, ONC, CDC, FDA, NLM, NPPES, LOINC, RxNorm), `DomainLoader` convention, clinical prompts, taxonomy, validator
- **Complete surface:** 20 CLI commands, 26 FastAPI endpoints, 12 Dagster assets with RetryPolicy — all surfaces verified E2E
- **Export pipeline:** DataTrove curation, Q&A + instruction-tuning dataset generation, Parquet/JSONL gold zone with contamination gate
- **Train/eval contamination guard:** hard gate in all 3 export functions — fail-closed by default

### What Worked

- **`--auto --chain` discuss→plan→execute pipeline:** reduced context accumulation and decision fatigue; GSD auto-advance kept momentum across all 6 phases
- **Registry-first write pattern:** established in Phase 1, never deviated — every downstream phase extended cleanly without revisiting the lineage model
- **Thin `@asset` wrapping pure pipeline functions:** meant every stage was independently testable and the Dagster layer stayed thin; no logic lived in asset decorators
- **Deterministic-first extraction before LLM:** quality scorer, dedup, chunker all run regex/heuristics first; LLM only for gray-zone cases — costs stayed predictable
- **TDD wave-0 stubs:** writing xfail tests before implementation caught API mismatches early (e.g., Dagster retry_policy attribute name)
- **Human checkpoints in E2E plans:** the `autonomous: false` checkpoint in Plan 06-04 surfaced the Dagster container staleness issue before it became a verification failure

### What Was Inefficient

- **Phase 1 Typer version conflict:** docling-core's dep on Typer pinned us to <0.25.0 — should have been caught in research; cost one debugging cycle
- **Dagster containers require rebuild:** no hot-reload; every code change to definitions.py required `docker compose build` — undocumented until UAT
- **E2E test contamination false positive:** the `_enforce_no_contamination()` gate flagged shared dev-DB artifacts from Phase 5 during Phase 6 E2E — required a `contamination_override_artifact_ids` workaround; proper per-test DB isolation would have prevented this
- **DOMAIN-03 wire left open until audit:** the `domain_system_prompt` param was implemented in `enrich_document()` but no caller was wired — the integration checker audit caught it, but it should have been a plan acceptance criterion

### Patterns Established

- **`domains/{name}/` convention:** zero core code changes per new domain pack — proven with healthcare; extend by adding a new directory
- **Content-hash caching for LLM calls:** `_enrichment_cache_key()` pattern prevents re-billing identical documents across runs — reuse for any future LLM stage
- **Budget cap + graceful halt:** `LlmSpend` table + `budget_usd` setting pattern — replicate for any cost-sensitive stage
- **`AssetSelection.assets()` with Python object refs (not strings):** rename-safe; prevents silent asset selection failures on refactor

### Key Lessons

1. **Wire the param, not just the signature.** Adding `domain_system_prompt` to `enrich_document()` without wiring it in all callers (CLI, API, Dagster) left a silent degradation. Acceptance criteria should explicitly verify the param is passed, not just defined.
2. **Container rebuild is not obvious.** Dagster webserver showed "0 assets, 0 jobs" after Phase 6 deployment — the fix was a rebuild. Document this prominently (done in README.md).
3. **Shared dev DB accumulates state.** E2E tests against a shared Postgres hit contamination from prior phases. Per-test isolation (separate DB or truncate between tests) is the right long-term fix.
4. **Integration checker is worth spawning.** The audit milestone step found 2 gaps (domain prompt wire, missing `/dedupe` API) that all other verification passes missed. Run it before calling any phase "done."
5. **`--auto --chain` works well for greenfield phases.** The full discuss→plan→execute auto-chain with `--auto` produced good results for all 6 phases — no human steering needed beyond UAT checkpoints.

### Cost Observations

- Model mix: primarily Sonnet 4.6 (1M context) for all orchestration and planning
- 259 commits over 5 days; ~25 plans executed across 6 phases
- Notable: 1M context window allowed cross-phase context enrichment (prior CONTEXT.md + SUMMARY.md files) without truncation — planner and verifier agents received full prior-phase context

---

## Milestone: v2.0 — Agent-Ready Lake

**Shipped:** 2026-07-12
**Phases:** 6 (7–12) | **Plans:** 38 | **Timeline:** 5 days (2026-07-08 → 2026-07-12) | **Commits:** 252 (61 feat)

### What Was Built

- **Metadata + filtered search (P7):** expanded Qdrant payload (7 provenance fields) + keyword payload indexes; source/format/tag filters across CLI + REST
- **Crawl maturation (P8):** per-source config, `crawl-all`, adaptive rate limiting, truncation-resilient enrichment, linked-doc ingest with SSRF guard + bounded frontier
- **Storage segmentation (P9):** domain/source-scoped S3 keys + object tags + gold-zone segmentation — forward-only, WORM-safe
- **Hybrid retrieval (P10):** BM25 + dense named vectors with server-side RRF, re-embedding alias-swap reindex with count-parity gate, fail-loud mode switch
- **Crawl scheduling (P11):** Dagster re-crawl sensor with normalized-text change gate, tick-storm dedup, per-source concurrency
- **Agent surfaces (P12):** curated MCP server (stdio + Streamable HTTP), 11 tools, 4 Claude skills, OpenAPI + OpenAI defs from one schema source (parity-gated)

### What Worked

- **STRIDE threat register authored at plan time:** every PLAN carried a `<threat_model>` block, so retroactive `/gsd-secure-phase` was a cheap grep-verification (all mitigations found in code) rather than a rediscovery — 6 SECURITY.md files, `threats_open: 0`, in one pass
- **Wave-0 RED scaffolds again paid off:** most xfail stubs flipped to XPASS on execution; the requirement→test contract in each plan-time VALIDATION.md made `/gsd-validate-phase` a straight audit
- **Single schema source of truth:** `model_json_schema()` → OpenAPI/OpenAI/MCP with a parity gate proved `stdio==http==openapi==openai` by construction — no surface drift
- **Forward-only changes:** domain-scoped S3 keys and additive Alembic migrations meant zero data-migration risk
- **Integration carry-forward:** the re-audit proved `git diff -- src/` empty since the prior audit, so "all seams wired" carried forward with evidence instead of a redundant cold checker run

### What Was Inefficient

- **Quality gates run retroactively, not per-phase:** `/gsd-secure-phase` and `/gsd-validate-phase` weren't run during execution, so phases 7–11 shipped with `nyquist_compliant: false` drafts and no SECURITY.md — forcing a milestone re-audit after the fact. The `verify:post` hooks exist to run these inline; enabling them per-phase would have avoided the rework
- **A self-fulfilling xfail masked a real defect:** `test_hybrid_prefetch_limits` (`xfail(strict=False)`) silently XFAILed on a test-wiring bug while the D-12 prefetch guard went unasserted; the P10 verifier logged it as a "Known Limitation" but nobody fixed it until validate-phase
- **Dagster code-location staleness recurred:** the running daemon still holds pre-phase-11 definitions (needs a reload) — the same v1.0-era issue, now in project memory
- **Live-service E2E still unrunnable here:** Postgres/MinIO/Qdrant absent, so STORE/PAYLOAD/RETR/SCHED live paths and the P10/P11 integration suites are gated, not green

### Patterns Established

- **Threat model in PLAN.md:** a STRIDE register per plan turns security verification into mechanical grep-matching later
- **Requirement→test contract in VALIDATION.md at plan time:** binds each REQ-ID to a concrete test + command before code exists; validate-phase just confirms green
- **Gate-local normalization:** suppress volatile tokens (timestamps/UUIDs/nonces) inside the change gate rather than mutating shared `clean.py` — keeps the WORM signature stable without redesigning the silver stage
- **Parity gate across surfaces:** assert generated schemas are byte-equal across transports to prevent drift

### Key Lessons

1. **Run secure/validate gates per-phase, not at milestone close.** The `verify:post` hooks are there for a reason — retroactive gating works but forces a re-audit.
2. **`xfail(strict=False)` can hide a genuinely failing test.** Audit xfails at phase verification; once behavior lands, remove the marker (or use strict xfail) so the assertion actually guards.
3. **Author the STRIDE register at plan time.** It makes retroactive security verification cheap and turns "is it mitigated?" into "grep for the control."
4. **Carry forward a verified integration result when inputs are provably unchanged.** An empty `git diff -- src/` since the last check is stronger evidence than re-deriving the same conclusion with a cold subagent.

### Cost Observations

- Model: Opus 4.8 for orchestration and all quality-gate work this session
- 252 commits over 5 days; 38 plans across 6 phases; retroactive secure + validate + re-audit completed in a single session
- Notable: authoring threat models and validation contracts at plan time made the retroactive gates fast — most of the cost was verification, not rediscovery

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 6 | 25 | First milestone — GSD auto-chain established; TDD wave-0 pattern validated |
| v2.0 | 6 | 38 | Plan-time threat models + validation contracts; single schema source across agent surfaces; quality gates run retroactively (lesson: run inline) |

### Cumulative Quality

| Milestone | Unit Tests | xpassed | Zero regressions | Secured | Nyquist |
|-----------|------------|---------|-----------------|---------|---------|
| v1.0 | 324 | 20 | ✓ all phases passed | — | — |
| v2.0 | 522 | 39 | ✓ all phases passed | 6/6 (`threats_open: 0`) | 6/6 compliant |

### Top Lessons (Verified Across Milestones)

1. **Wire params end-to-end — function signatures aren't enough.** (v1.0)
2. **Shared test state causes false negatives.** Plan for isolation from the start. (v1.0)
3. **Integration checker catches what unit tests and phase verifiers miss.** Always audit cross-phase wiring before milestone close. (v1.0)
4. **Run quality gates (secure/validate) per-phase, not retroactively.** Plan-time threat models + validation contracts make them cheap — but only if run inline via `verify:post`. (v2.0)
5. **`xfail(strict=False)` can mask a real failure.** Audit xfails at verification; a self-fulfilling stub is worse than no test. (v2.0)
