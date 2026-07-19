# Project Research Summary

**Project:** Knowledge Lake Framework — v2.7 (Governed Dataset Production and Release Lifecycle)
**Domain:** DatasetOps control plane — repositioning an existing document-ingestion/RAG framework into a governed dataset-production system (versioned specs, usage-policy gating, multi-level quality contracts, deterministic splits/contamination detection, immutable releases + reproducibility manifests, diffing, lineage explorer, evaluation-run foundation)
**Researched:** 2026-07-19
**Confidence:** HIGH

## Executive Summary

v2.7 repositions Knowledge Lake from a RAG/ingestion framework into a single-team DatasetOps control plane -- the correctly-scoped middle ground between "just run scripts" and heavyweight multi-tenant tools like lakeFS/DVC/HF Hub, at a scale of one PostgreSQL registry, S3-compatible storage, and one team producing one flagship dataset at a time. Experts building this kind of system at this scale favor a **manifest-over-immutable-storage** pattern (an insert-only `Release` row referencing content-hashed S3 manifest objects, functioning as a "commit" without adopting git-for-data branch/merge semantics) layered on top of infrastructure that is, encouragingly, almost entirely already in place: `pipeline/quality/predicates.py`'s pure-function combinator, `curate.py`'s DataTrove filter-scoring pattern, the WR-05 content-hash convention, and the existing `Artifact` lineage graph. Zero new production runtime dependencies are required for 5 of 6 researched capabilities; even Croissant metadata (the one new package) is recommended as a dev-only CI validator, not a production import -- the actual work of this milestone is architectural and data-modeling, not toolchain adoption.

The recommended approach is 12-14 new Postgres tables (Dataset Project, Dataset Specification, Policy Definition/Decision, Quality Contract, Curation Run/Result, Validation Run/Result, Example Recovery Attempt, Dataset Release/Artifact/Approval, Evaluation Run) added incrementally -- one small, reversible Alembic migration per phase, in FK-dependency order -- plus additive lifecycle columns on the existing `DatasetExample` table, never a rewrite of `Dataset`/`DatasetExample`'s existing mutable-export contract. New governance concepts are process/decision records, not `Artifact`-shaped content-lineage nodes, and get their own tables with FKs back into the existing lineage graph rather than being crammed into `Artifact.metadata_` JSON blobs (an anti-pattern this milestone must specifically avoid repeating). `pipeline/curate.py` is wrapped, not rewritten, by a new `CurationEngine` protocol whose DataTrove backend preserves the FOUND-03 single-S3-client invariant by staging data through the existing `StorageBackend` rather than adopting DataTrove's own fsspec/S3 I/O.

The dominant risk category is **silent breakage of assumptions four existing production call sites already depend on** -- `Dataset.name` uniqueness, the payload-shape-sniffing contamination check, `license_type="unknown"` as an unenforced default on the entire existing 34-source corpus, and the deliberate architectural rejection of DataTrove's native I/O scaffolding that a prior milestone specifically built around. Every one of these has a documented, low-cost mitigation (explicit backfill migrations shipped in the same unit as schema changes, a grandfather/legacy-review pass for existing sources, DB-level immutability triggers rather than application-only checks, and staging DataTrove I/O through the existing boto3-backed `StorageBackend`). The second-order risk is that the flagship non-healthcare dataset will expose that domain-pack quality-gate conventions have only ever been exercised against healthcare content -- this needs its own budgeted task, not an assumed side effect of "add a domain pack."

## Key Findings

### Recommended Stack

No new production dependencies are needed. `datatrove==0.9.0`, `datasketch==2.0.0`, `sentence-transformers==5.6.0`, `jinja2`, `pyyaml`, `orjson`, `xxhash`, and stdlib (`hashlib`, `importlib.metadata`, `subprocess`) already cover all six researched v2.7 capabilities. The only new package is `mlcroissant==1.1.0`, and it is recommended **dev-only** (CI conformance checker via `mlcroissant validate`), with production Croissant manifests hand-emitted as Pydantic models + `orjson` to avoid pulling `absl-py`/`etils`/`jsonpath-rw`/`rdflib` into every operator's install.

