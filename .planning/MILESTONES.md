# Milestones

## v2.6 Data Quality & Enrichment (Shipped: 2026-07-18)

**Phases completed:** 6 phases, 24 plans, 47 tasks

**Key accomplishments:**

- Retrofitted `clean()` with an optional in-memory `parsed_doc` kwarg, WR-05 parent-scoped content hashing, and unconditional per-section kept/rejected/considered counting with a runtime conservation invariant — the foundational substrate every other Phase 17 plan (Dagster wiring, CLI wiring, quality-audit) depends on.
- `clean_document` now forwards the cleaned `ParsedDoc` (not the raw uncleaned one) under the same `"parsed_doc"` key to `chunk_document`/`tree_index_document`/`enrich_document`, proven by a materialize-test object-identity assertion and a curate_document_asset regression check — the literal CLEAN-01 acceptance criterion, with zero changes to any of the three consumer assets or to curate.py.
- Inserted `clean()` between `parse()` and `chunk()` inside `pipeline/process.py::process_crawled` — the single function shared by CLI, API, and MCP entry points — closing the CLI half of the clean-stage bypass with zero new failure modes.
- `run_quality_audit()` pipeline function + `klake quality-audit` CLI command that re-run parse→clean per `Source.domain`-filtered source and surface a reproducible, per-source garbage-rate table — the MEAS-01 baseline harness every subsequent v2.6 phase measures against.
- Froze gate-local boilerplate patterns in `_GATE_BOILERPLATE_PATTERNS` + `_gate_normalize()`, severing `_signature()` from `remove_boilerplate()` in clean.py so Phase 19 pattern extensions don't trigger spurious re-crawls.
- Zero-I/O `pipeline/quality/` package with 7 composable substance predicates (token floor, alpha ratio, link density, stopword ratio, terminal-punct ratio, table/domain-allowlist exemptions) and a `run_predicates()` combinator, backed by 100%-branch-covered tests — the deterministic-first primitive Plan 19-04's section classifier and Phase 20's chunk substance gate will both consume.
- `DomainLoader` gains optional `filters.yaml` support (CLEAN-06): a new `DomainFilters` Pydantic model, a never-raise-on-absence load in `DomainLoader.__init__`, and a `domains/healthcare/filters.yaml` fixture carrying the healthcare pack's clinical-code allowlist — the domain-pack-contributed half of the allowlist mechanism Plan 19-04's `classify_sections()` will consume.
- `BOILERPLATE_PATTERNS` in `clean.py` grows from 4 to 9 compiled regex entries via a single additive `.extend()` call, covering CLEAN-05's five garbage categories (navigation, terms-of-service, marketing CTAs, cookie consent, government disclaimer) — the raw-text pattern list Plan 19-04's `classify_sections()` will read directly to help decide `is_boilerplate`.
- `classify_sections()` wired into `clean.py`'s `_clean_sections()`/`clean()` flow via full TDD (RED→GREEN), actually dropping boilerplate sections from `cleaned_doc.sections` while an unconditional domain-allowlist override protects clinical codes and dosage patterns — the integration point where Plans 19-01/02/03's mechanisms become load-bearing (CLEAN-04).
- Wires DataTrove's FineWebQualityFilter and Phase 19's pure predicate module into `chunk()` as a composite substance gate (enforce/report modes, `is_table`/domain-allowlist exemptions), and folds `filter_config_version` into the WR-05 per-chunk content hash so a threshold change forces re-processing.
- Wires `DomainLoader.from_name(settings.domain.domain_name).filters` into both `chunk_document` (Dagster) and `process_crawled()` (CLI/API/MCP), and adds a cardinality-constraint pattern to the healthcare pack's `filters.yaml`, making Plan 20-01's substance-gate domain allowlist exemption actually active in every production pipeline run instead of only at the unit-test level.
- Chunk-level substance_passed gate on export_rag_corpus() plus version-tagged eval/instruction dataset examples derived from filter_config_version
- Ships `tests/fixtures/must_not_reject.yaml` (25 hand-labeled clinical fixtures across ICD-10, dosage, LOINC, HIPAA §-reference, and cardinality-constraint categories) and `tests/unit/test_must_not_reject.py`, a parametrized CI test proving every entry survives the real `chunk()` substance gate with `domain_filters` resolved exactly as production resolves it via `DomainLoader.from_name("healthcare")`.
- Postgres-backed `chunk_dedup_ledger` table (migration 0011) plus `claim_dedup_ledger_entry`/`get_dedup_ledger_entry`/`append_dedup_contributor` in `registry/repo.py`, proven atomic via a live two-transaction Postgres race test and a 12-test SQLite unit-test file.
- Zero-I/O `normalize_for_dedup`/`text_sha256_for`/`point_id_for_text` primitives plus `DedupSettings.contributor_cap`, forming the exact-dedup key and deterministic point-ID scheme every later Phase 21 plan builds on.
- Added `set_payload(collection, point_id, payload) -> bool` to the `VectorStorePlugin` protocol and `QdrantVectorStore`, translating qdrant-client's `UnexpectedResponse(404)` into a `False` return without swallowing genuine server errors — the primitive Plan 21-05's duplicate-routing branch will use to merge `contributors[]` onto an existing point.
- `dedup_chunks()` router added to `pipeline/dedup.py` — atomically claims every chunk against the corpus-wide `ChunkDedupLedger`, annotates it with `text_sha256`/`point_id`, and partitions into `new`/`duplicates`, proven end-to-end against a real SQLite ledger including cross-document idempotent re-index.
- `index()` gains a `duplicate_chunks` kwarg that appends a ledger contributor, mirrors a capped primary-first `contributors[]` + exact `contributor_count` onto the existing Qdrant point via `set_payload()`, and self-heals (re-embed + repair) when the point has vanished out-of-band — the DEDUP-03 payload-preservation contract and the write side of DEDUP-02's point-ID determinism.
- `process_crawled()` (the CLI/API/MCP shared entry point) now routes every chunk through `dedup_chunks()` between `chunk()` and `embed()`/`index()`, embedding only first-seen text and threading duplicates into `index()`'s `duplicate_chunks` kwarg — closing DEDUP-01's dead-code gap on the non-Dagster path.
- New `dedup_chunks` Dagster asset added between `chunk_document` and `embed_chunks`, calling `pipeline.dedup.dedup_chunks` unchanged; `embed_chunks`/`index_chunks` rewired to consume its `new`/`duplicates` output; `core_pipeline_e2e_job`'s selection extended with a Pitfall-1 (KL-06-shaped) regression guard proven non-vacuous.
- Two new live-stack integration test files close out Phase 21: one proves the CLI path and the Dagster path produce byte-identical deterministic point IDs and ledger state for the same text (D-18's "enforced by test" guarantee), the other proves `reindex_collection()`'s two upsert modes never disturb a deduplicated point's contributor lineage or its ledger row (D-08).
- `run_full_pipeline_audit()` measures the milestone's two originally-audited criteria (chunk garbage rate, gold-export junk rate) in their literal units by reusing `clean()`/`chunk()`/`export_rag_corpus()` unmodified, scoped to only this run's own chunk IDs to avoid diluting the measurement with ~4,512 pre-v2.6 chunks — and fixes a real domain_filters gap in the existing `run_quality_audit()` along the way.
- `klake quality-audit --full [--json]` now reaches Plan 22-01's `run_full_pipeline_audit()` measurement (chunk-level garbage rate + export-level junk rate vs 28%/33% baselines) through the existing `quality-audit` command, with the pre-existing non---full path left byte-identical.
- Ran `klake quality-audit --domain healthcare --full --json` against the live dev stack's real 34 healthcare sources: chunk-level `chunk_garbage_rate` came out at 45.64% (vs. 28% baseline) while export-level `export_junk_rate` came out at 0.0% (vs. 33% baseline) — the Pitfall-2/A1 convergence check holds (0.0% <= 45.64%), and the gold RAG corpus's actual junk content is now measured at zero.

---

## v2.5 PageIndex Plugin Integration (Shipped: 2026-07-15)

**Phases completed:** 4 phases, 14 plans, 22 tasks

**Delivered:** Tree-based reasoning retrieval (PageIndex) and compiled knowledge bases (OpenKB) alongside the existing vector RAG pipeline, joined by a heuristic query router.

**Key accomplishments:**

- **Tree Index Foundation (P13 · TREE-01..05):** A hierarchical tree index as a new silver-zone artifact type, built by a deterministic stack-based builder over `ParsedDoc.sections` with content-hash no-op dedup and an opt-in, budget-capped LLM summary mode. Shipped as the `PageIndexIndexer` builtin behind a new `IndexerPlugin` Protocol + `knowledge_lake.indexers` entry-point group, and wired as a `tree_index_document` Dagster asset fanning out from `clean_document` parallel to chunking — tool-agnostic seam preserved, full lineage back to source.
- **Tree Retrieval (P14 · RETR-04..08):** Two-stage retrieval — the existing chunk `search()` reused *unchanged* for a Qdrant document shortlist, then Semaphore-bounded concurrent async loading and traversal of candidate trees. Deterministic keyword+DFS traversal by default with an opt-in, budget-capped LLM-guided navigation mode that never raises (heuristic hits are always computed first as fallback). Results carry page-level citations via an additive `citation_source: tree` discriminator on `Hit`, behind a `RetrieverPlugin` Protocol mirroring the indexer seam.
- **Query Router (P15 · ROUTE-01..04):** `classify_route()` heuristic classifier (section/page refs, comparison, structural-breadth triggers) plus a `routed_search()` dispatcher over `chunk|tree|two_stage|auto`, with auto-fallback to chunk on empty tree results. Wired to all four surfaces — REST, CLI, MCP, OpenAPI. Ships defaulting to `auto` with `KLAKE_ROUTER__DEFAULT_ROUTE=chunk` as a zero-code-change rollback lever.
- **OpenKB Export (P16 · KB-01..05):** `compile_wiki()` compiles enrichment metadata into an interlinked Markdown knowledge base in the gold zone — per-document summary pages, cross-document concept pages, and a root index, cross-linked on IDF-filtered entities so only specific terms generate links. Manifest-based content-hash diffing rebuilds only affected pages; exposed via `klake export-wiki` and `POST /export-wiki`, with archive export for Obsidian vault import.
- **E2E Hardening (post-phase, 2026-07-15):** A full end-to-end gap analysis found and closed **19 findings**. The most consequential were structural rather than cosmetic: a `python:3.14-slim` base image that could not build (greenlet has no CPython 3.14 support) had silently left a 13-day-old API container running — which is why two endpoint families returning 500s (`DetachedInstanceError` from responses built after session expiry) stayed invisible; and a section-less parse path that was collapsing 38 sections into 1 chunk, fixed by a silver-zone sections sidecar (51 real per-section chunks, ~30x faster: 43s → 1.4s). `xfail_strict = true` is now active — a stale xfail marker is exactly what hid the 500s.

**Quality gates:** all 4 phases verified `passed` (19/19 requirements), threat-secured, and Nyquist-compliant. Milestone audit: PASSED (19/19 requirements · 4/4 phases · 5/5 E2E flows observable). Full suite: 971 passed, 0 failed, 0 xpassed.

**Known deferred:** ROUTE-05/06 (LLM routing, telemetry), KB-06/07/08 (watch mode, wiki lint, grounded chat), TREE-06/07 (schema versioning, meta-tree). Open tech debt carried into v2.6: MCP `_search_handler` crashes on non-empty results (needs `dataclasses.asdict(h)`); `mode` param dual-semantics on the tree path; domain path-traversal regex duplicated across 3 modules; `sources.config["domain"]` dual-write pending removal; domain packs still cannot contribute Dagster jobs.

---

## v2.0 Agent-Ready Lake (Shipped: 2026-07-12)

**Phases completed:** 6 phases, 38 plans, 60 tasks

**Key accomplishments:**

- **Metadata Foundation (P7 · PAYLOAD-01/02):** Every indexed chunk carries an expanded Qdrant payload (`source_id`, `source_name`, `source_url`, `format`, `tags`, `title`, `organization`) backed by keyword payload indexes — enabling source/format/tag filtered search across both the CLI and the REST API, backward-compatible with existing points.
- **Crawl Maturation (P8 · CRAWL-01/02/03, ENRICH-07, INGEST-10):** Per-source crawl config, `klake crawl-all` batch crawling, adaptive rate limiting (429/403 exponential backoff + per-host cooldown, floored by robots.txt crawl-delay), truncation-resilient LLM enrichment (finish_reason-driven longest-valid-prefix recovery, never cached as complete), and linked-doc (`.pdf`/`.docx`) ingestion with an SSRF guard on every followed link and a bounded, deduped frontier.
- **Storage Segmentation (P9 · STORE-01/02/03):** Domain/source-scoped S3 keys `{zone}/{domain}/{source_id}/{hash}.{ext}` with an `_unclassified` fallback, best-effort S3 object tagging, and gold-zone segmentation by domain + dataset type — all forward-only, preserving WORM raw immutability and content-addressed dedup/lineage.
- **Hybrid Retrieval (P10 · RETR-01/03):** Hybrid BM25 + dense search via Qdrant named sparse/dense vectors with server-side RRF fusion, delivered through a zero-downtime alias-swap **re-embedding** reindex gated by a point-count parity check; `KLAKE_SEARCH__MODE=hybrid|dense|sparse` fails loud on absent vectors rather than silently degrading.
- **Crawl Scheduling (P11 · SCHED-01/02):** A Dagster sensor drives cron-scheduled re-crawl with a normalized silver-text change gate (inline timestamps/UUIDs/nonces suppressed so the WORM raw zone doesn't thrash), a max-staleness backstop, deterministic `run_key` + cursor watermark, and per-source `QueuedRunCoordinator` concurrency for tick-storm safety.
- **Agent Surfaces (P12 · MCP-01/02, SKILL-01/02/03):** A curated MCP server over stdio + Streamable HTTP exposing 11 intent-level tools as thin shims over `pipeline/*.py` (never proxying REST), four Claude Code skills, and OpenAPI + OpenAI tool defs generated from a single Pydantic schema source of truth — `stdio == http == openapi == openai`, proven by a parity gate.

**Quality gates:** all 6 phases verified `passed` (19/19 requirements), threat-secured (`threats_open: 0` across the milestone), and Nyquist-compliant. Milestone audit: PASSED.

---

## v1.0 Knowledge Lake Framework MVP (Shipped: 2026-07-07)

**Phases completed:** 6 phases, 25 plans, 25 tasks

**Key accomplishments:**

- 1. [Rule 1 - Bug] Typer 0.26.8 incompatible with docling 2.108.0
- Wrote 20 failing tests across test_ids.py and test_version.py covering prefix assertions (src_/doc_/chk_/art_), UUIDv7 structure (version nibble == 7), time-sortability, unknown-kind ValueError, uniqueness, and pipeline_version format with/without git SHA, fallback to "0.0.0", never-raise contract.
- Wrote 17 failing tests across test_storage.py covering single-client assertion, put/get round-trips, exists() semantics, object_uri format, AWS-mode client construction (endpoint_url=None → amazonaws.com endpoint), and raw bucket bootstrap verification (versioning, object lock, delete-deny policy).
- `tests/unit/test_plugin_resolver.py` written with 15 tests covering:
- `tests/fixtures/hhs_security_rule.pdf` — locally generated PDF with real HIPAA Security Rule content (Administrative, Technical, Physical Safeguards sections). The hhs.gov direct PDF URL returned HTTP 403 during fixture creation; the equivalent content is preserved for hermetic testing. Docling parses it successfully into 4 sections.
- `api/schemas.py`
- 1. [Rule 1 - Version Mismatch] playwright version adjusted from 1.61.0 to 1.49.0
- 1. [Rule 3 - Blocking] Added source_type_override to register_source
- Multi-format parser fallback chain (Docling 6-format + JsonXmlParser) with weighted heuristic quality scoring, optional LLM gray-zone check, Alembic 0006 migration, and torture-test corpus validation across 5 healthcare document formats.
- Boilerplate removal with line-anchored regex patterns, lingua language detection, SHA256 exact dedup, and transient MinHash LSH near-dup flagging — all producing cleaned_document artifacts in the silver zone.
- Token-aware tiktoken chunker with table atomicity, clean_document Dagster asset inserted between parse and chunk stages, and klake parse/clean/chunk CLI commands with POST /parse, /clean, /chunk API endpoints.
- Migration 0007 (llm_spend + vector_collections tables), Artifact.quality_score mapped as a real ORM column, and 7 new repo.py functions plus EnrichSettings/IndexSettings for the enrichment and index/search vertical slices
- pipeline/deterministic.py + llm/pricing.py + pipeline/enrich.py deliver a cached, budget-capped single-call LiteLLM enrichment producing enriched_document artifacts, wired into klake enrich / POST /enrich / a parallel Dagster asset — the blocking live-Bedrock-smoke-test checkpoint is RESOLVED via a human-authorized live test (commit ac299e1)
- Qdrant alias-based collection management with zero-downtime reindex, an extended chunk payload carrying enrichment metadata, and filterable, backward-compatible semantic search across CLI/API — closing STATE.md's second Phase-4 blocker (Qdrant collection aliasing)
- `_build_filters(settings)`
- `QAPairResult(BaseModel)`
- `_GOLD_PREFIX = "gold"`
- DomainLoader class with path-traversal guard, YAML/Jinja2/importlib loading, and full 28-source healthcare domain pack (domain.yaml, sources.yaml, taxonomy.yaml, enrich.j2, qa_generation.j2, HealthcareValidator)
- DomainSettings nested config model (KLAKE_DOMAIN__ prefix) and optional domain_system_prompt kwarg on enrich_document/_build_enrichment_prompt enabling domain pack prompt injection without any pipeline redesign
- klake init --domain (bulk source registration) and klake index (reindex alias) CLI commands plus 8 additive REST endpoints completing the D-07 API surface gap audit
- RetryPolicy on all 12 Dagster assets with DRY constants, healthcare_e2e_job registered in Definitions, and 5-source E2E test infrastructure for DOMAIN-04 validation.

---
