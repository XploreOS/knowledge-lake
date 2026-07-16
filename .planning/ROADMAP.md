# Roadmap: Knowledge Lake Framework

## Milestones

- ✅ **v1.0 MVP** — Phases 1-6 (shipped 2026-07-07)
- ✅ **v2.0 Agent-Ready Lake** — Phases 7-12 (shipped 2026-07-12)
- ✅ **v2.5 PageIndex Plugin Integration** — Phases 13-16 (shipped 2026-07-15)
- 📋 **v2.6 Data Quality & Enrichment** — Phases 17-21 (active)

## Phases

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

### v2.6 Data Quality & Enrichment (Phases 17-21)

**Milestone Goal:** Stop garbage content from reaching the silver zone, chunking, tree index, and gold export — so the RAG corpus is trustworthy rather than merely populated.

**Evidence:** 4,499 chunks from 34 healthcare sources. ~28% garbage chunks, 33% of gold RAG corpus unusable.
**Root cause:** The clean stage is architecturally bypassed — `clean_document` forwards the uncleaned `parsed_doc` to all downstream consumers.

**Scope decisions:**

- D-1 Crawler extraction: DEFERRED (section classifier covers superset)
- D-2 Forward-only: CONFIRMED (test data wiped; fresh stack for production)
- D-3 Index-time dedup: CONFIRMED (after substance gate — L3 before L4)

**References:**

- Requirements: [.planning/REQUIREMENTS.md](.planning/REQUIREMENTS.md) (20 requirements)
- Research: [.planning/research/SUMMARY.md](.planning/research/SUMMARY.md) (4 parallel researchers)
- Context: [.planning/MILESTONE-CONTEXT.md](.planning/MILESTONE-CONTEXT.md) (audit evidence, root causes)

**Hard Ordering Constraints:**

1. Phase 17 first — the only phase whose defects corrupt data rather than degrade it
2. Measurement before filtering — or v2.6 repeats v2.5's failure
3. Phase 18 before 19 — or extending patterns triggers a 34-source re-crawl storm
4. L3 before L4 (Phase 20 before 21) — dedup before filtering makes BM25 worse via IDF inversion
5. L3 before L5 — export gate has no chunk-level signal until L3 provides one

**Critical path:** 17 --> 19. Phases 18 and 20 are leaves/parallelizable.

- [ ] **Phase 17: Close the Bypass + Measurement** - Wire cleaned text onto the load-bearing path (both Dagster and CLI), fix lineage hash, establish garbage-rate baseline
- [ ] **Phase 18: Gate Decouple** - Sever the re-crawl change gate from evolving clean patterns (parallelizable with 17)
- [ ] **Phase 19: Section Classifier + Patterns** - Section-aware filtering with substance annotations, extended patterns, domain-pack allowlists
- [ ] **Phase 20: Chunk Substance Gate + Export Gate** - Reject garbage at chunk scope, gate gold export on chunk-level quality signal
- [ ] **Phase 21: Index-Time Dedup** - Corpus-wide exact dedup between chunk and embed with idempotent point IDs

## Phase Details

### Phase 17: Close the Bypass + Measurement

**Goal**: The cleaned text reaches all downstream consumers and garbage is measurable against a frozen baseline
**Depends on**: Nothing (first phase — highest risk, hard prerequisite for all others)
**Requirements**: CLEAN-01, CLEAN-02, CLEAN-03, QUAL-04, QUAL-05, MEAS-01
**Success Criteria** (what must be TRUE):

  1. After processing a source with known boilerplate, `chunk_document` receives sections with boilerplate removed — the uncleaned `parsed_doc` is no longer forwarded by `clean_document`
  2. `klake process <source>` produces chunks from cleaned text — identical output whether processed via Dagster or via `klake process`
  3. Two documents with identical cleaned text produce distinct `cleaned_document` artifacts with different content hashes (parent-scoped WR-05 convention)
  4. `klake quality-audit` produces a per-source table (34 rows) showing total sections, kept, rejected, rejection reasons, and garbage rate — reproducible across runs and independent of any gate's heuristic
  5. Every gate asserts `rejected + kept == sections_considered` at runtime — a broken parser returning 0 sections is detected as distinct from a correct gate rejecting all sections

**Plans:** 4 plans

Plans:
**Wave 1**

- [ ] 17-01-PLAN.md — Retrofit clean() with parsed_doc threading, per-section cleaning, WR-05 parent-scoped hash, and conservation invariant (CLEAN-01/02 substrate, CLEAN-03, QUAL-04, QUAL-05)

**Wave 2** *(blocked on Wave 1 completion)*

- [ ] 17-02-PLAN.md — Wire the cleaned ParsedDoc through the Dagster clean_document asset; verify curate_document_asset regression-free (CLEAN-01)
- [ ] 17-03-PLAN.md — Insert clean() into process_crawled between parse() and chunk() for CLI/API/MCP parity (CLEAN-02)
- [ ] 17-04-PLAN.md — Build the klake quality-audit harness (pipeline/quality_audit.py + CLI command) (MEAS-01, QUAL-04)

### Phase 18: Gate Decouple

**Goal**: Extending boilerplate patterns no longer triggers re-crawl of all sources
**Depends on**: Nothing (parallelizable with Phase 17)
**Requirements**: GATE-01
**Success Criteria** (what must be TRUE):

  1. Adding a new pattern to `BOILERPLATE_PATTERNS` does not change the content signature of any existing source
  2. A pinning test asserts gate-signature byte-stability across a clean-stage pattern change

**Plans**: TBD

### Phase 19: Section Classifier + Patterns

