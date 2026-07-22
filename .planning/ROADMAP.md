# Roadmap: Knowledge Lake Framework

## Milestones

- ✅ **v1.0 MVP** — Phases 1-6 (shipped 2026-07-07)
- ✅ **v2.0 Agent-Ready Lake** — Phases 7-12 (shipped 2026-07-12)
- ✅ **v2.5 PageIndex Plugin Integration** — Phases 13-16 (shipped 2026-07-15)
- ✅ **v2.6 Data Quality & Enrichment** — Phases 17-22 (shipped 2026-07-18)
- 📋 **v2.7 Governed Dataset Production and Release Lifecycle** — Phases 23-32 (planned)

## Phases

<details>
<summary>✅ v2.6 Data Quality & Enrichment (Phases 17-22) — SHIPPED 2026-07-18</summary>

Full archive: [.planning/milestones/v2.6-ROADMAP.md](.planning/milestones/v2.6-ROADMAP.md)

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 17 | Close the Bypass + Measurement | 4/4 | ✅ Complete | 2026-07-16 |
| 18 | Gate Decouple | 1/1 | ✅ Complete | 2026-07-16 |
| 19 | Section Classifier + Patterns | 4/4 | ✅ Complete | 2026-07-17 |
| 20 | Chunk Substance Gate + Export Gate | 4/4 | ✅ Complete | 2026-07-17 |
| 21 | Index-Time Dedup | 8/8 | ✅ Complete | 2026-07-17 |
| 22 | Address Tech Debt: Measure Garbage/Junk Rates E2E | 3/3 | ✅ Complete | 2026-07-18 |

**Total:** 6 phases, 24 plans, 47 tasks, 155 commits, 128 files changed (+22,928/-146). All phases verified `passed` (20/20 requirements), integration 19/19 wired (both Dagster and CLI/API/MCP call sites confirmed consistent), Nyquist-compliant (6/6). Milestone audit: PASSED. Real measurement against the live 34-source healthcare corpus: `export_junk_rate` fell 33%→0.0% (target <2%, decisively met).

</details>

<details>
<summary>✅ v2.5 PageIndex Plugin Integration (Phases 13-16) — SHIPPED 2026-07-15</summary>

Full archive: [.planning/milestones/v2.5-ROADMAP.md](.planning/milestones/v2.5-ROADMAP.md)

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 13 | Tree Index Foundation | 6/6 | ✅ Complete | 2026-07-13 |
| 14 | Tree Retrieval | 4/4 | ✅ Complete | 2026-07-14 |
| 15 | Query Router | 2/2 | ✅ Complete | 2026-07-14 |
| 16 | OpenKB Export | 2/2 | ✅ Complete | 2026-07-14 |

**Total:** 4 phases, 14 plans, 190 commits, 243 files changed (+32,060/-2,377). All phases verified `passed` (19/19 requirements), threat-secured, and Nyquist-compliant. Milestone audit: PASSED. E2E gap analysis closed — all 19 findings resolved.

</details>

<details>
<summary>✅ v2.0 Agent-Ready Lake (Phases 7-12) — SHIPPED 2026-07-12</summary>

Full archive: [.planning/milestones/v2.0-ROADMAP.md](.planning/milestones/v2.0-ROADMAP.md)

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 7 | Metadata Foundation | 4/4 | ✅ Complete | 2026-07-08 |
| 8 | Crawl Maturation | 6/6 | ✅ Complete | 2026-07-08 |
| 9 | Storage Segmentation | 6/6 | ✅ Complete | 2026-07-09 |
| 10 | Hybrid Retrieval | 8/8 | ✅ Complete | 2026-07-10 |
| 11 | Crawl Scheduling | 6/6 | ✅ Complete | 2026-07-10 |
| 12 | Agent Surfaces | 8/8 | ✅ Complete | 2026-07-11 |

**Total:** 6 phases, 38 plans, 252 commits, 85 files changed (+14,487/-419). All phases verified `passed` (19/19 requirements), threat-secured (`threats_open: 0`), and Nyquist-compliant.

</details>

<details>
<summary>✅ v1.0 MVP (Phases 1-6) — SHIPPED 2026-07-07</summary>

