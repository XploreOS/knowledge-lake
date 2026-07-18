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

## Milestone: v2.5 — PageIndex Plugin Integration

**Shipped:** 2026-07-15
**Phases:** 4 (13-16) | **Plans:** 14

### What Was Built

Tree-based reasoning retrieval and compiled knowledge bases, added *alongside* the existing vector RAG pipeline rather than replacing it. A deterministic tree-index builder over `ParsedDoc.sections` (silver-zone JSON artifact, content-hash no-op, opt-in budget-capped LLM summaries), shipped behind an `IndexerPlugin` seam. Two-stage retrieval reusing chunk `search()` unchanged for the Qdrant shortlist, then concurrent tree traversal behind a `RetrieverPlugin` seam. A heuristic `classify_route()` + `routed_search()` dispatcher wired to all four surfaces. And `compile_wiki()`, compiling enrichment metadata into an IDF-cross-linked Markdown knowledge base with manifest-based incremental rebuild.

### What Worked

- **Mirroring an established seam costs almost nothing.** `RetrieverPlugin` (P14) was modeled directly on `IndexerPlugin` (P13) — same Protocol shape, same entry-point group pattern, same `_validate_swap_key` guard. The second seam took a fraction of the first.
- **Heuristic-first with LLM opt-in, plus a guaranteed fallback.** Every LLM path (tree summaries, tree navigation, wiki summaries) shipped as an opt-in mode over a working deterministic default. `PageIndexRetriever` computes heuristic hits *before* LLM-nav regardless of mode, so the LLM can reorder but never degrade — and never raise.
- **Reusing `search()` untouched for stage 1.** Two-stage retrieval added zero risk to the existing chunk path.
- **Wave-0 RED scaffolds** continued to give every implementation task a concrete verify target before code was written.

### What Was Inefficient

- **The Dockerfile landmine wasted the most time and hid the most.** The base image had been bumped to `python:3.14-slim`, which cannot build (greenlet has no CPython 3.14 support). `docker compose up -d` silently kept a 13-day-old image alive, so every "live" check was testing stale code — for 13 days. This is the direct reason two API endpoint families returning 500s went unnoticed.
- **Phase 14's VERIFICATION.md was missing at audit time**, forcing the audit to classify five RETR requirements as integration-verified rather than verified, then a retroactive `/gsd-verify-work 14` run.
- **19 findings surfaced in an E2E gap analysis *after* all four phases had passed verification.** The remediation took six quick tasks — real work that phase-level gates should have caught.

### Patterns Established

- **Sidecar for derived structure.** `parse()` writes a JSON sections sidecar to silver; `chunk`/`tree-index` read it with a re-parse fallback for pre-sidecar artifacts. Sections carry full text, so they belong in S3, never Postgres.
- **Thin-shell Dagster assets.** `tree_index_document` is a shell over `pipeline.tree_index.tree_index()` — no logic duplicated in the asset layer.
- **Strict xfail as a build gate**, not a convention.

### Key Lessons

1. **"Verified" measured mechanism, not data.** All 4 phases passed, the milestone audit scored 19/19, 5/5 E2E flows were observable — and the pipeline was producing ~28% garbage chunks the whole time. Every gate asked "does the code do what the plan said?" None asked "is the output any good?" A pipeline can be fully correct and fully worthless simultaneously. **v2.6 exists because of this gap.**
2. **A recorded lesson is not an enforced one.** v2.0's retrospective explicitly warned that `xfail(strict=False)` can mask a real failure. It then masked two API endpoints returning 500s for months. The lesson only became real when `xfail_strict = true` made it a build gate. Write lessons into CI, not into documents.
3. **A stale container invalidates every live check, silently.** Pin the Docker base to `.python-version`, build the image in CI, and have `/health` report the running version — otherwise "I tested it live" means nothing.
4. **Import-time binding defeats patching.** `pipeline/route.py` does `from ... import search`, so patching `pipeline.search.search` never affects `routed_search` — patch `pipeline.route.search`. This silently neutered 4 tests (KL-19).
5. **An E2E run on real data is a different instrument than a test suite.** 971 green tests and a passing milestone audit did not surface what one real 34-source run made obvious in minutes.

