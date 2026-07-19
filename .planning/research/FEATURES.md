# Feature Research

**Domain:** DatasetOps / governed AI-dataset production control plane (v2.7 milestone)
**Researched:** 2026-07-19
**Confidence:** MEDIUM (official docs/specs for HF/Croissant/DataTrove/RAGAS are well-documented and cross-checked; the license/usage-policy prior art is sparser and rated LOW-MEDIUM; contamination-detection tiers are well-established in the literature)

## Context

This milestone repositions Knowledge Lake from a RAG/ingestion framework into a DatasetOps control plane. The scale constraint matters for every categorization below: **single PostgreSQL registry, S3-compatible storage, one team, no distributed/multi-tenant requirement.** That constraint rules out several "gold standard" patterns used by HF/lakeFS/DVC at their scale (git-for-data storage engines, distributed metric aggregation) and instead favors **manifest-over-immutable-storage** patterns that reuse what's already built: the `Artifact` lineage graph, `pipeline/quality/predicates.py`'s pure-function combinator, `pipeline/curate.py`'s direct `.filter(doc)` DataTrove-wrapping pattern, and the WR-05 content-hash convention.

## Feature Landscape

### Table Stakes (Users Expect These)

Standard practice in every credible DatasetOps/dataset-curation tool at this scale. Missing these makes the "governed dataset" claim non-credible.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Dataset Project lifecycle (state machine: draft→configured→sources_pending→ready→processing→validating→review_required→releasable→released→failed→archived) | Every DatasetOps tool (MLflow model registry stages, HF Hub repo states, DVC pipeline stages) gates promotion through explicit states — "just run scripts" is the anti-pattern this milestone is escaping | MEDIUM | New table + enum + transition-guard functions. No prior art gives you this off the shelf — HF/DVC version *files*, not *projects with a lifecycle*. This is where the framework earns its "control plane" name, not a copy of an existing tool's feature |
| Versioned, hashed Dataset Specification (YAML/JSON) | Direct analog of DVC's `dvc.yaml`/`params.yaml` + HF's dataset-card YAML frontmatter — declarative config + a content hash is the standard reproducibility unit across the ecosystem | LOW-MEDIUM | Reuses the WR-05 "hash the config, fold into idempotency key" convention already used for `filter_config_version` in chunk hashing (Phase 20, PIPE-01) — not a new concept, just a new place to apply it |
| Accepted/rejected result partitioning with a reason per item | DataTrove itself already does this: every filter's `.filter(doc)` call in `pipeline/curate.py` returns pass/fail + reason, aggregated via `BaseStats`. This is the industry default for any quality/curation pipeline | LOW | Direct precedent: `curate.py`'s CURATE-01 "never call `.run()`, always the direct filter loop so every heuristic's outcome is recorded regardless of earlier failures" is exactly the discipline the Quality Contract needs to generalize |
| Multi-level Quality Contract with pass/fail per level | Standard in mature curation pipelines (FineWeb's own pipeline scores/filters at document AND corpus level; HF datasets apply per-split validation) — a single global "quality score" is considered too coarse for governed datasets | MEDIUM-HIGH | **Direct dependency:** chunk-level rules should wrap `pipeline/quality/predicates.py`'s `run_predicates()` combinator (7 pure predicates, zero I/O) rather than reimplementing thresholds. Document-level rules reuse `quality/scorer.py`'s `compute_composite_quality_score()`. Source-level, example-level, split-level, and release-level are the genuinely new levels this milestone must build — the framework already has 2 of 6 levels' underlying logic |
| `CurationEngine` protocol (prepare/execute/collect) | Consistent with the project's own established plugin-protocol convention (`VectorStorePlugin`, `IndexerPlugin`) — every external tool is a swappable plugin behind a narrow interface | LOW-MEDIUM | Thin wrapper around the existing `pipeline/curate.py` DataTrove integration; DataTrove becomes "the first production backend," not a rewrite. **Anti-pattern already flagged in curate.py's own docstring:** never route through DataTrove's `.run()`/reader/writer/executor scaffolding — the new protocol must preserve that boundary |
| `ExampleValidator` interface + generated-example lifecycle (generated→validating→accepted/recoverable/repaired/rejected) | Same shape as every "LLM-generated content needs a validation gate" pattern (Pydantic-schema-validated LLM output is already how `pipeline/datasets.py`'s `QAPairResult`/`InstructionPairResult` work) | LOW-MEDIUM | Direct extension of `pipeline/datasets.py`'s existing "validate against Pydantic schema before persisting" pattern (D-05/D-07) — the new work is a status enum on `DatasetExample` + a repair/re-validate hook, not new LLM-call plumbing |
| Deterministic, versioned, group-aware train/validation/test splits | Standard ML practice (scikit-learn `GroupKFold`, HF `datasets.train_test_split` with stratify/seed) — ungrouped random splits leak near-duplicates across splits, a well-known correctness bug | MEDIUM | **Direct dependency:** grouping key should be `cleaned_document`/`Source` lineage (already in the registry) plus `curate.py`'s existing `dedup_status='near_dup'` MinHash flag (CURATE-02) — group assignment must keep near-dup clusters together, reusing data that already exists rather than recomputing similarity |
| Exact + n-gram-overlap contamination gate for splits/benchmarks | This is literally the "minimum credible bar" identified across the contamination-detection literature (NeMo Curator's decontamination pipeline uses 8–13-gram overlap as its baseline method) — anything less (today's payload-shape/ID-sniffing check) is not a credible contamination gate | MEDIUM | **Replaces, not extends,** `pipeline/export.py`'s `check_train_eval_contamination()` — that function only checks `cleaned_document` *ID* overlap between eval/train sets, never *text content* overlap, so a re-crawled or paraphrased duplicate with a new artifact ID slips through undetected today. This is a real, not hypothetical, gap |
| Immutable Dataset Release with a manifest bundle (dataset/splits/card/quality/source/license/policy-decisions/lineage/validation/checksums/reproduce.yaml) | Exactly DVC/lakeFS's "commit = immutable checkpoint, tag it, reproduce by checking it out" pattern, scaled down to a single-team Postgres+S3 stack instead of a git-for-data storage engine | MEDIUM | This is the correctly-scoped version of what lakeFS/DVC provide at a heavier operational cost — a new `Release` row referencing immutable S3 manifest objects is the single-team equivalent of a lakeFS commit, without adopting branching/merge semantics the project explicitly ruled out already (`VERSION-01` deferred, "lakeFS/DVC data versioning... raw zone immutability covers the core need") |
| Machine-readable reproducibility manifest + rebuild-equivalence test | Same DVC/lakeFS principle ("tag code+data+config, reproduce exactly") applied without adopting their storage layer | MEDIUM | Manifest = Dataset Specification hash + pipeline/library versions + filter_config_version + seed; the "test" is comparing a rebuild's output hashes against the manifest's recorded hashes — reuses the WR-05 hashing convention throughout |
| Minimal lineage explorer (Project→Release→Split→Example→Validation→Candidate→Chunk→Parsed Doc→Raw Doc→Source→Policy Decision) | Core Value of the whole project is end-to-end traceability; the `Artifact` table is already a self-referencing lineage graph (v1.0) | LOW-MEDIUM | **Must be scoped as a read-only recursive-CTE query layer over the existing Postgres `Artifact.parent_id` chain, extended with the new tables** — not a new graph database. Standing up Neo4j/similar for a single-team framework is the textbook over-engineering anti-pattern this research explicitly flags below |
| Human-readable + machine-readable dataset card bundled with the release | HF's dataset card (YAML frontmatter + README rendered on the Hub) is the universal expectation — every dataset consumer expects license/size/splits/provenance in one place | LOW | Generated from the Release manifest fields already planned; no new data, just a rendering/serialization step |

### Differentiators (Competitive Advantage)

Not required to be credible, but where this framework can genuinely out-perform HF Hub / DVC / lakeFS / DataTrove at single-team scale — either because those tools don't solve this problem, or solve it in a way too heavy for this scale.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Recoverable / quarantined partitions (beyond binary accept/reject) | DataTrove and typical pretraining pipelines are binary — filter fails, document dropped, done. Nothing reviewed later. For a *governed* dataset (as opposed to a bulk pretraining corpus) "silently discarded" is unacceptable — a recoverable/quarantined state lets an operator or a repair step reclaim borderline content instead of losing it | MEDIUM | New value entirely — no upstream tool models this. Directly enabled by extending `pipeline/quality/predicates.py`'s `PredicateResult(passed, reason)` return shape to a 4-way outcome enum rather than reworking predicate logic itself |
| Structured, deterministic, per-source usage-policy decision matrix (approved/retrieval/training/commercial/derivatives/redistribution/attribution/share-alike/unknown) | Datasheets for Datasets and the Data Nutrition Project are narrative questionnaires, not machine-decidable. ODRL is a full rights-expression language (permission/prohibition/duty/asset/party) capable of automated policy evaluation, but it's built for enforcement across untrusted multi-party data spaces — far heavier than a single team needs, and its natural extension point (parsing license *text* into ODRL policies) is exactly the "LLM legal-interpretation engine" this milestone explicitly rules out | LOW-MEDIUM | New table (extends `Source.license_type`/`license_url`, which today are free-text/unenforced) with one **fixed enum per dimension** (allowed / denied / unknown / conditional) and a human-entered rationale field. Evaluated deterministically at Dataset Spec compile-time and Release-time by matching a Dataset Project's declared intended-use against each contributing source's row — pure enum/boolean logic, zero NLP. This is the "steal the shape, skip the machinery" reading of ODRL |
| `klake dataset diff <release-a> <release-b>` | lakeFS/DVC diff at the *storage* layer (which files changed) — heavy infra for a single team. HF Hub gives you git-style file diffs but no dataset-semantic diff (splits changed, quality contract deltas, example counts by outcome, policy decisions changed) | LOW-MEDIUM | Because Release manifests are already structured JSON (per the table-stakes row above), diff is a manifest-to-manifest JSON comparison — no storage-versioning engine needed. Directly enabled by, and only possible after, the Release manifest structure exists |
| Croissant JSON-LD export in the release manifest for external interop | Croissant is explicitly designed to layer on top of an existing metadata registry as an export/interop format (4-layer JSON-LD: Metadata/Resources/Structure/ML-semantics + RAI extension), not to replace one — makes released datasets loadable by HF/Kaggle/Croissant-aware tooling for free | LOW-MEDIUM | Pure projection of existing registry fields (`Source.license_type`, `Dataset`/`DatasetExample` counts, split info) into JSON-LD — no new data collection required. Good stretch/differentiator, not core-path critical |
| Evaluation Run data model shaped to slot into RAGAS/RAG-FiT without a schema migration later | RAGAS's own `EvaluationDataset`/`SingleTurnSample` (`user_input`/`response`/`reference`/`retrieved_contexts`, all-optional fields) has **no persisted "run" entity** — RAGAS is a stateless scoring function, not a system of record. Building the missing persistence layer (which release/split was evaluated, which adapter, aggregate + per-example scores, timestamp) is real, non-duplicative value | MEDIUM | New `EvaluationRun`/`EvaluationResult` tables + one deterministic adapter (e.g., citation/answer exact-match against the existing `dataset_examples.payload.citation_chunk_id` field from `pipeline/datasets.py`). Field-name the sample schema after RAGAS's own shape now so a future RAGAS adapter is a pure mapping function, not a redesign |
| MinHash-based near-dup contamination gate (benchmark ↔ training), reusing existing infra | Goes one tier past the table-stakes exact/n-gram gate toward the literature's "credible upper-middle" bar (Jaccard ≥0.8 near-dup catches lightly-edited copies n-gram overlap alone misses) — without paying for the top tier (embedding-similarity + LLM-judge, i.e. the "LLM Decontaminator" pattern) | MEDIUM | The framework **already has this infrastructure**: `clean.py`'s `compute_minhash()` and `curate.py`'s corpus-wide `MinHashLSH` index (CURATE-02) exist today for document-level near-dup detection. Extending the same index to check benchmark/held-out eval text against training-split text is mostly wiring, not new algorithm work |

### Anti-Features (Commonly Requested, Often Problematic)

Features that look attractive given the prior art surveyed, but would be wrong for this scale or explicitly contradict the milestone's stated non-goals.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|------------------|-------------|
| Git-for-data storage engine (lakeFS/DVC-style branch/merge/diff at the object-storage layer) | "Real" dataset versioning tools (lakeFS, DVC) do this, and the milestone talks about versioning and diffing | Operationally heavy for one team (lakeFS itself just got acquired by DVC in Nov 2025 — even that ecosystem is consolidating rather than expanding); duplicates work the raw-zone WORM immutability + `Release` manifest pattern already covers; explicitly out of scope already (`VERSION-01` deferred at v2.0/v2.6: "raw zone immutability covers the core need") | Immutable `Release` row + manifest of content-hashed S3 objects (already table stakes above) — a "commit," without adopting branch/merge semantics |
| LLM-based legal/license-text interpretation engine | Tempting because free-text `license_type`/`license_url` today is unenforced, and an LLM could "read the license and decide" | Explicitly out of scope per this milestone's own framing ("NOT an LLM legal-interpretation engine"); legal interpretation needs human accountability, not a probabilistic model; also breaks the project's "deterministic first" constraint at the exact point where determinism matters most (compliance) | The structured enum-based usage-policy decision matrix (differentiator above) — a human fills in the enum once per source, the system evaluates deterministically forever after |
| ODRL as the internal policy *engine* (not just a design reference) | ODRL is the closest real standard for machine-enforceable data-usage policy, so "just adopt ODRL" seems like reuse-not-reinvent | ODRL is built for automated policy negotiation/enforcement across untrusted multi-party data spaces (its usual pairing is with data-space connectors like Eclipse Dataspace Components) — massive surface area for a single-registry, single-team framework with one clear owner per source. You'd be importing a rights-expression language and its evaluator to answer a question that's really "is this source's `commercial` flag true or false" | Borrow ODRL's *shape* (party/asset/permission/prohibition/duty) conceptually when designing the enum dimensions, but implement as flat Postgres columns/enums, not an ODRL document + evaluator |
| A second `CurationEngine` backend (e.g. NeMo Curator) built alongside DataTrove in this milestone | The protocol design ("first production backend") implies more backends are coming, and it's tempting to prove the abstraction with a second implementation now | No second backend has a proven need yet; this mirrors the project's own established convention (interface-first, one concrete implementation, second implementation only when a real driver appears — see `IndexerPlugin`/`VectorStorePlugin` history) — premature abstraction proof is wasted effort here | Ship `CurationEngine` as a protocol with DataTrove as the only concrete implementation; add a second backend only when a specific need (e.g. GPU-scale curation) actually arrives |
| Graph-database-backed lineage explorer (Neo4j or similar) | "Lineage explorer" sounds like a graph-traversal problem, and dedicated graph DBs are the obvious tool for graph traversal | Adds a second stateful system to operate for a single-team framework whose Core Value already lives in Postgres; the existing `Artifact` table is already a self-referencing lineage graph proven at v1.0 scale; recursive CTEs handle multi-hop traversal fine at this scale | Postgres recursive CTE queries over `Artifact.parent_id` + the new Project/Release/Split/Example/Validation/PolicyDecision tables; expose via CLI/API as a read-only graph projection (JSON tree or DOT/Mermaid render), no new database |
| Full RAGAS/RAG-FiT metric integration (faithfulness, answer relevancy, context precision — the LLM-judge metrics) in this milestone | RAGAS is the obvious "real" RAG-eval tool, and the milestone explicitly gestures at "eventually plug into these" | Explicitly scoped out ("not a full RAGAS/RAG-FiT integration"); those metrics require LLM-judge calls at eval time, which is real cost/latency/budget-cap surface area the milestone hasn't scoped; premature before the Evaluation Run *data model* itself is proven | Evaluation Run foundation (differentiator above) with one deterministic adapter now; a RAGAS adapter is a follow-up milestone once the data model is proven against real dataset releases |
| Embedding-similarity + LLM-judge contamination detection ("LLM Decontaminator" pattern) | It's the literature's gold standard and catches paraphrased contamination n-gram/MinHash both miss | Expensive (embedding pass + LLM judge calls over every eval/train pair), contradicts "deterministic first," and the milestone's own contamination-gate scope is "deterministic ... gate," not a probabilistic one | Exact + n-gram (table stakes) plus MinHash near-dup (differentiator, reusing existing `curate.py` infra) is the correctly-scoped bar; flag it as a documented residual risk in the reproducibility manifest, revisit only if a real contamination incident occurs |
| Croissant compliance as a hard release-blocking requirement | Once you're emitting Croissant, it's tempting to make it authoritative | Croissant's `license` field is a plain string/URL, not a decision object — it cannot express the milestone's own 9-dimension usage-policy matrix (retrieval/training/commercial/derivatives/etc.), so treating it as authoritative would be a step backward in policy fidelity, not forward | Emit Croissant as a derived, best-effort export projection for interop (differentiator above); the internal policy/quality-contract model stays the source of truth |

## Feature Dependencies

```
Dataset Project (lifecycle state machine)
    └──requires──> Versioned, hashed Dataset Specification
                       └──requires──> Quality Contract (levels referenced by spec)
                                          └──requires──> CurationEngine (executes contract rules)
                                                             └──produces──> Accepted/Rejected/Recoverable/Quarantined partitions

Usage Policy Decision matrix (per-source, extends Source.license_type)
    └──gates──> Dataset Specification activation (policy check at compile-time)
    └──gates──> Dataset Release (policy check at release-time)

ExampleValidator + generated-example lifecycle
    └──extends──> pipeline/datasets.py's existing QAPairResult/InstructionPairResult validation
    └──feeds──> Deterministic group-aware splits (only accepted/recoverable examples are split-eligible)

Deterministic group-aware splits
    └──requires──> Quality Contract results (example-level outcome) + curate.py's dedup_status (grouping key)
    └──requires──> Contamination gate (exact + n-gram; MinHash near-dup as a differentiator extension)

Dataset Release (immutable)
    └──requires──> Splits finalized + Quality Contract results finalized + Policy Decisions finalized
    └──produces──> Reproducibility manifest (spec hash + versions + seed)
    └──produces──> Dataset card (rendered from manifest)

Dataset Diff
    └──requires──> Two or more Dataset Releases to exist (cannot exist before the first release ships)

Lineage Explorer
    └──cuts across──> Project, Release, Split, Example, Validation, Candidate, Chunk, Parsed Doc, Raw Doc, Source, Policy Decision
    └──requires──> Nothing new structurally — read-only query layer over existing Artifact graph + new tables

Evaluation Run foundation
    └──requires──> Dataset Release (or at minimum a finalized Split) to evaluate against
    └──enhances (future)──> RAGAS/RAG-FiT integration (deferred; schema must be shaped for it now)

Croissant export ──enhances──> Dataset card / release manifest (optional interop layer, not on the critical path)
```

### Dependency Notes

- **Dataset Project requires Dataset Specification:** a project without a hashed, versioned spec has nothing reproducible to point to — the spec is the reproducibility contract's root.
- **Quality Contract requires CurationEngine:** the contract defines *what* passes at each level; the engine is *how* rules execute (DataTrove today). Building the contract schema without the engine abstraction would hardcode DataTrove-specific assumptions into contract semantics.
- **Splits require Contamination gate + Quality Contract outcomes:** you cannot deterministically assign held-out/eval groups until you know which examples are even eligible (accepted/recoverable) and which are near-dup clusters (grouping key) — sequencing splits before quality-gating would let rejected/garbage content leak into a "final" split.
- **Dataset Release requires Splits + Quality Contract + Policy Decisions all finalized:** immutability means nothing else can change after release — this is the hard ordering constraint that makes Release the last node before "done," mirroring lakeFS/DVC's "immutable commit" semantics.
- **Dataset Diff requires ≥2 Releases:** naturally a v1.x feature, not v1 — the very first release of the flagship dataset has nothing to diff against.
- **Usage Policy Decisions gate both spec-activation and release-time, not just once:** a source's policy could change between spec-draft and release (e.g., a source gets re-reviewed) — checking only once would let a stale decision silently persist through a long-running project.
- **Lineage Explorer has no upstream dependency** — it's a read-only projection, so it can be built incrementally in parallel with everything else, as long as the new tables (Project/Release/Split/Validation/PolicyDecision) exist to be queried.

## MVP Definition

### Launch With (v1 — this milestone)

Minimum viable set to legitimately claim "governed dataset production," aligned to the milestone's own target-feature list:

- [ ] Dataset Project lifecycle (state machine + transition guards) — the organizing entity everything else hangs off
- [ ] Versioned, hashed Dataset Specification (YAML/JSON) — reproducibility root
- [ ] Structured per-source usage-policy decision table (9 fixed enum dimensions, extends `Source.license_type`) — deterministic, no LLM
- [ ] Multi-level Quality Contract (source/document/chunk/example/split/release) — reusing `pipeline/quality/predicates.py` at chunk level and `quality/scorer.py` at document level; genuinely new at the other 4 levels
- [ ] `CurationEngine` protocol wrapping the existing `pipeline/curate.py` DataTrove integration as the sole backend
- [ ] Accepted/rejected/recoverable/quarantined partitioning with aggregated rejection reporting
- [ ] `ExampleValidator` interface + generated-example lifecycle, extending `pipeline/datasets.py`
- [ ] Deterministic, versioned, group-aware splits + exact/n-gram contamination gate, replacing `check_train_eval_contamination()`
- [ ] Immutable Dataset Release with full manifest bundle (dataset/splits/card/quality/source/license/policy-decisions/lineage/validation/checksums/reproduce.yaml)
- [ ] Machine-readable reproducibility manifest + rebuild-equivalence test
- [ ] Coherent CLI/API/MCP command groups (`dataset`/`project`/`policy`/`curation`/`release`) as thin shims over shared application services
- [ ] Minimal lineage explorer (Postgres recursive CTE query layer, no new infra)
- [ ] Evaluation Run foundation (schema + one deterministic adapter, e.g. citation exact-match)
- [ ] Flagship proof dataset (AI Agent Security and Permission Dataset) released end-to-end with full manifests + one traceable lineage demonstration

### Add After Validation (v1.x)

- [ ] `klake dataset diff <release-a> <release-b>` — trigger: as soon as a second Release exists (naturally impossible before then)
- [ ] MinHash-based near-dup contamination gate extending exact/n-gram — trigger: if the flagship dataset's exact/n-gram gate is empirically found to miss lightly-edited duplicates (existing `curate.py` MinHash infra makes this a low-cost extension whenever justified)
- [ ] Croissant JSON-LD export in the release manifest — trigger: first external consumer (HF Hub upload, Kaggle, or any Croissant-aware downstream tool) actually requests it

### Future Consideration (v2+)

- [ ] Full RAGAS/RAG-FiT metric integration (faithfulness, answer relevancy, context precision) — defer until the Evaluation Run data model has been proven against ≥2 real releases
- [ ] Second `CurationEngine` backend beyond DataTrove — defer until a specific concrete need appears (e.g., GPU-scale curation volume)
- [ ] Embedding-similarity + LLM-judge contamination detection — defer to a dedicated future milestone if a real contamination incident is ever found
- [ ] lakeFS/DVC-style branch/merge storage-versioning layer — likely never; the immutable-release + manifest pattern is the intentionally-scoped substitute for a single-team framework

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Dataset Project lifecycle | HIGH | MEDIUM | P1 |
| Versioned, hashed Dataset Specification | HIGH | LOW-MEDIUM | P1 |
| Usage-policy decision matrix (deterministic enum) | HIGH | LOW-MEDIUM | P1 |
| Multi-level Quality Contract | HIGH | MEDIUM-HIGH | P1 |
| `CurationEngine` protocol (DataTrove backend only) | MEDIUM | LOW-MEDIUM | P1 |
| Accepted/rejected/recoverable/quarantined partitions | HIGH | MEDIUM | P1 |
| `ExampleValidator` + generated-example lifecycle | MEDIUM | LOW-MEDIUM | P1 |
| Deterministic group-aware splits + exact/n-gram contamination gate | HIGH | MEDIUM | P1 |
| Immutable Dataset Release + manifests | HIGH | MEDIUM | P1 |
| Reproducibility manifest + rebuild-equivalence test | HIGH | MEDIUM | P1 |
| Minimal lineage explorer | MEDIUM | LOW-MEDIUM | P1 |
| Evaluation Run foundation (1 adapter) | MEDIUM | MEDIUM | P1 |
| `dataset diff` | MEDIUM | LOW-MEDIUM | P2 |
| MinHash near-dup contamination extension | MEDIUM | MEDIUM | P2 |
| Croissant export | LOW-MEDIUM | LOW-MEDIUM | P2 |
| Full RAGAS/RAG-FiT integration | HIGH (eventually) | HIGH | P3 |
| Second CurationEngine backend | LOW (no driver yet) | HIGH | P3 |
| Embedding+LLM-judge contamination | LOW (over-engineering at this scale) | HIGH | P3 |

**Priority key:**
- P1: Must have — this is the milestone's actual scope
- P2: Should have, add when the natural trigger arrives (second release, empirical gap found, first external consumer)
- P3: Nice to have, explicitly future/deferred

## Competitor Feature Analysis

| Feature dimension | HF Hub / `datasets` | DVC / lakeFS | MLCommons Croissant | This framework's approach |
|---|---|---|---|---|
| Versioning unit | Git commit/tag on a repo of files | Git-style commit on data-lake objects (lakeFS) or DVC-tracked file pointers | N/A (metadata format, not a versioning system) | Immutable `Release` row referencing content-hashed S3 manifest objects — a "commit" without adopting branch/merge storage semantics |
| Dataset card / metadata | YAML frontmatter + README, human+machine readable | N/A (DVC has no card concept; lakeFS has commit metadata only) | 4-layer JSON-LD (Metadata/Resources/Structure/ML-semantics) + RAI extension | Card rendered from the Release manifest; optional Croissant JSON-LD projection for interop |
| Splits | Declared in YAML (`train`/`validation`/`test`), no code required | N/A | Croissant's `RecordSet` can describe splits as a field, but doesn't enforce group-awareness or contamination | Deterministic, versioned, **group-aware** splits (dedup-cluster-aware) + an explicit contamination gate — stronger correctness guarantee than either prior art |
| License/usage model | Single license string/tag in card metadata | N/A | Single `license` field (string/URL) in Metadata layer | 9-dimension deterministic enum decision matrix per source (retrieval/training/commercial/derivatives/redistribution/attribution/share-alike/approved/unknown) — materially more granular than any of the three |
| Diff | Git file diff (which bytes changed) | Git-style file/commit diff at storage layer | N/A | Manifest-semantic diff (`dataset diff`): example counts by outcome, split membership deltas, quality-contract deltas, policy-decision changes — a higher-level diff than "which bytes changed" |
| Curation/quality reporting | N/A (no built-in curation pipeline) | N/A | N/A | Multi-level Quality Contract with accepted/rejected/recoverable/quarantined outcomes — no prior-art tool surveyed does leveled contracts with a 4-way (not binary) outcome |
| Contamination detection | N/A | N/A | N/A | Exact + n-gram gate (table stakes) at minimum, MinHash near-dup as a stretch — replaces today's ID-sniffing check with actual text-overlap detection |
| Lineage | Commit history (file-level, not semantic) | Commit history (file-level) | Croissant can reference a `source` but has no lineage-graph concept | Recursive lineage graph over the existing `Artifact` table, extended through Project→Release→Split→Example→Candidate→Chunk→Doc→Source→PolicyDecision — this is the framework's original Core Value, kept intact |

## Sources

- [Dataset Cards · Hugging Face](https://huggingface.co/docs/hub/datasets-cards)
- [Share a dataset to the Hub · Hugging Face](https://huggingface.co/docs/datasets/upload_dataset)
- [Datasets Overview · Hugging Face](https://huggingface.co/docs/hub/datasets-overview)
- [DVC — Home](https://dvc.org/)
- [Best Data Version Control Tools in 2026 — lakeFS](https://lakefs.io/data-version-control/dvc-tools/)
- [DVC vs. Git-LFS vs. Dolt vs. lakeFS: Data Versioning Compared](https://lakefs.io/blog/dvc-vs-git-vs-dolt-vs-lakefs/)
- [Croissant Format Specification (GitHub)](https://github.com/mlcommons/croissant/blob/main/docs/croissant-spec.md)
- [Croissant: A Metadata Format for ML-Ready Datasets (arXiv)](https://arxiv.org/pdf/2403.19546)
- [Croissant — MLCommons](https://mlcommons.org/working-groups/data/croissant/)
- [huggingface/datatrove (GitHub)](https://github.com/huggingface/datatrove)
- [datatrove/examples/fineweb.py](https://github.com/huggingface/datatrove/blob/main/examples/fineweb.py)
- [Evaluation Dataset — Ragas docs](https://docs.ragas.io/en/stable/concepts/components/eval_dataset/)
- [Evaluation Sample — Ragas docs](https://docs.ragas.io/en/stable/concepts/components/eval_sample/)
- [Schemas — Ragas docs](https://docs.ragas.io/en/stable/references/evaluation_schema/)
- [Datasheets for Datasets — CACM](https://cacm.acm.org/research/datasheets-for-datasets/)
- [Datasheets for Datasets (Gebru et al., arXiv)](https://arxiv.org/pdf/1803.09010)
- [The Dataset Nutrition Label: A Framework To Drive Higher Data Quality Standards (arXiv)](https://arxiv.org/pdf/1805.03677)
- [Data Nutrition Project](https://datanutrition.org/)
- [Policy Patterns for Usage Control in Data Spaces (ODRL extension, arXiv)](https://arxiv.org/pdf/2309.11289)
- [A Survey on Data Contamination for Large Language Models (arXiv)](https://arxiv.org/pdf/2502.14425)
- [Benchmark Contamination in LLMs: Detection & Mitigation Strategies](https://mbrenndoerfer.com/writing/benchmark-contamination-llm-detection-mitigation)
- [LLM Benchmark Datasets Should Be Contamination-Resistant (arXiv)](https://arxiv.org/html/2605.19999v1)
- Internal (repo-verified): `src/knowledge_lake/pipeline/curate.py`, `src/knowledge_lake/pipeline/datasets.py`, `src/knowledge_lake/pipeline/export.py`, `src/knowledge_lake/pipeline/quality/predicates.py`, `src/knowledge_lake/registry/models.py`, `.planning/PROJECT.md`

---
*Feature research for: DatasetOps control plane repositioning (v2.7 milestone)*
*Researched: 2026-07-19*