Full archive: [.planning/milestones/v1.0-ROADMAP.md](.planning/milestones/v1.0-ROADMAP.md)

| Phase | Name | Plans | Status | Completed |
|-------|------|-------|--------|-----------|
| 1 | Foundation & End-to-End Spike | 6/6 | ✅ Complete | 2026-07-03 |
| 2 | Ingestion | 6/6 | ✅ Complete | 2026-07-04 |
| 3 | Parse, Clean & Chunk | 3/3 | ✅ Complete | 2026-07-05 |
| 4 | Enrichment, Embedding & Search | 3/3 | ✅ Complete | 2026-07-06 |
| 5 | Curation, Datasets & Export | 3/3 | ✅ Complete | 2026-07-06 |
| 6 | Healthcare Domain Pack & Full-Surface Validation | 4/4 | ✅ Complete | 2026-07-07 |

**Total:** 6 phases, 25 plans, 259 commits, 303 files changed

</details>

### 📋 v2.7 Governed Dataset Production and Release Lifecycle (Phases 23-32, planned)

**Milestone Goal:** Reposition Knowledge Lake from a document-ingestion/RAG framework into an open-source DatasetOps control plane that manufactures versioned, policy-evaluated, quality-validated, reproducible AI datasets traceable to their sources — proven end-to-end with a flagship non-healthcare dataset.

**Scale note:** This milestone adds 12-14 new Postgres tables, a new `CurationEngine` abstraction, a full dataset release lifecycle, and a flagship non-healthcare domain pack — a phase count above this project's `standard` granularity baseline is a deliberate, work-driven deviation (not padding), matching this project's own "derive phases from requirements" philosophy at this milestone's actual scale.

**Scope decisions carried in from research (PITFALLS.md):**

- Phase 23 resolves the `Dataset.name` / `export_finetune_dataset()` versioning-identity break before anything else references a spec version (Pitfall 2).
- Phase 24 (flagship domain pack) is scaffolded immediately after Phase 23 — not at the end — so every later phase has real non-healthcare data to build and test against; its domain-specific quality-gate tuning still waits on Phase 26 (Quality Contract) to exist.
- Phase 25 (Usage Policy) ships its one-time grandfather/backfill report over the existing 34-source healthcare corpus in the *same phase* as the policy engine, never deferred (Pitfall 3).
- Phase 27 (CurationEngine + DataTrove backend) records an explicit, documented checkpoint-storage decision (Postgres-ledger reuse vs. a reviewed `s3fs` addition) in its own plan before implementation starts (Pitfall 7).
- Phase 29 (splits) ships its `DatasetExample` backfill migration in the same unit as the schema change — never a bare `ADD COLUMN` with no backfill (Pitfall 1).
- Phase 30 (Release) ships a Postgres `BEFORE UPDATE` immutability trigger in the same migration as the `dataset_releases` table — application-only checks are UX, not the guarantee (Pitfall 4).
- Every schema-touching phase ships exactly one small, reversible Alembic migration — never one giant migration for the whole milestone (Pitfall 8).
- SURFACE-01/02/03 (CLI/API/MCP conventions) and most of SEC-01..04 are distributed into the phase that introduces the relevant capability rather than living in one final "surfaces" phase — matching how v2.0/v2.5 shipped CLI/API/MCP wiring incrementally.

**References:**

- Requirements: [.planning/REQUIREMENTS.md](.planning/REQUIREMENTS.md) (46 v1 requirements — see Coverage Note below)
- Research: [.planning/research/SUMMARY.md](.planning/research/SUMMARY.md), [ARCHITECTURE.md](.planning/research/ARCHITECTURE.md), [PITFALLS.md](.planning/research/PITFALLS.md)

**Coverage note:** REQUIREMENTS.md's own footer stated "43 total" v1 requirements; a direct count of `**CATEGORY-NN**` markers under its `## v1 Requirements` section found **46** distinct IDs (the footer undercounted). All 46 are mapped below; REQUIREMENTS.md's traceability section is corrected to 46 as part of this roadmap update.

**Hard Ordering Constraints:**