### Cost Observations

- Model mix: Opus 4.8 for orchestration, planning, and quality gates; Sonnet for execution (`model_overrides.gsd-executor`)
- 190 commits over 3 days; 14 plans across 4 phases; plus 6 remediation quick tasks
- Notable: the plugin-seam mirroring (P13 → P14) was the cheapest phase-to-phase transition so far. The expensive work was not building features — it was the E2E remediation that phase gates should have prevented.

---

## Milestone: v2.6 — Data Quality & Enrichment

**Shipped:** 2026-07-18
**Phases:** 6 (17-22) | **Plans:** 24 | **Tasks:** 47 | **Timeline:** ~2 days (2026-07-16 → 2026-07-18) | **Commits:** 155

### What Was Built

The exact gap v2.5's retrospective named: a pipeline that was mechanically correct but produced ~28% garbage chunks and 33% junk gold-export rows, because `clean_document` and `process_crawled` both forwarded the *uncleaned* `ParsedDoc` to every downstream consumer. Phase 17 closed that bypass on both the Dagster and CLI/API/MCP paths, added a parent-scoped content hash, and shipped the first quality-audit harness. Phase 18 froze the re-crawl change gate's boilerplate patterns independently of `clean.py` so Phase 19 could safely extend them without triggering a 34-source re-crawl storm. Phase 19 added section-granularity substance classification (a zero-I/O, 100%-branch-covered predicate module) with domain-pack clinical-code allowlists protecting ICD-10/LOINC/RxNorm/dosage text from false-positive removal. Phase 20 moved the same gate to chunk scope (DataTrove's `FineWebQualityFilter` + the Phase-19 predicates), gated the gold RAG export on chunk-level `substance_passed`, and shipped a 25-fixture must-not-reject CI safety net. Phase 21 added corpus-wide index-time exact deduplication (Postgres ledger, deterministic `uuid5` point IDs, capped contributor-payload mirroring, self-heal on out-of-band point loss) wired identically into both call sites. Phase 22 — added after the first milestone audit found the two headline success criteria had never actually been measured — built a real chunk+export-level measurement harness and ran it against the live 34-source corpus.

### What Worked

- **Deterministic-first predicate module reused twice, unmodified.** Phase 19's `pipeline/quality/` package (7 pure predicates, zero I/O) was built once and consumed as-is by Phase 20's chunk-level gate — no drift between "what counts as garbage" at section scope vs. chunk scope, because it's the literal same code.
- **Dual-call-site wiring became an explicit, tested deliverable, not an afterthought.** Phases 17, 20, and 21 each wired their new stage into *both* the Dagster asset graph and `process_crawled()` (CLI/API/MCP) as separate, individually-tested tasks — and the milestone-close integration checker confirmed zero drift between the two paths across all 19 requirement wirings.
- **Post-execution code review caught a real, non-cosmetic bug in four consecutive phases** (19, 20, 21, 22) — an overbroad marketing-CTA regex that would have stripped genuine clinical enrollment text, a missing `domain_filters` thread that could silently drop a clinical code a stage before the new gate ever saw it, a contributor-count double-count on document reprocessing, and an unguarded `chunk()`/`export_rag_corpus()` call that could crash mid-audit. Every fix was independently re-verified via revert-and-retest, not trusted from the review narrative.
- **The D-04 dilution risk was proven real, not assumed away.** Phase 22's export-junk measurement seeded a pre-v2.6 chunk with no `substance_passed` key alongside a freshly-gated chunk in the same fixture DB and showed the scoped measurement correctly excludes the old one, while the real unmodified `export_rag_corpus()` independently proves it would have scanned both — turning a plausible-sounding scoping decision into a demonstrated one.
- **An honest, surfaced interpretive ambiguity beat a silently-picked answer.** Phase 22's verifier found that `chunk_garbage_rate` (45.64%) and `export_junk_rate` (0.0%) measure genuinely different things and routed the "is criterion #1 met" question to human sign-off rather than guessing — the UAT decision is now a durable, documented artifact instead of an assumption buried in a SUMMARY.md.

### What Was Inefficient

- **The Nyquist-reconciliation lesson recurred for a third time.** v2.0's retrospective named this exact failure mode ("quality gates run retroactively, not per-phase") and v2.5 repeated it. v2.6 did too: phases 17-21 shipped with `VALIDATION.md` still in its pre-execution seed state (`status: draft`/`planned`, `nyquist_compliant: false`) — the `verify:post` hook exists and is configured, but wasn't exercised inline during phase execution. It took a dedicated post-milestone session (`/gsd-validate-phase 17` through `22`) to reconcile all 6 phases, finding zero actual coverage gaps in the process — all the planned test coverage was real, it just was never marked as confirmed.
- **Security gating (`/gsd-secure-phase`) only ran for Phase 22**, not phases 17-21, despite `security_enforcement: true` in the current config. Unlike Nyquist, this was not caught or reconciled by any workflow this milestone — worth a retroactive `/gsd-secure-phase 17` through `21` pass, or confirming intentionally out of scope for a backend-only, no-new-trust-boundary milestone.
- **The milestone's own headline success criterion needed a phase (22) just to produce a real number.** Phases 17-21 all shipped "passed" verification with 100% of their own test suites green, but the two quantitative criteria the milestone existed to satisfy (<5% garbage chunks, <2% junk export rows) had zero live-corpus evidence until Phase 22 — an explicit repeat of v2.5's lesson #1 ("green gates measure mechanism, not output") even though that exact lesson was written down one milestone ago.

### Patterns Established

- **Zero-I/O predicate modules as a reusable substance-quality primitive**, consumed identically at multiple pipeline granularities (section, chunk) rather than reimplemented per call site.
- **Domain-pack allowlist as an unconditional override, evaluated before any threshold predicate** — short clinical codes structurally cannot pass length/alpha-ratio checks on their own merits, so the allowlist must short-circuit, never merely bias, the decision.
- **Dilution-safe measurement scoping**: when re-running a corpus-wide audit against a codebase with historical (pre-gate) data, scope the reported rate to only the current run's own artifact IDs, and prove the scoping matters with a fixture that seeds both eras in the same test DB.
- **Interpretive ambiguity in a milestone's own success criteria gets a UAT decision, not a verifier guess.** When two defensible readings of a requirement diverge, document the human call as its own artifact (`*-UAT.md`) rather than resolving it silently in prose.

### Key Lessons

1. **A lesson written down once is not a lesson enforced.** "Run quality gates per-phase" has now been the explicit takeaway of v2.0 and v2.5's retrospectives, and v2.6 still shipped 5 of its 6 phases without inline Nyquist reconciliation. The only fix that has ever actually worked in this project (per the v2.5 retrospective) is turning a lesson into a build gate — `verify:post` hooks exist for exactly this, and leaving them configured-but-unexercised is the same failure shape every time.
2. **"Complete" and "measured" are different claims, and a milestone can ship the first without the second.** Every phase 17-21 acceptance criterion was about mechanism (the gate exists, is wired, rejects the right inputs in a fixture). None of them, on their own, produced a real number against real data — that took a dedicated Phase 22, added only after a milestone audit noticed the gap.
3. **When a metric name is ambiguous between two measurement bases, that ambiguity will eventually need a human to resolve it — surface it before it's discovered by someone downstream.** `chunk_garbage_rate` (live gate-rejection rate) and `export_junk_rate` (garbage reaching the corpus) diverged by 45.64% vs 0.0% and both are "correct" by their own definition; only a documented product decision (not a verifier's best guess) can settle which one the original requirement meant.
4. **A validated pattern from N-1 milestones ago transfers cheaply.** Phase 20's chunk-scope gate consumed Phase 19's zero-I/O predicate module completely unmodified — the cost of the second consumer was near zero because the first was built as a genuinely reusable primitive, not a one-off.

