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

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 6 | 25 | First milestone — GSD auto-chain established; TDD wave-0 pattern validated |

### Cumulative Quality

| Milestone | Unit Tests | xpassed | Zero regressions |
|-----------|------------|---------|-----------------|
| v1.0 | 324 | 20 | ✓ all phases passed |

### Top Lessons (Verified Across Milestones)

1. **Wire params end-to-end — function signatures aren't enough.** (v1.0)
2. **Shared test state causes false negatives.** Plan for isolation from the start. (v1.0)
3. **Integration checker catches what unit tests and phase verifiers miss.** Always audit cross-phase wiring before milestone close. (v1.0)
