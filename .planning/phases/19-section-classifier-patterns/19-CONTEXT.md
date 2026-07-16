# Phase 19: Section Classifier + Patterns - Context

**Gathered:** 2026-07-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Section-level boilerplate classification with substance annotations, extended patterns covering all 5 audit garbage categories, domain-pack filter configuration (allowlists for clinical codes), and a pure quality predicate module. After this phase, junk sections are identified and removed at section granularity with domain-aware exemptions protecting clinical content.

**Requirements:** CLEAN-04, CLEAN-05, CLEAN-06, QUAL-01

</domain>

<decisions>
## Implementation Decisions

### Section Classifier Architecture (CLEAN-04)
- **D-01:** A dedicated `classify_sections()` function computes per-section substance annotations (link_density, terminal_punct_ratio, stopword_ratio, token_count) and a `is_boilerplate: bool` flag. Classification is separated from filtering — the classifier annotates, a subsequent step decides keep/reject. This follows the project's "deterministic first" constraint.
- **D-02:** `clean()` evolves to operate at section granularity: load `ParsedDoc.sections`, run `classify_sections()` on each, filter out boilerplate sections, and return a cleaned `ParsedDoc` with only kept sections. The monolithic `remove_boilerplate(full_text)` remains available but `clean()` uses section-level classification as the primary path.
- **D-03:** Boilerplate classification uses the existing `BOILERPLATE_PATTERNS` regex list (extended per CLEAN-05) PLUS the substance signals. A section is classified as boilerplate if: (a) it matches a boilerplate regex pattern, OR (b) its substance signals fall below thresholds (low token_count + low terminal_punct_ratio + high link_density). Domain allowlists (CLEAN-06) can override the classification.

### Substance Annotation Storage (CLEAN-04)
- **D-04:** Per-section substance annotations are stored in the `cleaned_document` artifact's `metadata_` dict under a `section_annotations` key. Each entry carries the section index, substance signals, and the keep/reject decision with reason. No new artifact type is created — the cleaned sidecar IS the cleaned_document artifact.

### Extended Boilerplate Patterns (CLEAN-05)
- **D-05:** Extend `BOILERPLATE_PATTERNS` beyond the current 4 regexes to cover all 5 garbage categories from the audit: navigation menus, terms-of-service blocks, enrollment/marketing CTAs, cookie consent, and government disclaimer boilerplate. New patterns are additive — existing 4 patterns remain unchanged. Phase 3 test assertions must continue to pass.
- **D-06:** The gate-local frozen `_GATE_BOILERPLATE_PATTERNS` in `crawl.py` (Phase 18) is NOT updated when `BOILERPLATE_PATTERNS` is extended. This is the entire point of Phase 18's decoupling.

### Domain-Pack Filter Configuration (CLEAN-06)
- **D-07:** `DomainLoader` gains optional `filters.yaml` loading. The file is optional — domain packs without it work with framework defaults only. When present, it is validated against a `DomainFilters` Pydantic model containing: `boilerplate_patterns` (additional regex patterns), `normative_allowlists` (regex patterns that must never be dropped), and `thresholds` (domain-specific substance thresholds).
- **D-08:** The healthcare pack contributes a `filters.yaml` with a clinical-code allowlist: `ICD-10`, `LOINC`, `RxNorm`, `§\d+\.\d+`, dosage patterns (`\d+\s*mg`, `PO\s+BID`, etc.). A section matching any allowlist pattern is never classified as boilerplate regardless of its substance signals.
- **D-09:** The `DomainFilters` model is defined in `domains/models.py` alongside the existing `DomainManifest`, `SourceEntry`, and `TaxonomyManifest` models.

### Quality Predicate Module (QUAL-01)
- **D-10:** A `pipeline/quality/` package with pure predicate functions: `f(text, metadata) -> PredicateResult(passed: bool, reason: str)`. Zero dependencies on I/O, S3, Dagster, or settings. Each predicate is a standalone function.
- **D-11:** Predicates include: `check_token_floor()`, `check_alpha_ratio()`, `check_link_density()`, `check_stopword_ratio()`, `check_table_exemption()`, `check_domain_allowlist()`. A `run_predicates()` combinator applies them in sequence and returns a composite result.
- **D-12:** The quality predicate module is designed for consumption by Phase 20's chunk substance gate (QUAL-03). Phase 19 builds the module; Phase 20 wires it into the pipeline. The same predicates can also be used by the section classifier's substance check (D-03), providing consistency between section-level and chunk-level quality gates.

