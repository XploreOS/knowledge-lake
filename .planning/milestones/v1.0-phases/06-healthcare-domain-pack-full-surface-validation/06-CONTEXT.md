# Phase 6: Healthcare Domain Pack & Full-Surface Validation - Context

**Gathered:** 2026-07-07
**Status:** Ready for planning
**Mode:** `--auto` — all gray areas auto-resolved with recommended defaults (no interactive session). Every decision below is tagged `(auto-selected)` and logged with rationale so the user can audit/override before planning.

<domain>
## Phase Boundary

Phase 6 delivers two parallel deliverables: (1) **Domain pack loader** — a directory-convention mechanism (`domains/{name}/domain.yaml`, `sources.yaml`, `taxonomy.yaml`, `prompts/`, `validators/`) that loads a domain pack into the framework with zero core code changes, validated by the healthcare pack; (2) **Full-surface validation** — 5-10 real healthcare sources flowing end-to-end (ingest → parse → clean → chunk → enrich → index → search → export) with CLI, API, and Dagster surfaces all proven complete and observable.

Requirements: DOMAIN-01, DOMAIN-02, DOMAIN-03, DOMAIN-04, IFACE-01, IFACE-02, IFACE-03.

</domain>

<decisions>
## Implementation Decisions

### Domain pack loading mechanism (DOMAIN-01)
- **D-01 (auto-selected):** Domain packs live in a `domains/{name}/` directory at the project root (alongside `src/`, `pyproject.toml`). The loader reads: `domain.yaml` (metadata: name, version, description — Pydantic-validated schema), `sources.yaml` (seed source entries), `taxonomy.yaml` (entity types and categories), `prompts/` (Jinja2 `.j2` files keyed by task: `enrich.j2`, `qa_generation.j2`, `instruction_tuning.j2`), and `validators/validate.py` (a `DomainValidator` class with a `validate_document()` method). **No core code changes required** — the loader is a thin reader that sits outside the framework's plugin system. The `klake init --domain <name>` CLI command triggers loading and bulk-registers `sources.yaml` entries into the source registry. The healthcare pack lives at `domains/healthcare/`.
- **D-02 (auto-selected):** The only core-code touch point for domain packs is in `pipeline/enrich.py` — if a domain pack is loaded, its `prompts/enrich.j2` overrides the generic enrichment prompt; otherwise the existing generic prompt is used unchanged. This is **additive-only** (no existing behavior changed). Whether domain prompt override is passed via per-call arguments or a global `DomainSettings` model is Claude/planner's call — either works, planner picks the approach consistent with existing `Settings` nesting pattern.

### Healthcare seed sources (DOMAIN-02)
- **D-03 (auto-selected):** `domains/healthcare/sources.yaml` ships with 28 curated entries (≥25 per DOMAIN-02). Grouped by category:
  - **Standards bodies:** HL7 FHIR R4 spec (build.fhir.org), US Core Implementation Guide, SMART on FHIR, CDA/C-CDA
  - **Federal agencies — CMS:** CMS Conditions of Participation, HCPCS Level II codes, Medicare Coverage Database, cms.gov/medicare
  - **Federal agencies — HHS/OCR:** HIPAA Security Rule (PDF — hhs.gov/hipaa), HIPAA Privacy Rule (PDF)
  - **Federal agencies — ONC:** USCDI v3 (healthit.gov), ONC Interoperability Regulations
  - **Federal agencies — CDC:** ICD-10-CM tabular (CSV bulk), MMWR, CDC WONDER data
  - **Federal agencies — FDA:** FDA drug label (DailyMed API/HTML), NDC database (CSV bulk)
  - **Terminology services — NIH/NLM:** LOINC (loinc.org — CSV bulk), RxNorm (NLM RxNav API), MedlinePlus
  - **Registry — NPPES:** NPI bulk data file (CSV download — `ingest_type: upload` not crawl)
  - **Clinical guidelines:** AHRQ National Guideline Clearinghouse, AHA/ACC guidelines index
  - **Research:** NIH PubMed Central open access subset sample, NCI Thesaurus
  Each entry has: `name`, `url`, `source_type` (html/pdf/csv/json), `license` (public-domain/CC/open), `tags` (list of domain taxonomy tags), `crawl_config` (depth, rate_limit_rps, robots_txt: true). Sources with bulk downloads (NPPES, ICD-10-CM, NDC) get `ingest_type: upload` rather than `crawl`.

