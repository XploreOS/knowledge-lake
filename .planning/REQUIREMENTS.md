# Requirements: v2.6 — Data Quality & Enrichment

**Milestone Goal:** Stop garbage content from reaching the silver zone, chunking, tree index, and gold export — so the RAG corpus is trustworthy rather than merely populated.

**Scope Decisions:**

- D-1: Crawler extraction **DEFERRED** (no-op today; section classifier covers superset)
- D-2: Forward-only **CONFIRMED** (existing data is test data; fresh stack before production)
- D-3: Index-time dedup **CONFIRMED** (after substance gate)
- D-4: Research complete

**Phase range:** 17–21 (continuing from v2.5's Phase 16)

---

## Requirements

### CLEAN-01: Close the Dagster bypass — forward cleaned ParsedDoc

`clean_document` must return the cleaned `ParsedDoc` (output of `clean()`) to downstream consumers (`chunk_document`, `tree_index_document`, `enrich_document`), not the uncleaned original.

**Acceptance:** After processing a source with known boilerplate, `chunk_document` receives sections with boilerplate removed. The uncleaned `parsed_doc` is no longer forwarded.

---

### CLEAN-02: Close the process_crawled bypass — add clean stage

`pipeline/process.py::process_crawled` must call `clean()` between parse and chunk, matching the Dagster asset graph's intended flow.

**Acceptance:** `klake process <source>` produces chunks from cleaned text. The same source produces identical chunks whether processed via Dagster or via `klake process`.

---

### CLEAN-03: Parent-scoped content hash in clean()

`clean.py` must adopt the WR-05 convention: hash `f"{parsed_artifact_id}:{cleaned_text}"` instead of `sha256(cleaned_text)` alone, preventing cross-document lineage corruption on hash collision.

**Acceptance:** Two documents with identical cleaned text produce distinct `cleaned_document` artifacts with different content hashes. The `UNIQUE(content_hash, artifact_type)` constraint does not cause one document to silently receive another's artifact.

---

### CLEAN-04: Section-aware cleaning with substance annotations

`clean()` must operate at section granularity: load `ParsedDoc.sections`, apply boilerplate patterns per-section, annotate each section with substance signals (link_density, terminal_punct_ratio, stopword_ratio, token_count), and return a cleaned `ParsedDoc` with junk sections removed.

**Acceptance:** A parsed document with nav, footer, and clinical sections retains only clinical sections in the cleaned output. Annotations are persisted in the cleaned sidecar.

---

### CLEAN-05: Extended boilerplate patterns

Extend `BOILERPLATE_PATTERNS` beyond the current 4 regexes to cover: navigation menus, terms-of-service blocks, enrollment/marketing CTAs, cookie consent, and government disclaimer boilerplate. Existing Phase-3 test assertions must continue to pass.

**Acceptance:** Patterns cover all 5 garbage categories from the audit (too-short, no-sentences, boilerplate, marketing). New patterns are additive — existing 4 unchanged.

---

### CLEAN-06: Domain-pack filter configuration

Domain packs may contribute a `filters.yaml` (loaded via `DomainLoader`) specifying: additional boilerplate patterns, normative-phrase allowlists (terms that must never be dropped), and domain-specific thresholds. The healthcare pack contributes a clinical-code allowlist (`ICD-10`, `LOINC`, `RxNorm`, `§\d+\.\d+`, dosage patterns).

**Acceptance:** A chunk containing `ICD-10 E11.9` or `Metformin 500 mg PO BID` is never dropped by the substance gate regardless of length.

---

### GATE-01: Decouple SCHED-02 change gate from clean patterns

The re-crawl change gate (`crawl.py`) must use a frozen, gate-local copy of normalization patterns, not the evolving `BOILERPLATE_PATTERNS` from `clean.py`. Extending clean patterns must not trigger re-crawl of all sources.

**Acceptance:** Adding a new pattern to `BOILERPLATE_PATTERNS` does not change the content signature of any existing source. A pinning test asserts gate-signature byte-stability across a clean-stage pattern change.

---

### QUAL-01: Pure quality predicate module

A `pipeline/quality/` module providing pure predicate functions: `f(text, metadata) -> (pass: bool, reason: str)`. Zero dependencies on I/O, S3, or Dagster. Composable predicates for: token floor, alpha ratio, link density, stopword ratio, table exemption, domain allowlist lookup.

**Acceptance:** Module is independently importable and testable with no infrastructure. 100% branch coverage. All predicates are deterministic.

---

### QUAL-02: FineWebQualityFilter integration at chunk scope

Wire DataTrove's `FineWebQualityFilter` (installed, currently unused) with **chunk-scoped settings** (not `CurateSettings`). Handles the "too short" and "no real sentences" categories.

**Acceptance:** `FineWebQualityFilter` rejects chunks matching the audit's "too short" and "no real sentences" categories while passing a clinical-prose control set. Settings are chunk-appropriate (not document-level DataTrove defaults).

---

### QUAL-03: Chunk min-substance gate

`chunk_document` (and `process_crawled`'s chunk step) must apply a composite substance predicate before emitting chunks. Gate operates in two modes: `report` (log + count, emit anyway) and `enforce` (reject). Default: `enforce`.

**Acceptance:** Chunks failing the substance predicate are rejected (in enforce mode) or flagged (in report mode). Rejection reason is recorded. `is_table=True` chunks are always exempt.

---

### QUAL-04: Rejection recording and garbage-rate metric

Every rejected chunk must be recorded with its rejection reason. A per-source garbage-rate metric is computable from these records. The metric definition is frozen independently of the gate's heuristic (to prevent circular measurement).

**Acceptance:** After processing, `klake quality-report` (or equivalent) produces a per-source table showing: total sections, kept, rejected, rejection reasons, and garbage rate. The audit's 28% baseline is reproducible.

---

### QUAL-05: Conservation invariant

Every gate must assert `rejected + kept == sections_considered`. This distinguishes correct drops from parser regressions, over-pruning, and broken gates — all of which produce fewer chunks and lower garbage rates.

**Acceptance:** A broken parser that returns 0 sections is detected as distinct from a correct gate that rejects all sections. The invariant is checked and logged at runtime.

---

### DEDUP-01: Index-time exact deduplication

A dedup stage between chunk and embed prevents duplicate text from being embedded and indexed. Dedup is corpus-wide (cross-document), using a Postgres ledger with `sha256(normalized_text)` lookup. Chunk artifacts remain per-document (WR-05 intact).

**Acceptance:** Processing two documents containing identical boilerplate text produces one Qdrant point (not two). The chunk registry still has both chunk artifacts with correct lineage. Embedding cost is paid once.

---

### DEDUP-02: Point ID determinism

Qdrant point IDs for deduplicated chunks use `uuid5(NAMESPACE, sha256(normalized_text))` — making re-index idempotent by construction and dedup lookup O(1).

**Acceptance:** Re-processing the same document produces the same point ID. No duplicate points exist after re-index.

---

### DEDUP-03: Payload preservation for deduplicated points

When multiple documents contribute the same chunk text, the single Qdrant point's payload carries: the primary source's metadata (deterministic: earliest `created_at`) and an additive `contributors[]` list. Existing PAYLOAD-01/02 filters remain functional.

**Acceptance:** A deduplicated point is filterable by source_id, domain, and format. The `contributors` field lists all source documents that contained this text.

---

### EXPORT-01: Gold RAG export quality gate

`export_rag_corpus` must gate on a **chunk-level** quality signal (from QUAL-03), not the document-level `enriched.quality_score` (which is identical for all chunks from the same document and cannot distinguish within-document variance).

**Acceptance:** A document with mixed quality (clinical tables + cookie banners) exports only the clinical chunks. The 33% junk in gold drops to near-zero.

---

### EXPORT-02: Eval dataset versioning

Existing Q&A eval datasets generated from pre-v2.6 garbage must be versioned/regenerated. A v2.6 quality improvement must not score worse on eval sets grounded in boilerplate.

**Acceptance:** Eval datasets carry a version tag. Regeneration after v2.6 produces sets grounded in clinical content, not "Featured".

---

### MEAS-01: Quality audit harness

A re-runnable quality audit produces a per-source comparison table (34 rows) showing garbage rate before and after pipeline changes. Runs against a held-out subset from the raw zone.

**Acceptance:** `klake quality-audit` (or equivalent) produces the same format as the original audit table. Reproducible across runs. Independent of the gate's own heuristic.

---

### MEAS-02: Must-not-reject fixtures in CI

A set of ~20 hand-labeled short-but-vital clinical chunks (ICD codes, dosage instructions, LOINC codes, cardinality constraints, HIPAA section references) that must never be rejected by any gate.

**Acceptance:** CI fails if any fixture in the must-not-reject set is dropped by the substance gate or quality predicates.

---

### PIPE-01: Filter configuration versioning

Quality filter settings must be versioned (reuse the proven `_curation_cache_key` pattern). A config change invalidates the cache for affected artifacts, ensuring re-processing uses updated rules.

**Acceptance:** Changing a filter threshold triggers re-processing of affected documents on next run. Old cache entries are not served for new config versions.

---

## Phase Mapping

| Phase | Name | Requirements | Hard Dependencies |
|-------|------|-------------|-------------------|
| 17 | Close the Bypass + Measurement | CLEAN-01, CLEAN-02, CLEAN-03, QUAL-04, QUAL-05, MEAS-01 | — |
| 18 | Gate Decouple | GATE-01 | — (parallelizable with 17) |
| 19 | Section Classifier + Patterns | CLEAN-04, CLEAN-05, CLEAN-06, QUAL-01 | 17, 18 |
| 20 | Chunk Substance Gate + Export Gate | QUAL-02, QUAL-03, MEAS-02, EXPORT-01, EXPORT-02, PIPE-01 | 17 (parallelizable with 19) |
| 21 | Index-Time Dedup | DEDUP-01, DEDUP-02, DEDUP-03 | 20 (L3 before L4) |

**Critical path:** 17 → 19. Phases 18 and 20 are leaves/parallelizable.

---

## Success Criteria

1. **Primary:** `klake process` on the audit's 34 sources produces <5% garbage chunks (down from 28%)
2. **Gold:** RAG corpus export contains <2% junk rows (down from 33%)
3. **Safety:** Must-not-reject fixtures pass — no clinical codes, dosage instructions, or normative statements dropped
4. **Conservation:** `rejected + kept == considered` holds for every source
5. **Lineage:** No cross-document artifact corruption (WR-05 extended to clean stage)
6. **No regressions:** 971+ tests pass, `xfail_strict=true` holds, no tree-index fallback-rate increase

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| CLEAN-01 | Phase 17 | Complete |
| CLEAN-02 | Phase 17 | Complete |
| CLEAN-03 | Phase 17 | Complete |
| CLEAN-04 | Phase 19 | Pending |
| CLEAN-05 | Phase 19 | Pending |
| CLEAN-06 | Phase 19 | Pending |
| GATE-01 | Phase 18 | Pending |
| QUAL-01 | Phase 19 | Pending |
| QUAL-02 | Phase 20 | Pending |
| QUAL-03 | Phase 20 | Pending |
| QUAL-04 | Phase 17 | Complete |
| QUAL-05 | Phase 17 | Complete |
| DEDUP-01 | Phase 21 | Pending |
| DEDUP-02 | Phase 21 | Pending |
| DEDUP-03 | Phase 21 | Pending |
| EXPORT-01 | Phase 20 | Pending |
| EXPORT-02 | Phase 20 | Pending |
| MEAS-01 | Phase 17 | Complete |
| MEAS-02 | Phase 20 | Pending |
| PIPE-01 | Phase 20 | Pending |