**Core technologies:**
- `LocalPipelineExecutor` (DataTrove, already pinned) -- CurationEngine's DataTrove backend; do NOT install `datatrove[s3]` or `datatrove[ray]` -- no scale justification, and `[s3]` would introduce a second S3 client path violating the documented FOUND-03 invariant
- Hand-rolled deterministic hash-bucket splitter (stdlib `hashlib`) -- same technique already shipped in Phase 21's `chunk_dedup_ledger`; growth-stable across dataset releases, unlike `sklearn.GroupShuffleSplit` which reshuffles prior release assignments as the group set grows
- Tiered contamination detection (stdlib n-gram -> `datasketch` MinHash -> `sentence-transformers` embedding), all already pinned -- explicitly avoid `datatrove[decont]`/`lighteval`, which is Bloom-filter machinery built for trillion-token corpora, a scale mismatch two orders of magnitude beyond this milestone's dozens-to-hundreds-example flagship dataset
- Jinja2 templates (already used for `enrich.j2`/`qa_generation.j2`) -- dataset card generation, no new library
- Postgres `BEFORE UPDATE` trigger -- the actual enforcement mechanism for Release immutability; application-layer checks alone are not sufficient (see Pitfall 4)

### Expected Features

**Must have (table stakes) -- the milestone's actual P1 scope:**
- Dataset Project lifecycle (11-state state machine: draft through released/archived) with transition guards
- Versioned, hashed Dataset Specification (YAML/JSON) -- the reproducibility root
- Structured per-source usage-policy decision matrix (9 fixed enum dimensions: retrieval/training/commercial/derivatives/redistribution/attribution/share-alike/approved/unknown) -- deterministic, zero LLM/NLP
- Multi-level Quality Contract (source/document/chunk/example/split/release) reusing existing `predicates.py`/`scorer.py` at 2 of 6 levels
- `CurationEngine` protocol (prepare/execute/collect) with DataTrove as the sole production backend
- Accepted/rejected/recoverable/quarantined partitioning (4-way, not binary -- no upstream tool models this)
- `ExampleValidator` interface + generated-example lifecycle (generated -> validating -> accepted/recoverable/repaired/rejected)
- Deterministic, versioned, group-aware splits + exact/n-gram contamination gate, replacing `check_train_eval_contamination()`
- Immutable Dataset Release with full manifest bundle (dataset/splits/card/quality/source/license/policy-decisions/lineage/validation/checksums/reproduce.yaml)
- Machine-readable reproducibility manifest + rebuild-equivalence test (scoped honestly to the deterministic tier only)
- Minimal lineage explorer (Postgres recursive CTE over the existing `Artifact` graph, no new database)
- Evaluation Run foundation (schema + one deterministic adapter)
- Flagship proof dataset (AI Agent Security and Permission Dataset) released end-to-end

**Should have (differentiators):**
- `klake dataset diff <release-a> <release-b>` -- manifest-semantic diff, not storage-layer file diff
- MinHash near-dup contamination extension (existing `curate.py` infra reused)
- Croissant JSON-LD export in the release manifest for HF/Kaggle interop

**Defer (v2+):**
- Full RAGAS/RAG-FiT metric integration -- defer until Evaluation Run data model is proven against >= 2 real releases
- A second `CurationEngine` backend beyond DataTrove -- no driver exists yet
- Embedding+LLM-judge ("LLM Decontaminator") contamination detection -- contradicts deterministic-first constraint, over-engineered at this scale
- lakeFS/DVC-style branch/merge storage-versioning layer -- likely never; immutable-release + manifest is the intentional substitute

### Architecture Approach

New governance concepts are added as `Artifact`-adjacent process/decision tables (never crammed into `Artifact.metadata_` JSON), following one-file-per-stage pipeline conventions (`pipeline/project.py`, `policy.py`, `quality_contract.py`, `validation.py`, `split.py`, `release.py`, `eval.py`, plus a new `pipeline/curation/` package). `curate.py` is kept as a thin backward-compatible wrapper delegating to the new `CurationEngine`/`DataTroveCurationEngine`, so existing CLI/API/MCP/Dagster call sites never break. `DatasetExample` gets additive lifecycle/split columns rather than a parallel storage system; `Dataset Release` is a genuinely new insert-only table, never a flag on the existing mutable `Dataset` row.