### Healthcare enrichment prompts, taxonomy & validator (DOMAIN-03)
- **D-04 (auto-selected):** `domains/healthcare/prompts/enrich.j2` — override prompt that adds healthcare-specific named entity recognition (ICD-10 codes, NDC codes, LOINC codes, RxNorm CUIs, HCPCS codes, clinical procedures, diagnoses). `domains/healthcare/prompts/qa_generation.j2` — Q&A generation prompt grounded in clinical document citations (reuses DATA-01 chain). `domains/healthcare/taxonomy.yaml` — entity types: `Condition`, `Medication`, `Procedure`, `ClinicalCode` (subtypes: ICD10, LOINC, NDC, HCPCS, RxNorm), `Regulation`, `Guideline`, `Standard`. `domains/healthcare/validators/validate.py` — `HealthcareValidator.validate_document()` checks: (a) clinical code references use known coding systems (pattern match), (b) PHI heuristic gate (keyword list — per PROJECT.md constraint "PHI/PII handling — only in explicitly controlled test environments"). Validator returns `ValidationResult(passed: bool, warnings: list[str], errors: list[str])`.

### End-to-end validation scope (DOMAIN-04)
- **D-05 (auto-selected):** The DOMAIN-04 E2E run is a **Dagster job** (`healthcare_e2e_job`) composing the full existing asset chain. Exactly **5 sources** covering all required formats: 2 HTML (CMS Conditions of Participation page, CDC ICD overview), 2 PDF (HIPAA Security Rule, US Core IG), 1 CSV (NPPES NPI sample). The E2E test (`tests/e2e/test_e2e_healthcare.py`) materializes this job against a live local stack (docker-compose services: MinIO + Postgres + Qdrant), then verifies: (a) lineage chain intact from source → artifact at every stage via `lineage.py`, (b) `klake search <query>` returns ≥1 result, (c) export produces Parquet file in gold zone. This is a UAT-style integration test (no mocks), consistent with prior phase E2E patterns and the project's "deterministic first" preference.

### CLI surface gaps (IFACE-01)
- **D-06 (auto-selected):** Two CLI commands need adding to match IFACE-01's expected surface:
  - `klake init --domain <name>` — loads domain pack from `domains/<name>/`, validates schema, bulk-registers `sources.yaml` entries into the source registry, prints "Registered N sources from <domain> pack."
  - `klake index` — explicit name per IFACE-01 requirement; can be a thin wrapper around the existing `reindex` logic. `reindex` remains as an alias/power-user command. Consistent with the single-file Typer pattern in `cli/app.py`.
  Current CLI already has: `add-source`, `upload`, `discover`, `parse`, `clean`, `chunk`, `enrich`, `curate`, `dedupe`, `generate-dataset`, `crawl`, `ingest-url`, `search`, `reindex`, `lineage`, `export`. **Missing:** `init`, `index`.

### API surface completeness (IFACE-02)
- **D-07 (auto-selected):** A gap audit during research will map existing API endpoints against IFACE-02's required groups (sources, discover, crawl-jobs, uploads, documents, pipeline actions, search, curation, datasets, exports). Gaps are filled **additively** — no redesign of existing endpoints. The planner enumerates missing endpoints from the research audit and adds them. The primary likely gap is domain-pack-related endpoints (e.g., `POST /domains/load`, `GET /domains/{name}/sources`) — research confirms.

### Dagster observability completeness (IFACE-03)
- **D-08 (auto-selected):** `dagster_defs/assets.py` already has all pipeline assets. Remaining IFACE-03 work: (a) audit existing assets for `RetryPolicy` — add where absent (all assets should have at least 2 retries with linear backoff, matching the "retries" requirement); (b) add `healthcare_e2e_job` Dagster job composing the 5-source validation run; (c) confirm `dagster-webserver` is exposed in docker-compose for UI observability. Research confirms which assets are missing retries.

### Claude's Discretion
- Exact Jinja2 template structure for `enrich.j2` / `qa_generation.j2` (variable names, prompt phrasing) — Claude decides, consistent with existing `pipeline/enrich.py` prompt structure.
- Whether domain prompt override flows through per-call kwargs or a `DomainSettings` model added to `Settings` — Claude/planner decides; either is acceptable.
- `DomainValidator` protocol definition (separate `protocols.py` entry or inline in `domains/`) — Claude/planner decides.
- Exact `RetryPolicy` parameters for Dagster assets (retry count, delay strategy) — Claude decides sensible defaults (2-3 retries, exponential backoff).
- `healthcare_e2e_job` Dagster job composition style (selection-based or explicit job graph) — Claude/planner decides consistent with existing job patterns.
- Full API endpoint list for gap audit — researcher produces this; planner decides naming.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project planning docs
- `.planning/PROJECT.md` — Constraints table (LLM-gateway-only, S3-only, deterministic-first), Key Decisions, Technology Stack
- `.planning/REQUIREMENTS.md` — DOMAIN-01..04, IFACE-01..03 definitions (the scope anchor for this phase)
- `.planning/ROADMAP.md` — Phase 6 goal and 5 success criteria
- `.planning/STATE.md` — Current status and any accumulated blockers