**Goal**: Junk sections are identified and removed at section granularity with domain-aware exemptions protecting clinical content
**Depends on**: Phase 17, Phase 18
**Requirements**: CLEAN-04, CLEAN-05, CLEAN-06, QUAL-01
**Success Criteria** (what must be TRUE):

  1. A parsed document with nav, footer, and clinical sections retains only clinical sections in the cleaned output — substance annotations (link_density, terminal_punct_ratio, stopword_ratio, token_count) are persisted in the cleaned sidecar
  2. Extended boilerplate patterns cover all 5 garbage categories from the audit (too-short, no-sentences, boilerplate, marketing, navigation) while existing Phase-3 test assertions continue to pass
  3. A chunk containing `ICD-10 E11.9` or `Metformin 500 mg PO BID` is never dropped by any gate — healthcare-pack domain-code allowlist enforced via `DomainLoader`
  4. Quality predicates in `pipeline/quality/` are independently importable with zero I/O, S3, or Dagster dependencies — deterministic and 100% branch coverage

**Plans**: TBD

### Phase 20: Chunk Substance Gate + Export Gate

**Goal**: Garbage chunks are rejected before embedding and the gold RAG export contains only quality content
**Depends on**: Phase 17 (parallelizable with Phase 19)
**Requirements**: QUAL-02, QUAL-03, MEAS-02, EXPORT-01, EXPORT-02, PIPE-01
**Success Criteria** (what must be TRUE):

  1. `FineWebQualityFilter` rejects chunks matching the audit's "too short" and "no real sentences" categories while passing a clinical-prose control set — using chunk-scoped settings, not `CurateSettings`
  2. Chunks failing the composite substance predicate are rejected (in enforce mode) or flagged with recorded reason (in report mode) — `is_table=True` chunks are always exempt
  3. CI fails if any fixture in the ~20 hand-labeled must-not-reject set (ICD codes, dosage instructions, LOINC codes, HIPAA references) is dropped by the substance gate
  4. A document with mixed quality (clinical tables + cookie banners) exports only the clinical chunks to gold — the 33% junk in gold drops to near-zero
  5. Changing a filter threshold invalidates the cache for affected artifacts and triggers re-processing on next run (reuses `_curation_cache_key` versioning pattern)

**Plans**: TBD

### Phase 21: Index-Time Dedup

**Goal**: Duplicate text is embedded and indexed exactly once while preserving per-document chunk lineage
**Depends on**: Phase 20 (L3 must precede L4 — dedup before filtering promotes garbage via IDF inversion)
**Requirements**: DEDUP-01, DEDUP-02, DEDUP-03
**Success Criteria** (what must be TRUE):

  1. Processing two documents containing identical boilerplate text produces one Qdrant point (not two) — the chunk registry still has both chunk artifacts with correct per-document lineage (WR-05 intact)
  2. Re-processing the same document produces the same point ID — re-index is idempotent by construction via `uuid5(NAMESPACE, sha256(normalized_text))`
  3. A deduplicated point is filterable by source_id, domain, and format — the `contributors[]` field lists all source documents that contained this text, with primary determined by earliest `created_at`

**Plans**: TBD

## Coverage

| Requirement | Phase | Category |
|-------------|-------|----------|
| CLEAN-01 | 17 | Close bypass (Dagster) |
| CLEAN-02 | 17 | Close bypass (CLI) |
| CLEAN-03 | 17 | Parent-scoped hash |
| CLEAN-04 | 19 | Section-aware cleaning |
| CLEAN-05 | 19 | Extended patterns |
| CLEAN-06 | 19 | Domain-pack filters |
| GATE-01 | 18 | Gate decouple |
| QUAL-01 | 19 | Quality predicates |
| QUAL-02 | 20 | FineWebQualityFilter |
| QUAL-03 | 20 | Chunk substance gate |
| QUAL-04 | 17 | Rejection recording |
| QUAL-05 | 17 | Conservation invariant |
| DEDUP-01 | 21 | Exact dedup |
| DEDUP-02 | 21 | Point ID determinism |
| DEDUP-03 | 21 | Payload preservation |
| EXPORT-01 | 20 | Gold export gate |
| EXPORT-02 | 20 | Eval dataset versioning |
| MEAS-01 | 17 | Quality audit harness |
| MEAS-02 | 20 | Must-not-reject fixtures |
| PIPE-01 | 20 | Filter config versioning |

**Mapped: 20/20 requirements. No orphans.**

## Milestone Success Criteria

1. **Primary:** `klake process` on the audit's 34 sources produces <5% garbage chunks (down from 28%)
2. **Gold:** RAG corpus export contains <2% junk rows (down from 33%)
3. **Safety:** Must-not-reject fixtures pass — no clinical codes, dosage instructions, or normative statements dropped
4. **Conservation:** `rejected + kept == considered` holds for every source
5. **Lineage:** No cross-document artifact corruption (WR-05 extended to clean stage)
6. **No regressions:** 971+ tests pass, `xfail_strict=true` holds, no tree-index fallback-rate increase

## Progress

**Execution Order:**
Phases execute in numeric order. v2.6 begins at Phase 17.

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-6 | v1.0 MVP | 25/25 | ✅ Shipped | 2026-07-07 |
| 7-12 | v2.0 Agent-Ready Lake | 38/38 | ✅ Shipped | 2026-07-12 |
| 13-16 | v2.5 PageIndex Plugin Integration | 14/14 | ✅ Shipped | 2026-07-15 |
| 17 | v2.6 Close the Bypass + Measurement | 0/0 | Not started | - |
| 18 | v2.6 Gate Decouple | 0/0 | Not started | - |
| 19 | v2.6 Section Classifier + Patterns | 0/0 | Not started | - |
| 20 | v2.6 Chunk Substance Gate + Export Gate | 0/0 | Not started | - |
| 21 | v2.6 Index-Time Dedup | 0/0 | Not started | - |