**Major components:**
1. `pipeline/project.py` + `dataset_projects`/`dataset_specs` -- Dataset Project state machine and versioned/hashed spec, the root everything else scopes to
2. `pipeline/policy.py` + `policy_definitions`/`policy_decisions` -- deterministic per-source usage-policy evaluation, extends (never replaces) `Source.license_type`
3. `pipeline/curation/` (protocol.py, datatrove_engine.py, run.py) -- `CurationEngine` Protocol wrapping the existing DataTrove filter-scoring logic, preserving the CURATE-01 "always evaluate every filter" discipline and the FOUND-03 single-S3-client invariant
4. `pipeline/quality_contract.py` + `pipeline/validation.py` -- multi-level rule evaluation and scoped validation runs, reusing `pipeline/quality/`'s pure predicates as one rule type
5. `pipeline/split.py` -- deterministic hash-bucket splits + contamination gate, superseding `check_train_eval_contamination()` while explicitly retaining its lineage-based overlap signal
6. `pipeline/release.py` -- immutable Release assembly (manifest bundle, checksums, approvals), read-only against `Dataset`/`DatasetExample`, DB-trigger-enforced immutability
7. New `pipeline/lineage_explorer.py` (or extended `lineage.py`) -- a second, complementary graph query joining the existing content-lineage `Artifact` graph with the new governance-entity graph

### Critical Pitfalls

1. **Adding `split`/`status` columns to `DatasetExample` without a same-unit backfill silently makes every pre-migration row invisible to the new contamination gate** -- backfill must derive from the exact same payload-shape signal the current sniff already uses, and ship in the same migration, with a verification assertion (`COUNT(*) WHERE split IS NULL = 0`) as a CI gate.
2. **Introducing versioning to `Dataset` breaks all four existing `export_finetune_dataset(dataset_name)` call sites (CLI/API/MCP/Dagster) at once**, since `UNIQUE(name)` is today's whole identity contract -- requires an explicit, tested "no-version-argument resolves to X" rule and updating all four call sites in the same commit, including the MCP tool's hardcoded `assert len(TOOLS) == 11` tripwire.
3. **A Usage Policy engine gating on `license_type` will fail closed on nearly the entire existing 34-source healthcare corpus**, since `"unknown"` is the unenforced default at every ingest call site today -- requires a one-time human-reviewed grandfather pass over existing sources, run in report-only mode first, before the gate blocks anything.
4. **Application-layer-only immutability checks on Dataset Release are bypassable** by direct SQL, migrations, or forgotten call sites -- must be enforced with a Postgres `BEFORE UPDATE` trigger (with a narrow allowlist for legitimate post-release fields like `retracted_at`), verified by a raw-SQL test that bypasses the ORM entirely.
5. **Adopting DataTrove's real `PipelineExecutor`/checkpoint machinery reintroduces the exact I/O anti-pattern `curate.py`'s docstring was written to avoid** -- its checkpoint state defaults to local disk (breaking S3-as-production-store) and its S3 support requires `s3fs`, a second S3 client path. Resolve explicitly per-phase: either build resumability on the existing Postgres-ledger pattern (Phase 21 precedent) or add `s3fs` as a deliberately reviewed new dependency with `logging_dir` explicitly pointed at S3/MinIO.

## Implications for Roadmap

Based on combined research, the dependency graph across STACK/FEATURES/ARCHITECTURE/PITFALLS converges on the same build order (this is also the order the architecture research's "suggested build order" and the pitfalls' "phase to address" columns independently arrive at):