### Prior phase context (carry-forward decisions)
- `.planning/phases/05-curation-datasets-export/05-CONTEXT.md` — D-01 (registry-first pattern), D-09 (gold zone extension), D-10 (Polars/PyArrow writes, DuckDB queries); CLI surface note: "Full `klake` CLI surface completeness (IFACE-01) and FastAPI OpenAPI completeness (IFACE-02) — formally Phase 6 requirements" (this phase resolves that deferral)
- `.planning/phases/04-enrichment-embedding-search/04-CONTEXT.md` — D-01 (every transformation = Artifact node), plugin-architecture decisions
- `.planning/phases/03-parse-clean-chunk/03-CONTEXT.md` — MinHash defaults, quality scoring pattern

### Existing implementation (extend, don't rewrite)
- `src/knowledge_lake/cli/app.py` — single-file Typer app to extend with `init` and `index` commands
- `src/knowledge_lake/api/app.py` — FastAPI app to extend with missing IFACE-02 endpoints
- `src/knowledge_lake/dagster_defs/assets.py` — asset chain to extend with `healthcare_e2e_job` and retry policies
- `src/knowledge_lake/plugins/protocols.py` — plugin protocol contracts (reference pattern for `DomainValidator` protocol if needed)
- `src/knowledge_lake/plugins/resolver.py` — plugin resolution pattern (reference for domain pack loader)
- `src/knowledge_lake/pipeline/enrich.py` — the one core-code touch point: domain prompt override injection (additive-only)
- `src/knowledge_lake/registry/repo.py` — `create_source()` / `create_*_document()` functions to use for bulk source registration from `sources.yaml`
- `src/knowledge_lake/config/settings.py` — nested `BaseModel` pattern for any new `DomainSettings` model

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `registry/repo.py::create_source()` — direct function to call per source entry when bulk-registering from `sources.yaml`; no new registry machinery needed
- `pipeline/enrich.py::_call_llm_for_enrichment()` — template for any domain-prompt LLM call override
- `plugins/resolver.py` — entry-point resolution pattern; domain pack loader is similar (directory scan vs entry-point scan) but simpler (no dynamic imports for the pack itself)
- Existing Dagster assets (`ingest_raw_document` → ... → `export_rag_corpus`) — already form the full pipeline chain; `healthcare_e2e_job` composes a selection of them

### Established Patterns
- Registry-first writes: every transformation creates `Artifact` + `LineageEvent` rows — domain pack loading creates `Source` rows (not Artifacts; sources are registry primitives)
- Settings: nested `BaseModel` per stage under `KLAKE_<STAGE>__*` — any `DomainSettings` follows this shape
- Plugin swap: single settings value change, no core edits — domain pack loader follows the same zero-core-edit principle
- Thin `@asset` wrapping plain pipeline functions — the `healthcare_e2e_job` is a job, not a new asset
- S3 zones: raw → bronze → silver → gold (Phase 5) — no new zones needed for Phase 6

### Integration Points
- New `domains/healthcare/` directory tree — entirely new, no conflicts
- `cli/app.py` additions: `init` and `index` commands (additive)
- `api/app.py` additions: gap-audit-identified endpoints (additive)
- `dagster_defs/assets.py` additions: `RetryPolicy` on existing assets + `healthcare_e2e_job` definition
- `pipeline/enrich.py` modification: domain prompt override branch (additive condition, no existing behavior changed)
- `tests/e2e/test_e2e_healthcare.py` — new integration test file

</code_context>

<specifics>
## Specific Ideas

- The `domains/` directory is entirely new — the first commit of this directory establishes the convention that DOMAIN-01 validates
- The healthcare pack's `sources.yaml` is the deliverable of DOMAIN-02; it's a data file, not code — curate it carefully with correct URLs, license labels, and ingest type annotations
- `klake init --domain healthcare` is the first user-visible entry point for the entire domain pack system — its output message ("Registered 28 sources from healthcare pack") is the proof that DOMAIN-01 works
- The 5-source E2E test is the single most important integration test in the codebase — it proves every prior phase's work composes correctly
- PHI guard in `HealthcareValidator` is a keyword heuristic only (not ML-based) per PROJECT.md's explicit "PHI/PII handling — only in explicitly controlled test environments" constraint
- Researcher's top priority: audit the current API surface against IFACE-02's required endpoint groups to produce a concrete gap list for the planner

</specifics>

<deferred>
## Deferred Ideas

- RAGAS faithfulness judge, Promptfoo schema-regression CI, Arize Phoenix OpenTelemetry tracing, and `tests/eval/` suite — deferred from Phase 5, still deferred; a standalone eval-harness phase or future milestone
- Multi-domain pack support (loading multiple packs simultaneously, pack conflict resolution) — Phase 6 proves the convention with one pack; multi-pack is a future milestone
- Domain pack registry / catalog (listing available packs, versioning, publishing) — future milestone
- RETR-01: Hybrid dense + sparse (BM25) search — v2 requirement, not in this milestone
- Admin UI / web dashboard — out of scope per PROJECT.md

None — discussion stayed within phase scope (all items above were already deferred in prior phases or are genuine future work).

</deferred>

---

*Phase: 6-Healthcare Domain Pack & Full-Surface Validation*
*Context gathered: 2026-07-07*
