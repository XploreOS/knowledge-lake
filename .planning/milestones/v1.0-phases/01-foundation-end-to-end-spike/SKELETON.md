# Walking Skeleton — Knowledge Lake Framework

**Phase:** 1
**Generated:** 2026-07-02

## Capability Proven End-to-End

> One sentence: the smallest user-visible capability that exercises the full stack.

An operator runs `docker compose up`, then `klake demo`, and one real HHS HIPAA guidance PDF flows ingest → parse → chunk → embed → index → search, returning cited chunks whose lineage resolves chunk → parsed doc → raw doc → source — on top of the config, S3 storage, immutable content-addressed raw zone, PostgreSQL+Alembic registry, and plugin-protocol foundation every later phase reuses.

## User Story

**As an** operator of the Knowledge Lake, **I want to** bring up the full stack with one command and flow one real document from ingest to a cited, lineage-traceable search result, **so that** the tool-agnostic foundation every later phase depends on is proven working end-to-end.

> Note: the ROADMAP `**Goal:**` line for Phase 1 is stated as an outcome, not in canonical "As a / I want to / so that" form. The three slots above are derived faithfully from that goal plus the phase's five explicit success criteria (no invention). If a canonical ROADMAP goal line is desired, run `/gsd mvp-phase 1`.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Language / packaging | Python 3.12 + uv (import pkg `knowledge_lake`, dist `knowledge-lake`, CLI `klake`) | Pinned stack; uv lockfile reproducibility (D-09). Note stdlib `uuid.uuid7` is 3.14+ — use `uuid-utils` behind a helper now |
| Config | pydantic-settings 2.14.2, single typed source `knowledge_lake.config.settings` | One typed source; env > .env > defaults; no scattered `os.getenv` (FOUND-02, D-… discretion) |
| Object storage | Single boto3 client; `endpoint_url` = MinIO (dev) / None = AWS S3 (prod) | One code path for both backends (FOUND-03); no local FS as store (D-10 `data/` is gitignored scratch) |
| Raw-zone immutability | Content-addressed SHA256 keys + registry hash no-op + `head_object` guard + MinIO versioning/object-lock + delete-deny bucket policy | Backend-portable WORM. MinIO does **not** support S3 `If-None-Match:'*'`; never use the conditional-write wildcard (FOUND-04) |
| Registry | PostgreSQL 16 + SQLAlchemy 2.0 (`postgresql+psycopg://`) + Alembic from migration #1; single self-referencing `artifacts` node table (+ `sources`, `lineage_events`, empty `jobs`/`datasets`) | Lineage = one recursive CTE; FOUND-06 "parent artifact id" is native; FOUND-09 Alembic from table 1 |
| Entity IDs | UUIDv7 (RFC 9562) with short type prefixes (`src_`, `doc_`, `chk_`, `art_`) via `uuid-utils` behind `knowledge_lake.ids` | Time-sortable indexes + self-describing IDs (D-15); one-line swap to stdlib at 3.14 |
| Pipeline version | package version + short git SHA (`0.1.0+abc1234`), pkg-only fallback | Stamped on every artifact for provenance (D-04, FOUND-06) |
| Plugins | `typing.Protocol` contracts + config-keyed resolver over entry points; built-ins live in-package under `plugins/builtin/` | Swap parser/embedder/vector-store by a settings value, no core edits (FOUND-08, D-11). pluggy deferred to Phase 3 fallback chains |
| Embeddings (spike default) | local sentence-transformers (384-dim MiniLM/bge-small); LiteLLM/Bedrock is a pure config switch | `docker compose up` + demo runs with zero AWS creds (D-13); ENRICH-06 configurability seam starts here |
| Model gateway | LiteLLM proxy as a compose service, aliases mapped in `infra/litellm/config.yaml` (never in code) | Up & healthy for FOUND-01 but off the spike's critical path (D-12/D-13); task aliases only |
| Orchestration | Dagster (webserver+daemon) in compose from commit 1; pipeline is plain functions first, wrapped as assets before phase close | "Dagster from day 1" without over-engineering (Pitfall #1, D-01/D-02) |
| User surface | Typer `klake` CLI + FastAPI (uvicorn) service — thin subset of the full command/endpoint lists | Same names grow each phase; CLI/API call pipeline in-process in Phase 1 (D-02) |
| Deployment target | Local `docker compose up` on the dev droplet; `klake demo` / `make spike` is the documented full-stack run + smoke test | FOUND-01 acceptance is one-command bring-up (D-03) |

## Stack Touched in Phase 1

- [x] Project scaffold (uv package, pyproject, ruff, mypy, pytest + pytest-asyncio test runner)
- [x] Routing / surface — Typer CLI (`ingest-url`, `search`, `lineage`, `demo`) + FastAPI (`/health`, `/search`, `/lineage/{id}`)
- [x] Database — real read AND write: registry writes source/artifact/chunk nodes and a lineage-resolving recursive CTE read
- [x] Object storage — real read AND write: content-addressed put/get against MinIO
- [x] UI/interaction wired to API — CLI + FastAPI both drive the pipeline and lineage query in-process
- [x] Deployment — `docker compose up` brings up postgres, minio, qdrant, litellm, dagster(web+daemon), api healthy; `klake demo` runs the full path

## Out of Scope (Deferred to Later Slices)

> Explicit — prevents later phases from re-litigating Phase 1's minimalism.

- Ingestion breadth: crawlers (Crawl4AI/Scrapy/Playwright), uploads, SearXNG discovery, robots.txt/rate-limits (Phase 2)
- Parsing breadth: multi-format parsing, Docling→Unstructured→Tika fallback chain, torture-test corpus, cleaning/dedup, advanced chunking (Phase 3)
- LLM enrichment, embedding-provider switch exercised at scale, caching, budget caps, Qdrant collection aliasing, citations eval harness (Phase 4)
- Curation, dataset generation, Parquet/JSONL/DuckDB export (Phase 5)
- Healthcare domain pack loading, seed sources, full CLI/API/Dagster surface, multi-source validation (Phase 6)
- Multi-tenant auth / RBAC, admin UI, SSRF allow-listing hardening (auth out of scope for MVP; SSRF seam noted, hardened in Phase 2)

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering its architectural decisions:

- Phase 2 (Ingestion): register sources, download/upload/crawl into the same immutable raw zone via the same registry + lineage
- Phase 3 (Parse/Clean/Chunk): widen the parser plugin into the fallback chain and structure-aware chunking behind the same Protocols
- Phase 4 (Enrichment/Embed/Search): LiteLLM enrichment + configurable embeddings + Qdrant aliasing on the same chunk nodes
- Phase 5 (Curation/Datasets/Export): curate and export the enriched corpus with lineage intact
- Phase 6 (Healthcare Pack + Full Surface): load the healthcare pack by convention and prove 5-10 real sources through every stage
