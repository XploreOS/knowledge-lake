# Requirements: Knowledge Lake Framework — v2.7 Governed Dataset Production and Release Lifecycle

**Defined:** 2026-07-21
**Core Value:** Every domain resource ingested must be traceable from raw source through every transformation to its final AI-ready output — and the framework must remain tool-agnostic so any processor can be swapped without breaking lineage.
**Milestone promise:** Provide Knowledge Lake with authoritative sources and a dataset specification, and it will produce a versioned, policy-evaluated, quality-validated AI dataset whose records can be traced to their original sources and reproduced.

## v1 Requirements

Requirements for milestone v2.7. Each maps to roadmap phases (Phase 23+).

### Dataset Project (PROJ)

- [x] **PROJ-01**: User can create a Dataset Project (name, description, purpose, intended/prohibited uses, dataset_type, domain pack, owners)
- [ ] **PROJ-02**: Dataset Project enforces its defined lifecycle (draft → configured → sources_pending → ready → processing → validating → review_required → releasable → released → failed → archived) with guarded transitions — illegal transitions rejected with a clear error
- [ ] **PROJ-03**: User can list/show Dataset Projects and transition their state via CLI (`klake project new/list/show/transition`) and API

### Dataset Specification (SPEC)

- [ ] **SPEC-01**: User can define a declarative Dataset Specification (YAML/JSON) capturing purpose, type, domain, included/excluded sources, allowed license categories, usage policy, quality contract, curation engine, generation strategy, validation requirements, split strategy, decontamination targets, export formats, release requirements, human-approval requirements
- [x] **SPEC-02**: Every Dataset Specification change produces a new immutable spec version with a content hash, schema version, timestamp, author, and parent-version link
- [ ] **SPEC-03**: `klake dataset spec validate` checks schema validity and referential integrity (referenced sources/quality-contract/policy exist) before a spec can move a project to `ready`

### Usage Policy (POLICY)

- [ ] **POLICY-01**: System records a structured per-source usage-policy decision across 9 dimensions (approved-for-ingestion, retrieval-use, training-use, commercial-use, derivatives-allowed, redistribution-allowed, attribution-required, share-alike, unknown-status) with a reason and policy version, extending (not replacing) `Source.license_type`
- [ ] **POLICY-02**: Policy evaluation is declarative and deterministic — no LLM-based legal interpretation
- [ ] **POLICY-03**: A one-time grandfather/backfill pass evaluates every existing source in report-only mode, producing a human-reviewable report, before any policy gate becomes release-blocking
- [ ] **POLICY-04**: A Dataset Release is blocked when a required policy decision is missing, a source's license is unknown under a fail-on-unknown policy, redistribution is prohibited for a public-distribution export, or a source violates the spec's intended-use policy
- [ ] **POLICY-05**: User can define and evaluate policies and view a policy report via CLI (`klake policy define/decide/list`) and API

### Quality Contract (QCON)

- [ ] **QCON-01**: A Dataset Quality Contract defines rules at source, document, chunk, generated-example, split, and release levels
- [ ] **QCON-02**: Every rule evaluation produces a structured outcome (passed/failed/recoverable/skipped/not_applicable) carrying rule ID, rule version, reason code, human-readable explanation, input artifact/example ID, config hash, validator identity/version, timestamp
- [ ] **QCON-03**: Chunk-level Quality Contract rules reuse the existing `pipeline/quality/predicates.py` combinator as one rule type — no duplicate substance-detection logic

### Result Partitions (PART)

- [ ] **PART-01**: Every curation and validation outcome partitions into exactly one of accepted / rejected / recoverable / quarantined — nothing is silently discarded
- [ ] **PART-02**: Rejected and recoverable records remain inspectable and traceable, with aggregated rejection reports by reason (duplicate, low substance, unsupported generated answer, disallowed license, unknown usage rights, contamination, invalid schema, domain-validator failure, safety-policy failure, human-review-required)
- [ ] **PART-03**: `accepted + rejected + recoverable + quarantined == total processed` is enforced as a runtime conservation invariant (same discipline as the existing QUAL-05 chunk gate)

### Curation Engine (CENGINE)

