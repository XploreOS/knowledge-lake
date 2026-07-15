# Milestones

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
