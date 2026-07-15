# Roadmap: Knowledge Lake Framework

## Milestones

- ✅ **v1.0 MVP** — Phases 1-6 (shipped 2026-07-07)
- ✅ **v2.0 Agent-Ready Lake** — Phases 7-12 (shipped 2026-07-12)
- ✅ **v2.5 PageIndex Plugin Integration** — Phases 13-16 (shipped 2026-07-15)
- 📋 **v2.6 Data Quality & Enrichment** — Phase 17+ (planning)

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

### 📋 v2.6 Data Quality & Enrichment (Phases 17–21)

**Milestone Goal:** Stop garbage content from reaching the silver zone, chunking, tree index, and gold export — so the RAG corpus is trustworthy rather than merely populated.

**Requirements:** [.planning/REQUIREMENTS.md](.planning/REQUIREMENTS.md) (20 requirements)
**Research:** [.planning/research/SUMMARY.md](.planning/research/SUMMARY.md) (synthesis of 4 parallel researchers)
**Context:** [.planning/MILESTONE-CONTEXT.md](.planning/MILESTONE-CONTEXT.md) (audit evidence, root causes)

**Scope decisions:** Crawler extraction DEFERRED · Forward-only CONFIRMED (fresh stack) · Dedup after substance gate · No FilterPlugin seam

| Phase | Name | Requirements | Depends On | Status |
|-------|------|-------------|------------|--------|
| 17 | Close the Bypass + Measurement | CLEAN-01, CLEAN-02, CLEAN-03, QUAL-04, QUAL-05, MEAS-01 | — | 📋 |
| 18 | Gate Decouple | GATE-01 | — (parallel with 17) | 📋 |
| 19 | Section Classifier + Patterns | CLEAN-04, CLEAN-05, CLEAN-06, QUAL-01 | 17, 18 | 📋 |
| 20 | Chunk Substance Gate + Export Gate | QUAL-02, QUAL-03, MEAS-02, EXPORT-01, EXPORT-02, PIPE-01 | 17 | 📋 |
| 21 | Index-Time Dedup | DEDUP-01, DEDUP-02, DEDUP-03 | 20 | 📋 |

**Critical path:** 17 → 19 (section classifier needs the bypass closed + gate decoupled).
**Parallelizable:** 18 with 17; 20 with 19.
**Hard constraint:** L3 before L4 (Phase 20 before 21) — dedup without filtering promotes garbage via IDF inversion.

#### Phase 17: Close the Bypass + Measurement
The only phase whose defects *corrupt* data rather than degrade it. Proves the plumbing and establishes the baseline while changing filter policy as little as possible.
- Close the Dagster bypass — `clean_document` returns cleaned `ParsedDoc` (CLEAN-01)
- Close the `process_crawled` bypass — add clean stage (CLEAN-02)
- Parent-scoped content hash in `clean()` — adopt WR-05 convention (CLEAN-03)
- Rejection recording + garbage-rate metric (QUAL-04)
- Conservation invariant: `rejected + kept == considered` (QUAL-05)
- Re-runnable quality audit harness (MEAS-01)

#### Phase 18: Gate Decouple
Small, isolated prerequisite for touching `BOILERPLATE_PATTERNS`. Severs the SCHED-02 change gate from the evolving clean patterns.
- Frozen `_GATE_NORMALIZE_PATTERNS` in `crawl.py` (GATE-01)
- Pinning test: gate signature stable across clean-stage pattern changes

#### Phase 19: Section Classifier + Patterns
Highest-yield policy change, now measurable against Phase 17's baseline. Should move garbage rate from 28% to single digits.
- Section-aware cleaning with substance annotations (CLEAN-04)
- Extended boilerplate patterns covering all 5 audit categories (CLEAN-05)
- Domain-pack `filters.yaml` + healthcare clinical-code allowlist (CLEAN-06)
- Pure quality predicate module — `pipeline/quality/` (QUAL-01)

#### Phase 20: Chunk Substance Gate + Export Gate
The gate that prevents garbage from reaching Qdrant and gold export.
- Wire `FineWebQualityFilter` with chunk-scoped settings (QUAL-02)
- Chunk min-substance gate with report/enforce modes (QUAL-03)
- Must-not-reject CI fixtures (~20 clinical chunks) (MEAS-02)
- Gold RAG export quality gate on chunk-level signal (EXPORT-01)
- Eval dataset versioning (EXPORT-02)
- Filter configuration versioning (PIPE-01)

#### Phase 21: Index-Time Dedup
Build against the residual after Phase 20 — most of the 653 duplicates are boilerplate removed at source.
- Postgres `chunk_text_index` ledger + Alembic migration (DEDUP-01)
- Deterministic point IDs via `uuid5(NAMESPACE, sha256(text))` (DEDUP-02)
- Payload preservation with `contributors[]` for deduplicated points (DEDUP-03)

#### Success Criteria
1. `klake process` on audit sources: <5% garbage (down from 28%)
2. Gold RAG corpus: <2% junk (down from 33%)
3. Must-not-reject fixtures all pass (no clinical codes dropped)
4. Conservation: `rejected + kept == considered` for every source
5. Lineage: no cross-document artifact corruption
6. No regressions: 971+ tests, `xfail_strict=true`, no tree-index fallback increase

## Progress

**Execution Order:**
Phases execute in numeric order. v2.6 begins at Phase 17.

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-6 | v1.0 MVP | 25/25 | ✅ Shipped | 2026-07-07 |
| 7-12 | v2.0 Agent-Ready Lake | 38/38 | ✅ Shipped | 2026-07-12 |
| 13-16 | v2.5 PageIndex Plugin Integration | 14/14 | ✅ Shipped | 2026-07-15 |
| 17+ | v2.6 Data Quality & Enrichment | — | 📋 Planning | — |