- [ ] **CENGINE-01**: A `CurationEngine` Protocol (`prepare`/`execute`/`collect`) is the stable contract; Knowledge Lake retains ownership of dataset identity, source lineage, policy decisions, release state, and final acceptance decisions — the engine only executes
- [ ] **CENGINE-02**: `pipeline/curate.py`'s existing DataTrove filter/scoring logic is wrapped by the new engine, not duplicated or broken — existing call sites (`curate_document_asset`, CLI `curate`/`dedupe`) keep working with unchanged public signatures

### DataTrove Backend (DTROVE)

- [ ] **DTROVE-01**: DataTrove is registered as the first production `CurationEngine` backend, Dagster-launched and monitored, with accepted/rejected writers and an explicit, documented checkpoint-storage decision (Postgres-ledger reuse vs. a reviewed new dependency) — local curation behavior is not removed until this backend has compatibility coverage
- [ ] **DTROVE-02**: Every Curation Run records engine name/version, input manifest, output manifest, config hash, accepted/rejected counts, rejection-reason counts, statistics, start/completion timestamps, runtime, environment version, and source/output artifact relationships

### Generated-Example Candidate Lifecycle (CAND)

- [ ] **CAND-01**: Generated examples carry an explicit lifecycle status: `generated → validating → accepted`, or `generated → validating → recoverable → repaired → validating → accepted`, or `generated → validating → rejected`
- [ ] **CAND-02**: Every candidate records source artifact ID, exact supporting passage/span, Dataset Project, spec version, generator prompt version, generator model alias, generation parameters, validation outcomes, recovery attempts, final state, and content hash
- [ ] **CAND-03**: An `ExampleValidator` interface ships with validators for schema validity, source answerability, source-grounding, duplicate detection, usage-policy compliance, domain-specific rules, and contamination; any LLM-as-judge validator goes through LiteLLM only and records evaluator alias, prompt version, and result evidence

### Deterministic Splits & Contamination (SPLIT)

- [ ] **SPLIT-01**: Train/validation/test split assignment is deterministic, versioned, and group-aware (grouped by source document/parent artifact to prevent related-example leakage across splits), replacing today's payload-shape-sniffing behavior in `check_train_eval_contamination()`
- [ ] **SPLIT-02**: A benchmark contamination gate blocks a release when protected evaluation examples overlap training beyond a configured threshold, retaining the existing lineage-based (shared `cleaned_document` ancestor) overlap check as the primary signal

### Immutable Dataset Release (REL)

- [ ] **REL-01**: An immutable Dataset Release captures project ID, spec version, semantic release version, dataset type, status, source snapshot, record/split counts, storage URIs, content hashes, quality summary, policy summary, curation/validation/evaluation run IDs, pipeline version, git commit, creation timestamp, approval metadata, and superseded-release relationship
- [ ] **REL-02**: A released row cannot be mutated after publication — enforced at the database layer (trigger), not application checks alone
- [ ] **REL-03**: A release produces the full manifest bundle: `dataset.parquet`, `train.jsonl`, `validation.jsonl`, `test.jsonl`, `dataset-card.md`, `quality-report.json`, `source-manifest.jsonl`, `license-manifest.jsonl`, `policy-decisions.jsonl`, `lineage-manifest.jsonl`, `validation-manifest.jsonl`, `split-manifest.json`, `checksums.txt`, `reproduce.yaml`
- [ ] **REL-04**: A failed release never exposes partial artifacts as a published release
- [ ] **REL-05**: Retrying an already-completed deterministic run does not create duplicate release records

### Reproducibility (REPRO)

- [ ] **REPRO-01**: `reproduce.yaml` captures Knowledge Lake version, git commit, spec hash, source snapshot identifiers/content hashes, domain-pack version, quality-contract version, policy version, curation engine + version, validator versions, prompt versions, model aliases, split strategy + seed, environment fingerprint, and output checksums
- [ ] **REPRO-02**: An automated test proves that rebuilding from the same immutable inputs and configuration produces equivalent release manifests and deterministic outputs where determinism is expected; the manifest explicitly distinguishes a deterministic-reproducible tier from an explainable-not-replayable tier for LLM-generation steps

### Dataset Diff (DIFF)

- [ ] **DIFF-01**: `klake dataset diff <release-a> <release-b>` reports sources added/removed/version-changed, documents added/removed/modified, records added/removed, split changes, license-policy changes, quality-contract changes, validator changes, rejection-rate changes, contamination changes, and evaluation-metric changes where available — computed from manifests, not full record-by-record comparison

### Lineage Explorer (LINEAGE)