1. Phase 23 (Dataset Project + Spec) first — every other governance concept scopes to a project/spec version.
2. Phase 24 (Flagship scaffold) immediately after Phase 23 — parallelizable with Phases 25-28's pipeline work once real flagship sources exist.
3. Phase 25 (Policy) and Phase 26 (Quality Contract) can build in parallel with each other, both after Phase 23.
4. Phase 27 (CurationEngine + DataTrove + Partitions) depends on Phase 25 (policy gates eligibility) and Phase 26 (contract to evaluate against).
5. Phase 28 (Candidate lifecycle + Validation) depends on Phase 27's curated output and Phase 26's contract.
6. Phase 29 (Splits + Contamination) depends on Phase 28 — only validated/accepted examples are split-eligible.
7. Phase 30 (Release + Reproducibility) is the latest-dependent entity — needs Phases 23, 25, 26/28, and 29 all landed; it is the hard convergence point.
8. Phase 31 (EvalRun + Diff + Lineage) depends on Phase 30 — needs at least one Release to evaluate/explore, at least two to diff meaningfully.
9. Phase 32 (Flagship Release + Lineage Demo) is last — it proves the entire lifecycle (Phases 24 through 31) end-to-end on real, non-healthcare data.

**Critical path:** 23 → 25/26 → 27 → 28 → 29 → 30 → 31 → 32. Phase 24 runs parallel to 25-28 once scaffolded.

- [x] **Phase 23: Dataset Project + Specification Foundation** - Dataset Project lifecycle state machine, versioned/hashed Dataset Specification, and the CLI/API/MCP surface convention established (completed 2026-07-21)
- [ ] **Phase 24: Flagship Domain Pack Foundation** - Real non-healthcare source corpus scaffolded and ingested so every later phase has genuine flagship data to build against
- [ ] **Phase 25: Usage Policy Engine** - Deterministic 9-dimension per-source policy decisions, with the existing 34-source corpus grandfathered in report-only mode first
- [ ] **Phase 26: Quality Contract** - Multi-level (source/document/chunk/example/split/release) rule evaluation with structured, auditable outcomes
- [ ] **Phase 27: CurationEngine Protocol + DataTrove Backend + Result Partitions** - Dagster-launched curation runs through a stable protocol, DataTrove as the first production backend, accepted/rejected/recoverable/quarantined partitioning
- [ ] **Phase 28: Generated-Example Candidate Lifecycle + Validation** - Generated examples move through an auditable generated→validating→accepted/recoverable/repaired/rejected lifecycle via pluggable validators
- [ ] **Phase 29: Deterministic Splits + Contamination Gate** - Deterministic, versioned, group-aware train/validation/test splits with a paraphrase-resistant, boilerplate-safe contamination gate
- [ ] **Phase 30: Immutable Dataset Release + Reproducibility Manifest** - Full manifest bundle, DB-enforced immutability, and a reproducibility manifest that honestly separates deterministic-replayable from explainable-not-replayable claims
- [ ] **Phase 31: Evaluation Run Foundation + Dataset Diff + Lineage Explorer** - Minimal evaluation adapter, manifest-based release diffing, and end-to-end Project→Release→Source lineage navigation
- [ ] **Phase 32: Flagship Release + Lineage Demo** - The AI Agent Security and Permission Dataset released end-to-end with a traced record-level lineage demonstration

## Phase Details

### Phase 23: Dataset Project + Specification Foundation

**Goal**: Users can create and version-manage Dataset Projects and their declarative Specifications, with the existing dataset export identity contract preserved across all four call sites, and the CLI/API/MCP surface convention for this milestone established.
**Depends on**: Nothing new — first phase of v2.7; builds on the existing `Dataset`/`DatasetExample` tables from v1.0-v2.6.
**Requirements**: PROJ-01, PROJ-02, PROJ-03, SPEC-01, SPEC-02, SPEC-03, SURFACE-01, SURFACE-02, SURFACE-03
**Success Criteria** (what must be TRUE):

  1. A user can run `klake project new` and see a new Dataset Project in `draft` state; `klake project list/show` reflect it, and `klake project transition` moves it through the lifecycle.
  2. An illegal lifecycle transition (e.g. `draft` → `released` directly) is rejected via CLI/API with a clear, specific error naming the invalid transition.
  3. Editing a Dataset Specification produces a new immutable spec version with its own content hash, schema version, timestamp, author, and parent-version link; the previous version remains retrievable unmodified.
  4. `klake dataset spec validate` fails with a specific reason when a spec references a nonexistent source, quality contract, or policy, and passes when every reference resolves.
  5. `export_finetune_dataset("name")` (no version argument), called from CLI, API, MCP, and the existing Dagster asset, resolves via one named, tested "latest released" rule instead of an ambiguous row — verified against a Dataset Project carrying two spec versions.
  6. New CLI sub-Typer groups mirror the existing `domain_app` pattern, new API routes call `pipeline/*.py` directly with shared Pydantic schemas, and any new MCP tool is a thin shim with the `TOOLS` count assertion bumped in the same change — proven by the full existing CLI/API/MCP test suite still passing unchanged.