### Cost Observations

- 155 commits over ~2 days; 24 plans, 47 tasks across 6 phases
- 4 of 6 phases (19, 20, 21, 22) had a post-execution code-review-fix cycle that caught a genuine bug — a much higher hit rate than v1.0/v2.0/v2.5, suggesting either the domain (data-quality gating with many interacting call sites and edge cases) is intrinsically harder to get right in one pass, or code review is catching real things at a stable rate across the whole project and it's simply more visible in a smaller-phase-count milestone
- Notable: this was the first milestone where a phase (22) existed solely to produce a measurement rather than ship a feature — worth normalizing "run the real thing against real data" as an explicit phase type for any future milestone whose success criteria are quantitative

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 6 | 25 | First milestone — GSD auto-chain established; TDD wave-0 pattern validated |
| v2.0 | 6 | 38 | Plan-time threat models + validation contracts; single schema source across agent surfaces; quality gates run retroactively (lesson: run inline) |
| v2.5 | 4 | 14 | Plugin seams mirrored at near-zero cost; heuristic-first + LLM-opt-in with guaranteed fallback became the default shape; `xfail_strict` promoted from lesson to build gate; first E2E run on real data exposed that all gates measured mechanism, not output quality |
| v2.6 | 6 | 24 | Directly remediated v2.5's "measures mechanism, not output" gap by closing the clean-stage bypass and shipping section/chunk-level substance gates + index-time dedup; added a dedicated measurement-only phase (22) to produce real numbers against the live corpus; Nyquist reconciliation retroactive for the 3rd milestone running (lesson still not enforced as a build gate) |