- [ ] **LINEAGE-01**: A user can navigate Dataset Project → Dataset Release → Split → Dataset Example → Validation Results → Generated Candidate → Source Chunk → Parsed Document → Raw Document → Source → License/Policy Decision via API, demonstrated end-to-end for at least one released example

### Evaluation Run Foundation (EVALRUN)

- [ ] **EVALRUN-01**: An Evaluation Run records dataset release, evaluation type, model/RAG system under test, evaluator, configuration, benchmark, metrics, failure examples, execution metadata, and timestamp
- [ ] **EVALRUN-02**: One minimal, deterministic evaluation adapter ships against a released dataset (full RAGAS/RAG-FiT integration is out of scope)

### CLI / API / MCP Surfaces (SURFACE)

- [ ] **SURFACE-01**: New CLI command groups (`project`, `policy`, `dataset`) mirror the existing `domain` sub-Typer group pattern; every existing command remains unchanged and backward compatible
- [ ] **SURFACE-02**: New API routes reuse shared Pydantic schemas and call the same `pipeline/*.py` functions as the CLI — no duplicated business logic in route handlers
- [ ] **SURFACE-03**: New MCP tools are thin shims over `pipeline/*.py` (never proxying REST); read tools are prioritized over mutating ones per governance-action risk; the hardcoded `TOOLS` count assertion is updated in the same change

### Security & Governance (SEC)