### Phase 1: Dataset Project + Dataset Specification foundation
**Rationale:** Everything else scopes to a project/spec version; must exist first per both the architecture dependency graph and Pitfall 2 (versioning identity contract must be decided before any other governance concept references a spec version).
**Delivers:** `dataset_projects`, `dataset_specs` tables; `pipeline/project.py` (state machine + versioned/hashed spec); `dpj_`/`dsp_` ID prefixes; explicit resolution rule for the 4 existing `export_finetune_dataset` call sites plus their updated signatures/tests.
**Addresses:** Dataset Project lifecycle, Versioned hashed Dataset Specification (FEATURES.md table stakes).
**Avoids:** Pitfall 2 (silent breakage of 4 existing call sites' identity assumptions).

### Phase 2: Usage Policy engine
**Rationale:** Can build in parallel with Phase 1 (extends `Source.license_type` independently), but must ship with its grandfather/backfill pass in the same phase, not deferred.
**Delivers:** `policy_definitions`, `policy_decisions` tables; `pipeline/policy.py` (deterministic enum evaluation, LLM fallback only for `unknown` classification); a printed, human-reviewed grandfather report over the existing 34-source corpus run in report-only mode first.
**Addresses:** Structured per-source usage-policy decision matrix (FEATURES.md differentiator, positioned as table-stakes-adjacent per the milestone brief).
**Avoids:** Pitfall 3 (fail-closed gate breaking every existing export path on day one).

### Phase 3: Quality Contract
**Rationale:** Must exist before CurationEngine or ValidationRun can consume it; scoped to a project/spec once Phase 1 lands. This is also where the reusable "domain contributes a normative allowlist" mechanism should be designed -- one phase before the flagship phase needs it (Pitfall 9).
**Delivers:** `quality_contracts` (+ optional `quality_contract_rules`) table; `pipeline/quality_contract.py`, reusing `pipeline/quality/predicates.py`/`scorer.py` as one rule type among several; documented domain-level allowlist extension pattern.
**Uses:** Existing pure-predicate combinator (Phase 19/20 precedent).
**Implements:** Multi-level rule evaluation architecture component.

### Phase 4: CurationEngine protocol + DataTrove backend
**Rationale:** Depends on Phase 3 (contract to evaluate against) and Phase 2 (policy decisions gate eligibility).
**Delivers:** `pipeline/curation/` package (protocol.py, datatrove_engine.py, run.py); `curation_runs`/`curation_results` tables; `curate.py` converted to a thin compat wrapper; an explicit, documented decision on checkpoint storage (Postgres-ledger vs. reviewed `s3fs` addition) recorded in the phase plan.
**Uses:** `datatrove==0.9.0` (`LocalPipelineExecutor`), existing `StorageBackend`.
**Avoids:** Pitfall 7 (reintroducing the rejected DataTrove I/O anti-pattern without an explicit decision).

### Phase 5: Example Candidate lifecycle + Recovery Attempt
**Rationale:** Depends on Phase 4's curated output as candidate input.
**Delivers:** `DatasetExample.status`/`generation_metadata` columns; `example_recovery_attempts` table; `ExampleValidator` interface extending `pipeline/datasets.py`'s existing Pydantic-schema-validated LLM output pattern.
**Addresses:** ExampleValidator + generated-example lifecycle (FEATURES.md table stakes).

### Phase 6: Validation Run/Result
**Rationale:** Depends on Phase 3 (contract) and Phase 5 (candidates to validate); can partially overlap with Phase 5.
**Delivers:** `validation_runs`/`validation_results` tables; `pipeline/validation.py`.

### Phase 7: Deterministic group-aware splits + contamination gate
**Rationale:** Depends on Phases 5/6 (only validated/accepted examples are split-eligible); must exist before Release.
**Delivers:** `DatasetExample.split`/`split_version`/`split_group_key` columns (with mandatory backfill in the same migration); `pipeline/split.py` replacing `check_train_eval_contamination()` while explicitly retaining its lineage-based overlap signal as the primary check, adding n-gram/MinHash as supplementary signals with an explicit "unclassified" bucket.
**Avoids:** Pitfalls 1, 6, and 10 (backfill gap, paraphrase/boilerplate false negatives/positives, silent-skip on unrecognized status).

### Phase 8: Immutable Dataset Release
**Rationale:** Depends on Phases 1, 2, 3/6, 7 -- the latest-dependent entity; needs everything else's manifest to reference.
**Delivers:** `dataset_releases`/`release_artifacts`/`release_approvals` tables; `pipeline/release.py`; a Postgres `BEFORE UPDATE` immutability trigger shipped in the same migration as the table; the reproducibility manifest with an explicit two-tier (deterministic-reproducible vs. explainable-not-replayable) schema; rebuild-equivalence test scoped to the deterministic tier only.
**Avoids:** Pitfalls 4 and 5 (bypassable application-only immutability; overpromising LLM-tier reproducibility).

### Phase 9: Evaluation Run foundation
**Rationale:** Depends on Phase 8 (evaluates against a cut Release); lowest-risk, can slip last among the P1 scope.
**Delivers:** `evaluation_runs` table; `pipeline/eval.py`; one deterministic adapter (e.g., citation exact-match), field-named after RAGAS's own sample shape for future compatibility without a schema migration.

### Phase 10: Diff + lineage explorer
**Rationale:** Depends on Phase 8 (needs >= 2 Releases to diff); read-only tooling built last over everything prior.
**Delivers:** `klake dataset diff`; `pipeline/lineage_explorer.py` joining the existing content-lineage `Artifact` graph with the new governance-entity graph.

### Phase 11: Flagship non-healthcare domain pack (AI Agent Security and Permission Dataset)
**Rationale:** Should be scaffolded early (right after/alongside Phase 1) per the architecture research, so every subsequent phase is tested against real flagship data -- but the domain-tuned quality-gate work itself depends on Phase 3's Quality Contract mechanism existing.
**Delivers:** New top-level `domains/<name>/` pack (never `domains/local/`, due to the known `DomainLoader.from_name()` path limitation); a domain-specific normative-allowlist rule set reviewed against a must-not-reject fixture, mirroring the healthcare precedent; end-to-end release of the flagship dataset with full manifests.
**Avoids:** Pitfall 9 (flagship pack exposing that quality-gate conventions were only ever exercised against healthcare).

### CLI/API/MCP/Dagster surface wiring
Wire incrementally per-entity as each pipeline function lands (Phases 1 through 10), not as one big final surface pass -- matching how prior milestones (v2.0, v2.5) shipped surface work phase-by-phase. Each phase bumps the MCP `TOOLS` count assertion as its own forcing function.

### Phase Ordering Rationale

- Ordering follows the FK dependency chain discovered in architecture research (Project -> Spec -> Policy -> Quality Contract -> Curation -> Candidates -> Validation -> Splits -> Release -> Eval/Diff) -- the same order the milestone brief's own target-feature list is already written in.
- One small, reversible Alembic migration per phase (never one giant multi-table migration), matching this project's established 11-migration history and explicitly avoiding Pitfall 8.
- The flagship domain pack is pulled forward (alongside Phase 1) specifically so Pitfall 9's domain-maturity gap surfaces early rather than at the end, even though its quality-gate-specific work depends on Phase 3.
- Immutable Release is deliberately the latest P1 phase -- it is the hard convergence point requiring every other governance concept finalized first, matching both the architecture "suggested build order" and the pitfalls' repeated emphasis on Release correctness (Pitfalls 4, 5, 8).

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 4 (CurationEngine + DataTrove backend):** The checkpoint-storage decision (Postgres-ledger vs. reviewed `s3fs` addition) has real architectural trade-offs not fully resolved by this research round -- needs a `--research-phase` pass or at minimum an explicit design-doc decision before implementation.
- **Phase 7 (splits + contamination gate):** The tiered contamination approach (lineage-primary, n-gram/MinHash-supplementary, boilerplate-aware) is architecturally clear but the specific boilerplate-normalization mechanism for this domain's regulatory disclaimers needs concrete design during planning.
- **Phase 11 (flagship domain pack):** No non-healthcare domain pack has ever been run through the substance/quality gate at volume -- this phase carries real unknowns (short/structured content shapes like permission-scope strings, tool-call identifiers) that synthetic planning cannot fully anticipate; report-only dry-run against real flagship sources is load-bearing here.

Phases with standard patterns (skip research-phase):
- **Phase 1 (Dataset Project + Spec):** Well-documented DVC/HF-analog pattern, direct precedent in this repo's own WR-05 hashing convention.
- **Phase 2 (Usage Policy):** Deterministic enum matrix, direct precedent in T-05-08 allow-list discipline.
- **Phase 3 (Quality Contract):** Reuses existing `pipeline/quality/predicates.py` pure-function combinator almost directly.
- **Phase 6 (Validation Run/Result):** Same shape as Curation Run/Result, no new pattern.
- **Phase 8 (Immutable Release):** Standard Postgres audit-trigger pattern, well-documented externally and internally motivated by this project's own `xfail_strict` history.
- **Phase 9 (Evaluation Run foundation):** Explicitly scoped thin per the milestone brief (schema + one adapter, no RAGAS integration).

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Version numbers live-verified against PyPI/GitHub; all footprint/dependency claims cross-checked against this repo's actual `uv.lock` |
| Features | MEDIUM | HF/Croissant/DataTrove/RAGAS docs well-documented and cross-checked; license/usage-policy prior art (Datasheets, ODRL) is sparser (LOW-MEDIUM); contamination-detection tiers are well-established in the literature |
| Architecture | HIGH | Grounded in direct inspection of the actual codebase (`models.py`, `ids.py`, `alembic/versions/`, `cli/app.py`, `agent/registry.py`, `dagster_defs/assets.py`, `curate.py`, `datasets.py`, `export.py`, `api/schemas.py`) |
| Pitfalls | HIGH for repo-grounded findings (cited file:line); MEDIUM for external DB/LLM-determinism claims (cross-checked against current docs/community sources) |

**Overall confidence:** HIGH

### Gaps to Address

- **Croissant emission strategy (hand-roll vs. `mlcroissant` library):** the research recommends hand-rolling for now, but this should be revisited if the hand-rolled emitter proves brittle across a future Croissant spec bump -- flag as a P2 decision, not blocking for v1.
- **DataTrove checkpoint storage decision (Pitfall 7):** genuinely unresolved between two valid options (Postgres-ledger reuse vs. reviewed `s3fs` addition) -- must be decided explicitly in Phase 4's plan, not discovered during implementation.
- **`check_train_eval_contamination()` delegation vs. legacy fallback:** architecture research flags this as needing an explicit REQUIREMENTS.md decision -- full delegation (breaking change to existing callers' return shape) vs. legacy fallback path kept alive during transition.
- **KL-16 (domain-pack-owned Dagster jobs) interaction with the flagship pack:** architecturally consistent to defer per this research, but flag as an open question for REQUIREMENTS.md rather than pre-deciding -- becomes a hard prerequisite only if the flagship pack needs a genuinely distinct Dagster schedule/sensor, not just parameterized asset behavior.
- **MCP tool parity for governance actions:** not every new entity needs an MCP tool; which mutating actions (cutting a Release, approving it) stay CLI/API-only vs. agent-accessible is a decision for REQUIREMENTS.md, not assumed full parity.

## Sources

### Primary (HIGH confidence)
- https://pypi.org/project/datatrove/, https://pypi.org/project/mlcroissant/, https://pypi.org/project/scikit-learn/ -- live-fetched version/release data
- https://github.com/huggingface/datatrove (README, `pyproject.toml`, `pipeline/filters/base_filter.py`, `executor/base.py`, `executor/local.py`, `io.py`) -- executor types, checkpoint mechanism, exclusion-writer machinery
- https://github.com/mlcommons/croissant (`python/mlcroissant` `pyproject.toml`, README) + https://docs.mlcommons.org/croissant/docs/croissant-spec.html
- https://www.postgresql.org/docs/current/plpgsql-trigger.html -- immutability trigger pattern
- Direct repo inspection (HIGH confidence, ground truth): `src/knowledge_lake/registry/models.py`, `ids.py`, `alembic/versions/*`, `cli/app.py`, `agent/registry.py`, `dagster_defs/assets.py`, `pipeline/curate.py`, `pipeline/datasets.py`, `pipeline/export.py`, `api/schemas.py`, `domains/aviation/`, `domains/climate/`, `domains/healthcare/filters.yaml`, `.planning/PROJECT.md`, `uv.lock`

### Secondary (MEDIUM confidence)
- https://huggingface.co/docs/hub/datasets-cards, https://huggingface.co/docs/datasets/upload_dataset -- dataset card conventions
- https://dvc.org/, https://lakefs.io/data-version-control/dvc-tools/ -- versioning-tool prior art (lakeFS acquired by DVC Nov 2025, ecosystem consolidating)
- https://docs.ragas.io/en/stable/concepts/components/eval_dataset/ and /eval_sample/ -- Evaluation Run schema shaping
- https://arxiv.org/pdf/1803.09010 (Datasheets for Datasets), https://arxiv.org/pdf/2309.11289 (ODRL usage-control patterns)
- https://arxiv.org/pdf/2502.14425, https://arxiv.org/html/2605.19999v1 -- benchmark contamination detection literature
- LLM temperature/determinism sources (vLLM discussion #17166, multiple independent practitioner write-ups) -- cross-checked, converging conclusion that temperature=0 + seed does not guarantee bit-identical reproduction

### Tertiary (LOW confidence)
- None flagged as needing further validation beyond the gaps listed above.

---
*Research completed: 2026-07-19*
*Ready for roadmap: yes*