### Cumulative Quality

| Milestone | Unit Tests | xpassed | Zero regressions | Secured | Nyquist |
|-----------|------------|---------|-----------------|---------|---------|
| v1.0 | 324 | 20 | ✓ all phases passed | — | — |
| v2.0 | 522 | 39 | ✓ all phases passed | 6/6 (`threats_open: 0`) | 6/6 compliant |
| v2.5 | 971 | 0 (`xfail_strict`) | ✓ all phases passed | 4/4 | 4/4 compliant |
| v2.6 | 1181 | 0 (`xfail_strict`) | ✓ all phases passed | 1/6 (Phase 22 only — 17-21 not retroactively secured) | 6/6 compliant (reconciled retroactively post-milestone) |

### Top Lessons (Verified Across Milestones)

1. **Wire params end-to-end — function signatures aren't enough.** (v1.0)
2. **Shared test state causes false negatives.** Plan for isolation from the start. (v1.0)
3. **Integration checker catches what unit tests and phase verifiers miss.** Always audit cross-phase wiring before milestone close. (v1.0)
4. **Run quality gates (secure/validate) per-phase, not retroactively.** Plan-time threat models + validation contracts make them cheap — but only if run inline via `verify:post`. (v2.0)
5. **`xfail(strict=False)` can mask a real failure.** Audit xfails at verification; a self-fulfilling stub is worse than no test. (v2.0 — **recurred in v2.5**; only fixed by making it a build gate, which is the real lesson)
6. **Green gates prove the code matches the plan, not that the output is good.** Verification, audits, and E2E flow checks all measured mechanism. Data quality needs its own instrument, or a "complete" pipeline ships 28% garbage. (v2.5)
7. **Anything that can silently serve stale code will eventually hide a real bug.** Pin base images, build them in CI, and make the running version observable. (v2.5)
8. **A lesson written down is not a lesson enforced — this is now a 3-milestone pattern.** "Run quality gates per-phase, not retroactively" was v2.0's explicit takeaway, recurred in v2.5, and recurred again in v2.6 (5 of 6 phases needed retroactive Nyquist reconciliation). The only instance where this pattern actually stopped recurring was `xfail_strict` — because it became a build gate, not a document. Any future recurrence of "we should run X per-phase" should be resolved by wiring the `verify:post` hook, not by writing it down again. (v2.6)
9. **When a metric's name is ambiguous between two valid measurement bases, surface the ambiguity and get a human decision — don't silently pick one.** `chunk_garbage_rate` and `export_junk_rate` diverged by 45 percentage points and both were "correct" readings of the same milestone criterion; the fix was a documented UAT decision, not a verifier's best guess. (v2.6)