- [ ] **SEC-01**: Release immutability is enforced at the database layer (Postgres trigger with a narrow allowlist for legitimate post-release fields), verified by a raw-SQL test that bypasses the ORM
- [ ] **SEC-02**: Public vs. private release modes are distinguished — a redistribution-prohibited source cannot enter a public release
- [ ] **SEC-03**: Secrets are redacted from logs and exported manifests; any LLM-based validator respects existing untrusted-content/prompt-injection boundaries
- [ ] **SEC-04**: Any new external-engine dependency introduced for the DataTrove backend is exactly pinned and explicitly reviewed (matching the repo's existing exact-pinning convention), never silently added

### Flagship Proof (FLAGSHIP)

- [ ] **FLAGSHIP-01**: A new non-healthcare domain pack ("AI Agent Security and Permission Dataset") is released end-to-end through the full v2.7 lifecycle with a curated RAG corpus, a small grounded instruction set, a protected evaluation set, and complete manifests (quality report, policy report, rejection report, release manifest)
- [ ] **FLAGSHIP-02**: At least one released example from the flagship dataset is traced through the complete source-to-release chain via the lineage explorer, as the milestone's key demo

## v2 Requirements

Deferred to a future milestone. Tracked but not in the current roadmap.

### Evaluation Depth

- **EVALRUN-03**: Full RAGAS / RAG-FiT metric integration (deferred until the Evaluation Run data model is proven against ≥2 real releases)

### Curation Engines

- **CENGINE-03**: A second `CurationEngine` backend beyond DataTrove (e.g. NeMo Curator, IBM Data Prep Kit) — no driver exists yet and none is needed at this milestone's scale

### Contamination Depth

- **SPLIT-03**: Embedding + LLM-judge ("LLM Decontaminator") contamination detection — contradicts the deterministic-first constraint and is over-engineered at this corpus scale; MinHash near-dup (reusing `curate.py`'s existing `MinHashLSH` index) may be added as a supplementary signal within v1 scope if low-cost, otherwise deferred here

### Interop

- **DIFF-02**: Croissant (MLCommons) JSON-LD metadata export — research recommends a dev-only `mlcroissant` CI conformance checker over a production dependency; a hand-rolled Croissant-compatible field set in the release manifest is a stretch goal for Phase 8, not a blocking v1 requirement. Revisit full library adoption post-v2.7.

### Domain Expansion

- **DOMAIN-07**: Domain-pack-owned Dagster jobs/schedules (KL-16) — architecturally consistent to keep deferred for v2.7 since the flagship pack runs through the existing `DomainLoader.from_name()` runtime-branch pattern; becomes a hard prerequisite only if a future domain pack needs a genuinely distinct Dagster schedule/sensor, not just parameterized asset behavior

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Supporting every vector database | Qdrant remains the only supported vector store; out of scope per milestone brief |
| Replacing Dagster, PostgreSQL, or S3-compatible storage | Existing orchestration/registry/storage layers are preserved architectural invariants |
| Full multimodal curation | Not required for the flagship proof or stated success criteria |
| Deep NeMo Curator / IBM Data Prep Kit integration | `CurationEngine` provides the extension seam; deep integration is future work, not this milestone |
| Fine-tuning infrastructure / training foundation models | Knowledge Lake produces datasets, not training infrastructure |
| Ontology editor / domain-pack marketplace | Unrelated to the dataset production/release lifecycle |
| Enterprise RBAC and billing | Single-team scale; out of scope per milestone brief |
| Automated legal interpretation / regulatory compliance claims | Policy engine is declarative and deterministic; explicitly "supports compliance evidence," never "is compliant" |
| Adding many new domains | One flagship non-healthcare domain pack proves the lifecycle; healthcare remains the only production pack otherwise |
| Rebuilding DataTrove functionality | `CurationEngine` wraps DataTrove; no reimplementation of its filters/executor |
| Building a generic chat application | Unrelated to dataset production |
| lakeFS/DVC-style branch/merge storage versioning | Immutable Release + manifest is the intentional, correctly-scoped substitute at this team size |

## Traceability

Populated during roadmap creation (`/gsd-roadmapper`, 2026-07-21).

| Requirement | Phase | Status |
|-------------|-------|--------|
| PROJ-01 | Phase 23 | Complete |
| PROJ-02 | Phase 23 | Pending |
| PROJ-03 | Phase 23 | Pending |
| SPEC-01 | Phase 23 | Pending |
| SPEC-02 | Phase 23 | Complete |
| SPEC-03 | Phase 23 | Pending |
| SURFACE-01 | Phase 23 | Pending |
| SURFACE-02 | Phase 23 | Pending |
| SURFACE-03 | Phase 23 | Pending |
| POLICY-01 | Phase 25 | Pending |
| POLICY-02 | Phase 25 | Pending |
| POLICY-03 | Phase 25 | Pending |
| POLICY-04 | Phase 25 | Pending |
| POLICY-05 | Phase 25 | Pending |
| QCON-01 | Phase 26 | Pending |
| QCON-02 | Phase 26 | Pending |
| QCON-03 | Phase 26 | Pending |
| CENGINE-01 | Phase 27 | Pending |
| CENGINE-02 | Phase 27 | Pending |
| DTROVE-01 | Phase 27 | Pending |
| DTROVE-02 | Phase 27 | Pending |
| PART-01 | Phase 27 | Pending |
| PART-02 | Phase 27 | Pending |
| PART-03 | Phase 27 | Pending |
| SEC-04 | Phase 27 | Pending |
| CAND-01 | Phase 28 | Pending |
| CAND-02 | Phase 28 | Pending |
| CAND-03 | Phase 28 | Pending |
| SEC-03 | Phase 28 | Pending |
| SPLIT-01 | Phase 29 | Pending |
| SPLIT-02 | Phase 29 | Pending |
| REL-01 | Phase 30 | Pending |
| REL-02 | Phase 30 | Pending |
| REL-03 | Phase 30 | Pending |
| REL-04 | Phase 30 | Pending |
| REL-05 | Phase 30 | Pending |
| REPRO-01 | Phase 30 | Pending |
| REPRO-02 | Phase 30 | Pending |
| SEC-01 | Phase 30 | Pending |
| SEC-02 | Phase 30 | Pending |
| EVALRUN-01 | Phase 31 | Pending |
| EVALRUN-02 | Phase 31 | Pending |
| DIFF-01 | Phase 31 | Pending |
| LINEAGE-01 | Phase 31 | Pending |
| FLAGSHIP-01 | Phase 32 | Pending |
| FLAGSHIP-02 | Phase 32 | Pending |

**Enabling phase (no directly-owned requirement):** Phase 24 (Flagship Domain Pack Foundation) scaffolds the real non-healthcare corpus that FLAGSHIP-01/02 (Phase 32) build on — see ROADMAP.md Phase 24 for rationale.

**Coverage:**

- v1 requirements: 46 total (corrected from a stale "43 total" — a direct count of `**CATEGORY-NN**` markers under `## v1 Requirements` found 46 distinct IDs)
- Mapped to phases: 46/46 (100%)
- Unmapped: 0

---
*Requirements defined: 2026-07-21*
*Last updated: 2026-07-21 after v2.7 roadmap creation — 46/46 v1 requirements mapped to Phases 23-32, coverage corrected from stale "43 total"*