### Claude's Discretion

Claude has flexibility on: exact substance signal thresholds, regex pattern details for the 5 new garbage categories, `PredicateResult` implementation (namedtuple vs dataclass), internal module structure of `pipeline/quality/`, test fixture content, and whether `classify_sections()` lives in `clean.py` or a new `pipeline/classify.py` module.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & Scope
- `.planning/REQUIREMENTS.md` §CLEAN-04, §CLEAN-05, §CLEAN-06, §QUAL-01 — Full requirement definitions and acceptance criteria
- `.planning/ROADMAP.md` §Phase 19 — Success criteria and dependency graph
- `.planning/MILESTONE-CONTEXT.md` — Audit evidence (28% garbage, 5 categories), root causes, scope decisions

### Prior Phase Context
- `.planning/phases/17-close-the-bypass-measurement/17-CONTEXT.md` — Phase 17 decisions (bypass wiring, conservation invariant infrastructure that Phase 19 populates)
- `.planning/phases/18-gate-decouple/18-CONTEXT.md` — Phase 18 decisions (frozen gate patterns — D-06 above depends on this)

### Pipeline Code (the clean stage)
- `src/knowledge_lake/pipeline/clean.py` — `BOILERPLATE_PATTERNS` (line 46), `remove_boilerplate()` (line 81), `_normalize_whitespace()` (line 66), `clean()` (line 170)
- `src/knowledge_lake/pipeline/process.py` — `process_crawled()` (line 17) — CLI path that must also use section-level cleaning

### Domain Pack Infrastructure
- `src/knowledge_lake/domains/loader.py` — `DomainLoader` class, `from_name()` factory, YAML loading patterns
- `src/knowledge_lake/domains/models.py` — `DomainManifest`, `SourceEntry`, `TaxonomyManifest` Pydantic models
- `domains/healthcare/` — Healthcare domain pack (domain.yaml, sources.yaml, taxonomy.yaml, prompts/, validators/)

### Quality Module (to be created)
- `src/knowledge_lake/pipeline/quality/` — Does not exist yet. QUAL-01 requires creating this as a new package.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BOILERPLATE_PATTERNS` in `clean.py:46` — 4 existing regexes; extended (not replaced) by CLEAN-05
- `remove_boilerplate()` in `clean.py:81` — Applies patterns + normalizes whitespace; remains available but section classifier is the primary path
- `_normalize_whitespace()` in `clean.py:66` — 5-line function for whitespace normalization; reusable in section-level cleaning
- `DomainLoader` in `domains/loader.py` — Loads domain packs; extended with optional `filters.yaml`
- `DomainManifest`, `SourceEntry` in `domains/models.py` — Pydantic models for domain pack validation; `DomainFilters` follows this pattern

### Established Patterns
- Domain pack convention: `domains/{name}/` with mandatory YAML files + optional additions
- YAML loaded via `yaml.safe_load` exclusively (T-06-04)
- Pydantic models for validation of domain pack YAML files
- Content hashing via `hashlib.sha256` for artifact dedup
- `structlog` for structured logging throughout pipeline
- `clean()` returns a dict with `artifact_id`, `content_hash`, `language`, `dedup_status`, `storage_uri`

### Integration Points
- `clean()` is called by `clean_document` Dagster asset and by `process_crawled()` — both paths must gain section-level classification
- Phase 17 wires cleaned text to downstream consumers; Phase 19 upgrades what "cleaning" means (section-level vs monolithic)
- Phase 17's conservation infrastructure (QUAL-05) receives section-level rejection counts from Phase 19's classifier
- Phase 20's chunk substance gate (QUAL-03) consumes the quality predicates built here
- `ParsedDoc.sections` is produced by Docling during parsing — the sections are available as input to the classifier

</code_context>

<specifics>
## Specific Ideas

No specific requirements — the implementation follows naturally from the existing codebase patterns. The section classifier extends `clean()` with section-level granularity, and the quality predicate module is a new pure-function package consumed by both this phase and Phase 20.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 19-Section Classifier + Patterns*
*Context gathered: 2026-07-16*