**Plans**: 7/7 plans executed

Plans:
**Wave 1**

- [x] 23-01-PLAN.md — Schema foundation: DatasetProject/DatasetSpec models, migration 0012, ids.py prefixes (Wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 23-02-PLAN.md — pipeline/project.py core: create_project/get_project/list_projects/transition_project + IllegalProjectTransitionError (Wave 2)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 23-03-PLAN.md — Dataset Specification versioning: DatasetSpecFields, content hash, create_spec_version/get_latest_spec/validate_spec (Wave 3)

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 23-04-PLAN.md — D-02 export identity fix: get_latest_released_dataset_by_name() + export_finetune_dataset() internal swap (Wave 4)
- [x] 23-05-PLAN.md — API surface: /projects, /projects/{id}/transition, /projects/{id}/specs, /specs/{id}/validate routes + schemas (Wave 4)
- [x] 23-06-PLAN.md — CLI surface: project_app (new/list/show/transition), dataset_app/spec_app (create/validate) (Wave 4)

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 23-07-PLAN.md — MCP surface: project_list/project_show/spec_validate read tools, TOOLS count bump 11→14 (Wave 5)

### Phase 24: Flagship Domain Pack Foundation

**Goal**: A real, non-healthcare domain pack and its source corpus exist early enough that every subsequent v2.7 phase can be built and tested against genuine flagship data instead of synthetic fixtures, and the healthcare-only quality-gate tuning gap is surfaced now rather than at milestone end.
**Depends on**: Phase 23 (sequenced immediately after so the flagship corpus can be scoped as a Dataset Project going forward; the domain-pack scaffolding itself has no hard schema dependency on Phase 23).
**Requirements**: None (infrastructure prerequisite phase — see note below)
**Success Criteria** (what must be TRUE):

  1. A new top-level `domains/<flagship-name>/` pack (domain.yaml, sources.yaml, taxonomy.yaml, prompts, validators) is registered and loadable via `klake init --domain <flagship-name>` — not under `domains/local/`, avoiding the known `DomainLoader.from_name()` path limitation.
  2. Real AI-agent-security-and-permission sources are ingested end-to-end through the existing parse → clean → chunk → enrich → embed → index pipeline, producing a genuine non-healthcare corpus.
  3. The existing chunk-substance gate runs against the flagship corpus in report-only mode, and a human review of its rejection list documents whether domain-specific short/structured content (permission scopes, tool identifiers, CVSS-style scores) is being wrongly dropped by healthcare-tuned heuristics.
  4. A Dataset Project scoped to the flagship pack exists in `sources_pending`/`ready` state, ready for Phases 25-31 to build and test their own mechanisms against real data.

**Note**: This phase enables (but does not itself formally satisfy) the flagship requirements owned by Phase 32 — those requirements complete only once Release and the Lineage Explorer exist. Scaffolding it now, per PITFALLS.md Pitfall 9, surfaces the healthcare-only quality-gate tuning gap early instead of at milestone end.

**Plans**: 4 plans

Plans:
**Wave 1**

- [ ] 24-01-PLAN.md — Domain pack scaffold + customization (domain.yaml/taxonomy.yaml/prompts/validator per D-01/D-03) + `--source-url` CLI fix (Pitfall 1) + live-verified sources.yaml (Wave 1)

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 24-02-PLAN.md — Real ingestion: register+crawl sources, batch-process in report mode, close the enrich gap (Wave 2)

**Wave 3** *(blocked on Wave 2 completion)*

- [ ] 24-03-PLAN.md — Gate review findings document: report-only rejection measurement + human-reviewed judgment + Phase 26 handoff (Wave 3)
- [ ] 24-04-PLAN.md — Dataset Project lifecycle: spec authoring/validation + transition to `ready` (Wave 3)

### Phase 25: Usage Policy Engine

**Goal**: Every source carries an auditable, deterministic usage-policy decision across 9 dimensions, and the existing 34-source healthcare corpus is grandfathered before any policy gate becomes release-blocking.
**Depends on**: Phase 23 (policy decisions are scopable to a spec version).
**Requirements**: POLICY-01, POLICY-02, POLICY-03, POLICY-04, POLICY-05
**Success Criteria** (what must be TRUE):

  1. A user can run `klake policy define` to create a policy definition and `klake policy decide` to record a per-source decision across all 9 dimensions (approved-for-ingestion/retrieval/training/commercial/derivatives/redistribution/attribution/share-alike/unknown), with a reason and policy version, viewable via `klake policy list` and the API.
  2. Policy evaluation never calls an LLM for legal interpretation — every decision is produced by declarative rule matching alone.
  3. A one-time grandfather report runs against the entire existing 34-source healthcare corpus in report-only mode, producing a human-reviewable table of every source's interim policy status, with zero previously-working export paths failing closed before a human approves the report.
  4. A Dataset Release is blocked with a specific, named reason when a required policy decision is missing, a source's license is unknown under a fail-on-unknown policy, or a source's redistribution/intended-use terms conflict with the spec.

**Plans**: TBD

### Phase 26: Quality Contract

**Goal**: A Dataset Quality Contract can declare rules at every governance level (source/document/chunk/example/split/release) and every rule evaluation produces a structured, auditable outcome — reusing, not duplicating, the existing chunk substance predicates.
**Depends on**: Phase 23 (contracts are scoped to a project/spec).
**Requirements**: QCON-01, QCON-02, QCON-03
**Success Criteria** (what must be TRUE):

  1. A Quality Contract can be defined with rules scoped independently to source, document, chunk, generated-example, split, and release levels.
  2. Evaluating a chunk-level rule against real chunks produces a structured outcome (passed/failed/recoverable/skipped/not_applicable) carrying rule ID, rule version, reason code, human-readable explanation, input artifact/example ID, config hash, validator identity/version, and timestamp.
  3. The chunk-level rule type delegates directly to the existing `pipeline/quality/predicates.py` combinator — no second, independently-drifting substance-detection implementation exists.
  4. A documented, reusable pattern for a domain pack to contribute its own normative allowlist to a Quality Contract exists — written now, before Phase 32's flagship release needs it.

**Plans**: TBD

### Phase 27: CurationEngine Protocol + DataTrove Backend + Result Partitions

**Goal**: Curation runs execute through a stable `CurationEngine` protocol with DataTrove as a Dagster-launched, checkpointed production backend, and every curation outcome lands in exactly one of accepted/rejected/recoverable/quarantined with nothing silently discarded.
**Depends on**: Phase 25 (policy decisions gate what's eligible for curation), Phase 26 (contract to evaluate against).
**Requirements**: CENGINE-01, CENGINE-02, DTROVE-01, DTROVE-02, PART-01, PART-02, PART-03, SEC-04
**Success Criteria** (what must be TRUE):

  1. The existing `curate_document`/`batch_dedup_corpus` CLI and Dagster call sites keep working with unchanged public signatures after `pipeline/curate.py` becomes a thin wrapper over the new `DataTroveCurationEngine`.
  2. A Curation Run launched from Dagster records engine name/version, input/output manifests, config hash, accepted/rejected counts by reason, statistics, start/completion timestamps, runtime, and environment version.
  3. Every processed document/chunk in a Curation Run lands in exactly one partition (accepted/rejected/recoverable/quarantined); `accepted + rejected + recoverable + quarantined == total processed` is enforced as a runtime `RuntimeError` invariant, mirroring the existing QUAL-05 discipline.
  4. The checkpoint-storage decision (Postgres-ledger reuse vs. a reviewed `s3fs` dependency) is explicitly documented in this phase's plan and verified by an integration test that kills/restarts mid-run against the real production storage backend, not local disk.
  5. Any new external dependency introduced for the DataTrove backend is exactly pinned, with its addition explicitly recorded as a reviewed decision, matching the repo's existing pinning convention.

**Plans**: TBD

### Phase 28: Generated-Example Candidate Lifecycle + Validation

**Goal**: Generated dataset examples carry an explicit, auditable lifecycle from generation through validation to a final accepted/rejected state, validated by a pluggable `ExampleValidator` interface that includes safe LLM-as-judge validators.
**Depends on**: Phase 27 (curated output is the candidate input), Phase 26 (Quality Contract rules drive validation outcomes).
**Requirements**: CAND-01, CAND-02, CAND-03, SEC-03
**Success Criteria** (what must be TRUE):

  1. A generated example moves through `generated → validating → accepted`, or the `recoverable → repaired → validating` path, or `generated → validating → rejected`, with every transition recorded.
  2. Every candidate record carries its source artifact ID, exact supporting passage/span, Dataset Project, spec version, generator prompt version, generator model alias, generation parameters, and content hash.
  3. Validators exist for schema validity, source answerability, source-grounding, duplicate detection, usage-policy compliance, domain-specific rules, and contamination — each producing a structured pass/fail outcome.
  4. An LLM-as-judge validator call goes through LiteLLM only, records evaluator alias/prompt version/result evidence, respects the existing untrusted-content/prompt-injection boundaries, and secrets are redacted from its logged output.

**Plans**: TBD

### Phase 29: Deterministic Splits + Contamination Gate

**Goal**: Train/validation/test split assignment is deterministic, versioned, and group-aware, and a benchmark contamination gate blocks releases on real overlap while staying immune to the false-negative/false-positive traps of naive n-gram matching.
**Depends on**: Phase 28 (only validated/accepted examples are split-eligible).
**Requirements**: SPLIT-01, SPLIT-02
**Success Criteria** (what must be TRUE):

  1. Running split assignment twice against the same input set produces identical train/validation/test assignments, with examples grouped by source document/parent artifact so related examples never split across train and eval.
  2. Every pre-migration `DatasetExample` row is backfilled with a split value derived from the same signal the old payload-shape sniff used, in the same migration as the schema change; `SELECT count(*) FROM dataset_examples WHERE split IS NULL` is `0` after migration.
  3. A fixture pair (an LLM-paraphrased eval/train example from the same source chunk, sharing almost no exact n-grams) is still caught by the lineage-based check; a fixture pair sharing only regulatory boilerplate is not flagged as real contamination.
  4. A `DatasetExample` with an unrecognized split/status value is surfaced as a countable "unclassified — needs review" result, never silently dropped from the gate.

**Plans**: TBD

### Phase 30: Immutable Dataset Release + Reproducibility Manifest

**Goal**: Cutting a Dataset Release produces a complete, immutable, reproducible manifest bundle that the database itself — not just application code — refuses to let anyone mutate after publication.
**Depends on**: Phase 23 (spec being released), Phase 25 (policy decisions manifest), Phase 26/28 (quality/validation manifest), Phase 29 (splits manifest). The latest-dependent entity in the milestone.
**Requirements**: REL-01, REL-02, REL-03, REL-04, REL-05, REPRO-01, REPRO-02, SEC-01, SEC-02
**Success Criteria** (what must be TRUE):

  1. A completed Dataset Release produces all thirteen manifest files (`dataset.parquet`, `train.jsonl`, `validation.jsonl`, `test.jsonl`, `dataset-card.md`, `quality-report.json`, `source-manifest.jsonl`, `license-manifest.jsonl`, `policy-decisions.jsonl`, `lineage-manifest.jsonl`, `validation-manifest.jsonl`, `split-manifest.json`, `checksums.txt`, `reproduce.yaml`).
  2. A raw SQL `UPDATE` issued directly against a `released` row, bypassing the ORM entirely, is rejected by a Postgres trigger; a legitimate narrow-allowlist field (e.g. `retracted_at`) can still be updated.
  3. A failed release run never leaves partial artifacts visible as a published release, and retrying an already-completed deterministic run does not create a duplicate release record.
  4. `reproduce.yaml` explicitly separates a deterministic-reproducible tier (source → clean → chunk → curate → split, rebuilt bit-identical from the same inputs, proven by an automated test) from an explainable-not-replayable tier (LLM generation steps, served from cache on rebuild rather than re-invoked).
  5. A source whose redistribution is prohibited cannot enter a public-mode release; a private-mode release referencing the same source succeeds.

**Plans**: TBD

### Phase 31: Evaluation Run Foundation + Dataset Diff + Lineage Explorer

**Goal**: A released dataset can be evaluated with a minimal deterministic adapter, two releases can be diffed from their manifests alone, and any record can be traced from Project through Release down to its original Source.
**Depends on**: Phase 30 (needs at least one Release to evaluate/explore; at least two to diff meaningfully).
**Requirements**: EVALRUN-01, EVALRUN-02, DIFF-01, LINEAGE-01
**Success Criteria** (what must be TRUE):

  1. An Evaluation Run against a released dataset records the release, evaluation type, model/RAG system under test, evaluator, configuration, benchmark, metrics, failure examples, and execution metadata.
  2. `klake dataset diff <release-a> <release-b>` reports sources/documents/records added-removed-changed, split changes, and license-policy/quality-contract/validator/rejection-rate/contamination changes — computed from manifests, not a full record-by-record scan.
  3. A user can navigate Project → Release → Split → Example → Validation Result → Candidate → Chunk → Parsed Document → Raw Document → Source → Policy Decision via the API for at least one real example, joining the existing content-lineage graph with the new governance-entity graph.

**Plans**: TBD

### Phase 32: Flagship Release + Lineage Demo

**Goal**: The AI Agent Security and Permission Dataset is released end-to-end through the complete v2.7 lifecycle, proving every governance mechanism built in this milestone on real, non-healthcare data.
**Depends on**: Phase 24 (flagship corpus), Phase 30 (release mechanics), Phase 31 (lineage explorer for the demo).
**Requirements**: FLAGSHIP-01, FLAGSHIP-02
**Success Criteria** (what must be TRUE):

  1. The flagship Dataset Project completes its full lifecycle (draft → ... → released), producing a curated RAG corpus, a small grounded instruction set, and a protected evaluation set.
  2. The flagship release ships with complete manifests — quality report, policy report, rejection report, and release manifest — all non-empty and internally consistent.
  3. At least one released flagship example is traced through the complete source-to-release chain via the lineage explorer, as the milestone's key demo.

**Plans**: TBD

## Next Milestone

Not yet defined. Phase numbering will continue at **Phase 33** for the milestone after v2.7.

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-6 | v1.0 MVP | 25/25 | ✅ Shipped | 2026-07-07 |
| 7-12 | v2.0 Agent-Ready Lake | 38/38 | ✅ Shipped | 2026-07-12 |
| 13-16 | v2.5 PageIndex Plugin Integration | 14/14 | ✅ Shipped | 2026-07-15 |
| 17-22 | v2.6 Data Quality & Enrichment | 24/24 | ✅ Shipped | 2026-07-18 |
| 23. Dataset Project + Specification Foundation | v2.7 | 7/7 | Complete    | 2026-07-21 |
| 24. Flagship Domain Pack Foundation | v2.7 | 0/4 | Not started | - |
| 25. Usage Policy Engine | v2.7 | 0/TBD | Not started | - |
| 26. Quality Contract | v2.7 | 0/TBD | Not started | - |
| 27. CurationEngine Protocol + DataTrove Backend + Result Partitions | v2.7 | 0/TBD | Not started | - |
| 28. Generated-Example Candidate Lifecycle + Validation | v2.7 | 0/TBD | Not started | - |
| 29. Deterministic Splits + Contamination Gate | v2.7 | 0/TBD | Not started | - |
| 30. Immutable Dataset Release + Reproducibility Manifest | v2.7 | 0/TBD | Not started | - |
| 31. Evaluation Run Foundation + Dataset Diff + Lineage Explorer | v2.7 | 0/TBD | Not started | - |
| 32. Flagship Release + Lineage Demo | v2.7 | 0/TBD | Not started | - |
